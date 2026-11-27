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
TEMPLATE_NAME = "Research Flow 360"  # Kit email template to wrap the email in, if it exists

# Same tokens and fonts as the website (assets/styles.css). Email apps that can't load the web fonts
# (Gmail, Outlook) fall back to the next font in each list.
PAPER, SURFACE, SURFACE2 = "#F5F6F1", "#FFFFFF", "#ECEFE8"
INK, INK2, INK3, LINE = "#0C1F1B", "#4A5A55", "#7C8A85", "#DCE1D8"
PINE, PINE_INK, PINE_MUTE, SIGNAL, UP, DOWN = "#0F3B32", "#EAF3EF", "#9FC0B5", "#FF5B23", "#12855A", "#C2410C"
F_DISPLAY = "'Bricolage Grotesque', 'Avenir Next', 'Segoe UI', Helvetica, Arial, sans-serif"
F_BODY = "Geist, 'Helvetica Neue', 'Segoe UI', Helvetica, Arial, sans-serif"
F_MONO = "'Geist Mono', 'SF Mono', Menlo, Consolas, 'Courier New', monospace"
FONTS_CSS = ("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800"
             "&family=Geist:wght@400..600&family=Geist+Mono:wght@400;500&display=swap")

LABEL = f"font:500 12px/1.4 {F_MONO};letter-spacing:.08em;text-transform:uppercase;color:{SIGNAL};margin:0 0 14px"
P = f"font:400 16px/1.65 {F_BODY};color:{INK};margin:0 0 14px"
SRC = f"font:400 13px/1.6 {F_BODY};color:{INK2};margin:0 0 4px"
LINK = f"color:{INK};text-decoration:underline;text-decoration-color:{INK3}"


# --------------------------------------------------------------------------- email HTML
def style_tags(h: str) -> str:
    """Give the site's section HTML inline styles (email apps ignore stylesheets)."""
    row = (lambda m: f'<tr><td style="font:500 13px/1.5 {F_MONO};color:{PINE};padding:11px 14px 11px 0;'
                     f'border-top:1px solid {LINE};white-space:nowrap;vertical-align:top">{m.group(1)}</td>'
                     f'<td style="font:400 15px/1.5 {F_BODY};color:{INK};padding:11px 0;border-top:1px solid {LINE}">'
                     f'{m.group(2)}</td></tr>')
    h = re.sub(r'<ul class="watch">(.*?)</ul>',
               lambda m: '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                         'style="border-collapse:collapse">'
                         + re.sub(r"<li><time>(.*?)</time><span>(.*?)</span></li>", row, m.group(1)) + "</table>",
               h, flags=re.S)
    # Quick hits: tag chip beside the headline, like the site
    h = re.sub(r'<div class="hit"><span class="hit__tag">(.*?)</span>',
               lambda m: f'<div style="padding:16px 0;border-top:1px solid {LINE}">'
                         f'<span style="display:inline-block;font:500 11px/1 {F_MONO};letter-spacing:.06em;'
                         f'text-transform:uppercase;color:{INK2};border:1px solid {LINE};background:{SURFACE};'
                         f'border-radius:6px;padding:6px 8px;margin:0 0 10px">{m.group(1)}</span>', h)
    rules = [
        ('<h2>', f'<h2 style="font:700 24px/1.2 {F_DISPLAY};letter-spacing:-.02em;color:{INK};margin:0 0 14px">'),
        ('<h3>', f'<h3 style="font:700 18px/1.3 {F_DISPLAY};letter-spacing:-.01em;color:{INK};margin:0 0 6px">'),
        ('<p>', f'<p style="{P}">'),
        ('<p class="src">', f'<p style="{SRC}">'),
        ('<div class="why"><strong>Why it matters</strong>',
         f'<div style="background:{SURFACE};border-left:3px solid {SIGNAL};border-radius:0 12px 12px 0;'
         f'padding:16px 18px;margin:4px 0 16px;font:400 16px/1.6 {F_BODY};color:{INK}">'
         f'<strong style="display:block;font:500 11px/1.4 {F_MONO};letter-spacing:.08em;text-transform:uppercase;'
         f'color:{INK2};margin:0 0 6px">Why it matters</strong>'),
        ('<div class="hits">', '<div>'),
        ('<ul class="plain-list">', f'<ul style="font:400 16px/1.65 {F_BODY};color:{INK};padding-left:20px;margin:0 0 14px">'),
        ('<div class="sponsor-box"><p class="issue__label">Sponsored</p>',
         f'<div style="background:{SURFACE};border:1px solid {LINE};border-radius:16px;padding:18px 20px">'
         f'<p style="font:500 11px/1.4 {F_MONO};letter-spacing:.08em;text-transform:uppercase;color:{INK3};'
         'margin:0 0 10px">Sponsored</p>'),
        ('<a href=', f'<a style="{LINK}" href='),
    ]
    for old, new in rules:
        h = h.replace(old, new)
    return h


