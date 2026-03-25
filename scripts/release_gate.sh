#!/usr/bin/env bash
set -euo pipefail

echo "[canovr] Release Gate gestartet"

# Waehlt zuerst einen fuer pyreason kompatiblen Interpreter.
select_python_bin() {
  if [[ -n "${CANOVR_PYTHON_BIN:-}" ]]; then
    if command -v "${CANOVR_PYTHON_BIN}" >/dev/null 2>&1; then
      echo "${CANOVR_PYTHON_BIN}"
      return 0
    fi
    echo "[canovr] Fehler: CANOVR_PYTHON_BIN='${CANOVR_PYTHON_BIN}' wurde nicht gefunden." >&2
    return 1
  fi

  for candidate in python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done

  echo "[canovr] Fehler: Kein Python-Interpreter gefunden." >&2
  return 1
}

# Nutzt eine lokale virtuelle Umgebung, falls kein venv aktiv ist.
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PYTHON_BIN="python3"
else
  HOST_PYTHON_BIN="$(select_python_bin)"
  HOST_PYTHON_ID="$("$HOST_PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")')"
  GATE_VENV=".venv-release-gate-py${HOST_PYTHON_ID}"
  if [[ ! -d "$GATE_VENV" ]]; then
    "$HOST_PYTHON_BIN" -m venv "$GATE_VENV"
  fi
  # shellcheck disable=SC1091
  source "$GATE_VENV/bin/activate"
  PYTHON_BIN="python"
fi

"$PYTHON_BIN" -m pip install --quiet --disable-pip-version-check --no-cache-dir -r requirements.txt pytest

echo "[canovr] Tests laufen"
"$PYTHON_BIN" -m pytest -q

echo "[canovr] Sicherheits-Checks laufen"
if rg -n 'print\(|LOGGER\.(debug|info)\(.*(token|password|Authorization|refresh_token|access_token)' app >/dev/null; then
  echo "[canovr] Fehler: Potenziell sensibles Logging im Backend gefunden."
  exit 1
fi

echo "[canovr] Release Gate erfolgreich"
