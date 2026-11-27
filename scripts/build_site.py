"""Build the Research Flow 360 website from templates/ and issues/.

    python3 scripts/build_site.py           # build every page into the repository root
    python3 scripts/build_site.py --check   # only validate the issue files (used on pull requests)

Pages written: index.html, brief.html (latest issue + live market snapshot), archive.html,
about.html, advertise.html, 404.html and one permanent page per issue in briefs/.
Issue format: see issues/TEMPLATE.md. Standard library only.
"""
from __future__ import annotations

import html
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ISSUES = ROOT / "issues"
TEMPLATES = ROOT / "templates"
ET = ZoneInfo("America/New_York")

TYPES = {"daily": ("The Daily Brief", "Daily", "pill--on"),
         "alert": ("Breaking alert", "Alert", "pill--beta"),
         "wrap": ("Weekend Wrap", "Wrap", "pill--off"),
         "inside": ("Inside Accel Trading", "Inside", "pill--beta")}

ISSUE_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})(-[a-z0-9-]+)?\.md$")


class IssueError(Exception):
    pass


# --------------------------------------------------------------------------- text helpers
def inline(text: str) -> str:
    """Escape HTML, then allow **bold**, *emphasis* and [links](https://...)."""
    t = html.escape(text, quote=False)

    def link(m):
        label, url = m.group(1), m.group(2)
        if not re.match(r"^https?://", url):
            raise IssueError(f"link must start with http:// or https://: {url}")
        return f'<a href="{html.escape(url, quote=True)}" rel="noopener">{label}</a>'

    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", t)
    return t


def plain(text: str) -> str:
    """Strip the markdown markers for places that need plain text (titles, meta tags)."""
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return t.replace("**", "").replace("*", "")


def attr(text: str) -> str:
    return html.escape(plain(text), quote=True)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", plain(text).lower()).strip("-")


# --------------------------------------------------------------------------- issue model
@dataclass
class Section:
    name: str
    lines: list[str]


@dataclass
class Issue:
    path: Path
    slug: str
    date: date
    kind: str
    title: str
    summary: str
    read_time: str
    sample: bool
    sections: list[Section] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"briefs/{self.slug}.html"

    @property
    def type_name(self) -> str:
        return TYPES[self.kind][0]


def parse_issue(path: Path) -> Issue:
    m = ISSUE_FILE.match(path.name)
    if not m:
        raise IssueError(f"{path.name}: file name must look like 2026-11-30.md or 2026-11-30-alert.md")
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise IssueError(f"{path.name}: must start with a --- header block")
    try:
        head, body = text[4:].split("\n---\n", 1)
    except ValueError:
        raise IssueError(f"{path.name}: the header block is not closed with ---")
    meta = {}
    for line in head.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            if ":" not in line:
                raise IssueError(f"{path.name}: header line needs 'name: value': {line!r}")
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.split(" #", 1)[0].strip()
    for req in ("date", "title"):
        if not meta.get(req):
            raise IssueError(f"{path.name}: missing '{req}:' in the header")
    try:
        d = date.fromisoformat(meta["date"])
    except ValueError:
        raise IssueError(f"{path.name}: date must be YYYY-MM-DD, got {meta['date']!r}")
    if meta["date"] != m.group(1):
        raise IssueError(f"{path.name}: date in the header ({meta['date']}) must match the file name")
    kind = meta.get("type", "daily").lower()
    if kind not in TYPES:
        raise IssueError(f"{path.name}: type must be one of {', '.join(TYPES)}, got {kind!r}")

    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    sections, current = [], None
    for line in body.splitlines():
        if line.startswith("## "):
            current = Section(line[3:].strip(), [])
            sections.append(current)
        elif current is not None:
            current.lines.append(line)
        elif line.strip():
            raise IssueError(f"{path.name}: text before the first '## ' section: {line[:60]!r}")
    if not sections:
        raise IssueError(f"{path.name}: needs at least one '## ' section")

    issue = Issue(path, path.stem, d, kind, meta["title"], meta.get("summary", ""),
                  meta.get("read_time", ""), meta.get("sample", "false").lower() in ("true", "yes", "1"),
                  sections)
    try:
        render_issue_sections(issue)  # validate everything now, so errors show on the pull request
    except IssueError:
        raise
    except Exception as exc:  # anything unexpected still names the file
        raise IssueError(f"{path.name}: could not read this issue ({exc})")
    return issue


