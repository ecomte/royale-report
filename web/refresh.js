/* The Royale Report: player switch and Refresh button for the hosted pages.
 *
 * Refresh starts the "build.yml" workflow on GitHub, which pulls new battles
 * for everyone, rebuilds the pages and republishes them. Starting a workflow
 * needs a GitHub token, so each device keeps one in localStorage. A link
 * ending in #token=<token> saves it automatically, which is how Ryan's link
 * works. Opening a page also refreshes it, unless it was built in the last
 * few minutes. window.RR (written by build_site.py) holds the settings.
 */
(function () {
  "use strict";
  const RR = window.RR;
  const TOKEN_KEY = "rr-github-token";
  const LAST_KEY = "rr-last-refresh";   // when this device last started a refresh
  const COOLDOWN_MS = 10 * 60 * 1000;   // skip the on-load refresh if the page is newer than this
  const POLL_MS = 5000;
  const GIVE_UP_MS = 6 * 60 * 1000;
  const API = "https://api.github.com/repos/" + RR.repo + "/actions";

  function store(fn) { try { return fn(localStorage); } catch (e) { return null; } }
  const getToken = () => store((s) => s.getItem(TOKEN_KEY));
  const setToken = (t) => store((s) => (t ? s.setItem(TOKEN_KEY, t) : s.removeItem(TOKEN_KEY)));

  // A #token=... link: save it, then drop it from the address bar (before the page reads its tab).
  const m = location.hash.match(/(?:^#|&)token=([^&]+)/);
  if (m) {
    setToken(decodeURIComponent(m[1]).trim());
    history.replaceState(null, "", location.pathname + location.search);
  }

  let bar, btn, msg;

  function ago(iso) {
    const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
    if (s < 90) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400 * 2) return Math.round(s / 3600) + " hr ago";
    return Math.round(s / 86400) + " days ago";
  }

  function idle(text) {
    btn.disabled = false;
    btn.textContent = "Refresh";
    bar.classList.remove("busy");
    msg.textContent = text || "Updated " + ago(RR.generated);
    msg.classList.toggle("warn", !!text);
  }

  function busy(text) {
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    bar.classList.add("busy");
    msg.classList.remove("warn");
    msg.textContent = text;
  }

  async function gh(path, token, opts) {
    const res = await fetch(API + path, Object.assign({
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
      },
      cache: "no-store",
    }, opts || {}));
    if (res.status === 401) throw Object.assign(new Error("token"), { code: 401 });
    if (res.status === 403 || res.status === 404) throw Object.assign(new Error("access"), { code: res.status });
    if (!res.ok) throw new Error("GitHub said " + res.status);
    return res.status === 204 ? null : res.json();
  }

  const runs = (token) => gh("/workflows/" + RR.workflow + "/runs?per_page=10", token)
    .then((d) => d.workflow_runs);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function refresh(auto) {
    let token = getToken();
    if (!token) {
      if (auto) return;
      token = (prompt("Paste your GitHub token. This device only needs it once.") || "").trim();
      if (!token) return;
      setToken(token);
    }
    const started = Date.now();
    store((s) => s.setItem(LAST_KEY, String(started)));
    busy("Starting…");
    try {
      // Join a build that's already running (someone else tapped, or the daily build) instead of
      // queueing another one behind it.
      const before = await runs(token);
      let run = before.find((r) => r.status !== "completed");
      if (!run) {
        await gh("/workflows/" + RR.workflow + "/dispatches", token, {
          method: "POST",
          body: JSON.stringify({ ref: RR.branch }),
        });
        const seen = new Set(before.map((r) => r.id));
        while (!run) {
          if (Date.now() - started > 60000) throw new Error("GitHub didn't start the build");
          await sleep(2000);
          run = (await runs(token)).find((r) => !seen.has(r.id));
        }
      }
      while (run.status !== "completed") {
        if (Date.now() - started > GIVE_UP_MS) throw new Error("The build is taking too long");
        const secs = Math.round((Date.now() - started) / 1000);
        busy((run.status === "queued" ? "Waiting for GitHub" : "Pulling new battles") + "… " + secs + "s");
        await sleep(POLL_MS);
        run = await gh("/runs/" + run.id, token);
      }
      if (run.conclusion !== "success") throw new Error("The build failed on GitHub");
      // The run is done once the new pages are published. Wait for this page's copy to change.
      busy("Loading new stats…");
      for (let i = 0; i < 12; i++) {
        const st = await fetch("../status.json?v=" + Date.now(), { cache: "no-store" }).then((r) => r.json());
        if (st.generated !== RR.generated) {
          await fetch(location.pathname, { cache: "reload" });
          location.reload();
          return;
        }
        await sleep(POLL_MS);
      }
      idle("Already up to date");
    } catch (e) {
      if (e.code === 401) {
        setToken(null);
        idle("Your token expired or is wrong. Tap Refresh to enter a new one.");
      } else if (e.code) {
        idle("That token can't run builds for this site. Tap Refresh to try a new one.");
        setToken(null);
      } else {
        idle((e.message || "Couldn't refresh") + ". Try again in a minute.");
      }
    }
  }

  function render() {
    bar = document.createElement("div");
    bar.className = "rr-bar";
    const links = RR.pages.map((p) =>
      '<a href="../' + p.path + '/"' + (p.path === RR.current ? ' aria-current="page"' : "") + ">" +
      p.name.replace(/[<>&"]/g, "") + "</a>").join("");
    bar.innerHTML =
      '<div class="rr-inner">' +
      '<nav class="rr-players" aria-label="Player">' + links + "</nav>" +
      '<span class="rr-msg" aria-live="polite"></span>' +
      '<button type="button" class="rr-key" title="Add or change your GitHub token" aria-label="GitHub token">' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="8" cy="12" r="4.5"/><path d="M12.5 12H21v3.5M17.5 12v2.5"/></svg></button>' +
      '<button type="button" class="rr-refresh">Refresh</button>' +
      "</div>";
    document.body.prepend(bar);
    btn = bar.querySelector(".rr-refresh");
    msg = bar.querySelector(".rr-msg");
    btn.addEventListener("click", () => refresh(false));
    bar.querySelector(".rr-key").addEventListener("click", () => {
      const had = !!getToken();
      const t = prompt(had
        ? "Paste a new GitHub token to replace the saved one, or leave it empty and tap OK to remove it."
        : "Paste your GitHub token. This device only needs it once.");
      if (t === null) return;   // Cancel: keep whatever is saved
      setToken(t.trim() || null);
      idle(t.trim() ? "Token saved." : "Token removed.");
    });
    // Keep the open tab when switching players.
    bar.querySelectorAll(".rr-players a").forEach((a) =>
      a.addEventListener("click", () => { a.href = a.href.split("#")[0] + location.hash; }));

    idle(RR.fetch && RR.fetch !== "ok" && RR.fetch !== "skipped"
      ? "Last refresh couldn't reach Clash Royale. Showing saved battles."
      : "");
    setInterval(() => { if (!btn.disabled && !msg.classList.contains("warn")) idle(); }, 60000);

    const last = Number(store((s) => s.getItem(LAST_KEY))) || 0;
    if (Date.now() - Date.parse(RR.generated) > COOLDOWN_MS && Date.now() - last > COOLDOWN_MS) refresh(true);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render);
  else render();
})();
