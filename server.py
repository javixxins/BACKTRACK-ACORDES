"""Servidor local de «Backtrack Acordes»: MP3/WAV -> acordes de guitarra -> vídeo backtrack y PDF.

Uso:  python server.py [--no-browser]
Usa el primer puerto libre entre 8921 y 8929 (no toca los de las otras apps:
Guitarra Flamenca usa 8850-8859, Vídeos musicales 8008, Audio a MIDI 47821…).
"""
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

import analisis
import acordes
import guitarra_ritmica
import exportar

HERE = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(HERE, "trabajos")
CONFIG = os.path.join(HERE, "config.json")
PORTS = range(8921, 8930)
SYSTEM = platform.system()
APP_ID = "backtrack-acordes"
AUDIO_EXT = (".mp3", ".wav", ".wave")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 600 * 1024 * 1024
sessions = {}
jobs = {}
work_lock = threading.Lock()
KEEP = 4


def load_config():
    cfg = {"last_folder": os.path.join(os.path.expanduser("~"), "Downloads")}
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(**kw):
    cfg = load_config()
    cfg.update(kw)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return cfg


def safe_name(name):
    name = os.path.splitext(os.path.basename(name or "audio"))[0]
    name = re.sub(r"[^\w\-. ()áéíóúñÁÉÍÓÚÑüÜ]", "_", name).strip() or "audio"
    return name[:80]


def _unique(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


# ------------------------------------------------------------------ páginas

@app.route("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.route("/icon.png")
def icon():
    return send_from_directory(HERE, "icon.png")


@app.route("/api/config")
def api_config():
    return jsonify({"app": APP_ID, "last_folder": load_config()["last_folder"]})


# ------------------------------------------------------------------ subir y analizar

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No has subido ningún archivo."}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in AUDIO_EXT:
        return jsonify({"error": "El archivo tiene que ser MP3 o WAV."}), 400
    for old in sorted(sessions.values(), key=lambda x: x["created"])[:-(KEEP - 1) or None]:
        sessions.pop(old["id"], None)
        shutil.rmtree(old["dir"], ignore_errors=True)
    sid = uuid.uuid4().hex[:10]
    d = os.path.join(JOBS_DIR, "s_" + sid)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "original" + (".wav" if ext == ".wave" else ext))
    f.save(path)
    rp = request.form.get("remove_percussion", "1") != "0"
    sess = {"id": sid, "dir": d, "path": path, "name": safe_name(f.filename), "created": time.time(),
            "status": "running", "progress": 0, "message": "Empezando…", "result": None}
    sessions[sid] = sess

    def progress(p, msg):
        sess["progress"], sess["message"] = round(float(p), 1), msg

    def work():
        try:
            with work_lock:
                prep = analisis.prepare(path, progress, 0.0, 0.62, remove_percussion=rp)
                res = acordes.detect(path, prep, lambda p, m: progress(62 + p * 0.38, m))
            sess["result"] = res
            sess["status"] = "done"
            progress(100, "Acordes listos")
        except Exception as e:
            traceback.print_exc()
            sess["status"], sess["message"] = "error", f"No he podido detectar los acordes: {e}"
    threading.Thread(target=work, daemon=True).start()
    return jsonify({"id": sid})


@app.route("/api/analysis/<sid>")
def api_analysis(sid):
    sess = sessions.get(sid)
    if not sess:
        return jsonify({"error": "El análisis ha caducado; vuelve a elegir el archivo."}), 404
    out = {k: sess.get(k) for k in ("id", "status", "progress", "message", "name")}
    if sess["status"] == "done":
        out["result"] = sess["result"]
    return jsonify(out)


@app.route("/api/audio/<sid>")
def api_audio(sid):
    sess = sessions.get(sid)
    if not sess or not os.path.exists(sess["path"]):
        abort(404)
    mime = "audio/mpeg" if sess["path"].endswith(".mp3") else "audio/wav"
    return send_file(sess["path"], mimetype=mime, conditional=True)


# ------------------------------------------------------------------ posturas y cejilla

@app.route("/api/chords/voicings", methods=["POST"])
def api_chord_voicings():
    """Posturas de guitarra para una secuencia de acordes (cejilla y conducción de voces)."""
    data = request.json or {}
    labels = data.get("labels", [])
    durs = data.get("durs") or [1.0] * len(labels)
    flavor = data.get("flavor", "flamenco")
    try:
        capo = guitarra_ritmica.choose_capo([(l, d) for l, d in zip(labels, durs) if l and l != "N"],
                                            data.get("capo", "auto"), flavor)
        vo = guitarra_ritmica.voice_lead(labels, capo, flavor)
    except Exception as e:
        return jsonify({"error": f"Acorde no válido: {e}"}), 400
    return jsonify({"capo": capo, "voicings": vo})


# ------------------------------------------------------------------ exportar vídeo y PDF

def _export_data(body):
    d = body.get("data") or {}
    segs = [{"start": float(x["start"]), "end": float(x["end"]), "label": x.get("label") or "N",
             "root": x.get("root"), "quality": x.get("quality")} for x in d.get("segments", [])]
    if not any(x["root"] is not None for x in segs):
        raise ValueError("No hay acordes que exportar.")
    d["segments"] = segs
    return d


def new_job(**kw):
    jid = uuid.uuid4().hex[:10]
    jobs[jid] = {"id": jid, "status": "queued", "progress": 0, "message": "En cola…", "created": time.time(), **kw}
    return jobs[jid]


@app.route("/api/chords/export", methods=["POST"])
def api_chords_export():
    """Exporta los acordes a la carpeta elegida: PDF (al momento) o vídeo backtrack (con progreso)."""
    body = request.json or {}
    folder = os.path.expanduser((body.get("folder") or "").strip())
    if not folder:
        return jsonify({"error": "Elige una carpeta."}), 400
    try:
        os.makedirs(folder, exist_ok=True)
        data = _export_data(body)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": f"No puedo usar la carpeta {folder}"}), 400
    name = safe_name(body.get("name") or data.get("title") or "acordes")
    if body.get("kind") == "pdf":
        dst = _unique(os.path.join(folder, f"{name} - acordes.pdf"))
        try:
            exportar.render_pdf(data, dst)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"No he podido crear el PDF: {e}"}), 500
        save_config(last_folder=folder)
        return jsonify({"saved": dst})

    sess = sessions.get(body.get("sid", ""))
    if not sess:
        return jsonify({"error": "El análisis ha caducado; vuelve a elegir el archivo."}), 404
    q = body.get("quality", "1080")
    qd = exportar.QUALITIES.get(q, exportar.QUALITIES["1080"])
    audio = [(sess["path"], float(body.get("orig_gain", 1.0)))]
    dst = _unique(os.path.join(folder, f"{name} - acordes backtrack ({qd['name']}).mp4"))
    job = new_job()

    def progress(p, msg):
        job["progress"], job["message"] = round(float(p), 1), msg

    def work():
        try:
            job["status"] = "running"
            with work_lock:
                exportar.render_video(data, audio, dst, progress, quality=q)
            mb = os.path.getsize(dst) / 1e6
            job["info"] = {"saved": dst, "mb": round(mb, 1), "quality": qd["name"],
                           "whatsapp_ok": mb < 16 if q == "whatsapp" else None}
            job["status"] = "done"
            save_config(last_folder=folder)
            progress(100, "¡Vídeo listo!")
        except Exception as e:
            traceback.print_exc()
            job["status"], job["message"] = "error", str(e)
    threading.Thread(target=work, daemon=True).start()
    return jsonify({"id": job["id"]})


