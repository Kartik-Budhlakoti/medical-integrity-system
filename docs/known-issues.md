# Known Issues

Things that are still broken or deferred, and things worth remembering before I touch this code again. If something isn't here, I either fixed it or haven't found it yet. Every route has tests now. 16 known bugs have tests marked "expected to fail" — `pytest -rx` lists them, and when I fix one, its test turns red until I delete the marker.

## Fix before it goes public

- **Bootstrap route.** `POST /bootstrap/superadmin` needs no login, so whoever calls it first becomes SuperAdmin. After the first deploy I call it myself before sharing the URL.
- **Uploads are only checked by file extension.** A `.pdf` name is trusted at face value; nothing looks at the actual bytes. Saving it for the security pass.
- **Deactivated accounts can still log in.** They get a token, but it's rejected everywhere else. The audit log still says `LOGIN_SUCCESS`, and the person learns their password was right.
- **`/docs` doesn't load.** My `Content-Security-Policy` header blocks the Swagger UI files it pulls from a CDN (checked in a real browser). Either I turn docs off in production on purpose, or I allow those hosts.
- **The app may see the wrong client IP on Render.** Rate limits and audit rows use the address the app sees. Behind Render's proxy that is the proxy's address unless uvicorn is told to trust the forwarded header, so every visitor would share one rate-limit bucket and every audit row would show the same IP. Trusting everyone (`--forwarded-allow-ips="*"`) is worse: uvicorn then takes the leftmost address in `X-Forwarded-For`, which a visitor can fake. A small test app showed all three cases (default: the proxy's address; trust-all: the leftmost, fakeable address; trusting only the proxy's own address: the real client). What Render's proxy really sends has to be tested on the first deploy.

## Smaller bugs

- `PATCH /patients/{id}` with a field sent as `null` crashes with a 500 instead of a clean 4xx (the columns are NOT NULL).
- Treatment notes accept blank text. Nursing notes reject it.
- A correctly signed token with odd contents (no role, unknown role) gives a 500 instead of a 401. It needs the signing key, so low risk. A token with no expiry is also accepted.
- Emails that differ only in capital letters (`A@x.com` vs `a@x.com`) are separate accounts.
- Login is much faster for an email that doesn't exist, so someone timing it could tell which emails are real.
- When the tamper check fails, the file is switched off but doesn't record why. The audit row does.
- `height_cm` and `weight_kg` can't be blank, so I can't create a patient in an emergency without real numbers. Fixing it means deciding how emergency admission should work, not loosening a constraint.
- Three spots check first and write second with no lock: bootstrap (two first callers), deactivating the last Admin, and assigning the same doctor twice (no unique index either). Low odds. I read these from the code and never reproduced them.
- Small stuff: blood pressure is free text, lists have no paging, the password special-character list is narrow, the "not authorized to update" error prints a Python set, zero-byte uploads are accepted.

## Decisions that have a cost (tests pin today's behaviour)

- A doctor or nurse who creates a patient can't open it until an admin assigns them.
- A doctor or nurse with no patients gets a 403 on the patient list, not an empty list.
- "Doesn't exist" (404) and "isn't yours" (403) are different answers, so they can tell which patient numbers exist.
- Changing a password doesn't end sessions that already exist (stateless JWT). Deactivating an account does, because every request looks the user up.
- Notes can't be edited or deleted. A wrong note stays; a correction is a new note with no link to the first.

## Logging and errors

- No plain 404 gets logged (wrong patient, user, file or assignment ID), and a few 400s aren't either (invalid role, bad file type, file too large). Real 403s are. Low priority — mostly typos, not attacks.
- If an audit row names a user that doesn't exist, the database refuses it and `log_action` swallows the error, so nothing is recorded. This happens in the "user not found" branch of `change_password` and for a signed token with a made-up user ID.
- `action` values are plain strings typed at each call site. It can't be exploited from outside; the risk is me spelling one two ways. The tests hard-code a few of them.
- `entity_type` and `entity_id` don't always point at the same table. On purpose: when something is rejected before the real record exists, I log the real ID I have instead of a meaningless placeholder.
- Four broad `except Exception` blocks hide the real error (one in `audit.py`, two in upload — one of them a silent `pass` when cleaning up — and one in download). I can see that something failed but not why. Fix: log the exception in each.

## Database and Docker

