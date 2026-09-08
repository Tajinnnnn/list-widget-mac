# List — sync server

Serves the PWA and holds the authoritative document. Two endpoints, one
Postgres row.

    GET  /api/state   -> {"doc": <document|null>, "version": <int>}
    POST /api/state   <- {"doc": <document>}
                      -> {"doc": <merged>, "version": <int>}

Both require `Authorization: Bearer <SYNC_SECRET>`.

## Layout

| Path | What it is |
|---|---|
| `api/state.py` | Vercel entrypoint. A thin HTTP adapter — no decisions. |
| `../sync_api.py` | Auth, dispatch, validation, merge. All 24 tests hit this. |
| `../sync_store.py` | The Postgres read-merge-write. |
| `../vault_sync.py` | `merge_docs()` — the conflict resolution itself. |
| `devserver.py` | Local dev: in-memory store, no Vercel, no Postgres. |
| `schema.sql` | One table. Idempotent, safe to re-run. |

`build.sh` copies the three shared modules and `todo.html` in from the
parent directory. **Those copies are gitignored on purpose.** Vendoring
them into git is precisely how the server's merge and the Mac app's merge
would drift apart, which is the failure this design set out to avoid.
Edit the originals one directory up and re-run `build.sh`.

## Local development

    uv run python server/devserver.py
    # then open http://localhost:8787 and enter sync key: dev

Backed by `sync_api.InMemoryStore`, so the real request logic and the real
merge run — only storage and the HTTP adapter are stand-ins. `todo.html`
is served straight from the parent directory, so an edit shows up on
reload without running `build.sh`.

Server state is in memory: restarting empties the server-side document.
The browser's `localStorage` survives and the next push re-seeds the
server from it, which is itself worth exercising.

## Deploying

These need your Vercel and Neon accounts, so they are yours to run.

**1. A Postgres database.** Any Postgres works; Neon's free tier is the
cheap default. Create a project, copy the connection string, and apply the
schema:

    psql "$DATABASE_URL" -f server/schema.sql

**2. Pick a sync key.** This is the only credential, so make it long:

    python3 -c "import secrets; print(secrets.token_urlsafe(32))"

**3. Set both environment variables in Vercel** (Production scope):

    DATABASE_URL   the Postgres connection string
    SYNC_SECRET    the key from step 2

Env vars are baked in at build time, so **setting or changing either one
requires a redeploy** before it takes effect.

**4. Deploy.**

    ./server/deploy.sh

That runs `build.sh` and then `npx vercel --prod`.

> **`--prod` is not optional.** Bare `npx vercel` creates a *preview*
> deployment and does **not** move the production alias. That mistake left
> a sibling project serving 14-day-old code while every deploy looked
> green — and it is invisible, because the preview URL works fine. Verify
> with `npx vercel inspect <your-domain>` and check the commit and age.
> `vercel alias ls` will **not** tell you this: it lists aliases without
> saying which build they resolve to, which is exactly how a stale alias
> hides.

**5. Install on the iPhone.** Open the deployment URL in Safari, Share →
Add to Home Screen, then open it from the home screen and enter the sync
key under Settings → Device sync.

Add to Home Screen matters for more than the icon: an installed PWA gets
its own storage that is not subject to Safari's 7-day eviction of
script-writable storage, and it is the only form in which iOS will ever
allow Web Push if notifications get built later.

## Notes

- **The document is small.** The live document measured ~38 KB, so the
  whole thing is transferred per sync. No delta protocol is warranted.
- **The Mac stays the only writer of the Obsidian daily note.** The phone
  cannot reach `VAULT_ROOT`, so a task added on the phone reaches
  `## Tasks` the next time the Mac is awake, not instantly.
- **Losing the sync key is not losing data.** Every device keeps a full
  copy in `localStorage`; the key only gates the shared row.
- **Anyone with the URL and the key can read the list.** It is a to-do
  list, not money — but keep the key out of git, and note it is stored in
  the browser's `localStorage` on each device you connect.
