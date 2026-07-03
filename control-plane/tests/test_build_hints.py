"""Unit tests for build_hints — pure log-substring heuristics."""
from koyracloud.build_hints import detect_log_hints


def test_no_signatures_returns_empty():
    assert detect_log_hints(["Step 1/8 : FROM node:22-alpine", "npm ci", "done"]) == []


def test_empty_lines_returns_empty():
    assert detect_log_hints([]) == []


def test_pnpm_unknown_builtin_module():
    hints = detect_log_hints(["...", "ERR_UNKNOWN_BUILTIN_MODULE: node:sea", "..."])
    assert len(hints) == 1
    assert "pnpm" in hints[0] and "corepack" in hints[0]


def test_pnpm_packages_field_missing():
    hints = detect_log_hints(["ERR_PNPM_WORKSPACE", "packages field missing or empty"])
    assert len(hints) == 1
    assert "pnpm-workspace.yaml" in hints[0]


def test_missing_public_build_arg():
    hints = detect_log_hints(["> next build", "Failed to collect page data for /"])
    assert len(hints) == 1
    assert "NEXT_PUBLIC" in hints[0] and "VITE_" in hints[0]


def test_multiple_signatures_all_returned_in_order():
    lines = [
        "ERR_UNKNOWN_BUILTIN_MODULE: node:sea",
        "Failed to collect page data for /about",
    ]
    hints = detect_log_hints(lines)
    assert len(hints) == 2
    assert "pnpm" in hints[0]
    assert "NEXT_PUBLIC" in hints[1]


def test_signature_split_across_lines_still_detected():
    # detect_log_hints joins lines before matching, so a signature that a
    # tool happened to emit is matched regardless of which line it's on.
    hints = detect_log_hints(["unrelated", "Failed to collect page data", "more output"])
    assert len(hints) == 1
