#!/usr/bin/env python3
"""Monitor sellers.json files across ad-tech domains: daily diff, dashboard and email.

Usage:
    python3 sellers_monitor.py              # fetch, diff, save, update dashboard, send email
    python3 sellers_monitor.py --dry-run    # fetch + diff, print report, change nothing
    python3 sellers_monitor.py --no-email   # everything except the email
    python3 sellers_monitor.py --dashboard  # only rebuild dashboard.html from the logs

Files (next to this script):
    domains.txt     one domain per line (e.g. rubiconproject.com); '#' for comments
    config.env      SMTP settings (see config.env.example)
    state/          last snapshot per domain (<domain>.json)
    history/        dated raw copies of every fetch
    reports/        dated HTML report of every run
    changes.jsonl   every new / removed / changed seller ever found (one JSON per line)
    runs.jsonl      one line per domain per run (seller count, totals, errors)
    dashboard.html  open in a browser; rebuilt after every run

Stdlib only — no pip install needed.
"""
import argparse
import datetime as dt
import gzip
import html
import json
import os
import re
import smtplib
import ssl
import sys
import urllib.request
from email.message import EmailMessage
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / "state"
HISTORY = BASE / "history"
REPORTS = BASE / "reports"
DOMAINS_FILE = BASE / "domains.txt"
CHANGES_LOG = BASE / "changes.jsonl"
RUNS_LOG = BASE / "runs.jsonl"
DASHBOARD = BASE / "dashboard.html"
DASHBOARD_TEMPLATE = BASE / "dashboard_template.html"
TRACKED_FIELDS = ("name", "domain", "seller_type", "is_confidential", "is_passthrough")
USER_AGENT = "Mozilla/5.0 (compatible; sellers-json-monitor/1.0)"


def ssl_context():
    """Default CA store, falling back to certifi or the macOS system bundle
    (python.org installs on macOS often ship without CA certificates)."""
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats()["x509_ca"]:
        return ctx
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    if Path("/etc/ssl/cert.pem").exists():
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ctx


# ---------- config ----------

