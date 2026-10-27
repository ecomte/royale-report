# The Royale Report

[![Release](https://img.shields.io/badge/release-v1.0.0-green)](https://github.com/ecomte/royale-report/releases)

**Open it: [ecomte.github.io/royale-report](https://ecomte.github.io/royale-report/)**. One page each for **Alpha** (E, `/e/`) and **OmNs_OaTs** (Ryan, `/ryan/`), with a switch at the top to go between them.

Clash Royale battle stats for E and Ryan: a scouting report, win rate for your deck and each of your cards, the enemy cards and combos that beat you most, and a filterable battle log. Tap **Refresh** (or just open the page) to pull your newest battles from the official Clash Royale API, and a popup shows what came in since you last looked.

This repository is the GitHub version of the Royale Report. It began as scripts run by hand on a Mac, with the page republished by hand afterward. Here the same Python runs on GitHub's machines and publishes to a free GitHub Pages site, so either of you can refresh it from your phone without the Mac.

## Releases

| Version | What it added |
|---|---|
| 0.1.0 | The Mac scripts moved to GitHub: GitHub Pages hosting, a page each for Alpha and OmNs_OaTs with a switch between them, a landing page, the Refresh button (on tap and on page open) with per-device GitHub tokens, a key button and Ryan's token link, the new-battles popup and refresh history, and a daily background build (RR-1, RR-2). Shipped without the build workflow, so it never deployed. |
| 0.2.0 | The build workflow and hosting settings (API key secret, Pages from Actions), and footer versions that match the release (RR-3). The first build couldn't save battles because `main` only takes pull requests. |
| 0.3.0 | Battles save to their own `battle-data` branch so `main` stays protected, the site deploys even if saving fails, `actions/checkout` v5, and the cascade merge from `main` into `develop` (RR-4, RR-5). The first release that builds and deploys end to end. |
| 1.0.0 | Pages open on Show all, and tabs no longer jump the page back to the top; Deck types, What decides games and Trophy road hidden for now; the player name on its own line under the title; "Updated <date>" in place of the date range; the new-battles popup and refresh history switched on in the hosted build; Clan Wars duels tracked in the background in their own files (RR-6). |

Release notes for each version are on the [Releases page](https://github.com/ecomte/royale-report/releases). The version shown in each page's footer comes from `version` in `config.json`.

Clan Wars boat battles and duels aren't counted in any stats or pages, for either player, and each page says so in its footer. Duels are saved separately in the background (see Duels under How it's set up) for a future Duels tab.

## How it's set up

```
Refresh tap / page open / daily ──► GitHub Actions ──► cr_collect.py (new battles → data/)
                                                   └─► cr_dashboard.py (pages) ──► GitHub Pages
                                                                                   ├─ /e/
                                                                                   └─ /ryan/
```

- **Landing page:** the site's root shows a button for each player with their record, win rate and trophies (`landing_template.html`).
- **Hosting:** GitHub Pages, deployed from GitHub Actions (`.github/workflows/build.yml`). `https://ecomte.github.io/royale-report/e/` and `.../ryan/`.
- **Refresh button:** starts the workflow through GitHub's API, waits for it (about a minute), then reloads with the new stats. One refresh updates both players. Opening a page also starts a refresh, unless the page was built or refreshed from that device in the last 10 minutes. If a build is already running, the page waits for that one instead of starting another. Code: `web/refresh.js`.
- **Why it needs a token:** the Clash Royale API key has to stay secret, so the browser can't call Clash Royale itself. Only the workflow can, and starting a workflow needs a GitHub token. Each device saves one in the browser, once (see [Tokens](#tokens)).
- **Duels (tracked, not shown yet):** Clan Wars duels are best of 3 with a different deck each round, so they stay out of every regular stat and page. `cr_duels.py` saves them on their own from the same API call: `data/<player>/duels.csv` (one row per duel, with each round's decks, crowns and result), `duels_raw.jsonl` (the API's full record, so the CSV can be re-parsed with `python3 cr_duels.py --rebuild`) and `DUEL_STATS.md` (duel and round record, sweeps, recent duels, round win rate per deck). A Duels tab can come later once there's enough data.
- **Daily build:** once a day at 09:00 UTC (5 AM Eastern in summer, 4 AM in winter). The API only remembers each player's last 25 battles, so this keeps history from being lost on days nobody opens the page.
- **History:** every run that finds battles commits them to the **`battle-data`** branch ("Save new battles" commits from github-actions), which holds only `data/`. `main` only takes changes through pull requests, so the build can't save there. Each run starts from `battle-data`'s copy of `data/`; the `data/` in `main` is just the starting point from before hosting. To grab the latest history locally: `git fetch origin battle-data && git checkout origin/battle-data -- data`. If saving ever fails, the pages still publish and the next run tries again.
- **Secrets:** one, `CR_API_TOKEN` (the Clash Royale API key). Calls go through the RoyaleAPI proxy (`proxy.royaleapi.dev`), so the key's allowed IP is `45.79.218.79` and it works from GitHub's machines.
- **Players:** `config.json` lists the pages (player folder, display name, URL path) and `players.json` their tags. Adding a friend is a line in each.
- **Branches:** `main` is what's deployed, and `battle-data` holds the saved battles (written only by the build). Work happens on `feature/RR-<n>-...` branches and merges through `develop`. Builds run on any branch so a feature branch can be checked from the Actions tab; only `main` saves battles and deploys.
- **Cascade merge:** every merge into `main` is merged back into `develop` automatically (`.github/workflows/cascade-merge.yml`), so `develop` never falls behind. If that merge conflicts, it opens a `main` → `develop` pull request to resolve by hand instead.

## First-time setup

1. **API key secret.** Repo **Settings › Secrets and variables › Actions › New repository secret**. Name `CR_API_TOKEN`, value: the key from [developer.clashroyale.com](https://developer.clashroyale.com) (allowed IP `45.79.218.79`, the same key the Mac uses in `.tokens/cr_api_token`).
2. **Pages.** Repo **Settings › Pages**, under **Build and deployment › Source** pick **GitHub Actions**.
3. **First build.** **Actions › Refresh battles and deploy › Run workflow** on `main`. After about a minute the site is live.
4. **Tokens** for E and Ryan, below.

## Tokens

Make one token per person, so either can be cancelled without touching the other.

1. On GitHub: profile picture › **Settings › Developer settings › Personal access tokens › Fine-grained tokens › Generate new token**.
2. Name it (`Royale Report - E`, `Royale Report - Ryan`), set **Expiration** to a year (or the longest it allows).
3. **Repository access:** *Only select repositories* › `royale-report`.
4. **Permissions › Repository permissions › Actions: Read and write.** Nothing else is needed (Metadata: Read is added automatically).
5. Generate and copy it (it starts with `github_pat_`).

**E:** open your page, tap **Refresh** (or the key button next to it), and paste the token. That device remembers it. The key button also replaces or removes a saved token.

**Ryan:** send him a personal link with his token on the end, after `#token=`:

```
https://ecomte.github.io/royale-report/ryan/#token=github_pat_...
```

Opening it saves the token and removes it from the address bar. If his browser ever forgets it, he opens the same link again. Saving it to his home screen (Share › Add to Home Screen) also stops iPhone Safari from clearing it after a week away.

Keep the links private: anyone with a token can start refreshes (that's all it can do). To cancel one, delete it on the same GitHub page; the page then asks for a new one.

When a token expires, the page says so and asks for a new one. Make a new one the same way.

## Run it locally

Python 3 with the standard library only.

```
python3 build_site.py --no-fetch --serve   # build site/ from the saved CSVs, serve at http://localhost:8000
python3 build_site.py                      # same, but fetch new battles first (needs the key)
python3 run_all.py                         # just fetch everyone's battles
python3 cr_dashboard.py me --name E        # one standalone dashboard page at data/me/dashboard.html
```

Locally the key is read from `CR_API_TOKEN` or `.tokens/cr_api_token` (git ignores `.tokens/`). The local site's Refresh button starts the real GitHub build.

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
| `web/` | `refresh.js` and `refresh.css` (the bar at the top), `favicon.svg`. |
| `config.json` | Repo, workflow, and the pages to build. |
| `players.json` | Player folder → tag. Tags use the digit 0, never the letter O. |
| `data/<player>/` | `battles.csv` (every saved battle) and `STATS.md`. Written by the scripts, not by hand. |

Clan Wars boat battles and duels are skipped for everyone (`EXCLUDED_TYPES` in `cr_collect.py`).

## Troubleshooting

- **"Last refresh couldn't reach Clash Royale"**: the build ran but the API refused. The Actions run shows a warning with the reason. 403 means the key's allowed IP isn't `45.79.218.79`, or the `CR_API_TOKEN` secret is wrong or missing.
- **"That token can't run builds for this site"**: the token is for another repo or lacks *Actions: Read and write*.
- **Refresh worked but the page didn't change**: there were no new battles, or Pages took longer than usual. Reload in a minute.
