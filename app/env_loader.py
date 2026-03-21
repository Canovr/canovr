"""Lädt lokale Umgebungsvariablen aus .env einmalig."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_environment() -> None:
    """Lädt Projekt-.env, falls python-dotenv verfügbar ist.

    Die Funktion ist idempotent und überschreibt bestehende
    Prozessvariablen nicht.
    """
    try:
        from dotenv import load_dotenv
    except Exception:  # noqa: BLE001
        return

    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env", override=False)

