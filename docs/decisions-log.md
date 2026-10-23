# Decisions Log

Real trade-offs I made on this project, and why, written down so I don't have to reconstruct the reasoning from memory later.

## Early on

- Roles live in their own table instead of being a column on `users`. Gives me room for department info and other role-level stuff later without touching the user table itself.
- SuperAdmin exists mainly to stop an Admin from being able to create another Admin: an Admin can only create Doctor and Nurse accounts, and only SuperAdmin can create an Admin. It can also deactivate users and see the doctor list, but not much else. SuperAdmin accounts can't be made through the normal user route at all — only through the one-time bootstrap route, which refuses once a SuperAdmin exists.
- Notes (treatment, nursing) are append-only. No editing, no deleting — a correction is just a new note, not a change to an old one.
- File integrity gets re-checked on every single access, not just once at upload. That's why the server fetches and re-hashes the actual bytes itself instead of handing back a link — a link would mean I stop being able to promise that guarantee the moment storage moves anywhere else.
- JWTs are stateless — no server-side session tracking. That means changing a password doesn't end sessions that already exist: an old token keeps working until it expires (`ACCESS_TOKEN_EXPIRE_MINUTES` sets how long). Deactivating an account is different — every request looks the user up, so a deactivated user's token stops working right away. Accepting the password-change gap — real session tracking felt like more architecture than this project needs.
- Files are stored under random UUID names on purpose, so nobody can guess or enumerate storage keys. The original filename is kept only in the database.
- Swapped `passlib` and `python-jose` for direct `bcrypt` and `PyJWT`. passlib's last release was in 2020; python-jose went from 2021 to early 2025 without one and has known CVEs — two of them (CVE-2024-33663, CVE-2024-33664) were fixed in 3.4.0, and PyPI's vulnerability data lists others with no fixed release. Wasn't optional, needed doing.
- Invalidated files stay in B2 instead of being deleted right away. Same logic as the append-only notes — I'd rather be able to recover from a wrong invalidation, or show nothing was tampered with after the fact, than destroy the file the instant it's flagged invalid. The API already blocks normal access to it immediately. The delayed deletion itself isn't built yet (see `known-issues.md`), so for now they stay indefinitely.

## Mid-build

- Nursing notes don't store weight. `patients.weight` already exists — storing it twice just means it can quietly drift out of sync with itself.
- Dropped `last_checked_at` entirely instead of finishing it. Same problem as weight — a stored value that has to be kept in sync by hand isn't worth the risk. If I ever need "last checked," I'll compute it from the notes themselves.
- Doctor specialty lives on `users`, not its own table — it's a fact about one person, not shared role data. Locked to a fixed list of values on purpose, since the whole point is filtering by it later, and free text would quietly break that.
- SuperAdmin can't assign or unassign patients. Not a practical use of that role — it's a safety net, not a day-to-day account.
- SuperAdmin can view the doctor list but can't touch someone's specialty. Viewing felt fine; editing clinical-adjacent data didn't.
- Built in a hard block against ever deactivating the last active Admin. Checked live, every time, not assumed.
- An Admin can't deactivate themselves. SuperAdmin can't be deactivated by anyone, period — no exceptions, since it's the one account that has to survive even if everything else gets compromised.
- The upload response includes the real storage key (`file_path`); the file list response doesn't. Seeing exactly where one upload landed is useful while I'm the only one testing it — showing that for every file in a list felt like more exposure than it's worth.
- The doctors list — the one I use to pick someone to assign patients to — leaves out deactivated doctors and is sorted alphabetically by name. A deactivated doctor showing up there would be actively misleading. The patient and file lists don't work that way: doctors and nurses only see patients they're assigned to, patients are sorted newest first, and the file list is newest first and includes invalidated files, shown as inactive.

## Testing

- Kept the tests at full strength instead of making the run faster. Most of the roughly 90-second run is bcrypt: the suite hashes and checks passwords at the same cost the app uses (12). I built a cheaper-cost version that took my run from 88 s to 32 s and passed, then chose not to use it. With a cheaper hash the suite no longer exercises the cost the app really runs with, and I'd rather wait 90 seconds than trust a faster, weaker run.
- Known bugs that the tests find are marked as strict expected-to-fail instead of being fixed on the spot or left red. The run stays green, `pytest -rx` keeps the list of what's broken, and when I fix one its test turns red until I delete the marker — so a fix can't go unnoticed and a bug can't hide. 16 so far; `pytest -rx` lists them.
- Tests are forced onto local file storage, whatever `.env` says, so they can never write to the real Backblaze bucket.
- The test database is dropped and recreated on every run, so `conftest.py` refuses to start unless `DATABASE_URL` points at a database whose name ends in `_test` on `localhost` or `127.0.0.1`. A forgotten `export` stops the run instead of touching anything real.