@app.route("/api/job/<jid>")
def api_job(jid):
    job = jobs.get(jid)
    if not job:
        return jsonify({"error": "Trabajo no encontrado."}), 404
    return jsonify({k: job.get(k) for k in ("id", "status", "progress", "message", "info")})


# ------------------------------------------------------------------ carpetas

def pick_folder(prompt, start):
    """Abre el selector de carpetas del sistema. Devuelve la ruta o "" si se cancela."""
    if not os.path.isdir(start):
        start = os.path.expanduser("~")
    if SYSTEM == "Darwin":
        script = (f'set f to choose folder with prompt "{prompt}" '
                  f'default location (POSIX file "{start}")\nPOSIX path of f')
        try:
            r = subprocess.run(["osascript", "-e", 'tell application "System Events" to activate',
                                "-e", script], capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return ""
        return r.stdout.strip().rstrip("/") if r.returncode == 0 else ""
    try:
        code = ("import sys, tkinter as tk; from tkinter import filedialog; r=tk.Tk(); r.withdraw(); "
                "r.attributes('-topmost', True); p=filedialog.askdirectory(title=sys.argv[1], initialdir=sys.argv[2]); "
                "sys.stdout.write(p or '')")
        r = subprocess.run([sys.executable, "-c", code, prompt, start], capture_output=True, text=True, timeout=600)
    except Exception:
        return ""
    return os.path.normpath(r.stdout.strip()) if r.stdout.strip() else ""


@app.route("/api/choose-folder", methods=["POST"])
def api_choose_folder():
    folder = pick_folder("¿Dónde guardo el vídeo o el PDF de acordes?", load_config()["last_folder"])
    if not folder:
        return jsonify({"cancelled": True})
    save_config(last_folder=folder)
    return jsonify({"folder": folder})


@app.route("/api/open-folder", methods=["POST"])
def api_open_folder():
    path = (request.json or {}).get("path", "")
    if os.path.exists(path):
        if SYSTEM == "Darwin":
            subprocess.run(["open", "-R", path] if os.path.isfile(path) else ["open", path])
        elif SYSTEM == "Windows":
            subprocess.run(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.run(["xdg-open", os.path.dirname(path)])
    return jsonify({"ok": True})


@app.route("/api/quit", methods=["POST"])
def api_quit():
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ arranque

def clean_old(max_age_h=24):
    if not os.path.isdir(JOBS_DIR):
        return
    now = time.time()
    for d in os.listdir(JOBS_DIR):
        p = os.path.join(JOBS_DIR, d)
        if os.path.isdir(p) and now - os.path.getmtime(p) > max_age_h * 3600:
            shutil.rmtree(p, ignore_errors=True)


def free_port():
    for p in PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise SystemExit("No hay ningún puerto libre entre 8921 y 8929.")


def warmup():
    try:
        analisis.get_model()
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    clean_old()
    port = free_port()
    with open(os.path.join(HERE, ".port"), "w") as f:
        f.write(str(port))
    with open(os.path.join(HERE, ".pid"), "w") as f:
        f.write(str(os.getpid()))
    threading.Thread(target=warmup, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    print(f"Backtrack Acordes en {url}", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