def load_env(path):
    """Read KEY=VALUE lines into os.environ (existing env vars win)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def normalize_domain(text):
    """Accept "pubmatic.com", "https://www.pubmatic.com/sellers.json", etc. Returns "" if invalid."""
    d = text.strip().lower().replace("https://", "").replace("http://", "").split("/", 1)[0]
    d = d.removeprefix("www.")
    return d if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", d) else ""


def load_domains(path=None):
    path = path or DOMAINS_FILE
    if not path.exists():
        return []
    domains = [normalize_domain(line.split("#", 1)[0]) for line in path.read_text().splitlines()]
    return list(dict.fromkeys(d for d in domains if d))


def add_domain(domain):
    lines = DOMAINS_FILE.read_text().splitlines() if DOMAINS_FILE.exists() else []
    if domain not in load_domains():
        lines.append(domain)
        DOMAINS_FILE.write_text("\n".join(lines) + "\n")


def remove_domain(domain):
    lines = DOMAINS_FILE.read_text().splitlines()
    kept = [l for l in lines if normalize_domain(l.split("#", 1)[0]) != domain]
    DOMAINS_FILE.write_text("\n".join(kept) + "\n")


# ---------- fetch ----------

def fetch_sellers(domain):
    url = f"https://{domain}/sellers.json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data.get("sellers"), list):
        raise ValueError("response has no 'sellers' array")
    return data


def index_sellers(data):
    out = {}
    for s in data.get("sellers", []):
        sid = str(s.get("seller_id", "")).strip()
        if sid:
            out[sid] = {f: s.get(f) for f in TRACKED_FIELDS if f in s}
    return out


# ---------- diff ----------

def diff(old, new):
    added = [dict(seller_id=k, **new[k]) for k in new.keys() - old.keys()]
    removed = [dict(seller_id=k, **old[k]) for k in old.keys() - new.keys()]
    changed = []
    for k in old.keys() & new.keys():
        deltas = {f: (old[k].get(f), new[k].get(f)) for f in TRACKED_FIELDS
                  if old[k].get(f) != new[k].get(f)}
        if deltas:
            changed.append({"seller_id": k, "name": new[k].get("name"), "changes": deltas})
    key = lambda r: (str(r.get("name") or "").lower(), r["seller_id"])
    return sorted(added, key=key), sorted(removed, key=key), sorted(changed, key=key)


# ---------- report ----------

CSS = """
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1f2328;max-width:980px}
h1{font-size:20px} h2{font-size:17px;margin-top:28px;border-bottom:1px solid #d0d7de;padding-bottom:4px}
h3{font-size:14px;margin:14px 0 6px}
table{border-collapse:collapse;font-size:13px;margin-bottom:8px}
th,td{border:1px solid #d0d7de;padding:4px 8px;text-align:left;vertical-align:top}
th{background:#f6f8fa} .add{color:#1a7f37} .rem{color:#cf222e} .chg{color:#9a6700} .muted{color:#656d76}
"""


def _table(rows, cols):
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '') if r.get(c) is not None else ''))}</td>"
                         for c in cols) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def build_report(results, run_date):
    cols = ["seller_id", "name", "domain", "seller_type"]
    total_add = sum(len(r.get("added", [])) for r in results)
    total_rem = sum(len(r.get("removed", [])) for r in results)
    total_chg = sum(len(r.get("changed", [])) for r in results)

    # summary table
    summary_rows = []
    for r in results:
        if r.get("error"):
            status = f"ERROR: {r['error']}"
        elif r.get("baseline"):
            status = "baseline saved (first run)"
        else:
            status = "ok"
        summary_rows.append({"domain": r["domain"], "sellers": r.get("count", ""),
                             "new": len(r.get("added", [])), "removed": len(r.get("removed", [])),
                             "changed": len(r.get("changed", [])), "status": status})

    parts = [f"<style>{CSS}</style>",
             f"<h1>sellers.json changes — {run_date}</h1>",
             f"<p><b class='add'>{total_add} new</b> · <b class='rem'>{total_rem} removed</b> · "
             f"<b class='chg'>{total_chg} changed</b> across {len(results)} domains</p>",
             _table(summary_rows, ["domain", "sellers", "new", "removed", "changed", "status"])]
    text = [f"sellers.json changes — {run_date}",
            f"{total_add} new, {total_rem} removed, {total_chg} changed across {len(results)} domains", ""]

    for r in results:
        parts.append(f"<h2>{html.escape(r['domain'])}</h2>")
        text.append(f"=== {r['domain']} ===")
        if r.get("error"):
            parts.append(f"<p class='rem'>Fetch failed: {html.escape(r['error'])}</p>")
            text += [f"  Fetch failed: {r['error']}", ""]
            continue
        if r.get("baseline"):
            parts.append(f"<p class='muted'>First run — baseline of {r['count']} sellers saved. "
                         "Changes will be reported from the next run.</p>")
            text += [f"  Baseline saved ({r['count']} sellers)", ""]
            continue
        if not (r["added"] or r["removed"] or r["changed"]):
            parts.append("<p class='muted'>No changes.</p>")
            text += ["  No changes", ""]
            continue
        if r["added"]:
            parts.append(f"<h3 class='add'>New entities ({len(r['added'])})</h3>" + _table(r["added"], cols))
            text.append(f"  NEW ({len(r['added'])}):")
            text += [f"    + {s['seller_id']} | {s.get('name')} | {s.get('domain')} | {s.get('seller_type')}"
                     for s in r["added"]]
        if r["removed"]:
            parts.append(f"<h3 class='rem'>Removed ({len(r['removed'])})</h3>" + _table(r["removed"], cols))
            text.append(f"  REMOVED ({len(r['removed'])}):")
            text += [f"    - {s['seller_id']} | {s.get('name')} | {s.get('domain')} | {s.get('seller_type')}"
                     for s in r["removed"]]
        if r["changed"]:
            rows = [{"seller_id": c["seller_id"], "name": c["name"],
                     "change": "; ".join(f"{f}: {a!r} → {b!r}" for f, (a, b) in c["changes"].items())}
                    for c in r["changed"]]
            parts.append(f"<h3 class='chg'>Changed ({len(rows)})</h3>" + _table(rows, ["seller_id", "name", "change"]))
            text.append(f"  CHANGED ({len(rows)}):")
            text += [f"    ~ {c['seller_id']} | {c['name']} | {c['change']}" for c in rows]
        text.append("")

    subject = f"sellers.json daily: {total_add} new, {total_rem} removed, {total_chg} changed ({run_date})"
    if any(r.get("error") for r in results):
        subject += " — some fetches failed"
    return subject, "\n".join(parts), "\n".join(text)


# ---------- logs + dashboard ----------

def previous_date(domain, run_date):
    """Date of the last successful check (what today's diff is compared with)."""
    dates = [r["date"] for r in read_jsonl(RUNS_LOG)
             if r.get("exchange") == domain and not r.get("error") and r["date"] <= run_date]
    return max(dates) if dates else None


def append_logs(results, run_date):
    with CHANGES_LOG.open("a") as ch, RUNS_LOG.open("a") as runs:
        for r in results:
            runs.write(json.dumps({
                "date": run_date, "exchange": r["domain"], "since": r.get("since"),
                "sellers": r.get("count"), "new": len(r.get("added", [])),
                "removed": len(r.get("removed", [])), "changed": len(r.get("changed", [])),
                "baseline": bool(r.get("baseline")), "error": r.get("error")}, ensure_ascii=False) + "\n")
            rows = ([("new", s, "") for s in r.get("added", [])] +
                    [("removed", s, "") for s in r.get("removed", [])] +
                    [("changed", c, "; ".join(f"{f}: {a!r} → {b!r}" for f, (a, b) in c["changes"].items()))
                     for c in r.get("changed", [])])
            for kind, s, detail in rows:
                ch.write(json.dumps({
                    "date": run_date, "exchange": r["domain"], "since": r.get("since"), "change": kind,
                    "seller_id": s["seller_id"], "name": s.get("name"), "seller_domain": s.get("domain"),
                    "seller_type": s.get("seller_type"), "detail": detail}, ensure_ascii=False) + "\n")


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def dashboard_data():
    return {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "domains": load_domains(),
            "runs": read_jsonl(RUNS_LOG), "changes": read_jsonl(CHANGES_LOG),
            # set on GitHub: lets the web page link to "add partner" / "check now"
            "repo": os.environ.get("GITHUB_REPOSITORY")}


def build_dashboard(out=None):
    """Write dashboard.html with the data baked in (works without the local server)."""
    data = dashboard_data()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = DASHBOARD_TEMPLATE.read_text().replace("/*__DATA__*/null", payload)
    (Path(out) if out else DASHBOARD).write_text(page)


# ---------- email ----------

def email_configured():
    pw = os.environ.get("SMTP_PASSWORD", "")
    return bool(pw) and "PASTE_" not in pw

def send_email(subject, html_body, text_body):
    need = ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"missing settings in config.env: {', '.join(missing)}")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("EMAIL_FROM") or os.environ["SMTP_USER"]
    msg["To"] = os.environ["EMAIL_TO"]  # comma-separated for multiple recipients
    msg.set_content(text_body)
    msg.add_alternative(f"<html><body>{html_body}</body></html>", subtype="html")
    port = int(os.environ.get("SMTP_PORT", "587"))
    ctx = ssl_context()
    if port == 465:
        with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], port, context=ctx, timeout=60) as s:
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=60) as s:
            s.starttls(context=ctx)
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)


