# Decisions Log

Real trade-offs I made on this project, and why, written down so I don't have to reconstruct the reasoning from memory later.

## Early on

- Roles live in their own table instead of being a column on `users`. Gives me room for department info and other role-level stuff later without touching the user table itself.
- SuperAdmin only really exists to stop an Admin from being able to create another Admin. It can't do much else — and the one thing it can do, create the first SuperAdmin, locks itself out after the first use.
- Notes (treatment, nursing) are append-only. No editing, no deleting — a correction is just a new note, not a change to an old one.
- File integrity gets re-checked on every single access, not just once at upload. That's why the server fetches and re-hashes the actual bytes itself instead of handing back a link — a link would mean I stop being able to promise that guarantee the moment storage moves anywhere else.
- JWTs are stateless — no server-side session tracking. That means if I change a password or deactivate an account, any token issued before that keeps working until it naturally expires. Accepting that — real session tracking felt like more architecture than this project needs.
- Filenames are UUIDs on purpose, so nobody can guess or enumerate them.
- Swapped `passlib` and `python-jose` for direct `bcrypt` and `PyJWT` — both were unmaintained, and `python-jose` had an unpatched CVE. Wasn't optional, needed doing.

## Mid-build

- Nursing notes don't store weight. `patients.weight` already exists — storing it twice just means it can quietly drift out of sync with itself.
- Dropped `last_checked_at` entirely instead of finishing it. Same problem as weight — a stored value that has to be kept in sync by hand isn't worth the risk. If I ever need "last checked," I'll compute it from the notes themselves.
- Doctor specialty lives on `users`, not its own table — it's a fact about one person, not shared role data. Locked to a fixed list of values on purpose, since the whole point is filtering by it later, and free text would quietly break that.
- SuperAdmin can't assign or unassign patients. Not a practical use of that role — it's a safety net, not a day-to-day account.
- SuperAdmin can view the doctor list but can't touch someone's specialty. Viewing felt fine; editing clinical-adjacent data didn't.
- Built in a hard block against ever deactivating the last active Admin. Checked live, every time, not assumed.
- An Admin can't deactivate themselves. SuperAdmin can't be deactivated by anyone, period — no exceptions, since it's the one account that has to survive even if everything else gets compromised.
- The single-file response includes the real storage key; the list response doesn't. Seeing exactly where one upload landed is useful while I'm the only one testing it — showing that for every file in a list felt like more exposure than it's worth.
- Patient and file lists filter out inactive records and sort alphabetically. A deactivated doctor showing up in a list I'd use to assign patients would be actively misleading.

## Infrastructure

- Render for hosting, not Azure. Azure's actual free compute tier is limited and I wasn't confident it could run my Docker setup — the tier that could is bundled with a 12-month credit, which just brings back the "this runs out eventually" problem I was trying to avoid.
- Neon for the database instead of Render's own free Postgres — Render's free database wipes itself after 30 days of inactivity, Neon's doesn't expire.
- Ruled out AWS completely — the student credit runs out in 6 months, wrong fit for something I want to stay live indefinitely.
- Switched from Cloudflare R2 to Backblaze B2 for file storage. R2 needs a card or PayPal to activate — found that out by actually trying to sign up, not by reading about it. Checked B2 the same way before committing, across more than one source.
- Local disk for my own dev, B2 for anything real — the switch lives entirely inside `storage.py`, so nothing else in the app has to know or care which one is active. Looked at MinIO as the more "correct" version of this, decided it wasn't worth the extra setup right now.
- Turned on server-side encryption on the bucket, even though it means giving up Backblaze's snapshot feature. Fine trade — my actual safety net for this data is Neon plus my own hash verification, not a Backblaze snapshot.
- Pinned `redis` to the 6.x line instead of grabbing the newest 8.x release. 8.x had a live, dated compatibility issue with the rate-limiting library I'm using — newest isn't always safest.
- Kept Valkey even though a single-instance deployment doesn't really need shared rate-limit storage yet. Decided that on purpose, for the practice, not by default.
- Docker Compose is strictly for running things locally while I develop — never how this actually gets deployed. Realizing that early saved me from a lot of confused assumptions later.

## Audit logging

- Didn't add a field to track what a value changed from and to. Considered it for things like specialty updates, but these are rare, low-stakes admin actions where I can just look at the current value directly — not worth the extra column.
- Left `action` as plain strings for now instead of building a shared list of valid values. Confirmed it's not a security risk — nothing external ever touches this field — so it's really just a maintenance nice-to-have I'm putting off.
- `entity_type` not always matching `entity_id`'s real table is intentional, not sloppy — I'd rather log a real value that happens to belong elsewhere than log a meaningless placeholder just to keep the two fields "matching."
- When I hardened the logging function against its own commit failing, I didn't try to make every log call in the codebase fully atomic with its business logic. Would've meant touching around 40 call sites for a benefit that only really applies to a third of them. Fixed the actual dangerous part instead — a logging failure can no longer crash a request or hide a success — and left true atomicity for later, if it ever actually matters.