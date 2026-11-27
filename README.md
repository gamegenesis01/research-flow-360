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
