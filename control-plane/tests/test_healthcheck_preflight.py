"""Unit tests for healthcheck_preflight — the alpine/no-python3 pre-flight
heuristic (separate from build_hints.py: this fires on a *successful*
build/deploy, never on a build-log signature)."""
from koyracloud.healthcheck_preflight import detect_healthcheck_hint
from koyracloud.manifest import parse_manifest


def _manifest(healthcheck="/health", uses_dockerfile=True):
    if uses_dockerfile:
        return parse_manifest(
            f"name: x\nruntime: dockerfile\nhealthcheck: {healthcheck}\n"
            if healthcheck else "name: x\nruntime: dockerfile\n")
    return parse_manifest(
        f"name: x\nstart: y\nhealthcheck: {healthcheck}\n"
        if healthcheck else "name: x\nstart: y\n")


def test_alpine_final_stage_without_python3_warns():
    hint = detect_healthcheck_hint(
        _manifest(), "FROM node:22-alpine\nCMD [\"node\", \"server.js\"]\n")
    assert hint is not None
    assert "alpine" in hint and "python3" in hint


def test_apk_add_no_cache_python3_no_warn():
    hint = detect_healthcheck_hint(
        _manifest(),
        "FROM node:22-alpine\nRUN apk add --no-cache python3\nCMD [\"node\"]\n")
    assert hint is None


def test_apk_add_python3_no_flags_no_warn():
    hint = detect_healthcheck_hint(
        _manifest(), "FROM node:22-alpine\nRUN apk add python3\n")
    assert hint is None


def test_apk_add_update_python3_no_warn():
    hint = detect_healthcheck_hint(
        _manifest(), "FROM node:22-alpine\nRUN apk add --update python3\n")
    assert hint is None


def test_apk_add_unrelated_packages_sharing_line_no_warn():
    hint = detect_healthcheck_hint(
        _manifest(), "FROM node:22-alpine\nRUN apk add git python3 make\n")
    assert hint is None


def test_apk_add_line_continuation_no_warn():
    dockerfile_text = (
        "FROM node:22-alpine\n"
        "RUN apk add --no-cache \\\n"
        "    python3\n"
    )
    assert detect_healthcheck_hint(_manifest(), dockerfile_text) is None


def test_python3_lookalikes_are_not_treated_as_installed():
    # A comment and an unrelated ENV var both contain the substring "python3"
    # but neither actually installs it — the regex must not be fooled.
    dockerfile_text = (
        "FROM node:22-alpine\n"
        "# TODO: install python3 later\n"
        "ENV PYTHON3_HOME=/foo\n"
        "CMD [\"node\"]\n"
    )
    hint = detect_healthcheck_hint(_manifest(), dockerfile_text)
    assert hint is not None


def test_non_alpine_final_stage_no_warn():
    hint = detect_healthcheck_hint(
        _manifest(), "FROM node:22-slim\nCMD [\"node\", \"server.js\"]\n")
    assert hint is None


def test_no_healthcheck_no_warn():
    hint = detect_healthcheck_hint(
        _manifest(healthcheck=""), "FROM node:22-alpine\nCMD [\"node\"]\n")
    assert hint is None


def test_not_uses_dockerfile_no_warn():
    hint = detect_healthcheck_hint(
        _manifest(uses_dockerfile=False), "FROM node:22-alpine\nCMD [\"node\"]\n")
    assert hint is None


def test_multistage_builder_python3_does_not_suppress_final_stage_warning():
    dockerfile_text = (
        "FROM python:3.11-alpine AS builder\n"
        "RUN apk add --no-cache python3\n"
        "RUN pip install -r requirements.txt\n"
        "\n"
        "FROM node:22-alpine AS runner\n"
        "COPY --from=builder /app /app\n"
        "CMD [\"node\", \"server.js\"]\n"
    )
    hint = detect_healthcheck_hint(_manifest(), dockerfile_text)
    assert hint is not None


def test_case_insensitive_from_and_alpine():
    hint = detect_healthcheck_hint(
        _manifest(), "from node:22-Alpine\nCMD [\"node\"]\n")
    assert hint is not None


def test_no_from_line_returns_none():
    assert detect_healthcheck_hint(_manifest(), "") is None
    assert detect_healthcheck_hint(_manifest(), "CMD [\"node\"]\n") is None
