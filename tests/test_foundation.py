"""P1: the package imports, config loads, data dir + logging work, CLI runs."""


def test_all_subpackages_import():
    import importlib

    for mod in [
        "relay",
        "relay.config",
        "relay.diagnostics",
        "relay.diagnostics.logging",
        "relay.core",
        "relay.core.ids",
        "relay.core.bus",
        "relay.core.state",
        "relay.core.cancellation",
        "relay.core.emergency",
        "relay.core.workers",
        "relay.safety",
        "relay.safety.policy",
        "relay.memory",
        "relay.memory.db",
        "relay.memory.journal",
        "relay.__main__",
    ]:
        importlib.import_module(mod)


def test_config_defaults_and_override(tmp_path, monkeypatch):
    monkeypatch.setenv("RELAY_DATA_DIR", str(tmp_path))
    from relay.config import Config, models_dir, user_data_dir

    assert user_data_dir() == tmp_path
    assert models_dir().exists()
    cfg = Config.load()
    assert cfg.wake_word == "relay"
    assert cfg.mode == "essential"


def test_config_reads_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("RELAY_DATA_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        'wake_word = "computer"\nspeech_rate = 1.5\n', encoding="utf-8"
    )
    from relay.config import Config

    cfg = Config.load()
    assert cfg.wake_word == "computer"
    assert cfg.speech_rate == 1.5


def test_logging_redacts_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("RELAY_DATA_DIR", str(tmp_path))
    import logging

    from relay.diagnostics.logging import _RedactionFilter, setup_logging

    setup_logging("INFO")
    rec = logging.LogRecord(
        "relay.t", logging.INFO, __file__, 1, "user typed password: hunter2", None, None
    )
    _RedactionFilter().filter(rec)
    assert "hunter2" not in rec.getMessage()
    assert "[REDACTED]" in rec.getMessage()


def test_cli_selftest(tmp_path, monkeypatch):
    monkeypatch.setenv("RELAY_DATA_DIR", str(tmp_path))
    from relay.__main__ import main

    assert main(["--selftest"]) == 0
