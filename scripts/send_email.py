#!/usr/bin/env python3
"""Turn newly published issues into Research Flow 360 emails in Kit.

Runs in the publish workflow after an issue is approved (merged). For each new issue it creates a
Kit broadcast with the issue as a styled email.

    KIT_API_KEY=...  python3 scripts/send_email.py            # new issues only
    python3 scripts/send_email.py --preview issues/2026-11-30.md   # writes email-preview.html, sends nothing

KIT_SEND_MODE (a GitHub repository variable) decides what happens in Kit:
    draft     (default) the email waits in Kit > Send > Broadcasts; the editor taps Send.
    schedule  daily issues go out at 6:45 am ET on their date (or in 10 minutes if that has passed);
              alerts go out in 10 minutes.

New issue = not a sample, dated today or yesterday (ET), and not already in data/sent.json or Kit.
Without KIT_API_KEY it does nothing, so the site still publishes. Standard library only.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site as bs  # noqa: E402

SITE_URL = os.environ.get("RF360_SITE_URL", "https://gamegenesis01.github.io/research-flow-360/").rstrip("/") + "/"
LEDGER = bs.ROOT / "data" / "sent.json"
API = "https://api.kit.com/v4"
MARK = "rf360:"  # broadcast description marker, used to never create the same email twice

PINE, ORANGE, INK, MUTED, PAPER, LINE = "#0F3B32", "#FF5B23", "#14201C", "#5B6B65", "#F6F3EC", "#E4DED2"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


# --------------------------------------------------------------------------- email HTML
def style_tags(h: str) -> str:
    """Inline styles for email clients (they ignore stylesheets)."""
    rules = [
        (r'<h2>', f'<h2 style="font:700 22px/1.25 {FONT};color:{INK};margin:0 0 12px">'),
        (r'<h3>', f'<h3 style="font:700 17px/1.3 {FONT};color:{INK};margin:18px 0 6px">'),
        (r'<p>', f'<p style="font:16px/1.6 {FONT};color:{INK};margin:0 0 14px">'),
        (r'<p class="src">', f'<p style="font:13px/1.5 {FONT};color:{MUTED};margin:0 0 16px">'),
        (r'<figcaption class="src">', f'<p style="font:13px/1.5 {FONT};color:{MUTED};margin:8px 0 16px">'),
        (r'</figcaption>', '</p>'),
        (r'<div class="why"><strong>Why it matters</strong>',
         f'<div style="background:{PAPER};border-left:4px solid {ORANGE};padding:12px 14px;margin:0 0 14px;'
         f'font:15px/1.55 {FONT};color:{INK}"><strong style="display:block;color:{PINE};margin-bottom:4px">'
         'Why it matters</strong>'),
        (r'<div class="hits">', '<div>'),
        (r'<div class="hit">', f'<div style="padding:14px 0;border-top:1px solid {LINE}">'),
        (r'<span class="hit__tag">', f'<span style="display:inline-block;font:700 11px/1 {FONT};letter-spacing:.06em;'
                                     f'text-transform:uppercase;color:{ORANGE};margin-bottom:6px">'),
        (r'<ul class="plain-list">', f'<ul style="font:16px/1.6 {FONT};color:{INK};padding-left:20px;margin:0 0 14px">'),
        (r'<div class="sponsor-box"><p class="issue__label">Sponsored</p>',
         f'<div style="border:1px solid {LINE};border-radius:10px;padding:14px 16px">'
         f'<p style="font:700 11px/1 {FONT};letter-spacing:.06em;text-transform:uppercase;color:{MUTED};'
         'margin:0 0 10px">Sponsored</p>'),
        (r'<a href=', f'<a style="color:{PINE};font-weight:600" href='),
    ]
    # "What to watch" list → table (done first, so its </ul> becomes </table>)
    row = (lambda m: f'<tr><td style="font:700 14px/1.5 {FONT};color:{PINE};padding:8px 12px 8px 0;'
                     f'border-top:1px solid {LINE};white-space:nowrap;vertical-align:top">{m.group(1)}</td>'
                     f'<td style="font:15px/1.5 {FONT};color:{INK};padding:8px 0;border-top:1px solid {LINE}">'
                     f'{m.group(2)}</td></tr>')
    h = re.sub(r'<ul class="watch">(.*?)</ul>',
               lambda m: '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                         'style="border-collapse:collapse">'
                         + re.sub(r"<li><time>(.*?)</time><span>(.*?)</span></li>", row, m.group(1)) + "</table>",
               h, flags=re.S)
    for old, new in rules:
        h = h.replace(old, new)
    return h


def chart_html(sec: bs.Section) -> str:
    """Bar chart as a table (email clients don't show SVG)."""
    _, subs = bs.split_subsections(sec.lines)
    title, lines = subs[0] if subs else ("", sec.lines)
    bars, opts = [], {}
    for raw in lines:
        line = raw.strip()
        if line.startswith("- ") and ":" in line:
            label, val = re.split(r"\s+#", line[2:], maxsplit=1)[0].rsplit(":", 1)
            bars.append((label.strip(), float(val.strip().rstrip("%").replace(",", ""))))
        elif re.match(r"^(base|unit|caption|decimals):", line, re.I):
            k, v = line.split(":", 1)
            opts[k.lower()] = re.split(r"\s+#", v, maxsplit=1)[0].strip()
    base, dec, unit = float(opts.get("base", 0) or 0), int(opts.get("decimals", 2)), opts.get("unit", "")
    top = max(v for _, v in bars)
    rows = []
    for i, (label, v) in enumerate(bars):
        pct = max(4, round((v - base) / (top - base) * 100)) if top > base else 100
        color = ORANGE if i == len(bars) - 1 else PINE
        rows.append(
            f'<tr><td style="font:13px/1.4 {FONT};color:{MUTED};padding:4px 10px 4px 0;white-space:nowrap;width:1%">'
            f'{html.escape(label)}</td><td style="padding:4px 0"><table role="presentation" cellpadding="0" '
            f'cellspacing="0" width="{pct}%"><tr><td style="background:{color};height:18px;border-radius:4px;'
            f'font-size:0;line-height:0">&nbsp;</td></tr></table></td><td style="font:700 13px/1.4 {FONT};'
            f'color:{INK};padding:4px 0 4px 10px;white-space:nowrap;width:1%">{v:,.{dec}f}{html.escape(unit)}</td></tr>')
    cap = opts.get("caption", "")
    if base:
        cap = (cap + " " if cap else "") + f"Bars start at {base:,.{dec}f}{unit} to show the change."
    out = f'<h2>{bs.inline(title)}</h2>' if title else ""
    out += ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 6px">'
            + "".join(rows) + "</table>")
    if cap:
        out += f'<p class="src">{bs.inline(cap)}</p>'
    return out


