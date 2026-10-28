# The Royale Report

[![Release](https://img.shields.io/badge/release-v1.1.0-green)](https://github.com/ecomte/royale-report/releases)

**Open it: [ecomte.github.io/royale-report](https://ecomte.github.io/royale-report/)**. One page each for **Alpha** (E, `/e/`) and **OmNs_OaTs** (Ryan, `/ryan/`), with a switch at the top to go between them.

Clash Royale battle stats for E and Ryan: a scouting report, win rate for your deck and each of your cards, the enemy cards and combos that beat you most, and a filterable battle log. Tap **Refresh** (or just open the page) to pull your newest battles from the official Clash Royale API, and a popup shows what came in since you last looked. Nobody needs a token: a free Cloudflare Worker starts the build for the site (see [Refresh service](#refresh-service)). The site also updates itself every day at 3 AM Eastern.

This repository is the GitHub version of the Royale Report. It began as scripts run by hand on a Mac, with the page republished by hand afterward. Here the same Python runs on GitHub's machines and publishes to a free GitHub Pages site, so either of you can refresh it from your phone without the Mac.

## Releases

| Version | What it added |
|---|---|
| 0.1.0 | The Mac scripts moved to GitHub: GitHub Pages hosting, a page each for Alpha and OmNs_OaTs with a switch between them, a landing page, the Refresh button (on tap and on page open) with per-device GitHub tokens, a key button and Ryan's token link, the new-battles popup and refresh history, and a daily background build (RR-1, RR-2). Shipped without the build workflow, so it never deployed. |
| 0.2.0 | The build workflow and hosting settings (API key secret, Pages from Actions), and footer versions that match the release (RR-3). The first build couldn't save battles because `main` only takes pull requests. |
| 0.3.0 | Battles save to their own `battle-data` branch so `main` stays protected, the site deploys even if saving fails, `actions/checkout` v5, and the cascade merge from `main` into `develop` (RR-4, RR-5). The first release that builds and deploys end to end. |
| 1.0.0 | Pages open on Show all, and tabs no longer jump the page back to the top; Deck types, What decides games and Trophy road hidden for now; the player name on its own line under the title; "Updated <date>" in place of the date range; the new-battles popup and refresh history switched on in the hosted build; Clan Wars duels tracked in the background in their own files (RR-6). |
| 1.1.0 | Refresh goes through a free Cloudflare Worker that holds the only GitHub token, so the token prompt, key button and Ryan's `#token=` link are gone; the Worker joins a running build and won't start a new one within 5 minutes of the last; `refresh_site.py` refreshes from a terminal; a note under Refresh says it takes about a minute and that the site updates daily at 3 AM Eastern; the daily build moved to 3 AM Eastern all year (RR-8). |

Release notes for each version are on the [Releases page](https://github.com/ecomte/royale-report/releases). The version shown in each page's footer comes from `version` in `config.json`.

Clan Wars boat battles and duels aren't counted in any stats or pages, for either player. Each page's footer says boat battles are left out and duels are tracked but not analyzed or shown yet. Duels are saved separately in the background (see Duels under How it's set up) for a future Duels tab.

## How it's set up

```
Refresh tap / page open ──► Cloudflare Worker ──┐
Daily ──────────────────────────────────────────┴► GitHub Actions ──► cr_collect.py (new battles → data/)
                                                                   └─► cr_dashboard.py (pages) ──► GitHub Pages
                                                                                                   ├─ /e/
                                                                                                   └─ /ryan/
```

- **Landing page:** the site's root shows a button for each player with their record, win rate and trophies (`landing_template.html`).
- **Hosting:** GitHub Pages, deployed from GitHub Actions (`.github/workflows/build.yml`). `https://ecomte.github.io/royale-report/e/` and `.../ryan/`.
- **Refresh button:** asks the refresh service to start the workflow, waits for it (about a minute), then reloads with the new stats. One refresh updates both players. Opening a page also starts a refresh, unless the page was built or refreshed from that device in the last 10 minutes. If a build is already running, the page waits for that one instead of starting another, and if one finished in the last 5 minutes it just loads that. Nobody needs a token. A note under the status line says Refresh takes about a minute and that the site updates on its own every day at 3 AM Eastern. Code: `web/refresh.js`.
- **Refresh service:** the Clash Royale API key has to stay secret, so the browser can't call Clash Royale itself. Only the workflow can, and starting a workflow needs a GitHub token. A free Cloudflare Worker (`worker/worker.js`, at `https://royale-refresh.ecomte.workers.dev`) holds that one token and starts the workflow for the pages, so it never reaches anyone's browser (see [Refresh service](#refresh-service)).
- **Duels (tracked, not shown yet):** Clan Wars duels are best of 3 with a different deck each round, so they stay out of every regular stat and page. `cr_duels.py` saves them on their own from the same API call: `data/<player>/duels.csv` (one row per duel, with each round's decks, crowns and result), `duels_raw.jsonl` (the API's full record, so the CSV can be re-parsed with `python3 cr_duels.py --rebuild`) and `DUEL_STATS.md` (duel and round record, sweeps, recent duels, round win rate per deck). A Duels tab can come later once there's enough data.
- **Daily build:** every day at 3 AM Eastern, summer and winter. GitHub schedules are in UTC, so `build.yml` has two (07:00 and 08:00 UTC) and a small `when` job skips whichever isn't 3 AM that day. GitHub sometimes starts scheduled runs a few minutes late. The API only remembers each player's last 25 battles, so this keeps history from being lost on days nobody opens the page.
- **History:** every run that finds battles commits them to the **`battle-data`** branch ("Save new battles" commits from github-actions), which holds only `data/`. `main` only takes changes through pull requests, so the build can't save there. Each run starts from `battle-data`'s copy of `data/`; the `data/` in `main` is just the starting point from before hosting. To grab the latest history locally: `git fetch origin battle-data && git checkout origin/battle-data -- data`. If saving ever fails, the pages still publish and the next run tries again.
- **Secrets:** one, `CR_API_TOKEN` (the Clash Royale API key). Calls go through the RoyaleAPI proxy (`proxy.royaleapi.dev`), so the key's allowed IP is `45.79.218.79` and it works from GitHub's machines.
- **Players:** `config.json` lists the pages (player folder, display name, URL path) and `players.json` their tags. Adding a friend is a line in each.
- **Branches:** `main` is what's deployed, and `battle-data` holds the saved battles (written only by the build). Work happens on `feature/RR-<n>-...` branches and merges through `develop`. Builds run on any branch so a feature branch can be checked from the Actions tab; only `main` saves battles and deploys.
- **Cascade merge:** every merge into `main` is merged back into `develop` automatically (`.github/workflows/cascade-merge.yml`), so `develop` never falls behind. If that merge conflicts, it opens a `main` → `develop` pull request to resolve by hand instead.

## First-time setup

1. **API key secret.** Repo **Settings › Secrets and variables › Actions › New repository secret**. Name `CR_API_TOKEN`, value: the key from [developer.clashroyale.com](https://developer.clashroyale.com) (allowed IP `45.79.218.79`, the same key the Mac uses in `.tokens/cr_api_token`).
2. **Pages.** Repo **Settings › Pages**, under **Build and deployment › Source** pick **GitHub Actions**.
3. **First build.** **Actions › Refresh battles and deploy › Run workflow** on `main`. After about a minute the site is live.
4. **Refresh service**, below.

## Refresh service

The Refresh button talks to a Cloudflare Worker on E's free Cloudflare account, which holds a GitHub token and starts the build. The free plan allows 100,000 requests a day; this site uses a few dozen.

What it allows: `POST /refresh` starts `build.yml` on `main`, joins a build that's already running, or hands back one that finished in the last 5 minutes. `GET /status?run=<id>` reports a build's progress, and `GET /status` the latest one. `/refresh` only answers requests from `https://ecomte.github.io` (and `http://localhost:8000` for local testing), and the 5-minute rule means it can't start more than about 12 builds an hour.

**Setting it up (once):**

1. **GitHub token.** Profile picture › **Settings › Developer settings › Personal access tokens › Fine-grained tokens › Generate new token**. Name `royale-refresh worker`, **Expiration** the longest it allows, **Repository access** *Only select repositories* › `royale-report`, **Permissions › Repository permissions › Actions: Read and write** (Metadata: Read is added automatically). Copy it.
2. **Worker.** On [dash.cloudflare.com](https://dash.cloudflare.com): **Workers & Pages › Create › Create Worker**, name it `royale-refresh`, **Deploy**. Then **Edit code**, replace everything with `worker/worker.js` from this repo, and **Deploy**.
3. **Secret.** The Worker's **Settings › Variables and Secrets › Add**: type *Secret*, name `GITHUB_TOKEN`, value the token. Save and deploy.
4. **Check it.** Open `https://royale-refresh.ecomte.workers.dev/status`. It shows the latest build as JSON. An error names what's wrong with the token.

**When `worker/worker.js` changes**, paste the new version into **Edit code** and deploy; merging it here doesn't update Cloudflare. **When the token expires**, make a new one the same way and replace the `GITHUB_TOKEN` secret; no code change. The address is in `config.json` (`worker`).

## Run it locally

Python 3 with the standard library only.

```
python3 build_site.py --no-fetch --serve   # build site/ from the saved CSVs, serve at http://localhost:8000
python3 build_site.py                      # same, but fetch new battles first (needs the key)
python3 run_all.py                         # just fetch everyone's battles
python3 cr_dashboard.py me --name E        # one standalone dashboard page at data/me/dashboard.html
```

To refresh the live site from a terminal instead of the button (no token or key needed):

```
python3 refresh_site.py    # runs the GitHub build through the Worker, waits, prints new battles per player
```

Locally the key is read from `CR_API_TOKEN` or `.tokens/cr_api_token` (git ignores `.tokens/`). The local site's Refresh button goes through the Worker and starts the real GitHub build.

## What's here

| Path | What it is |
|---|---|
| `cr_collect.py` | Fetches a player's battle log, merges new battles into `data/<player>/battles.csv`, rewrites `STATS.md`. |
| `cr_duels.py` | Clan Wars duels, kept separate: `duels.csv`, `duels_raw.jsonl`, `DUEL_STATS.md`. Run by `run_all.py` and `build_site.py` too. |
| `run_all.py` | `cr_collect.py` for everyone in `players.json`. |
| `cr_dashboard.py` | Builds one player's dashboard page from their CSV. |
| `dashboard_template.html` | The dashboard's look. Edit this to change the page. |
| `build_site.py` | What Actions runs: fetch, build every page into `site/`, add the player switch and Refresh bar. |
| `landing_template.html` | The front page with a button per player. |
| `web/` | `refresh.js` and `refresh.css` (the bar at the top), `news.js` (new-battles popup and refresh history), `favicon.svg`. |
| `refresh_site.py` | Refreshes the live site from a terminal, same as the Refresh button. |
| `worker/worker.js` | The refresh service, a Cloudflare Worker. The running copy is pasted into Cloudflare. |
| `config.json` | Repo, workflow, the refresh service's address, and the pages to build. |
| `players.json` | Player folder → tag. Tags use the digit 0, never the letter O. |
| `data/<player>/` | `battles.csv` (every saved battle) and `STATS.md`. Written by the scripts, not by hand. |

Clan Wars boat battles and duels are skipped for everyone (`EXCLUDED_TYPES` in `cr_collect.py`).

## Troubleshooting

- **"Last refresh couldn't reach Clash Royale"**: the build ran but the API refused. The Actions run shows a warning with the reason. 403 means the key's allowed IP isn't `45.79.218.79`, or the `CR_API_TOKEN` secret is wrong or missing.
- **"The Worker's GitHub token expired or is wrong"** or **"…can't run builds"**: replace the Worker's `GITHUB_TOKEN` secret with a new token (see [Refresh service](#refresh-service)); it needs *Actions: Read and write* on `royale-report`.
- **"Refresh only works from the Royale Report pages"**: the page was opened from somewhere other than `ecomte.github.io` or `localhost:8000`. Add that address to `ORIGINS` in `worker/worker.js` and paste it into Cloudflare again.
- **Refresh worked but the page didn't change**: there were no new battles, or Pages took longer than usual. Reload in a minute.
