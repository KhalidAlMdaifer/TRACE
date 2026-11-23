"""Settings: a developer's .env must not change what the tests see."""
from app import config


def _fresh(monkeypatch, tmp_path, text):
    (tmp_path / ".env").write_text(text)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_dotenv_loaded", False)
    # load_dotenv writes into os.environ itself; setting first makes monkeypatch restore it afterwards
    monkeypatch.setenv("FLIGHTS_AUTO", "unset")
    monkeypatch.delenv("FLIGHTS_AUTO")


def test_dotenv_is_read_by_default(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path, "FLIGHTS_AUTO=0\n")
    monkeypatch.delenv("TRACE_DOTENV", raising=False)
    assert config.flights_auto() is False


def test_dotenv_can_be_switched_off(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path, "FLIGHTS_AUTO=0\n")
    monkeypatch.setenv("TRACE_DOTENV", "0")
    assert config.flights_auto() is True


def test_the_suite_runs_without_the_developers_dotenv():
    import os

    assert os.environ.get("TRACE_DOTENV") == "0"