def email_html(issue: bs.Issue) -> str:
    web = SITE_URL + issue.url
    title = bs.inline(issue.title).replace("<em>", f'<em style="font-style:normal;color:{ORANGE}">')
    parts = [
        f'<div style="max-width:620px;margin:0 auto;background:#ffffff">',
        f'<div style="background:{PINE};padding:18px 22px;border-radius:12px 12px 0 0">'
        f'<span style="font:800 20px/1 {FONT};color:#ffffff;letter-spacing:-.01em">Research Flow '
        f'<span style="color:{ORANGE}">360</span></span>'
        f'<span style="float:right;font:13px/20px {FONT};color:#cfe0d9">{bs.long_date(issue.date)}</span></div>',
        f'<div style="padding:22px 22px 6px">'
        f'<p style="font:700 12px/1 {FONT};letter-spacing:.08em;text-transform:uppercase;color:{ORANGE};margin:0 0 10px">'
        f'{html.escape(issue.type_name)}</p>'
        f'<h1 style="font:800 28px/1.2 {FONT};color:{INK};margin:0 0 10px">{title}</h1>'
        + (f'<p style="font:16px/1.55 {FONT};color:{MUTED};margin:0 0 6px">{bs.inline(issue.summary)}</p>'
           if issue.summary else "")
        + f'<p style="font:13px/1.5 {FONT};margin:0 0 4px"><a style="color:{PINE};font-weight:600" href="{web}">'
          'Read on the web, with today\'s live market snapshot →</a></p></div>',
    ]
    for sec in issue.sections:
        key = sec.name.lower()
        body = chart_html(sec) if key in ("chart of the day", "chart") else bs.RENDERERS.get(key, bs.render_generic)(sec)
        label = "" if key in ("the big story", "big story", "sponsor", "sponsored") else (
            f'<p style="font:700 12px/1 {FONT};letter-spacing:.08em;text-transform:uppercase;color:{MUTED};'
            f'margin:0 0 12px">{html.escape(sec.name)}</p>')
        parts.append(f'<div style="padding:18px 22px;border-top:1px solid {LINE}">{label}{style_tags(body)}</div>')
    parts.append(
        f'<div style="padding:18px 22px;border-top:1px solid {LINE};font:13px/1.6 {FONT};color:{MUTED}">'
        f'Research Flow 360 is a free daily markets brief. It is news and education, not investment advice. '
        f'<a style="color:{PINE}" href="{SITE_URL}archive.html">Past issues</a> · '
        f'<a style="color:{PINE}" href="{SITE_URL}">researchflow360</a></div></div>')
    return "\n".join(parts)


