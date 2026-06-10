"""Unit tests for the runtime entrypoint's pure helpers."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import entrypoint as ep  # noqa: E402


def test_compute_dep_hash_changes_with_content(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    h1 = ep.compute_dep_hash(tmp_path)
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
    h2 = ep.compute_dep_hash(tmp_path)
    assert h1 != h2


def test_compute_dep_hash_stable(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    assert ep.compute_dep_hash(tmp_path) == ep.compute_dep_hash(tmp_path)


def test_compute_dep_hash_absent_vs_empty(tmp_path):
    h_absent = ep.compute_dep_hash(tmp_path)
    (tmp_path / "requirements.txt").write_text("")
    h_empty = ep.compute_dep_hash(tmp_path)
    assert h_absent != h_empty


def test_compute_dep_hash_includes_lockfile(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    h1 = ep.compute_dep_hash(tmp_path)
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package-lock.json").write_text('{"x":1}')
    h2 = ep.compute_dep_hash(tmp_path)
    assert h1 != h2


def test_read_manifest_valid(tmp_path):
    m = tmp_path / "app.yaml"
    m.write_text("name: demo\nstart: uvicorn app:app\nport: 8000\n")
    data = ep.read_manifest(m)
    assert data["name"] == "demo"
    assert data["start"] == "uvicorn app:app"


def test_read_manifest_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        ep.read_manifest(tmp_path / "nope.yaml")


def test_read_manifest_missing_required(tmp_path):
    m = tmp_path / "app.yaml"
    m.write_text("name: demo\n")  # no start
    with pytest.raises(ValueError):
        ep.read_manifest(m)


def test_read_manifest_not_mapping(tmp_path):
    m = tmp_path / "app.yaml"
    m.write_text("- a\n- b\n")
    with pytest.raises(ValueError):
        ep.read_manifest(m)


def test_build_path_prepends_venv(tmp_path):
    result = ep.build_path(tmp_path / "venv", "/usr/bin:/bin")
    assert result == f"{tmp_path / 'venv' / 'bin'}:/usr/bin:/bin"


def test_needs_build_cold_cache(tmp_path):
    assert ep.needs_build("abc", tmp_path / ".dep-hash", tmp_path / "venv",
                           uses_python=True) is True


def test_needs_build_hash_match(tmp_path):
    (tmp_path / ".dep-hash").write_text("abc")
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    assert ep.needs_build("abc", tmp_path / ".dep-hash", venv,
                          uses_python=True) is False


def test_needs_build_hash_mismatch(tmp_path):
    (tmp_path / ".dep-hash").write_text("old")
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    assert ep.needs_build("new", tmp_path / ".dep-hash", venv,
                          uses_python=True) is True


def test_needs_build_node_only_no_venv(tmp_path):
    (tmp_path / ".dep-hash").write_text("abc")
    # node-only app: missing venv must NOT force a rebuild
    assert ep.needs_build("abc", tmp_path / ".dep-hash", tmp_path / "venv",
                          uses_python=False) is False


def test_auth_args_with_token():
    import base64
    args = ep.auth_args("tok")
    assert args[0] == "-c"
    cred = base64.b64encode(b"x-access-token:tok").decode()
    assert args[1] == f"http.extraHeader=Authorization: Basic {cred}"


def test_auth_args_without_token():
    assert ep.auth_args("") == []
    assert ep.auth_args(None) == []


def test_validate_repo_ref_ok():
    ep.validate_repo_ref("https://github.com/o/r", "main")
    ep.validate_repo_ref("git@github.com:o/r.git", "v1.2.3")


def test_validate_repo_ref_rejects_flag_injection():
    with pytest.raises(ValueError):
        ep.validate_repo_ref("--upload-pack=evil", "main")
    with pytest.raises(ValueError):
        ep.validate_repo_ref("https://github.com/o/r", "--output=/etc/x")


def test_validate_repo_ref_rejects_bad_scheme():
    with pytest.raises(ValueError):
        ep.validate_repo_ref("file:///etc/passwd", "main")