## Access rules settled while writing tests

- A doctor or nurse who creates a patient isn't automatically assigned to it. Assignment stays an admin-only action, so the creator can't open their own patient until an admin assigns them. Known cost, left as is.
- A doctor or nurse with no assigned patients gets a 403 from the patient list, not an empty list. Left as is rather than changing the route this late.
- "Doesn't exist" (404) and "isn't yours" (403) stay different answers for now, which means a doctor or nurse can tell which patient numbers exist. Known cost, left as is.
- For all three, the tests pin today's behaviour, so changing any of them later means changing that one test on purpose.

## Infrastructure

Facts about outside services (prices, free tiers, limits) are as I found them when I made each decision, and they change. I re-checked the Render, Neon, Azure, AWS and Backblaze ones in October 2026.

- Render for hosting, not Azure. Azure's always-free App Service tier is limited (about an hour of compute a day) and I wasn't confident it could run my Docker setup. The free VM that could is only free for 12 months, which just brings back the "this runs out eventually" problem I was trying to avoid.
- Neon for the database instead of Render's own free Postgres. Render's free database expires 30 days after it's created, with a 14-day grace period before it's deleted (render.com/docs/free, checked 2026-10-21). Neon's free plan has no time limit (Neon's FAQ, checked 2026-10-21) — its compute scales to zero after 5 minutes idle, but the data stays.
- Ruled out AWS completely — its free plan lasts 6 months at most (or until the $200 in credits is used up, whichever comes first), wrong fit for something I want to stay live indefinitely.
- Switched from Cloudflare R2 to Backblaze B2 for file storage. R2 needs a card or PayPal to activate — found that out by actually trying to sign up, not by reading about it. Checked B2 the same way before committing, across more than one source.
- Local disk for my own dev, B2 for anything real — the switch lives entirely inside `storage.py`, so nothing else in the app has to know or care which one is active. Looked at MinIO as the more "correct" version of this, decided it wasn't worth the extra setup right now.
- Turned on server-side encryption on the bucket, even though it means encrypted files are left out of Backblaze's snapshots (their docs say so for snapshots made from the Browse Files page). Fine trade — my actual safety net for this data is Neon plus my own hash verification, not a Backblaze snapshot.
- Pinned `redis` to the 6.x line instead of grabbing the newest 8.x release. 8.x had a live, dated compatibility issue with the rate-limiting library I'm using — newest isn't always safest.
- Kept Valkey even though a single-instance deployment doesn't really need shared rate-limit storage yet. Decided that on purpose, for the practice, not by default.
- Docker Compose is strictly for running things locally while I develop — never how this actually gets deployed. Realizing that early saved me from a lot of confused assumptions later.
- Multi-stage Dockerfile, on purpose: build tools stay isolated in a throwaway first stage, only the finished venv and real code make it into the final image. Smaller image, smaller attack surface — matters more given the direction I'm taking this project.
- Chose the slim base image over alpine specifically because psycopg2 has known install friction against alpine's C library. Slightly bigger image, avoided a real, well-documented headache instead.
- Postgres and Valkey both pinned to major-version-only tags, not an exact patch and not a floating "latest" — same floor-without-ceiling logic I already used for the Python package pins.
- Postgres's port is never published to the host in Compose, on purpose. The only way in is through the container itself, which is actually the more secure path, not a limitation I'm accepting.
- The API container doesn't mount a live folder from my host — it builds as a sealed snapshot, matching what will actually run later, rather than being optimized for live-reloading convenience. Worth reconsidering once Docker's basic proof is further along, not settled forever.

## Audit logging

- Didn't add a field to track what a value changed from and to. Considered it for things like specialty updates, but these are rare, low-stakes admin actions where I can just look at the current value directly — not worth the extra column.
- Left `action` as plain strings for now instead of building a shared list of valid values. Confirmed it's not a security risk — nothing external ever touches this field — so it's really just a maintenance nice-to-have I'm putting off.
- `entity_type` not always matching `entity_id`'s real table is intentional, not sloppy — I'd rather log a real value that happens to belong elsewhere than log a meaningless placeholder just to keep the two fields "matching."
- When I hardened the logging function against its own commit failing, I didn't try to make every log call in the codebase fully atomic with its business logic. Would've meant touching around 40 call sites for a benefit that only really applies to a third of them. Fixed the actual dangerous part instead — a logging failure can no longer crash a request or hide a success — and left true atomicity for later, if it ever actually matters.