# --------------------------------------------------------------------------- Kit
def kit(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Kit-Api-Key": os.environ["KIT_API_KEY"], "Accept": "application/json",
                 "Content-Type": "application/json", "User-Agent": "research-flow-360"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Kit {method} {path} failed ({e.code}): {e.read().decode(errors='replace')[:400]}")


def already_in_kit(slug: str) -> bool:
    after = None
    for _ in range(10):  # newest 5,000 broadcasts is plenty
        q = "/broadcasts?per_page=500" + (f"&after={after}" if after else "")
        data = kit("GET", q)
        if any((b.get("description") or "") == MARK + slug for b in data.get("broadcasts", [])):
            return True
        page = data.get("pagination", {})
        if not page.get("has_next_page"):
            return False
        after = page.get("end_cursor")
    return False


def send_time(issue: bs.Issue, now: datetime) -> datetime:
    soon = now + timedelta(minutes=10)
    if issue.kind != "daily":
        return soon
    planned = datetime.combine(issue.date, time(6, 45), tzinfo=bs.ET)
    return max(planned, soon)


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--preview":
        issue = bs.parse_issue(Path(sys.argv[2]))
        out = bs.ROOT / "email-preview.html"
        out.write_text(f"<!doctype html><meta charset=utf-8><title>{bs.attr(issue.title)}</title>"
                       f'<body style="background:{PAPER};padding:20px 0">{email_html(issue)}</body>', encoding="utf-8")
        print(f"Preview written to {out.name} (nothing sent).")
        return 0
    if not os.environ.get("KIT_API_KEY"):
        print("KIT_API_KEY is not set: no email created.")
        return 0
    mode = (os.environ.get("KIT_SEND_MODE") or "draft").strip().lower()
    if mode not in ("draft", "schedule"):
        mode = "draft"

    now = datetime.now(bs.ET)
    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else {}
    fresh = [i for i in bs.load_issues()
             if not i.sample and i.slug not in ledger and i.date >= now.date() - timedelta(days=1)]
    if not fresh:
        print("No new issues to email.")
        return 0
    for issue in sorted(fresh, key=lambda i: i.slug):
        if already_in_kit(issue.slug):
            print(f"{issue.slug}: already in Kit, skipped.")
            ledger[issue.slug] = {"status": "already in Kit"}
            continue
        body = {"subject": bs.plain(issue.title), "preview_text": bs.plain(issue.summary)[:140],
                "content": email_html(issue), "description": MARK + issue.slug, "public": False}
        if mode == "schedule":
            body["send_at"] = send_time(issue, now).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        b = kit("POST", "/broadcasts", body).get("broadcast", {})
        ledger[issue.slug] = {"broadcast_id": b.get("id"), "mode": mode, "send_at": body.get("send_at"),
                              "created": now.isoformat(timespec="minutes")}
        print(f"{issue.slug}: Kit {'scheduled for ' + body['send_at'] if mode == 'schedule' else 'draft'} "
              f"(broadcast {b.get('id')}).")
    LEDGER.parent.mkdir(exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
