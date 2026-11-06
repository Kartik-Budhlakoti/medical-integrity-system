# Known Issues

Things that are still broken or deferred, and things worth remembering before I touch this code again. If something isn't here, I either fixed it or haven't found it yet. Every route has tests now. 14 known bugs have tests marked "expected to fail" — `pytest -rx` lists them, and when I fix one, its test turns red until I delete the marker.

## On Render (live since 2026-11-04)

The timings here are single measurements from my laptop against the real service, not averages.

- **`/docs` doesn't load.** My `Content-Security-Policy` header blocks the Swagger UI files it pulls from a CDN (checked in a real browser). Either I turn docs off in production on purpose, or I allow those hosts.
- **What I tested on the live service.** Creating the first SuperAdmin, logging in, creating a user and a patient, uploading a file to Backblaze and downloading it again (the SHA-256 hash matched), and checking that a deactivated account gets a 401. After that I deleted `BOOTSTRAP_TOKEN` from Render and redeployed, and the old token now gets a 403. Login took about 2 s, upload 1.7 s and download 0.5 s. Login is slow because Render's free CPU is small and the password check (bcrypt at cost 12) is deliberately heavy.
- **The app now logs the visitor's real IP address.** Behind Render's proxy it used to see only Render's own internal address. `scripts/start.sh` now tells uvicorn which proxies it may believe about who is calling: `127.0.0.1`, `10.0.0.0/8` and Cloudflare's published address ranges. I checked it with two requests, a normal one and one with a faked `X-Forwarded-For: 6.6.6.6` header. Both were logged in `audit_logs` with my real public address.
- **That trusted-proxy list needs upkeep.** The Cloudflare ranges are a copy of cloudflare.com/ips from 2026-11-04, and I have to refresh them by hand. If Cloudflare adds a range and I don't, the app would log a Cloudflare address instead of the visitor's. `10.0.0.0/8` is also a big block to trust; it's there because Render's internal hop showed up as a 10.x address. And that Render sits behind Cloudflare is something I saw, not something Render promises.
- **The first request after a long idle took 22.9 s.** Render puts the free service to sleep after 15 minutes without traffic and wakes it on the next request. I measured this once, and I didn't separate Render waking up from Neon waking up. Someone opening the demo cold should expect to wait. The next request took 0.25 s.
- **Rate limits start over when the service restarts or wakes up.** Render has no `VALKEY_URL`, so the limiter keeps its counters in memory. That works with one worker, but a restart or a sleep wipes them.
- **My smoke test left test data in the live database.** Two deactivated throwaway Admins, two fake patients and two small files in the bucket. The audit log is append-only, so those rows stay.

## Smaller bugs

- `PATCH /patients/{id}` with a field sent as `null` crashes with a 500 instead of a clean 4xx (the columns are NOT NULL).
- Treatment notes accept blank text. Nursing notes reject it.
- A correctly signed token with odd contents (no role, unknown role) gives a 500 instead of a 401. It needs the signing key, so low risk. A token with no expiry is also accepted.
- Emails that differ only in capital letters (`A@x.com` vs `a@x.com`) are separate accounts.
- Login is much faster for an email that doesn't exist, so someone timing it could tell which emails are real. On Render an unknown email got its 401 in about 0.25 s and a known one took about 2.0 s (one measurement each).
- When the tamper check fails, the file is switched off but doesn't record why. The audit row does.
- `height_cm` and `weight_kg` can't be blank, so I can't create a patient in an emergency without real numbers. Fixing it means deciding how emergency admission should work, not loosening a constraint.
- Three spots check first and write second with no lock: bootstrap (two first callers), deactivating the last Admin, and assigning the same doctor twice (no unique index either). Low odds. I read these from the code and never reproduced them.
- The 50 MB upload limit is checked only after the whole file has been read into memory, so a too-big upload still uses the memory first. Render's free plan has 512 MiB.
- Small stuff: blood pressure is free text, lists have no paging, the password special-character list is narrow, the "not authorized to update" error prints a Python set.

## Decisions that have a cost (tests pin today's behaviour)

- A doctor or nurse who creates a patient can't open it until an admin assigns them.
- A doctor or nurse with no patients gets a 403 on the patient list, not an empty list.
- "Doesn't exist" (404) and "isn't yours" (403) are different answers, so they can tell which patient numbers exist.
- Changing a password doesn't end sessions that already exist (stateless JWT). Deactivating an account does, because every request looks the user up.
- Notes can't be edited or deleted. A wrong note stays; a correction is a new note with no link to the first.
- The upload check only looks at the first bytes of a file. A file that starts like a real PDF and then holds junk still passes. What really protects downloads is that the download route sends every file as a plain attachment (`application/octet-stream`), so a browser saves it instead of opening it. DICOM files without the 128-byte header are refused on purpose, and so are empty files. I don't know how common DICOM files without that header are.

## Logging and errors

