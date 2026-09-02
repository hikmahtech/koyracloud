# Operations log — koyracloud.com

Dated notes on changes made to the hosted instance (koyracloud.com), as opposed
to the code. Newest first. Functional changes to the software are in
[`../CHANGELOG.md`](../CHANGELOG.md); this is the "what did we actually do to
the live system, and how do we undo it" record.

## 2026-09-02 — GitHub App sign-in, app members, avri-solva

**Why.** A user's private repo (`FaheemShk/Avri`, app 20) failed to deploy with
`Repository not found`: every clone used the one platform PAT (`arshadansari27`),
and sign-in was identity-only. Wanted: Vercel-style read-only access that the
user grants on their own repos.

**Code shipped** (both live via the CI deploy):

- [#116](https://github.com/hikmahtech/koyracloud/pull/116) — GitHub App sign-in.
  With `GITHUB_APP_SLUG` set, the login token is kept per user (Fernet, refreshed
  on expiry), `GET /api/github/repos` lists the repos the user installed the App
  on, the New-app page gets a picker, and clones try `KOYRA_GIT_TOKEN` → the
  owner's App token → the platform PAT (one retry on the PAT).
- [#118](https://github.com/hikmahtech/koyracloud/pull/118) — app **members**
  (teammates who see and operate an app; owner/admin manage delete + members),
  plus a deploy-log hint for `X: not found` after `npm ci` when
  `NODE_ENV=production` is in the manifest env (devDependencies skipped).

**Instance changes.**

1. Registered GitHub App **`koyracloud`** (app id 4808423, owner org `hikmahtech`,
   client id `Iv23livi4narFgJv1Rsp`, permissions Contents: read + Metadata: read,
   webhook inactive, setup URL `/new`). Done through the manifest flow with the
   script that became `deploy/register-github-app.py`; the client secret never
   touched a terminal.
2. `deploy/koyracloud.env` on the operator machine: `GITHUB_CLIENT_ID` swapped to the
   App's, `GITHUB_APP_SLUG=koyracloud` added. The previous OAuth App client id
   (`Ov23liD2lsWQLXJHOtIQ`) is kept in a comment for rollback; that OAuth App still
   exists on GitHub and can be deleted.
3. Client secret rotated with the `_v2` recipe (`deploy/README.md` §5): the
   service now mounts Docker secret `koyra_github_client_secret_v2` at
   `/run/secrets/koyra_github_client_secret`; the canonical
   `koyra_github_client_secret` was re-created with the same value so the next
   `stack deploy` swaps back to it. Env added in the same `service update`
   (`GITHUB_CLIENT_ID`, `GITHUB_APP_SLUG`). One restart, nothing in flight.
4. Verified: `/api/auth/login` redirects with the new client id and no `scope=`;
   `/api/github/repos` returns `enabled: true`; boot log clean.

**Rollback.** `docker service update --secret-rm koyra_github_client_secret_v2
--secret-add <old secret> --env-add GITHUB_CLIENT_ID=Ov23liD2lsWQLXJHOtIQ
--env-rm GITHUB_APP_SLUG koyracloud_control-plane` — but the old client secret
was destroyed with the old Docker secret, so rollback means generating a new
secret on the old OAuth App first. Stored user tokens are harmless if the slug is
unset (never read).

**avri-solva (app 20, `Solvatech-in/Avri`, owner `arshadansari27`).** Deploy
#487 died at `npm run build` with `sh: 1: tsc: not found`: the manifest's
`NODE_ENV: production` reaches `npm ci` as a build arg and devDependencies are
skipped. Fixed in the repo ([Solvatech-in/Avri#2](https://github.com/Solvatech-in/Avri/pull/2),
`npm ci --include=dev`); deploy #489 is live, `/health` 200. `PUBLIC_BASE_URL`
env override set to the app's real host. Members added: `faheemshk`, `ezad9029`,
`kamdipravin4120`, `rolishri26` (the last two are not on the allowlist yet).
Open: the app's API keys and `DATABASE_URL` were entered as plain env vars, not
Secrets — move them if that matters.

**What users see.** Sessions stay valid. On next sign-in, one GitHub consent
screen for the App. Private repos are opt-in: New app → "Add or manage repos on
GitHub" → install the App on the repos to deploy. Sessions from before the switch
hold no token until the user signs out and in.
