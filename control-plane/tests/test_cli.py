"""Tests for ``koyra validate`` (koyracloud.cli)."""
from koyracloud.cli import main

VALID = """
name: demo
runtime: python+node
port: 8000
start: uvicorn app:app
persist: [data]
secrets: [SECRET_KEY]
workers:
  - name: events
    start: python -m app.worker
cron:
  - name: nightly
    schedule: "0 2 * * *"
    command: python -m app.jobs.nightly
"""

BAD_RUNTIME = "name: x\nstart: y\nruntime: ruby\n"
BAD_CRON = ('name: x\nstart: y\n'
            'cron: [{name: c, schedule: "not-a-cron", command: run}]\n')


def test_validate_ok_file(tmp_path, capsys):
    manifest = tmp_path / "app.yaml"
    manifest.write_text(VALID)

    rc = main(["validate", str(manifest)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "OK  demo" in out
    assert "runtime:  python+node" in out
    assert "port:     8000" in out
    assert "workers:  1" in out
    assert "cron:     1" in out
    assert "persist:  1" in out
    assert "secrets:  1" in out


def test_validate_ok_directory_arg(tmp_path, capsys):
    (tmp_path / ".paas").mkdir()
    (tmp_path / ".paas" / "app.yaml").write_text(VALID)

    rc = main(["validate", str(tmp_path)])

    assert rc == 0
    assert "OK  demo" in capsys.readouterr().out


def test_validate_default_path_uses_dot_paas(tmp_path, monkeypatch, capsys):
    (tmp_path / ".paas").mkdir()
    (tmp_path / ".paas" / "app.yaml").write_text(VALID)
    monkeypatch.chdir(tmp_path)

    rc = main(["validate"])

    assert rc == 0
    assert "OK  demo" in capsys.readouterr().out


def test_validate_bad_runtime_exits_1_with_field_path(tmp_path, capsys):
    manifest = tmp_path / "app.yaml"
    manifest.write_text(BAD_RUNTIME)

    rc = main(["validate", str(manifest)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "manifest is invalid" in err
    assert "runtime:" in err
    assert "ruby" in err


def test_validate_bad_cron_schedule_exits_1_with_field_path(tmp_path, capsys):
    manifest = tmp_path / "app.yaml"
    manifest.write_text(BAD_CRON)

    rc = main(["validate", str(manifest)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "cron.0.schedule:" in err


def test_validate_missing_file_exits_1(tmp_path, capsys):
    rc = main(["validate", str(tmp_path / "nope.yaml")])

    assert rc == 1
    assert "no such file" in capsys.readouterr().err


def test_validate_strict_warns_on_unknown_key(tmp_path, capsys):
    manifest = tmp_path / "app.yaml"
    manifest.write_text("name: x\nstart: y\nport: 8000\nbogus_key: 1\n")

    rc = main(["validate", "--strict", str(manifest)])

    assert rc == 0
    err = capsys.readouterr().err
    assert "unknown top-level key 'bogus_key'" in err


def test_validate_without_strict_does_not_warn_on_unknown_key(tmp_path, capsys):
    manifest = tmp_path / "app.yaml"
    manifest.write_text("name: x\nstart: y\nport: 8000\nbogus_key: 1\n")

    rc = main(["validate", str(manifest)])

    assert rc == 0
    assert capsys.readouterr().err == ""
