"""``koyra`` — small CLI for app authors. Currently just ``koyra validate``:
lint a ``.paas/app.yaml`` locally against the exact rules the control plane
uses (reuses ``koyracloud.manifest.parse_manifest`` verbatim), so a bad
manifest is caught before pushing instead of on the next deploy.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from koyracloud.manifest import Manifest, parse_manifest

DEFAULT_MANIFEST = Path(".paas/app.yaml")


def _resolve_path(path_arg: str) -> Path:
    """A bare directory means ``<dir>/.paas/app.yaml``; anything else is used
    as-is (so both `koyra validate` and `koyra validate ./my-app` work)."""
    p = Path(path_arg)
    return p / ".paas" / "app.yaml" if p.is_dir() else p


def _format_loc(loc: tuple) -> str:
    return ".".join(str(part) for part in loc) if loc else "(top level)"


def _format_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        lines = []
        for err in exc.errors():
            msg = err["msg"]
            # pydantic prefixes validators that raise ValueError with
            # "Value error, " -- the field path already makes clear it's a
            # validation failure, so drop the redundant prefix.
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, "):]
            lines.append(f"  {_format_loc(err['loc'])}: {msg}")
        return "\n".join(lines)
    # yaml.YAMLError (bad syntax) or the plain ValueError for a non-mapping
    # document -- both already come with useful context (line/column etc).
    return f"  {exc}"


def _unknown_top_level_keys(text: str) -> list[str]:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        return []
    return sorted(set(data) - set(Manifest.model_fields))


def _summary(m: Manifest) -> str:
    return "\n".join([
        f"OK  {m.name}",
        f"  runtime:  {m.runtime}",
        f"  port:     {m.port}",
        f"  workers:  {len(m.workers)}",
        f"  cron:     {len(m.cron)}",
        f"  persist:  {len(m.persist)}",
        f"  secrets:  {len(m.secrets)}",
    ])


def _validate(path_arg: str, strict: bool) -> int:
    path = _resolve_path(path_arg)
    if not path.is_file():
        print(f"{path}: no such file", file=sys.stderr)
        return 1

    text = path.read_text()
    try:
        manifest = parse_manifest(text)
    except Exception as exc:  # ValidationError | ValueError | yaml.YAMLError
        print(f"{path}: manifest is invalid", file=sys.stderr)
        print(_format_error(exc), file=sys.stderr)
        return 1

    if strict:
        for key in _unknown_top_level_keys(text):
            print(f"warning: unknown top-level key {key!r} (ignored by the "
                  f"control plane)", file=sys.stderr)

    print(_summary(manifest))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="koyra")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser(
        "validate", help="lint a .paas/app.yaml against the control-plane rules")
    validate.add_argument(
        "path", nargs="?", default=str(DEFAULT_MANIFEST),
        help="manifest file, or a directory containing .paas/app.yaml "
             "(default: .paas/app.yaml)")
    validate.add_argument(
        "--strict", action="store_true",
        help="also warn on unknown top-level manifest keys")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.path, strict=args.strict)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
