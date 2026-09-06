# Overdue tasks → Cloudflare Worker → Google Sheets

Daily at **01:00 UTC**, a Cloudflare Worker calls Dexi’s overdue export API and appends each overdue work item as a row in a Google Sheet.

Dexi does **not** run a cron. The Worker is the scheduler and the Sheets writer.

## Prerequisites

- Dexi API deployed with env `OVERDUE_EXPORT_SECRET` set (same value you will put in the Worker).
- A Cloudflare account and [Wrangler](https://developers.cloudflare.com/workers/wrangler/install-and-update/) (`npm i -g wrangler` or `npx wrangler`).
- A Google account that can create Cloud projects and Sheets.

## 1. Create the Google Sheet

1. Create a new Google Spreadsheet.
2. Rename the first tab to `Sheet1` (or update `GOOGLE_SHEET_RANGE` later to match your tab name).
3. In row 1, add these headers (exactly these columns, left to right):

| A | B | C | D | E | F | G | H | I | J | K | L | M |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| as_of_date | generated_at | id | name | sequence_id | project_identifier | project_name | workspace_slug | state | priority | target_date | assignees | url |

4. Copy the **Spreadsheet ID** from the URL:

   `https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit`

## 2. Google Cloud service account

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable **Google Sheets API** (APIs & Services → Library → “Google Sheets API” → Enable).
4. **APIs & Services → Credentials → Create credentials → Service account**.
5. Create the service account; open it → **Keys → Add key → Create new key → JSON** → download the file.
6. From the JSON, note:
   - `client_email` → Worker secret `GOOGLE_SERVICE_ACCOUNT_EMAIL`
   - `private_key` → Worker secret `GOOGLE_PRIVATE_KEY`
7. Share your Google Sheet with the service account **email** as **Editor** (Share button on the Sheet).

## 3. Configure Dexi

1. Set on the API host (and redeploy / restart if needed):

   ```bash
   OVERDUE_EXPORT_SECRET=<long-random-string>
   ```

2. Confirm the endpoint (replace host and secret):

   ```bash
   curl -sS -H "X-Overdue-Export-Secret: <long-random-string>" \
     "https://dexi.dexqbit.com/api/instances/overdue-tasks/export/"
   ```

   Expect JSON with `overdue_count` and `tasks`. Wrong/missing secret → `401`.

## 4. Deploy the Worker

From this folder (`docs/overdue-export-worker/`):

```bash
cd docs/overdue-export-worker
npx wrangler login
```

Edit `wrangler.toml` if needed:

- `vars.DEXI_BASE_URL` — your Dexi origin (no trailing slash)
- `vars.GOOGLE_SHEET_RANGE` — default `Sheet1!A:M`
- `[triggers].crons` — default `0 1 * * *` = **01:00 UTC** every day

Set secrets (interactive prompts; paste values carefully):

```bash
npx wrangler secret put OVERDUE_EXPORT_SECRET
npx wrangler secret put GOOGLE_SHEET_ID
npx wrangler secret put GOOGLE_SERVICE_ACCOUNT_EMAIL
npx wrangler secret put GOOGLE_PRIVATE_KEY
```

For `GOOGLE_PRIVATE_KEY`, paste the full PEM from the JSON `private_key` field (including `BEGIN` / `END` lines). If Wrangler flattens newlines, store it as a single line with literal `\n` sequences — the Worker normalizes those.

Deploy:

```bash
npx wrangler deploy
```

Confirm in the Cloudflare dashboard that the Worker has a **Cron Trigger** of `0 1 * * *`.

### Timezone note

Cloudflare cron uses **UTC**. `0 1 * * *` is 1:00 AM UTC, not local time. Adjust the expression if you need another wall-clock hour (e.g. `0 20 * * *` ≈ 1:00 AM IST previous calendar day in UTC terms — pick the UTC hour that matches your local 1am).

## 5. Manual test (do not wait for 1am)

After deploy, open the Worker’s `*.workers.dev` URL (or your custom route) in a browser, or:

```bash
curl -sS "https://<your-worker>.workers.dev/"
```

That hits the same export + Sheets append path as the cron.

Check:

- Response JSON: `"ok": true`, `appended` equal to overdue count (or `appended: 0` if none).
- New rows under the header in your Sheet.

If Sheets returns 403, the Sheet is usually not shared with the service account email.

## 6. Local dry-run (optional)

```bash
cp .dev.vars.example .dev.vars
# edit .dev.vars
npx wrangler dev
# then curl http://127.0.0.1:8787/
```

## Behavior summary

| Step | What happens |
|------|----------------|
| Cron / HTTP | Worker runs |
| Dexi | `GET /api/instances/overdue-tasks/export/` with `X-Overdue-Export-Secret` |
| Empty list | Worker exits successfully; **no** Sheet rows written |
| Non-empty | Appends one row per task (history kept; does not clear old days) |

Dexi overdue rules: `target_date` before today (UTC), state group is **unstarted** or **started** only (backlog / completed / cancelled / other groups are excluded), not archived/draft/triage.
