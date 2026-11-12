# sellers.json monitor

**Dashboard (share this link with your team):** https://arielcopper6.github.io/sellers-json-monitor/

Every morning (08:00 Israel time in winter, 09:00 in summer) GitHub checks
`https://<partner>/sellers.json` for every partner in `domains.txt`, compares it with the
previous check, and records which sellers are **new**, **removed** or **changed**.
It runs on GitHub, so your Mac can be off.

## Using the dashboard
- Timeframe: Yesterday, last 7 / 30 / 90 days, all time, or your own dates.
- Changes are grouped by partner; filter by change type, seller type, or search a name.
- "Download CSV" exports what you see.

## Adding or removing a partner
Type it in the "Add partner" box (or click "Remove" on a row). A GitHub page opens:
click **Submit new issue**. About 2 minutes later the dashboard is updated and GitHub
replies on that page. Only people added to the project on GitHub can change the list
(Settings → Collaborators on github.com/ArielCopper6/sellers-json-monitor).

## Extra check (rarely needed)
On GitHub: Actions → Update dashboard → **Run workflow**. Extra checks are safe: each check
is compared with the one before it, and a day's checks are added up.

## Files
- `domains.txt` the partner list
- `changes.jsonl`, `runs.jsonl` full history the dashboard is built from
- `state/` the last seller list per partner
- `.github/workflows/update.yml` the daily job
- `server.py`, `install_schedule.sh` optional Mac-only version (not running)