- **Missing server defaults.** `is_active` and several `created_at` columns have no real default in the database, even though the models say they do. The migration meant to fix it (`3c97235fa47a`) is empty. I only found out by running every migration from an empty database inside Docker for the first time; fixed it there. Still not checked: my regular dev database, and Neon once it exists (list those columns with no `column_default` in `information_schema.columns`). The tests can't catch this because they build tables from the models, not from the migrations. CI also runs `alembic upgrade head` and `alembic check` on an empty database (the `migration_check` step), with `compare_server_default` switched on in `env.py`.
- **A DB connection killed mid-query** (backend restart while a request is running) raises an unhandled `OperationalError`. `pool_pre_ping` only checks a connection before handing it out, so it can't help a query already in flight. Fixing it means real retry logic, so deferred.
- **Invalidated files are never deleted from B2.** The invalidate route only flips the DB row and the bucket has no lifecycle rule, so they sit there forever and the API's access block is the only protection. If I build it: hide the object in the invalidate route, and use only `daysFromHidingToDeleting` in the lifecycle rule — `daysFromUploadingToHiding` would also purge active files.
- **Docker is proven for:** B2 upload, download and tamper detection; rate limiting through Valkey under real load; RBAC on the specialty routes with the rejection in the audit log; a missing secret failing cleanly on first use (with no audit trail); and Postgres going down and coming back. **Not yet run through the container:** an unclean `docker kill`, a near-50 MB upload, and patients, assignments and notes.
- **The Docker image carries test and dev files and runs as root.** The Dockerfile does `COPY . .` and `.dockerignore` doesn't exclude `tests/`, `requirements-dev.txt`, `ruff.toml` or `pytest.ini`. So all of those end up in the image. There's also no `USER` line, so the app runs as root inside the container. Harmless today (`.env` is excluded), but a production image shouldn't carry test code or run as root. Tidy up in the Phase 4 hardening pass.

## Tooling

- Ruff only runs the error rules (`E4`, `E7`, `E9`, `F`). The wider set flagged 188 things, mostly import order, `Optional[X]` and `Depends()` in defaults. I left it until more routes had tests; they do now.
- `requirements.txt` isn't fully pinned: `boto3>=1.34.0` and `redis>=6.2.0,<7.0.0` are ranges, and boto3's own dependencies (botocore and friends) aren't listed. It already shows: my venv has boto3 1.43.93 while the Docker image built from the same file has 1.43.114. Pin them once I've confirmed Backblaze still works with the pinned versions.
- CI uses a fixed test `SECRET_KEY` and database password written into `ci.yml`. They only guard a throwaway CI database, but the repo is public, so my real keys must never be the same. I'll generate the key at run time in the Phase 4 pass.

## Test suite

- 417 pass, 16 expected to fail, about 90 seconds. Most of that is real bcrypt at the same cost the app uses — on purpose (see the decisions log).
- The tests share one database and run in a fixed order set in `conftest.py`. Any single file also runs on its own.
- Rate limits exist on five routes (login, change password, upload, download, bootstrap) and each one is tested. The file list and invalidate routes have none.
- Not covered by tests: the real Backblaze bucket (tests are forced onto local storage), the real Alembic migrations, two requests at the same instant, and the `api` container.
- The tests drop and recreate their database every run, so they refuse to start unless `DATABASE_URL` points at a database ending in `_test` on `localhost` or `127.0.0.1`. Forgetting the `export` in a new terminal stops the run with "Refusing to drop/recreate…" and exit code 2.
- slowapi 0.1.10 (the newest release) raises a DeprecationWarning on Python 3.14 because it uses `asyncio.iscoroutinefunction`, which is slated for removal in 3.16.

## Notes to self

- Some config values are only read once, at startup. Editing `.env` while the app is running does nothing until I restart it.
- A shell variable I set without exporting it doesn't reliably reach a server started afterward. Real values go in `.env`.
- Inside `psql`, `$MY_VARIABLE` isn't a thing — it's read as a literal column name. It once matched a real column and silently updated six rows instead of one.
- Backblaze keeps deleted files as hidden versions by default. The app never sees them, but it explains leftover storage usage.
- Postgres 18 wants its data volume mounted at `/var/lib/postgresql`, not the old `/var/lib/postgresql/data`, and rejects the old path.
- Anything a running container creates on its own (like a migration file generated inside it) only exists in that container unless a folder is shared with my machine. I almost lost a real migration this way.
- Docker's DNS auto-detection guessed the wrong gateway on my network (`192.168.1.1`), so every outbound connection from a container hung, including Backblaze. The fix was explicit DNS servers (`8.8.8.8`, `1.1.1.1`) in Compose. If a container can't reach anything outside, check `ip route` early.
- A pytest traceback can print the whole database URL, password included. Run with `--tb=line` and don't paste raw output anywhere.
- `psql -c "A; B;"` runs both statements as one transaction, and `DROP DATABASE` / `CREATE DATABASE` refuse to run inside one. Use separate `-c` flags (or `autocommit = True` in psycopg2, which `conftest.py` does).
- `docker compose exec postgres psql ...` works without a published port because it runs inside the container. A program on the host, like pytest, needs the port published.
- Containers don't come back by themselves after a crash or a dead battery — Compose has no restart policy here. Run `docker compose up -d --wait postgres` before the tests; `--wait` returns once it's healthy.
- `alembic/env.py` imports every model by name so `Base.metadata` is complete, and `app/models/__init__.py` does the same for `create_all`. Ruff calls those imports unused and `ruff check --fix` deletes the ones in `env.py`. Never run autofix across the repo without reading `git diff` afterwards, and add every new model to both files.
- When a linter flags one line, change only that line. Ruff flagged a pointless `f` on one string in `patient.py`; I removed it from the neighbouring string too, which had `{blocked}` in it, and the message would have printed the braces literally.
- When a strict expected-to-fail test suddenly passes, the run goes red on purpose. The bug got fixed: delete the marker.