def chart_html(sec: bs.Section) -> str:
    """Bar chart as a table (email apps don't show SVG). Last bar in signal orange, like the site."""
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
        color = SIGNAL if i == len(bars) - 1 else PINE
        rows.append(
            f'<tr><td style="font:400 12px/1.4 {F_MONO};color:{INK2};padding:5px 12px 5px 0;white-space:nowrap;width:1%">'
            f'{html.escape(label)}</td><td style="padding:5px 0"><table role="presentation" cellpadding="0" '
            f'cellspacing="0" width="{pct}%"><tr><td style="background:{color};height:20px;border-radius:6px;'
            f'font-size:0;line-height:0">&nbsp;</td></tr></table></td><td style="font:500 13px/1.4 {F_MONO};'
            f'color:{INK};padding:5px 0 5px 12px;white-space:nowrap;width:1%">{v:,.{dec}f}{html.escape(unit)}</td></tr>')
    cap = opts.get("caption", "")
    if base:
        cap = (cap + " " if cap else "") + f"Bars start at {base:,.{dec}f}{unit} to show the change."
    out = f'<h2>{bs.inline(title)}</h2>' if title else ""
    out += (f'<div style="background:{SURFACE};border:1px solid {LINE};border-radius:16px;padding:16px 18px;'
            f'margin:0 0 10px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
            + "".join(rows) + "</table></div>")
    if cap:
        out += f'<p class="src">{bs.inline(cap)}</p>'
    return out


def snapshot_html() -> str:
    """The market snapshot as on the website, from data/snapshot.json at the time the email is made."""
    path = bs.ROOT / "data" / "snapshot.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    items = data.get("items", [])
    if not items:
        return ""
    cells = []
    for it in items:
        kind = it.get("kind", "usd")
        if kind == "yield":
            chg, d = bs.fmt_sign(it.get("change"), 2, " pts"), it.get("change")
        else:
            chg, d = bs.fmt_sign(it.get("change_pct"), 2, "%"), it.get("change_pct")
        color = UP if (d or 0) > 0 else DOWN if (d or 0) < 0 else INK2
        cells.append(f'<td width="25%" style="padding:12px 10px;border-top:1px solid {LINE};border-left:1px solid {LINE};'
                     f'vertical-align:top"><div style="font:400 12px/1.3 {F_BODY};color:{INK2}">'
                     f'{html.escape(it.get("label", ""))}</div><div style="font:500 15px/1.5 {F_MONO};color:{INK};'
                     f'margin-top:4px">{bs.fmt_price(kind, it.get("price"))}</div><div style="font:400 12px/1.4 {F_MONO};'
                     f'color:{color}">{chg}</div></td>')
    rows = "".join("<tr>" + "".join(cells[i:i + 4]) + "</tr>" for i in range(0, len(cells), 4))
    label = "Market snapshot"
    if data.get("updated_at"):
        when = datetime.fromisoformat(data["updated_at"]).astimezone(bs.ET)
        label += (" · market close, " if data.get("session") == "close" else " · morning, ") + \
            f"{when.strftime('%a, %b')} {when.day}"
    return (f'<p style="{LABEL}"><span style="color:{UP}">&#9679;</span>&nbsp; {label}</p>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{SURFACE};'
            f'border:1px solid {LINE};border-radius:16px;border-collapse:separate;border-spacing:0;overflow:hidden;'
            f'margin:0 0 10px">{rows}</table>'
            f'<p style="{SRC}">Funds that track each index, plus bitcoin, from Finnhub; 10-year yield from the U.S. '
            f'Treasury. <a style="{LINK}" href="{SITE_URL}brief.html">Live numbers on the website</a>.</p>')


def section_block(inner: str, first: bool = False) -> str:
    border = "" if first else f"border-top:1px solid {LINE};"
    return f'<tr><td style="padding:28px 28px 22px;{border}">{inner}</td></tr>'


