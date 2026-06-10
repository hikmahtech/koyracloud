# Contributing to koyracloud

Thanks for your interest! koyracloud is a small, focused project — contributions
that keep it that way are very welcome.

## Ground rules

- **Open an issue first** for anything non-trivial, so we can agree on the approach.
- Keep changes surgical and in the existing style. No drive-by refactors.
- All tests must pass, and new behavior needs tests.
- Respect the [non-goals](README.md#non-goals) — this is a single-operator,
  trusted-code platform, not a multi-tenant public cloud.

## Developer Certificate of Origin

By submitting a pull request, you certify the [DCO](https://developercertificate.org/)
— i.e. you wrote the code or have the right to submit it under the project's license.
Sign your commits with `git commit -s`.

> Note: contributions are accepted under AGPL-3.0, and the maintainer may also
> offer the combined work under a commercial license (see [LICENSING.md](LICENSING.md)).

## Dev setup

```bash
# control plane (SQLite, OAuth bypassed)
cd control-plane
KOYRA_DEV_LOGIN=you \
KOYRA_SECRET_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')" \
  uv run uvicorn koyracloud.main:app --reload

# UI
cd web && npm install && npm run dev
```

## Tests & checks

```bash
cd runtime-image  && uv run --with pytest --with pyyaml pytest
cd control-plane  && uv run --with-editable . --with pytest pytest
cd web            && npm run build
```

## Pull requests

- Branch from `main`, keep PRs focused.
- Describe what changed and why; link the issue.
- Make sure CI is green.
