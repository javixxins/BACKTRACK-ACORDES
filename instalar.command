#!/bin/bash
# Instalador de Backtrack Acordes para macOS (solo hace falta una vez).
cd "$(dirname "$0")" || exit 1
echo "==> Backtrack Acordes · instalación"
ok() { "$1" -c 'import sys; sys.exit(0 if (3,9) <= sys.version_info[:2] <= (3,11) else 1)' 2>/dev/null; }
PY=""
for c in python3.10 python3.11 python3.9 /usr/local/bin/python3.10 /opt/homebrew/bin/python3.10 \
         /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1 && ok "$c"; then PY="$c"; break; fi
done
if [ -z "$PY" ] && command -v brew >/dev/null 2>&1; then
  echo "==> Instalando Python 3.10 con Homebrew…"
  brew install python@3.10 && PY="$(brew --prefix)/bin/python3.10"
fi
if [ -z "$PY" ] || ! ok "$PY"; then
  echo "❌ Necesitas Python 3.10. Se abrirá la página de descarga."
  open "https://www.python.org/downloads/release/python-31011/"
  read -r -p "Pulsa Intro para cerrar…" _
  exit 1
fi
echo "==> Usando $("$PY" --version)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv || exit 1
.venv/bin/python -m pip install -q --upgrade pip
echo "==> Instalando dependencias (unos minutos, solo la primera vez)…"
.venv/bin/python -m pip install --prefer-binary -r requirements.txt || { read -r -p "Falló la instalación. Intro para cerrar…" _; exit 1; }
.venv/bin/python make_icon.py
chmod +x *.command "Backtrack Acordes.app/Contents/MacOS/launcher" 2>/dev/null
xattr -dr com.apple.quarantine . 2>/dev/null
echo "✅ Instalación terminada."
[ -n "$BA_NO_START" ] || "$(pwd)/Iniciar Backtrack Acordes.command"
