/* The Royale Report: player switch and Refresh button for the hosted pages.
 *
 * Refresh asks the refresh service (a Cloudflare Worker, worker/worker.js) to
 * start the "build.yml" workflow on GitHub, which pulls new battles for
 * everyone, rebuilds the pages and republishes them. The Worker holds the
 * GitHub token, so nobody needs one here. Builds only run when someone taps
 * Refresh (or runs refresh_site.py) and at 3 AM Eastern; opening a page never
 * starts one. window.RR (written by
 * build_site.py) holds the settings.
 */
(function () {
  "use strict";
  const RR = window.RR;
  const POLL_MS = 5000;
  const GIVE_UP_MS = 6 * 60 * 1000;

  function store(fn) { try { return fn(localStorage); } catch (e) { return null; } }

  // Tokens from before the Worker: forget any saved one, and drop an old #token= link's token
  // from the address bar.
  store((s) => { s.removeItem("rr-github-token"); s.removeItem("rr-last-refresh"); });
  if (/(?:^#|&)token=/.test(location.hash)) history.replaceState(null, "", location.pathname + location.search);

  let bar, btn, msg;

  function ago(iso) {
    const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
    if (s < 90) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400 * 2) return Math.round(s / 3600) + " hr ago";
    return Math.round(s / 86400) + " days ago";
  }

  // "Oct 28, 3:02 AM EDT", in the viewer's time zone.
  const when = (iso) => new Date(iso).toLocaleString(undefined,
    { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });

  function idle(text) {
    btn.disabled = false;
    btn.textContent = "Refresh";
    bar.classList.remove("busy");
    const t = RR.refreshed || RR.generated;   // last battle refresh, not when the page was built
    msg.textContent = text || "Updated " + when(t) + " · " + ago(t);
    msg.classList.toggle("warn", !!text);
  }

  function busy(text) {
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    bar.classList.add("busy");
    msg.classList.remove("warn");
    msg.textContent = text;
  }

  async function worker(path, opts) {
    const res = await fetch(RR.worker + path, Object.assign({ cache: "no-store" }, opts || {}));
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.message || "The refresh service said " + res.status);
    return body.run;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function refresh() {
    const started = Date.now();
    busy("Starting…");
    try {
      // Starts a build, or hands back the one already running (or just finished).
      let run = await worker("/refresh", { method: "POST" });
      while (run.status !== "completed") {
        if (Date.now() - started > GIVE_UP_MS) throw new Error("The build is taking too long");
        const secs = Math.round((Date.now() - started) / 1000);
        busy((run.status === "queued" ? "Waiting for GitHub" : "Pulling new battles") + "… " + secs + "s");
        await sleep(POLL_MS);
        run = await worker("/status?run=" + run.id);
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
      idle((e.message || "Couldn't refresh") + ". Try again in a minute.");
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
      '<div class="rr-status"><span class="rr-msg" aria-live="polite"></span>' +
      '<small class="rr-hint"><span class="rr-long">Refresh takes about a minute to pull new battles and recalculate stats · Updates on its own every day at 3 AM Eastern</span>' +
      '<span class="rr-short">Takes ~1 min · Auto-updates 3 AM ET</span></small></div>' +
      '<button type="button" class="rr-refresh">Refresh</button>' +
      "</div>";
    document.body.prepend(bar);
    btn = bar.querySelector(".rr-refresh");
    msg = bar.querySelector(".rr-msg");
    btn.addEventListener("click", refresh);
    // Keep the open tab when switching players.
    bar.querySelectorAll(".rr-players a").forEach((a) =>
      a.addEventListener("click", () => { a.href = a.href.split("#")[0] + location.hash; }));

    idle(RR.fetch && RR.fetch !== "ok" && RR.fetch !== "skipped"
      ? "Last refresh couldn't reach Clash Royale. Showing saved battles."
      : "");
    setInterval(() => { if (!btn.disabled && !msg.classList.contains("warn")) idle(); }, 60000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render);
  else render();
})();
