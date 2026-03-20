"""Tests für DB-Konfiguration und Startup-Verhalten."""

from __future__ import annotations

import app.database as database


def test_resolve_sqlite_default():
    settings = database.resolve_database_settings({})
    assert settings.mode == "sqlite"
    assert settings.database_url == "sqlite:///canovr.db"
    assert settings.auto_create_local_schema is True


def test_resolve_turso_mode():
    settings = database.resolve_database_settings(
        {
            "TURSO_DATABASE_URL": "libsql://example-db.turso.io",
            "TURSO_AUTH_TOKEN": "secret-token",
        }
    )
    assert settings.mode == "turso"
    assert settings.database_url.startswith("sqlite+libsql://example-db.turso.io")
    assert "secure=true" in settings.database_url
    assert settings.connect_args["auth_token"] == "secret-token"


def test_fail_fast_on_partial_turso_config():
    try:
        database.resolve_database_settings({"TURSO_DATABASE_URL": "libsql://example-db.turso.io"})
        assert False, "RuntimeError erwartet"
    except RuntimeError:
        pass

    try:
        database.resolve_database_settings({"TURSO_AUTH_TOKEN": "secret-token"})
        assert False, "RuntimeError erwartet"
    except RuntimeError:
        pass


def test_keep_explicit_secure_flag():
    settings = database.resolve_database_settings(
        {
            "TURSO_DATABASE_URL": "sqlite+libsql://example-db.turso.io?secure=false",
            "TURSO_AUTH_TOKEN": "secret-token",
        }
    )
    assert "secure=false" in settings.database_url


class _DummyConnection:
    def execute(self, _stmt):
        return None


class _DummyConnectContext:
    def __enter__(self):
        return _DummyConnection()

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyEngine:
    def connect(self):
        return _DummyConnectContext()


def test_init_db_local_creates_schema(monkeypatch):
    flags = {"create_all_called": False, "validate_called": False}

    def _fake_create_all(_engine):
        flags["create_all_called"] = True

    def _fake_validate():
        flags["validate_called"] = True

    monkeypatch.setattr(database, "engine", _DummyEngine())
    monkeypatch.setattr(
        database,
        "SETTINGS",
        database.DatabaseSettings(
            mode="sqlite",
            database_url="sqlite:///canovr.db",
            connect_args={},
            auto_create_local_schema=True,
        ),
    )
    monkeypatch.setattr(database, "IS_TURSO", False)
    monkeypatch.setattr(database.Base.metadata, "create_all", _fake_create_all)
    monkeypatch.setattr(database, "_validate_turso_schema", _fake_validate)

    database.init_db()
    assert flags["create_all_called"] is True
    assert flags["validate_called"] is False


def test_init_db_turso_always_migrates_then_validates(monkeypatch):
    """Turso mode: always runs alembic upgrade head, then validates."""
    flags = {"create_all_called": False, "validate_called": False, "migrate_called": False}

    def _fake_create_all(_engine):
        flags["create_all_called"] = True

    def _fake_validate():
        flags["validate_called"] = True

    def _fake_migrate():
        flags["migrate_called"] = True

    monkeypatch.setattr(database, "engine", _DummyEngine())
    monkeypatch.setattr(
        database,
        "SETTINGS",
        database.DatabaseSettings(
            mode="turso",
            database_url="sqlite+libsql://example-db.turso.io?secure=true",
            connect_args={"auth_token": "secret"},
            auto_create_local_schema=False,
        ),
    )
    monkeypatch.setattr(database, "IS_TURSO", True)
    monkeypatch.setattr(database.Base.metadata, "create_all", _fake_create_all)
    monkeypatch.setattr(database, "_validate_turso_schema", _fake_validate)
    monkeypatch.setattr(database, "_run_alembic_upgrade_head", _fake_migrate)
    monkeypatch.delenv("CANOVR_AUTO_MIGRATE_TURSO", raising=False)

    database.init_db()
    assert flags["validate_called"] is True
    assert flags["create_all_called"] is False
    assert flags["migrate_called"] is True


def test_init_db_turso_raises_if_auto_migrate_disabled(monkeypatch):
    """When auto-migrate is disabled and schema is broken, init_db raises."""
    flags = {"validate_calls": 0, "migrate_called": False}

    def _fake_validate():
        flags["validate_calls"] += 1
        raise RuntimeError("schema missing")

    def _fake_migrate():
        flags["migrate_called"] = True

    monkeypatch.setattr(database, "engine", _DummyEngine())
    monkeypatch.setattr(
        database,
        "SETTINGS",
        database.DatabaseSettings(
            mode="turso",
            database_url="sqlite+libsql://example-db.turso.io?secure=true",
            connect_args={"auth_token": "secret"},
            auto_create_local_schema=False,
        ),
    )
    monkeypatch.setattr(database, "IS_TURSO", True)
    monkeypatch.setattr(database, "_validate_turso_schema", _fake_validate)
    monkeypatch.setattr(database, "_run_alembic_upgrade_head", _fake_migrate)
    monkeypatch.setenv("CANOVR_AUTO_MIGRATE_TURSO", "false")

    try:
        database.init_db()
        assert False, "RuntimeError erwartet"
    except RuntimeError:
        pass

    assert flags["validate_calls"] == 1
    assert flags["migrate_called"] is False
