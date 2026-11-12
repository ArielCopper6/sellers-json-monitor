# sellers.json monitor

Every morning at 08:00 this checks `https://<website>/sellers.json` for every website in
`domains.txt`, compares it with the last check, and records which sellers are
**new**, **removed** or **changed**.

## See the results
- **Dashboard:** open **http://localhost:8765** in your web browser (bookmark it).
  - Add or remove partners, or click "Check all partners now".
  - Pick a timeframe (last 7 / 30 / 90 days, all time, or your own dates).
  - See changes grouped by partner; filter by change, seller type, or search a name.
  - "Download CSV" exports what you see.
  - `dashboard.html` is a read-only copy you can double-click if the address above doesn't open.
- **Email:** a daily summary, once your Google App Password is in `config.env`
  (until then the email is skipped and everything else still works).

## Common tasks
- Add a partner: use the box on the dashboard (or add a line to `domains.txt`).
- Run a check now: `python3 sellers_monitor.py`
- Change the time: `./install_schedule.sh 9 30` (09:30). Stop everything: `./install_schedule.sh --uninstall`
- Dashboard not opening? Run `./install_schedule.sh` again; see `dashboard.log`.
- If something looks wrong, open `monitor.log`.

The Mac must be on; if it was asleep at 08:00, the check runs when it wakes.

## Files
`changes.jsonl` and `runs.jsonl` hold the full history the dashboard is built from.
`state/` is the last list per website, `history/` keeps each day's raw file, `reports/` each day's email.