- No plain 404 gets logged (wrong patient, user, file or assignment ID), and a few 400s aren't either (invalid role, bad file type, file too large, file contents that don't match the type). Real 403s are, except a wrong setup token on the bootstrap route. Low priority — mostly typos, not attacks.
- If an audit row names a user that doesn't exist, the database refuses it and `log_action` swallows the error, so nothing is recorded. This happens in the "user not found" branch of `change_password` and for a signed token with a made-up user ID.
- `action` values are plain strings typed at each call site. It can't be exploited from outside; the risk is me spelling one two ways. The tests hard-code a few of them.
- `entity_type` and `entity_id` don't always point at the same table. On purpose: when something is rejected before the real record exists, I log the real ID I have instead of a meaningless placeholder.
- Four broad `except Exception` blocks hide the real error (one in `audit.py`, two in upload — one of them a silent `pass` when cleaning up — and one in download). I can see that something failed but not why. Fix: log the exception in each. Bandit flags the silent `pass` too (Low). If that cleanup fails, the stored file stays in storage with no database row, and nothing records that the cleanup failed.

## Database and Docker

- **Missing server defaults.** `is_active` and several `created_at` columns have no real default in the database, even though the models say they do. The migration meant to fix it (`3c97235fa47a`) is empty. I only found out by running every migration from an empty database inside Docker for the first time; fixed it there. Checked on Neon in October 2026: all the `created_at` and `is_active` columns have their defaults there. Still not checked: my regular dev database (list those columns with no `column_default` in `information_schema.columns`). The tests can't catch this because they build tables from the models, not from the migrations. CI also runs `alembic upgrade head` and `alembic check` on an empty database (the `migration_check` step), with `compare_server_default` switched on in `env.py`.
- **A DB connection killed mid-query** (backend restart while a request is running) raises an unhandled `OperationalError`. `pool_pre_ping` only checks a connection before handing it out, so it can't help a query already in flight. Fixing it means real retry logic, so deferred.
- **Invalidated files are never deleted from B2.** The invalidate route only flips the DB row and the bucket has no lifecycle rule, so they sit there forever and the API's access block is the only protection. If I build it: hide the object in the invalidate route, and use only `daysFromHidingToDeleting` in the lifecycle rule — `daysFromUploadingToHiding` would also purge active files.
- **Docker is proven for:** B2 upload, download and tamper detection; rate limiting through Valkey under real load; RBAC on the specialty routes with the rejection in the audit log; a missing secret failing cleanly on first use (with no audit trail); and Postgres going down and coming back. **Not yet run through the container:** an unclean `docker kill`, a near-50 MB upload, and patients, assignments and notes.
- **Docker image:** it now runs as an unprivileged user (uid 1000), and `.dockerignore` keeps tests, dev files and caches out of it. The only folder I made writable for that user is `/app/uploads`, which only matters for local storage.

## Tooling

- Ruff only runs the error rules (`E4`, `E7`, `E9`, `F`). The wider set flagged 188 things, mostly import order, `Optional[X]` and `Depends()` in defaults. I left it until more routes had tests; they do now.
- Every Python package in the image is pinned exactly. Dependabot only edits lines that already exist, so when an update brings in a new dependency, I regenerate `requirements.txt` from the image's package list. GitHub's security alerts don't see `requirements-dev.txt` (its dependency graph doesn't list that file), so pytest, httpx2, ruff and bandit get no alerts. Their version updates still arrive, every three months.
- CI generates the test `SECRET_KEY` on each run. The password for the throwaway CI database is still written into `ci.yml`. It only guards a database that exists for the length of one run, but the repo is public, so my real passwords must never be the same.

## Test suite

- 430 pass, 14 expected to fail, about 90 seconds. Most of that is real bcrypt at the same cost the app uses — on purpose (see the decisions log).
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
- Commenting `@dependabot ignore this major version` on a PR got no reply in 14 hours. A rule in `dependabot.yml` is what works: the SQLAlchemy one replaced the failing group PR within about ten minutes.
- The runtime image has no pip, so `docker compose run … pip freeze` no longer works. Freeze the builder stage instead: `docker build --target builder -t freezecheck . && docker run --rm freezecheck pip freeze`.
- `--forwarded-allow-ips` replaces uvicorn's default of `127.0.0.1`; it doesn't add to it. My first version left `127.0.0.1` out and every audit row showed a `127.0.0.x` address, even though my local tests passed. After changing proxy settings, I look at the audit log on the real service.
- The app refuses to deactivate the last active Admin, and the SuperAdmin doesn't count as one. A smoke test that creates a throwaway Admin can't clean up after itself unless another Admin exists.
- Don't create `VALKEY_URL` on Render, not even an empty one. An empty variable reads as an empty string, and `limiter.py` would use that instead of falling back to `memory://`.
- A strict expected-to-fail test treats any error as the expected failure, even a `NameError` from a typo. A stray test with an undefined name once passed as "expected" for a while. When I add or remove a marker, I check why the test fails.