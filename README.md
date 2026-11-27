# Research Flow 360

The website for **Research Flow 360**, a free weekday market news brief by **Accel Financial Solutions**,
part of Accel Global Holdings.

Plain HTML, CSS and JavaScript. No build step needed to host it.

| Page | File |
| --- | --- |
| Home | `index.html` |
| Today's brief (sample issue) | `brief.html` |
| Archive | `archive.html` |
| About | `about.html` |
| Advertise | `advertise.html` |
| Not found | `404.html` |

`assets/styles.css` holds every style (light and dark themes); `assets/app.js` holds the menu, archive
filters and sign-up form behaviour. `src/rf/` keeps the page bodies the pages were generated from.

## Live market snapshot

The snapshot on `brief.html` reads `data/snapshot.json`, which `scripts/snapshot.py` refreshes every
weekday at about **8:05 am ET** (the starting position) and **4:20 pm ET** (market close, with each
item's 8 am value shown underneath).

| Box | Source |
| --- | --- |
| S&P 500, Nasdaq 100, Dow | Finnhub: the SPY, QQQ and DIA funds that track them |
| Oil, gold, U.S. dollar | Finnhub: the USO, GLD and UUP funds |
| Bitcoin | Finnhub (BINANCE:BTCUSDT) |
| 10-year yield | U.S. Treasury daily yield curve (public data) |

Setup: add your Finnhub key as a repository secret named **`FINNHUB_API_KEY`**
(Settings → Secrets and variables → Actions). To refresh now: Actions → Publish Research Flow 360 →
Run workflow. Check that your Finnhub plan allows showing its data on a public website.

## Publishing

Every push to `main` publishes the site with GitHub Pages (`.github/workflows/pages.yml`).
One-time setup: **Settings → Pages → Build and deployment → Source: GitHub Actions**.

## Connecting researchflow360.com

1. At your domain registrar, add:
   - `A` records for `researchflow360.com` → `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`
   - a `CNAME` record for `www` → `<your-github-username>.github.io`
2. In **Settings → Pages → Custom domain**, enter `researchflow360.com` and save, then tick **Enforce HTTPS** once offered.

## Before launch

- Connect the sign-up forms to the newsletter platform; today they only confirm on screen.
- Add privacy and terms pages.
- The sample issue and archive entries are illustrations, labelled as such, until real issues are published.
