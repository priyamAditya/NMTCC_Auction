# Deploying to Streamlit Community Cloud

This app is ready to host on [share.streamlit.io](https://share.streamlit.io).
It needs:

- Python 3.11+ (the Cloud default works)
- The `DATABASE_URL` for your Neon Postgres
- A reachable GitHub repo + branch (PR is open at
  https://github.com/Pavanraju45-ops/NMTCC_Auction/pull/1; the same code lives
  on `priyamAditya/NMTCC_Auction:feat/db-auth-setup-revamp`)

## One-time setup

1. Go to <https://share.streamlit.io> and sign in with GitHub. Authorize access
   to the repo you want to deploy.

2. Click **New app** → choose:
   - **Repository:** `priyamAditya/NMTCC_Auction` (or the upstream once merged)
   - **Branch:** `feat/db-auth-setup-revamp` (or `main` after merge)
   - **Main file:** `streamlit_app.py`
   - **App URL:** anything you want, e.g. `nmtcc-auction.streamlit.app`

3. Open **Advanced settings → Secrets** and paste your secrets in TOML form:

   ```toml
   DATABASE_URL = "postgresql://neondb_owner:<password>@ep-delicate-block-aobbs2mc.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
   ```

   (Use the exact URL that's currently in your local `.env`.)

4. Click **Deploy**. First build pulls `psycopg2-binary`, `Pillow`, `bcrypt`,
   `streamlit-aggrid`, `extra-streamlit-components` from PyPI — takes ~2 min.

5. When the app loads, the bcrypt admin you created locally is already in the
   `admins` table on Neon, so the same login works.

## What's stored where

- **Postgres (Neon)** — all durable state: admins, sessions (auth cookies),
  players, teams, tournaments scaffold, auctions, auction_teams,
  auction_players (with `unsold` + `released` flags), auction_results,
  team logos, player photos, tournament logos/banners (all BYTEA inline).
- **Local disk on the runner** — `data/events/<auction_id>.jsonl` event logs.
  These are intentionally not synced. They're rebuildable from auction_results
  for sales/RTM and are nice-to-have for the timeline. They survive reruns
  but not container restarts on the Cloud — that's fine, the timeline is
  best-effort.
- **Browser cookie** — `nmtcc_auth` (session token). 7-day expiry. The token
  resolves via the `sessions` table.

## Connecting to a different DB

Override `DATABASE_URL` in the Cloud's Secrets. The app will pick it up on
the next rerun. Schema is idempotent (`CREATE TABLE IF NOT EXISTS` + `ALTER
TABLE … ADD COLUMN IF NOT EXISTS`) so re-pointing at an empty Neon project
just runs the migrations once and you're live.

## Running locally

Same `.env` you already have works:

```
streamlit run streamlit_app.py
```

If you want to seed the player master from the form-response CSV:

```
python seed_players.py
```

(The CSV is gitignored; place it next to `streamlit_app.py` first.)