def email_html(issue: bs.Issue) -> str:
    web = SITE_URL + issue.url
    title = bs.inline(issue.title).replace("<em>", f'<em style="font-style:normal;color:{SIGNAL}">')
    out = [
        # Thin pine bar, like the top of the website
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER}">'
        f'<tr><td style="background:{PINE};padding:11px 28px;font:500 13px/1.4 {F_BODY};color:{PINE_INK}">'
        f'Research Flow 360 <span style="color:{PINE_MUTE}">&nbsp;|&nbsp; Free daily markets brief</span></td></tr>',
        # Brand row
        f'<tr><td style="padding:22px 28px 0"><a href="{SITE_URL}" style="text-decoration:none;color:{INK}">'
        f'<img src="{SITE_URL}assets/email-logo.png" width="32" height="32" alt="" '
        f'style="vertical-align:middle;border:0;border-radius:9px">'
        f'<span style="vertical-align:middle;font:700 18px/32px {F_DISPLAY};letter-spacing:-.01em;color:{INK};'
        f'padding-left:10px">Research Flow 360</span></a></td></tr>',
        # Masthead: label, headline, summary
        section_block(
            f'<p style="font:400 12px/1.4 {F_MONO};letter-spacing:.08em;text-transform:uppercase;color:{INK2};'
            f'margin:0 0 16px"><span style="color:{SIGNAL}">&#9632;</span>&nbsp; {html.escape(issue.type_name)} · '
            f'{bs.long_date(issue.date)}</p>'
            f'<h1 style="font:800 34px/1.06 {F_DISPLAY};letter-spacing:-.035em;color:{INK};margin:0 0 14px">{title}</h1>'
            + (f'<p style="font:400 17px/1.55 {F_BODY};color:{INK2};margin:0 0 16px">{bs.inline(issue.summary)}</p>'
               if issue.summary else "")
            + f'<p style="font:400 12px/1.5 {F_MONO};color:{INK2};margin:0">'
              + (f'{html.escape(issue.read_time)} min read · ' if issue.read_time else "")
              + f'<a style="{LINK}" href="{web}">Read on the web</a></p>', first=True),
    ]
    snap = snapshot_html()
    if snap:
        out.append(section_block(snap))
    for sec in issue.sections:
        key = sec.name.lower()
        body = chart_html(sec) if key in ("chart of the day", "chart") else bs.RENDERERS.get(key, bs.render_generic)(sec)
        label = "" if key in ("sponsor", "sponsored") else f'<p style="{LABEL}">{html.escape(sec.name)}</p>'
        out.append(section_block(label + style_tags(body)))
    out.append(
        f'<tr><td style="background:{PINE};padding:26px 28px;font:400 13px/1.65 {F_BODY};color:{PINE_MUTE}">'
        f'<div style="font:700 17px/1.3 {F_DISPLAY};color:{PINE_INK};margin:0 0 8px">Research Flow 360</div>'
        f'A free daily markets brief, reviewed by our editor before it is sent. It is news and education, '
        f'not investment advice, and never recommends buying or selling any security.<br><br>'
        f'<a style="color:{PINE_INK}" href="{SITE_URL}brief.html">Today\'s brief</a> &nbsp;·&nbsp; '
        f'<a style="color:{PINE_INK}" href="{SITE_URL}archive.html">Archive</a> &nbsp;·&nbsp; '
        f'<a style="color:{PINE_INK}" href="{SITE_URL}advertise.html">Advertise</a></td></tr></table>')
    return ('<div style="background:' + PAPER + ';margin:0 auto;max-width:640px">' + "\n".join(out) + "</div>")


def preview_page(issue: bs.Issue) -> str:
    return (f'<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'
            f'<title>{bs.attr(issue.title)}</title><link rel="stylesheet" href="{FONTS_CSS}">'
            f'<body style="margin:0;background:{SURFACE2};padding:24px 0">{email_html(issue)}</body>')


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


def template_id() -> int | None:
    """Use the Kit email template named "Research Flow 360" if the editor created it."""
    for t in kit("GET", "/email_templates").get("email_templates", []):
        if (t.get("name") or "").strip().lower() == TEMPLATE_NAME.lower():
            return t.get("id")
    return None


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
        out.write_text(preview_page(issue), encoding="utf-8")
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
    tid = template_id()
    for issue in sorted(fresh, key=lambda i: i.slug):
        if already_in_kit(issue.slug):
            print(f"{issue.slug}: already in Kit, skipped.")
            ledger[issue.slug] = {"status": "already in Kit"}
            continue
        body = {"subject": bs.plain(issue.title), "preview_text": bs.plain(issue.summary)[:140],
                "content": email_html(issue), "description": MARK + issue.slug, "public": False}
        if tid:
            body["email_template_id"] = tid
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
