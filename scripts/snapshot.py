"""Update data/snapshot.json with the Research Flow 360 market snapshot.

Runs twice each weekday from GitHub Actions:
  * morning (about 8:05 am ET): the starting position, i.e. the latest closing prices before the open
  * close   (about 4:20 pm ET): the end-of-day prices, with each item's move since the morning

Sources
  * Finnhub (API key in the FINNHUB_API_KEY environment variable): SPY, QQQ, DIA, GLD, USO, UUP and bitcoin
  * U.S. Treasury daily par yield curve (public data, no key): the 10-year yield

Usage
  python3 scripts/snapshot.py               # runs only inside the morning or close window, once per session
  python3 scripts/snapshot.py --force       # run now, labelling the session by the time of day
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "snapshot.json"
UA = "ResearchFlow360-snapshot/1.0"

# Order matches the snapshot grid on the page.
ITEMS = [
    {"key": "spy", "label": "S&P 500 (SPY)", "symbol": "SPY", "kind": "usd"},
    {"key": "qqq", "label": "Nasdaq 100 (QQQ)", "symbol": "QQQ", "kind": "usd"},
    {"key": "dia", "label": "Dow (DIA)", "symbol": "DIA", "kind": "usd"},
    {"key": "y10", "label": "10-yr yield", "symbol": None, "kind": "yield"},
    {"key": "uso", "label": "Oil (USO)", "symbol": "USO", "kind": "usd"},
    {"key": "gld", "label": "Gold (GLD)", "symbol": "GLD", "kind": "usd"},
    {"key": "btc", "label": "Bitcoin", "symbol": "BINANCE:BTCUSDT", "kind": "usd0"},
    {"key": "uup", "label": "U.S. dollar (UUP)", "symbol": "UUP", "kind": "usd"},
]

MORNING = (time(7, 30), time(11, 0))
CLOSE = (time(16, 10), time(19, 0))


def get(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def finnhub_quote(symbol: str, key: str) -> dict:
    url = "https://finnhub.io/api/v1/quote?symbol=" + urllib.parse.quote(symbol)
    data = json.loads(get(url, {"X-Finnhub-Token": key}))
    if "error" in data or not data.get("c"):
        raise RuntimeError(f"{symbol}: {data.get('error', 'no price returned')}")
    as_of = datetime.fromtimestamp(data["t"], ET).date().isoformat() if data.get("t") else None
    return {"price": data["c"], "change": data.get("d"), "change_pct": data.get("dp"), "as_of": as_of}


def treasury_10y(year: int) -> dict:
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
           f"{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
    rows = list(csv.DictReader(io.StringIO(get(url).decode("utf-8-sig"))))
    rows = [r for r in rows if r.get("10 Yr")]
    if len(rows) < 2 and year > 2000:
        rows += [r for r in csv.DictReader(io.StringIO(get(url.replace(str(year), str(year - 1))).decode("utf-8-sig")))
                 if r.get("10 Yr")]
    if not rows:
        raise RuntimeError("Treasury: no 10-year rows")
    parse = lambda d: datetime.strptime(d, "%m/%d/%Y").date()
    rows.sort(key=lambda r: parse(r["Date"]), reverse=True)
    last, prev = float(rows[0]["10 Yr"]), float(rows[1]["10 Yr"]) if len(rows) > 1 else None
    return {"price": last, "change": round(last - prev, 2) if prev is not None else None, "change_pct": None,
            "as_of": parse(rows[0]["Date"]).isoformat()}


def which_session(now: datetime) -> str | None:
    t = now.time()
    if MORNING[0] <= t < MORNING[1]:
        return "morning"
    if CLOSE[0] <= t < CLOSE[1]:
        return "close"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="run now even outside the update windows")
    args = ap.parse_args()

    now = datetime.now(ET)
    if now.weekday() >= 5 and not args.force:
        print("Weekend: nothing to do.")
        return 0
    session = which_session(now) or ("morning" if now.time() < time(12, 0) else "close")
    if not args.force and which_session(now) is None:
        print(f"{now:%H:%M} ET is outside the update windows: nothing to do.")
        return 0

    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    today = now.date().isoformat()
    if not args.force and old.get("date") == today and old.get("session") == session:
        print(f"The {session} update for {today} is already done.")
        return 0

    key = os.environ.get("FINNHUB_API_KEY", "")
    items, problems = [], []
    for spec in ITEMS:
        entry = {k: spec[k] for k in ("key", "label", "kind")}
        try:
            if spec["symbol"]:
                if not key:
                    raise RuntimeError("FINNHUB_API_KEY is not set")
                entry.update(finnhub_quote(spec["symbol"], key))
                entry["source"] = "Finnhub"
            else:
                entry.update(treasury_10y(now.year))
                entry["source"] = "U.S. Treasury"
        except Exception as exc:  # keep going; one bad source shouldn't blank the snapshot
            problems.append(f"{spec['key']}: {exc}")
            prior = next((i for i in old.get("items", []) if i.get("key") == spec["key"]), None)
            if prior:
                entry.update({k: prior.get(k) for k in ("price", "change", "change_pct", "as_of", "source")})
                entry["stale"] = True
        items.append(entry)

    # At the close, remember where each item started the day (the morning update).
    if session == "close" and old.get("date") == today:
        start = old.get("start") or {i["key"]: i.get("price") for i in old.get("items", []) if old.get("session") == "morning"}
    else:
        start = {}
    if session == "morning":
        start = {i["key"]: i.get("price") for i in items}

    snapshot = {
        "date": today,
        "session": session,
        "updated_at": now.isoformat(timespec="minutes"),
        "items": items,
        "start": start,
        "sources": "Finnhub (funds and bitcoin); U.S. Treasury (10-year yield)",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"Wrote {session} snapshot for {today} with {len(items)} items.")
    for p in problems:
        print("WARNING", p)
    return 1 if len(problems) == len(ITEMS) else 0


if __name__ == "__main__":
    sys.exit(main())
