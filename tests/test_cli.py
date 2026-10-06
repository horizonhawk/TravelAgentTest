import json

from trip_agent.cli import main


def test_reviewer_setup_and_lifecycle_without_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    prefix = ["--config", str(tmp_path / "trip-agent.toml"), "--data-dir", str(tmp_path / "data")]
    assert main(prefix + ["config", "init"]) == 0
    assert "gpt-6.1-sol" in (tmp_path / "trip-agent.toml").read_text()
    assert main(prefix + ["config", "check"]) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err
    assert main(prefix + ["session", "create", "--name", "Review trip"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert main(prefix + ["session", "rename", record["session_id"], "Renamed"]) == 0
    assert main(prefix + ["session", "delete", "Renamed"]) == 0
    assert main(prefix + ["session", "restore", record["session_id"]]) == 0
    assert main(prefix + ["session", "set-model", "Renamed", "--profile", "other"]) == 1
    assert "not modified" in capsys.readouterr().err


def test_init_preserves_existing_config(tmp_path):
    args = ["--config", str(tmp_path / "config.toml"), "config", "init"]
    assert main(args) == 0
    before = (tmp_path / "config.toml").read_text()
    assert main(args) == 1
    assert (tmp_path / "config.toml").read_text() == before