def load_issues() -> list[Issue]:
    issues, errors = [], []
    for p in sorted(ISSUES.glob("*.md")):
        if p.name.upper().startswith("TEMPLATE") or p.name.upper() == "README.MD":
            continue
        try:
            issues.append(parse_issue(p))
        except IssueError as e:
            errors.append(str(e))
    if errors:
        raise IssueError("\n".join(errors))
    order = {"alert": 0, "daily": 1, "inside": 2, "wrap": 3}
    issues.sort(key=lambda i: (i.date, -order[i.kind]), reverse=True)
    return issues


# --------------------------------------------------------------------------- blocks
def blocks(lines: list[str]) -> list[tuple[str, str]]:
    """Group lines into ('p', text), ('why', text), ('src', text), ('li', text) blocks."""
    out, para = [], []

    def flush():
        if para:
            out.append(("p", " ".join(para)))
            para.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
        elif line.lower().startswith("> why it matters:"):
            flush()
            out.append(("why", line.split(":", 1)[1].strip()))
        elif line.startswith(">"):
            flush()
            out.append(("why", line.lstrip("> ").strip()))
        elif line.lower().startswith("source:") or line.lower().startswith("sources:"):
            flush()
            out.append(("src", line.split(":", 1)[1].strip()))
        elif line.startswith("- "):
            flush()
            out.append(("li", line[2:].strip()))
        else:
            para.append(line)
    flush()
    return out


