"""`python -m app.cli run FILE ...` prints a result JSON for a file."""
import json

from app import cli
from app.core import synth


def test_cli_runs_the_synthetic_file(tmp_path, capsys):
    # the `synth` command writes a recording, its boxes and the flight day; no decoys keeps it quick
    assert cli.main(["synth", str(tmp_path), "--decoys", "0", "--temperature", "28"]) == 0
    made = capsys.readouterr().out
    assert "synthetic.wav" in made and (tmp_path / "flights" / "test" / "2026-11-14-traces.npz").exists()

    # two of the three boxes: flights 1 and 3, nothing confirmed between them
    boxes = json.loads((tmp_path / "events.json").read_text())
    (tmp_path / "two.json").write_text(json.dumps([boxes[0], boxes[2]]))
    out_file = tmp_path / "result.json"
    rc = cli.main(["run", str(tmp_path / "synthetic.wav"), "--date", synth.DATE_LOCAL, "--pack", "test",
                   "--events", str(tmp_path / "two.json"), "--temperature", "28", "--data-dir", str(tmp_path),
                   "--synthetic-types", "--out", str(out_file)])
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result == json.loads(out_file.read_text())
    assert result["state"] == "candidates" and result["sublabel"] == "too_few_flights"   # no other flights to judge against
    assert result["candidates"][0]["icao"] == ["aaa001", "aaa003"]
    assert len(result["inputs"]["file_sha256"]) == 64 and result["inputs"]["temperature_source"] == "analyst"


def test_cli_rejects_a_missing_file(tmp_path, capsys):
    rc = cli.main(["run", str(tmp_path / "nope.mp4"), "--date", "2026-11-14", "--pack", "test",
                   "--events", str(tmp_path / "nope.json"), "--temperature", "28"])
    assert rc == 2 and "error" in capsys.readouterr().err.lower()


def test_cli_installs_the_demo_where_the_service_looks(tmp_path, capsys):
    assert cli.main(["demo", "--data-dir", str(tmp_path)]) == 0
    assert (tmp_path / "demo" / "synthetic.wav").stat().st_size > 10_000_000
    assert (tmp_path / "flights" / "test" / "2026-11-14-traces.npz").exists() and len(json.loads((tmp_path / "demo" / "events.json").read_text())) == 3
    assert "Synthetic test pack" in capsys.readouterr().out


def test_cli_adds_users_and_changes_passwords(tmp_path, capsys, monkeypatch):
    """Accounts are made from the terminal: there is no sign-up page. The password comes
    from a prompt or from standard input, never from the command line."""
    import io

    from app import db
    from app.api import auth

    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def run(args, typed):
        monkeypatch.setattr("sys.stdin", io.StringIO(typed))
        rc = cli.main(args)
        return rc, capsys.readouterr()

    rc, out = run(["user", "add", "Ana@Example.org", "--password-stdin"], "a long enough passphrase\n")
    assert rc == 0 and "ana@example.org" in out.out and "passphrase" not in out.out + out.err
    rc, out = run(["user", "add", "ana@example.org", "--password-stdin"], "another long passphrase\n")
    assert rc == 2 and "already" in out.err
    rc, out = run(["user", "add", "bo@example.org", "--password-stdin"], "short\n")
    assert rc == 2 and "at least" in out.err
    rc, out = run(["user", "add", "chief@example.org", "--role", "admin", "--password-stdin"], "the chief's long passphrase\n")
    assert rc == 0

    with db.connect() as conn:
        assert auth.check_password(conn, "ana@example.org", "a long enough passphrase")["role"] == "analyst"
        assert auth.check_password(conn, "ana@example.org", "not it") is None
    rc, out = run(["user", "passwd", "ana@example.org", "--password-stdin"], "a new and longer passphrase\n")
    assert rc == 0
    with db.connect() as conn:
        assert auth.check_password(conn, "ana@example.org", "a long enough passphrase") is None
        assert auth.check_password(conn, "ana@example.org", "a new and longer passphrase")
        assert [r["action"] for r in db.rows(conn, "SELECT action FROM audit_log ORDER BY id")] == ["user.create", "user.create", "user.password"]
    rc, out = run(["user", "passwd", "nobody@example.org", "--password-stdin"], "a long enough passphrase\n")
    assert rc == 2 and "no such user" in out.err.lower()

    rc, out = run(["user", "list"], "")
    assert rc == 0 and "ana@example.org" in out.out and "chief@example.org" in out.out and "admin" in out.out
