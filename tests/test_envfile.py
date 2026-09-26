"""The developer's one-paste settings file (.env)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from relay.envfile import load_env, parse

ROOT = Path(__file__).resolve().parent.parent


def test_parse_handles_comments_quotes_and_export():
    text = ("# comment\n\nSARVAM_API_KEY=sk_abc123\nexport RELAY_LLM_URL=http://localhost:3001/v1\n"
            "SARVAM_SPEAKER=\"shubh\"\nRELAY_LLM_KEY='freellmapi-x y'\n"
            "SARVAM_LANGUAGE=en-IN   # Indian English\nEMPTY=\nnot a line\nBAD KEY=1\n")
    assert parse(text) == {"SARVAM_API_KEY": "sk_abc123",
                           "RELAY_LLM_URL": "http://localhost:3001/v1",
                           "SARVAM_SPEAKER": "shubh", "RELAY_LLM_KEY": "freellmapi-x y",
                           "SARVAM_LANGUAGE": "en-IN", "EMPTY": ""}


def test_load_env_never_overrides_the_real_environment(tmp_path, monkeypatch):
    a, b = tmp_path / "a.env", tmp_path / "b.env"
    a.write_text("\ufeffRELAY_T1=from_a\nRELAY_T2=from_a\n", encoding="utf-8")  # BOM ok
    b.write_text("RELAY_T2=from_b\nRELAY_T3=from_b\n", encoding="utf-8")
    monkeypatch.delenv("RELAY_OFFLINE")
    monkeypatch.setenv("RELAY_T1", "from_shell")
    monkeypatch.delenv("RELAY_T2", raising=False)
    monkeypatch.delenv("RELAY_T3", raising=False)
    loaded = load_env([a, tmp_path / "missing.env", b])
    assert loaded == [a, b]
    assert os.environ["RELAY_T1"] == "from_shell"     # a one-off `set` still wins
    assert os.environ["RELAY_T2"] == "from_a"         # first file wins
    assert os.environ["RELAY_T3"] == "from_b"


def test_relay_offline_ignores_every_key(tmp_path, monkeypatch):
    from relay.config import Config
    from relay.llm import routes_from_config
    from relay.sarvam import settings
    f = tmp_path / ".env"
    f.write_text("RELAY_T4=x\n", encoding="utf-8")
    monkeypatch.delenv("RELAY_T4", raising=False)
    monkeypatch.setenv("RELAY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SARVAM_API_KEY", "sk_abc")
    monkeypatch.setenv("RELAY_LLM_URL", "http://localhost:3001/v1")
    monkeypatch.setenv("RELAY_OFFLINE", "1")
    assert load_env([f]) == [] and "RELAY_T4" not in os.environ
    assert settings()["key"] == "" and routes_from_config(Config()) == []
    monkeypatch.delenv("RELAY_OFFLINE")
    assert settings()["key"] == "sk_abc" and len(routes_from_config(Config())) == 2


def test_example_file_is_complete_and_has_no_keys():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    values = parse(text)
    assert values == {"RELAY_LLM_URL": "", "RELAY_LLM_KEY": "", "SARVAM_API_KEY": ""}
    # the optional settings are there, commented out, each alone on its line
    for k in ("SARVAM_SPEAKER", "SARVAM_TTS_MODEL", "SARVAM_LANGUAGE", "SARVAM_STT",
              "SARVAM_BASE_URL"):
        line = next(ln for ln in text.splitlines() if ln.startswith(f"# {k}="))
        assert " " not in line[len(f"# {k}="):], line      # uncommenting gives a clean value
    assert text.index("RELAY_LLM_URL=") < text.index("SARVAM_API_KEY=")   # FreeLLMAPI first


def test_freellmapi_alone_runs_without_sarvam(monkeypatch, tmp_path):
    """Only the router is configured: AI answers on, Sarvam fully off (offline voice)."""
    from relay.config import Config
    from relay.health import _online_checks
    from relay.llm import routes_from_config
    from relay.sarvam import settings
    monkeypatch.delenv("RELAY_OFFLINE")
    monkeypatch.setenv("RELAY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RELAY_LLM_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("RELAY_LLM_KEY", "freellmapi-test")
    assert settings()["key"] == "" and len(routes_from_config(Config())) == 2
    names = [c.name for c in _online_checks({})]
    assert names == ["AI assistant router (online)"]      # no Sarvam check, no Sarvam call


def test_real_env_file_is_git_ignored():
    r = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT)
    assert r.returncode == 0
