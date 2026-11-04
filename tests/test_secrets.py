import pytest

from app import create_app


def test_secret_key_is_required(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        create_app({"DATABASE_URL": f"sqlite:///{tmp_path / 'unused.sqlite3'}"})


def test_production_rejects_sqlite_and_dummy_key(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_app({"SECRET_KEY": "x" * 32, "DATABASE_URL": f"sqlite:///{tmp_path / 'unused.sqlite3'}"})
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        create_app({"SECRET_KEY": "dev-only-change-me", "DATABASE_URL": "postgresql+psycopg://dummy@localhost/dummy"})


def test_test_mode_rejects_production_named_url(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(RuntimeError, match="本番らしい"):
        create_app({"TESTING": True, "SECRET_KEY": "test-value", "DATABASE_URL": "postgresql+psycopg://dummy@localhost/production"})
