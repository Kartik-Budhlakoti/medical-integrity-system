# Known Issues

Things I know are still broken, deferred, or worth remembering before touching this code again. If something isn't here, treat it as resolved and tested.

## Still open

**File upload validation only checks the extension, not the actual content.** A `.pdf` extension is trusted at face value right now — nothing looks at the real bytes to confirm it. Leaving this for a dedicated security pass later rather than rushing a fix in now.

**Audit log `action` values are just plain strings**, typed out fresh at every call site instead of pulled from one shared list. Since `action` is never set from anything a client sends, this can't be exploited from outside — the real risk is just me spelling something two different ways in two different files, months apart, with nothing to warn me either way. Needs fixing eventually. Not right now.

**Two rejection branches in `assignment.py`** (bad role assigned, already assigned) don't log anything. Low priority — these are input mistakes, not anything worth flagging as suspicious.

**`entity_type` and `entity_id` on a log row don't always point at the same table.** When something gets rejected before the real record exists yet, I log whatever real ID I actually have on hand — usually a patient's ID — even if `entity_type` still says something else, like "files." Did this on purpose instead of logging a meaningless placeholder. Worth remembering next time something in these logs looks off.

**`patients.height_cm` and `weight_kg` can't be left blank**, which means I can't create a patient record — even during an emergency — without real numbers for both. No bypass exists for that case right now. Fixing it properly means deciding how emergency admission should actually work, not just loosening a constraint.

## Notes to self

- Some config values only get read once, when the app starts. Editing `.env` while it's already running does nothing until I actually restart it.
- A shell variable I set without exporting it doesn't reliably make it into a server process started afterward. Real values go in `.env`, not typed into the terminal first.
- Inside a `psql` session, `$MY_VARIABLE` isn't a thing — it gets read as a literal, lowercased column name. Learned this the hard way when it happened to match a real column and silently updated six rows instead of one.
- Backblaze keeps deleted files around as hidden versions by default instead of actually erasing them. The app never sees them again, so it doesn't matter functionally, but worth knowing before I'm confused by leftover storage usage later.