# ---------- check ----------

def check_domains(domains, run_date, save=True):
    """Fetch and diff each domain. With save=True, also update snapshots, history and logs."""
    for d in (STATE, HISTORY, REPORTS):
        d.mkdir(exist_ok=True)
    results = []
    for domain in domains:
        res = {"domain": domain}
        try:
            data = fetch_sellers(domain)
            new = index_sellers(data)
            res["count"] = len(new)
            snap = STATE / f"{domain}.json"
            if snap.exists():
                res["since"] = previous_date(domain, run_date)
                old = json.loads(snap.read_text())
                res["added"], res["removed"], res["changed"] = diff(old, new)
            else:
                res["baseline"] = True
            if save:
                snap.write_text(json.dumps(new, ensure_ascii=False))
                hdir = HISTORY / domain
                hdir.mkdir(exist_ok=True)
                (hdir / f"{run_date}.json").write_text(json.dumps(data, ensure_ascii=False))
        except Exception as e:  # keep going with other domains
            res["error"] = f"{type(e).__name__}: {e}"
        print(f"{domain}: " + (res.get("error") or
              ("baseline" if res.get("baseline") else
               f"{len(res['added'])} new, {len(res['removed'])} removed, {len(res['changed'])} changed")),
              file=sys.stderr)
        results.append(res)
    if save:
        append_logs(results, run_date)
        build_dashboard()
    return results


