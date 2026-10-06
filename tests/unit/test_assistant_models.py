"""Assistant configuration validation and provider network scope."""
import pytest

from src.assistant.models import ProfileInput, Settings


def test_configuration_defaults_and_provider_network_scope(monkeypatch):
    assert not Settings().mutations_enabled
    assert Settings().features.subagents
    with pytest.raises(ValueError):
        Settings(features={"subagents": False})
    base = {"name": "test", "provider": "ollama", "model": "tool-model"}
    assert ProfileInput(**base, base_url="http://localhost:11434").enabled
    for url in ("http://169.254.169.254", "file:///etc/passwd", "https://user:pass@api.openai.com", "https://api.openai.com?api_key=secret", "http://api.openai.com"):
        with pytest.raises(ValueError):
            ProfileInput(**base, base_url=url)
    monkeypatch.setenv("ASSISTANT_PROVIDER_HOSTS", "ollama.internal")
    assert ProfileInput(**base, base_url="http://ollama.internal:11434")

