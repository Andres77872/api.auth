import importlib
import os
import sys

from src.Util.env_loader import load_env_file


def test_load_env_file_sets_missing_values_without_overriding(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
        # comment
        PLAIN_VALUE=from-file
        export EXPORTED_VALUE='quoted value'
        INLINE_COMMENT=value # comment
        PRESERVED_VALUE=from-file
        """,
        encoding="utf-8",
    )
    monkeypatch.delenv("PLAIN_VALUE", raising=False)
    monkeypatch.delenv("EXPORTED_VALUE", raising=False)
    monkeypatch.delenv("INLINE_COMMENT", raising=False)
    monkeypatch.setenv("PRESERVED_VALUE", "from-process")

    assert load_env_file(env_file) is True

    assert os.environ["PLAIN_VALUE"] == "from-file"
    assert os.environ["EXPORTED_VALUE"] == "quoted value"
    assert os.environ["INLINE_COMMENT"] == "value"
    assert os.environ["PRESERVED_VALUE"] == "from-process"


def test_load_env_file_returns_false_when_missing(tmp_path):
    assert load_env_file(tmp_path / "missing.env") is False


def test_db_config_accepts_legacy_db_password_fallback(monkeypatch):
    module_name = "src.Util.db_config"
    original_module = sys.modules.pop(module_name, None)

    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "3306")
    monkeypatch.setenv("DB_USER", "test_user")
    monkeypatch.delenv("DB_MYSQL_PASSWORD", raising=False)
    monkeypatch.setenv("DB_PASSWORD", "legacy-password")
    monkeypatch.setenv("DB_NAME", "magic_auth")
    monkeypatch.setenv("REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_DB", "0")

    try:
        db_config = importlib.import_module(module_name)
        assert db_config.CONNECTION_CONFIG["password"] == "legacy-password"
    finally:
        sys.modules.pop(module_name, None)
        if original_module is not None:
            sys.modules[module_name] = original_module