def manage_partner(add, remove):
    """Used by the GitHub "Add partner" / "Remove partner" requests. Exits non-zero with a message on failure."""
    domain = normalize_domain(add or remove)
    if not domain:
        sys.exit(f"'{add or remove}' doesn't look like a website name. Try something like openx.com")
    if remove:
        if domain not in load_domains():
            sys.exit(f"{domain} is not on the list.")
        remove_domain(domain)
        build_dashboard()
        print(f"Stopped watching {domain}.")
        return
    if domain in load_domains():
        sys.exit(f"{domain} is already on the list.")
    try:
        fetch_sellers(domain)
    except Exception as e:
        reason = "the file doesn't exist there" if "404" in str(e) else f"{type(e).__name__}: {e}"
        sys.exit(f"Couldn't read https://{domain}/sellers.json ({reason}). Check the spelling.")
    add_domain(domain)
    res = check_domains([domain], dt.date.today().isoformat())[0]
    print(f"Added {domain} with {res.get('count')} sellers. Changes will show from the next daily check.")


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="don't save snapshots or send email")
    ap.add_argument("--no-email", action="store_true", help="save snapshots and report, skip email")
    ap.add_argument("--dashboard", action="store_true", help="only rebuild dashboard.html")
    ap.add_argument("--dashboard-out", help="also write the dashboard to this path (used for the website)")
    ap.add_argument("--add", metavar="DOMAIN", help="add a partner and save its first list")
    ap.add_argument("--remove", metavar="DOMAIN", help="stop watching a partner")
    ap.add_argument("--domains", default=str(BASE / "domains.txt"))
    args = ap.parse_args()
    if args.add or args.remove:
        return manage_partner(args.add, args.remove)
    if args.dashboard:
        build_dashboard(args.dashboard_out)
        print(f"Dashboard updated: {args.dashboard_out or DASHBOARD}", file=sys.stderr)
        return

    load_env(BASE / "config.env")
    run_date = dt.date.today().isoformat()
    results = check_domains(load_domains(Path(args.domains)), run_date, save=not args.dry_run)

    subject, html_body, text_body = build_report(results, run_date)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{run_date}.html").write_text(f"<html><body>{html_body}</body></html>")

    if args.dry_run:
        print(text_body)
        return
    print(f"Dashboard updated: {DASHBOARD}", file=sys.stderr)
    if args.no_email:
        print(text_body)
        return
    if not email_configured():
        print("Email skipped: add your App Password to config.env to get the daily email.", file=sys.stderr)
        return
    send_email(subject, html_body, text_body)
    print(f"Email sent: {subject}", file=sys.stderr)


if __name__ == "__main__":
    main()