def render_blocks(bl: list[tuple[str, str]]) -> str:
    parts, items = [], []

    def flush_list():
        if items:
            parts.append("<ul class=\"plain-list\">" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for kind, text in bl:
        if kind == "li":
            items.append(text)
            continue
        flush_list()
        if kind == "p":
            parts.append(f"<p>{inline(text)}</p>")
        elif kind == "why":
            parts.append(f'<div class="why"><strong>Why it matters</strong>{inline(text)}</div>')
        elif kind == "src":
            parts.append(f'<p class="src">Source: {inline(text)}</p>')
    flush_list()
    return "\n".join(parts)


def split_subsections(lines: list[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    intro, subs, cur = [], [], None
    for line in lines:
        if line.startswith("### "):
            cur = (line[4:].strip(), [])
            subs.append(cur)
        elif cur is None:
            intro.append(line)
        else:
            cur[1].append(line)
    return intro, subs


# --------------------------------------------------------------------------- sections
def render_big_story(sec: Section) -> str:
    intro, subs = split_subsections(sec.lines)
    out = []
    if subs:
        title, lines = subs[0]
        out.append(f"<h2>{inline(title)}</h2>")
        out.append(render_blocks(blocks(intro + lines)))
        for t, ls in subs[1:]:
            out.append(f"<h3>{inline(t)}</h3>\n{render_blocks(blocks(ls))}")
    else:
        out.append(render_blocks(blocks(intro)))
    return "\n".join(out)


def render_hits(sec: Section) -> str:
    _, subs = split_subsections(sec.lines)
    if not subs:
        raise IssueError(f"'{sec.name}' needs at least one '### ' story")
    out = ['<div class="hits">']
    for title, lines in subs:
        m = re.match(r"^\[([^\]]+)\]\s*(.+)$", title)
        tag, headline = (m.group(1), m.group(2)) if m else ("News", title)
        out.append(f'<div class="hit"><span class="hit__tag">{html.escape(tag)}</span>'
                   f"<h3>{inline(headline)}</h3>\n{render_blocks(blocks(lines))}</div>")
    out.append("</div>")
    return "\n".join(out)


def render_chart(sec: Section) -> str:
    _, subs = split_subsections(sec.lines)
    title, lines = subs[0] if subs else ("", sec.lines)
    bars, opts, extra = [], {}, []
    for raw in lines:
        line = raw.strip()
        if line.startswith("- ") and ":" in line:
            label, val = re.split(r"\s+#", line[2:], maxsplit=1)[0].rsplit(":", 1)
            try:
                bars.append((label.strip(), float(val.strip().rstrip("%").replace(",", ""))))
            except ValueError:
                raise IssueError(f"chart value must be a number: {line!r}")
        elif re.match(r"^(base|unit|caption|decimals):", line, re.I):
            k, v = line.split(":", 1)
            opts[k.lower()] = re.split(r"\s+#", v, maxsplit=1)[0].strip()
        else:
            extra.append(raw)
    if not 2 <= len(bars) <= 8:
        raise IssueError(f"'{sec.name}' needs 2 to 8 bars written as '- Label: 4.18'")
    try:
        base = float(opts.get("base", 0) or 0)
        dec = int(opts.get("decimals", 2))
    except ValueError:
        raise IssueError(f"'{sec.name}': base must be a number and decimals a whole number")
    unit = opts.get("unit", "")
    top = max(v for _, v in bars)
    if top <= base:
        raise IssueError(f"'{sec.name}': base ({base}) must be below the largest value")
    n = len(bars)
    slot = 540 / n
    bw = min(64, slot * 0.62)
    parts = ['<line class="fig-axis" x1="30" x2="590" y1="180" y2="180"/>']
    for i, (label, v) in enumerate(bars):
        h = max(0.0, (v - base) / (top - base) * 112)
        x = 40 + i * slot + (slot - bw) / 2
        cls = "fig-bar fig-bar--last" if i == n - 1 else "fig-bar"
        cx = x + bw / 2
        parts.append(f'<rect class="{cls}" x="{x:.1f}" y="{180 - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="6"/>')
        parts.append(f'<text class="fig-val" x="{cx:.1f}" y="{172 - h:.1f}" text-anchor="middle">'
                     f"{v:,.{dec}f}{html.escape(unit)}</text>")
        parts.append(f'<text class="fig-txt" x="{cx:.1f}" y="202" text-anchor="middle">{html.escape(label)}</text>')
    aria = f"{plain(title)}: " + ", ".join(f"{l} {v:,.{dec}f}{unit}" for l, v in bars)
    cap = opts.get("caption", "")
    if base:
        cap = (cap + " " if cap else "") + f"Bars start at {base:,.{dec}f}{unit} to show the change."
    out = []
    if title:
        out.append(f"<h2>{inline(title)}</h2>")
    out.append(f'<figure class="figure"><svg viewBox="0 0 600 220" role="img" aria-label="{attr(aria)}">'
               + "".join(parts) + "</svg>"
               + (f'<figcaption class="src">{inline(cap)}</figcaption>' if cap else "") + "</figure>")
    if any(l.strip() for l in extra):
        out.append(render_blocks(blocks(extra)))
    return "\n".join(out)


def render_watch(sec: Section) -> str:
    items = []
    for raw in sec.lines:
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("- ") or "|" not in line:
            raise IssueError(f"'{sec.name}' lines must look like '- 8:30 am | Jobless claims': {line!r}")
        when, what = line[2:].split("|", 1)
        items.append(f"<li><time>{html.escape(when.strip())}</time><span>{inline(what.strip())}</span></li>")
    return '<ul class="watch">' + "".join(items) + "</ul>"


def render_sponsor(sec: Section) -> str:
    return ('<div class="sponsor-box"><p class="issue__label">Sponsored</p>'
            + render_blocks(blocks(sec.lines)) + "</div>")


def render_generic(sec: Section) -> str:
    intro, subs = split_subsections(sec.lines)
    out = [render_blocks(blocks(intro))] if any(l.strip() for l in intro) else []
    for t, ls in subs:
        out.append(f"<h3>{inline(t)}</h3>\n{render_blocks(blocks(ls))}")
    return "\n".join(out)


RENDERERS = {"the big story": render_big_story, "big story": render_big_story,
             "quick hits": render_hits, "chart of the day": render_chart, "chart": render_chart,
             "what to watch": render_watch, "what to watch today": render_watch,
             "sponsor": render_sponsor, "sponsored": render_sponsor}


def render_issue_sections(issue: Issue) -> list[tuple[str, str, str]]:
    """Return (id, label, html) for each section. Raises IssueError on bad content."""
    out, seen = [], set()
    for sec in issue.sections:
        key = sec.name.lower()
        try:
            body = RENDERERS.get(key, render_generic)(sec)
        except IssueError as e:
            raise IssueError(f"{issue.path.name}: {e}")
        sid = slugify(sec.name) or "section"
        while sid in seen:
            sid += "-2"
        seen.add(sid)
        out.append((sid, sec.name, body))
    return out


# --------------------------------------------------------------------------- market snapshot
def fmt_price(kind: str, v) -> str:
    if v is None:
        return "—"
    if kind == "yield":
        return f"{v:.2f}%"
    return f"${v:,.0f}" if kind == "usd0" else f"${v:,.2f}"


def fmt_sign(v, digits: int, suffix: str) -> str:
    if v is None:
        return ""
    s = "+" if v > 0 else "−" if v < 0 else ""
    return f"{s}{abs(v):.{digits}f}{suffix}"


def snapshot_section() -> str:
    path = ROOT / "data" / "snapshot.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    cells = []
    for it in data.get("items", []):
        kind = it.get("kind", "usd")
        if kind == "yield":
            chg, direction = fmt_sign(it.get("change"), 2, " pts"), it.get("change")
        else:
            chg, direction = fmt_sign(it.get("change_pct"), 2, "%"), it.get("change_pct")
        cls = "chg-up" if (direction or 0) > 0 else "chg-down" if (direction or 0) < 0 else ""
        start = (data.get("start") or {}).get(it.get("key"))
        if data.get("session") == "close" and start and it.get("price"):
            note = "8 am: " + fmt_price(kind, start)
        elif it.get("as_of") and it.get("as_of") != data.get("date"):
            note = "as of " + it["as_of"][5:].replace("-", "/")
        else:
            note = ""
        cells.append(f'<div data-key="{attr(it.get("key", ""))}"><span>{html.escape(it.get("label", ""))}</span>'
                     f'<b>{fmt_price(kind, it.get("price"))}</b><i class="{cls}">{chg}</i><small>{note}</small></div>')
    if data.get("updated_at"):
        when = datetime.fromisoformat(data["updated_at"]).astimezone(ET)
        label = ("Market close" if data.get("session") == "close" else "Morning update")
        hour = when.strftime("%I:%M %p").lstrip("0")
        label = f"Market snapshot · {label}, {hour} ET, {when.strftime('%a, %b')} {when.day}"
    else:
        label = "Market snapshot"
    return f'''    <section class="issue__section" id="snapshot" aria-labelledby="h-snapshot" data-snapshot>
      <p class="issue__label" id="h-snapshot"><span class="live-dot" aria-hidden="true"></span><span data-snapshot-label>{label}</span></p>
      <div class="snapshot">
        {"".join(cells)}
      </div>
      <p class="src">Funds that track each index, plus bitcoin, from Finnhub; 10-year yield from the U.S. Treasury. Updated every weekday at about 8:05 am and 4:20 pm ET.</p>
    </section>'''


# --------------------------------------------------------------------------- page chrome
RF_MARK = ('<svg class="brand__mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="9" '
           'class="mark-bg"/><path d="M23.5 16a7.5 7.5 0 1 1-2.2-5.3" class="mark-a"/><path d="M22 6.8v4.4h-4.4" '
           'class="mark-a"/><circle cx="16" cy="16" r="2.2" class="mark-dot"/></svg>')
RF_ICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' "
           "height='32' rx='9' fill='%230F3B32'/%3E%3Cpath d='M23.5 16a7.5 7.5 0 1 1-2.2-5.3M22 6.8v4.4h-4.4' fill='none' "
           "stroke='%23F6F7F3' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/%3E%3Ccircle cx='16' "
           "cy='16' r='2.2' fill='%23FF5B23'/%3E%3C/svg%3E")
BRAND = f'{RF_MARK}\n      <span class="brand__name brand__name--rf">Research Flow 360</span>'
NAV = [("brief", "brief.html", "Today's brief"), ("archive", "archive.html", "Archive"),
       ("about", "about.html", "About"), ("advertise", "advertise.html", "Advertise")]
FOOTER_LEGAL = (
    "Research Flow 360 is published by Accel Financial Solutions, part of Accel Global Holdings. It publishes general "
    "market news for everyone; it is not investment advice and never recommends buying or selling any security. "
    "Sponsored content is labelled. Accel Media Ltd is an affiliated company and its stories are labelled when cited. "
    "Accel Trading results reported in the monthly section are for information only and are not an offer of any "
    "product. Issues marked as samples are illustrations.")
SITE = "https://gamegenesis01.github.io/research-flow-360/"


def page(*, active: str, title: str, desc: str, body: str, path: str, cta: str = "#start") -> str:
    up = "../" * path.count("/")
    home = up or "./"
    links = "".join(f'<a href="{up}{href}"{" aria-current=" + chr(34) + "page" + chr(34) if k == active else ""}>{label}</a>'
                    for k, href, label in NAV)
    cta_href = cta if cta.startswith("#") else up + cta
    url = SITE + ("" if path == "index.html" else path)
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(title)}</title>
<meta name="description" content="{attr(desc)}">
<meta name="theme-color" content="#0F3B32">
<meta property="og:title" content="{attr(title)}">
<meta property="og:description" content="{attr(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:type" content="website">
<link rel="canonical" href="{url}">
<link rel="icon" href="{RF_ICON}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800&family=Geist:wght@400..600&family=Geist+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="{up}assets/styles.css">
</head>
<body>

<a class="skip" href="#main">Skip to content</a>

<div class="announce groupbar">
  <div class="wrap groupbar__in">
    <a href="{home}" class="groupbar__home">Research Flow 360</a>
    <span class="groupbar__note">A publication of Accel Financial Solutions · part of Accel Global Holdings</span>
  </div>
</div>

<header class="header" id="top">
  <div class="wrap header__in">
    <a href="{home}" class="brand" aria-label="Research Flow 360 home">
      {BRAND}
    </a>
    <nav class="nav" id="nav" aria-label="Primary">
      {links}
      <div class="nav__mobile-cta">
        <a href="{cta_href}" class="btn btn--primary">Subscribe free</a>
      </div>
    </nav>
    <div class="header__cta">
      <a href="{cta_href}" class="btn btn--primary btn--sm">Subscribe free</a>
    </div>
    <button class="burger" id="burger" aria-label="Open menu" aria-expanded="false" aria-controls="nav">
      <span></span><span></span>
    </button>
  </div>
</header>

{body.strip()}

<footer class="footer">
  <div class="wrap">
    <div class="footer__top">
      <div class="footer__brand">
        <a href="{home}" class="brand" aria-label="Research Flow 360 home">
          {BRAND}
        </a>
        <p>The market, in five minutes. Before the open.</p>
      </div>
      <nav class="footer__cols" aria-label="Footer">
        <div><h4>Read</h4><a href="{up}brief.html">Today's brief</a><a href="{up}archive.html">Archive</a><a href="{up}index.html#inside">What's inside</a></div>
        <div><h4>Company</h4><a href="{up}about.html">About</a><a href="{up}about.html#standards">Editorial standards</a><a href="{up}advertise.html">Advertise</a></div>
        <div><h4>Subscribe</h4><a href="{up}index.html#start">Daily Brief</a><a href="{up}index.html#start">Breaking alerts</a><a href="{up}index.html#start">Weekend Wrap</a></div>
      </nav>
    </div>
    <div class="footer__legal">
      <p>{FOOTER_LEGAL}</p>
      <p class="footer__copy"><span>© <span id="year">{date.today().year}</span> Accel Financial Solutions</span><span class="footer__links"><a href="{up}about.html">About</a><a href="{up}about.html#standards">Standards</a></span></p>
    </div>
  </div>
</footer>

<script src="{up}assets/app.js"></script>
</body>
</html>
'''


# --------------------------------------------------------------------------- page bodies
def long_date(d: date) -> str:
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}"


def issue_body(issue: Issue, *, with_snapshot: bool, up: str) -> str:
    sections = render_issue_sections(issue)
    meta = []
    if issue.sample:
        meta.append('<span class="issue__sample">Sample issue</span><span>Illustrative stories showing the format</span>')
    if issue.read_time:
        meta.append(f"<span>· {html.escape(issue.read_time)} min read</span>")
    meta.append("<span>· Reviewed by our editor before sending</span>")
    secs = []
    if with_snapshot:
        secs.append(snapshot_section())
    toc = [("snapshot", "Market snapshot")] if with_snapshot else []
    for sid, label, body in sections:
        aria = f"h-{sid}"
        lab_cls = "issue__label"
        secs.append(f'''    <section class="issue__section" id="{sid}" aria-labelledby="{aria}">
      <p class="{lab_cls}" id="{aria}">{html.escape(label)}</p>
      {body}
    </section>''')
        toc.append((sid, label))
    toc_html = "".join(f'<a href="#{sid}">{html.escape(label)}</a>' for sid, label in toc)
    return f'''<main id="main">

<section class="page-hero">
  <div class="wrap page-hero__in">
    <p class="eyebrow">{issue.type_name} · {long_date(issue.date)}</p>
    <h1 class="display">{inline(issue.title)}</h1>
    {f'<p class="lede">{inline(issue.summary)}</p>' if issue.summary else ''}
    <div class="issue__meta">
      {"".join(meta)}
    </div>
  </div>
</section>

<div class="wrap issue-wrap">
  <article class="issue">
{chr(10).join(secs)}

    <footer class="issue__foot">
      <p>Every issue is reviewed by our editor before it's sent. Every story is linked to its source; stories from Accel Media Ltd are labelled.</p>
      <p>Spotted an error? Reply to the email and we'll correct it in the next issue.</p>
      <p>Research Flow 360 publishes general market news. It isn't investment advice.</p>
      <p><a href="{up}archive.html">← All issues</a></p>
    </footer>
  </article>

  <aside class="issue-side" aria-label="Subscribe and contents">
    <div class="side-card side-card--pine">
      <h3>Get this in your inbox</h3>
      <p>Free, every weekday before 7:00 am ET.</p>
      <form class="side-form" data-signup data-ok="Almost done, {{email}}: check your inbox and click the confirm link." novalidate>
        <label for="side-email" class="sr-only">Email</label>
        <input id="side-email" type="email" placeholder="you@email.com" autocomplete="email" required>
        <button class="btn btn--signal btn--block" type="submit">Subscribe free</button>
        <p role="status" aria-live="polite"></p>
      </form>
    </div>
    <div class="side-card">
      <h3>In this issue</h3>
      <nav class="toc" aria-label="In this issue">{toc_html}</nav>
    </div>
    <div class="side-card">
      <h3>Inside Accel Trading</h3>
      <p>Our monthly look at Accel's AI trading bots, mistakes first, arrives on the first business day of each month.</p>
    </div>
  </aside>
</div>

</main>'''


def archive_body(issues: list[Issue]) -> str:
    rows = []
    for i in issues:
        _, pill, pill_cls = TYPES[i.kind]
        when = f"{i.date.strftime('%a, %b')} {i.date.day}"
        sample = " · sample" if i.sample else ""
        rows.append(f'<li data-kind="{i.kind}"><a href="{i.url}"><time datetime="{i.date.isoformat()}">{when}</time>'
                    f'<span class="arch__t"><strong>{inline(plain(i.title))}</strong>'
                    f'<span>{inline(i.summary)}{sample}</span></span>'
                    f'<span class="pill {pill_cls}">{pill}</span></a></li>')
    empty = '<li><p class="src" style="padding:20px 4px">No issues yet. The first Daily Brief appears here as soon as it is published.</p></li>'
    filters = "".join(f'<button type="button" class="chip" data-filter="{k}" aria-pressed="false">{v[0]}</button>'
                      for k, v in TYPES.items())
    return f'''<main id="main">

<section class="page-hero">
  <div class="wrap page-hero__in">
    <p class="eyebrow">Archive</p>
    <h1 class="display">Every issue, <em>in one place.</em></h1>
    <p class="lede">Every Daily Brief, breaking alert, Weekend Wrap and Inside Accel Trading report, kept online with its sources and any corrections.</p>
  </div>
</section>

<section class="section section--tight" style="padding-top: clamp(32px, 4vw, 48px)">
  <div class="wrap">
    <div class="filters" role="group" aria-label="Filter issues">
      <button type="button" class="chip is-on" data-filter="all" aria-pressed="true">All</button>{filters}
    </div>
    <ul class="arch">
      {"".join(rows) or empty}
    </ul>
  </div>
</section>

<section class="cta" id="start">
  <div class="wrap">
    <div class="cta__box">
      <div class="cta__lines" aria-hidden="true"></div>
      <div class="cta__copy">
        <h2 class="display display--cta">Never miss <em>an issue.</em></h2>
        <p>Research Flow 360, free, every weekday before 7:00 am ET.</p>
      </div>
      <form class="cta__form" id="ctaForm" data-ok="Almost done, {{email}}: check your inbox and click the confirm link. Your first Daily Brief arrives the next weekday morning." novalidate>
        <label for="email" class="sr-only">Email</label>
        <input id="email" name="email" type="email" placeholder="you@email.com" autocomplete="email" required>
        <button class="btn btn--signal" type="submit">Subscribe free</button>
        <p class="cta__msg" id="ctaMsg" role="status" aria-live="polite"></p>
      </form>
    </div>
  </div>
</section>

</main>'''


NOT_FOUND = '''<main id="main">
<section class="page-hero">
  <div class="wrap page-hero__in">
    <p class="eyebrow">Error 404</p>
    <h1 class="display">This page <em>isn't in the brief.</em></h1>
    <p class="lede">The link may be old or mistyped. Today's brief and the archive are a click away.</p>
    <div class="hero__actions">
      <a href="brief.html" class="btn btn--primary btn--lg">Read today's brief <span aria-hidden="true">→</span></a>
      <a href="archive.html" class="btn btn--ghost btn--lg">Browse the archive</a>
    </div>
  </div>
</section>
</main>'''


# --------------------------------------------------------------------------- build
def write(rel: str, text: str) -> None:
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def build() -> None:
    issues = load_issues()
    daily = [i for i in issues if i.kind == "daily"] or issues
    latest = daily[0] if daily else None

    # one permanent page per issue
    briefs = ROOT / "briefs"
    briefs.mkdir(exist_ok=True)
    keep = set()
    for i in issues:
        keep.add(i.url)
        write(i.url, page(active="archive", title=f"{plain(i.title)} · Research Flow 360", desc=i.summary or plain(i.title),
                          body=issue_body(i, with_snapshot=False, up="../"), path=i.url, cta="index.html#start"))
    for old in briefs.glob("*.html"):
        if f"briefs/{old.name}" not in keep:
            old.unlink()

    # today's brief = latest daily issue, with the live market snapshot
    if latest:
        brief = issue_body(latest, with_snapshot=True, up="")
        brief_desc = latest.summary or plain(latest.title)
    else:
        brief = ('<main id="main"><section class="page-hero"><div class="wrap page-hero__in"><p class="eyebrow">The Daily Brief</p>'
                 '<h1 class="display">The first issue is <em>on its way.</em></h1></div></section></main>')
        brief_desc = "Today's Research Flow 360 Daily Brief."
    write("brief.html", page(active="brief", title="Today's brief · Research Flow 360", desc=brief_desc,
                             body=brief, path="brief.html", cta="index.html#start"))

    write("archive.html", page(active="archive", title="Archive · Research Flow 360",
                               desc="Every Research Flow 360 Daily Brief, breaking alert, Weekend Wrap and Inside Accel Trading report.",
                               body=archive_body(issues), path="archive.html"))

    home = (TEMPLATES / "home.html").read_text(encoding="utf-8")
    if latest:
        summary = latest.summary + (" A sample issue showing the format." if latest.sample else "")
        home = (home.replace("{{latest_title}}", inline(latest.title))
                    .replace("{{latest_summary}}", inline(summary))
                    .replace("{{latest_url}}", "brief.html"))
    else:
        home = (home.replace("{{latest_title}}", "The first Daily Brief is on its way.")
                    .replace("{{latest_summary}}", "Subscribe and it lands in your inbox before the next market open.")
                    .replace("{{latest_url}}", "archive.html"))
    write("index.html", page(active="", title="Research Flow 360",
                             desc="Research Flow 360: the stories that move markets, from Wall Street to Washington, in plain English every weekday before 7:00 am ET. Free.",
                             body=home, path="index.html"))
    write("about.html", page(active="about", title="About · Research Flow 360",
                             desc="About Research Flow 360: what we cover, how we work, our editorial standards and who's behind it.",
                             body=(TEMPLATES / "about.html").read_text(encoding="utf-8"), path="about.html"))
    write("advertise.html", page(active="advertise", title="Advertise · Research Flow 360",
                                 desc="Sponsor Research Flow 360 and reach active investors every weekday before the bell.",
                                 body=(TEMPLATES / "advertise.html").read_text(encoding="utf-8"), path="advertise.html",
                                 cta="index.html#start"))
    write("404.html", page(active="", title="Page not found · Research Flow 360", desc="Page not found.",
                           body=NOT_FOUND, path="404.html", cta="index.html#start"))
    print(f"Built site: {len(issues)} issue(s); today's brief = {latest.slug if latest else 'none'}")


def main() -> int:
    try:
        if "--check" in sys.argv:
            issues = load_issues()
            print(f"OK: {len(issues)} issue file(s) are valid.")
            for i in issues:
                print(f"  {i.path.name}: {i.type_name}, {i.date}, {plain(i.title)!r}")
        else:
            build()
    except IssueError as e:
        print("Issue file problem(s):\n" + str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
