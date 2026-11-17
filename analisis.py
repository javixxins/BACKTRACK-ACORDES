"""Análisis del audio (MP3 o WAV) para detectar acordes.

Es exactamente la misma preparación que usa «Guitarra Flamenca» antes de detectar los acordes:
1. Lee el audio (WAV o MP3) a 22 050 Hz mono y normaliza el nivel.
2. Separa la percusión (HPSS) para que baterías y palmas no ensucien la armonía.
3. Calcula el tempo y la afinación del original.
4. Pasa la red neuronal de notas basic-pitch (Spotify) por ventanas, con progreso.
El resultado (`Prepared`) es lo que necesita `acordes.detect`.
"""
import logging
import math
import threading
import warnings

import numpy as np

warnings.filterwarnings("ignore")
logging.getLogger().setLevel(logging.ERROR)

import librosa  # noqa: E402
from basic_pitch import ICASSP_2022_MODEL_PATH  # noqa: E402
from basic_pitch.constants import AUDIO_N_SAMPLES, AUDIO_SAMPLE_RATE, FFT_HOP  # noqa: E402
from basic_pitch.inference import Model, unwrap_output, window_audio_file  # noqa: E402

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        _model = Model(ICASSP_2022_MODEL_PATH)
    return _model


def _predict_window(model, x):
    if model.model_type == Model.MODEL_TYPES.COREML:  # evita los print de depuración
        r = model.model.predict({"input_2": x})
        return {"note": r["Identity_1"], "onset": r["Identity_2"], "contour": r["Identity"]}
    return model.predict(x)


class Prepared:
    def __init__(self, audio, duration, tempo, tuning, output):
        self.audio, self.duration, self.tempo, self.tuning, self.output = audio, duration, tempo, tuning, output


def prepare(path, progress=lambda *a: None, p0=0.0, p1=1.0, remove_percussion=True):
    def prog(p, msg):
        progress(p0 * 100 + (p1 - p0) * p, msg)

    prog(2, "Leyendo el archivo de audio…")
    audio, _ = librosa.load(path, sr=AUDIO_SAMPLE_RATE, mono=True)
    if len(audio) < AUDIO_SAMPLE_RATE * 0.2:
        raise ValueError("El audio es demasiado corto.")
    duration = len(audio) / AUDIO_SAMPLE_RATE
    peak = float(np.abs(audio).max())
    if peak < 1e-4:
        raise ValueError("El archivo está en silencio.")
    audio = audio / peak * 0.9

    if remove_percussion:
        prog(5, "Separando la percusión (baterías, palmas, golpes)…")
        audio = librosa.effects.harmonic(audio, margin=1.0).astype(np.float32)
        audio = audio / (np.abs(audio).max() or 1) * 0.9

    prog(9, "Calculando tempo y afinación…")
    try:
        tempo = float(np.atleast_1d(librosa.beat.beat_track(y=audio, sr=AUDIO_SAMPLE_RATE)[0])[0])
        if not (40 <= tempo <= 240):
            tempo = 120.0
    except Exception:
        tempo = 120.0
    try:
        tuning = float(librosa.estimate_tuning(y=audio, sr=AUDIO_SAMPLE_RATE))
    except Exception:
        tuning = 0.0

    model = get_model()
    n_overlap = 30
    overlap_len = n_overlap * FFT_HOP
    hop = AUDIO_N_SAMPLES - overlap_len
    padded = np.concatenate([np.zeros(overlap_len // 2, np.float32), audio.astype(np.float32)])
    n_win = max(1, math.ceil(len(padded) / hop))
    out = {"note": [], "onset": [], "contour": []}
    for i, (win, _) in enumerate(window_audio_file(padded, hop)):
        with _model_lock:
            r = _predict_window(model, np.expand_dims(win, axis=0).astype(np.float32))
        for k in out:
            out[k].append(r[k])
        prog(12 + 88 * (i + 1) / n_win, f"Escuchando las notas… ({i + 1}/{n_win})")
    output = {k: unwrap_output(np.concatenate(out[k]), len(audio), n_overlap) for k in out}
    return Prepared(audio, duration, tempo, tuning, output)
