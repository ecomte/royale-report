/* The Royale Report: "new battles" popup and refresh history for the hosted pages.
 *
 * Every refresh that brings in battles is logged in data/<player>/updates.json, and
 * build_site.py passes that log in as RR.updates. This device remembers the newest
 * update it has shown (localStorage), so opening the page after a refresh pops up the
 * battles that came in since. Dismissing it marks them seen. The clock button in the
 * top bar opens every past refresh. Battle details come from the dashboard's DATA.
 */
(function () {
  "use strict";
  const RR = window.RR;
  const SEEN_KEY = "rr-seen-" + RR.current;

  function store(fn) { try { return fn(localStorage); } catch (e) { return null; } }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const when = (iso) => new Date(iso).toLocaleString(undefined,
    { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const signed = (n) => (n > 0 ? "+" : n < 0 ? "−" : "±") + Math.abs(n);

  function battlesFor(update, byTime) {
    return update.battles.map((t) => byTime.get(t)).filter(Boolean)
      .sort((a, b) => (a.t < b.t ? 1 : -1));   // newest first
  }

  function summary(list) {
    const w = list.filter((b) => b.res === "W").length;
    const l = list.filter((b) => b.res === "L").length;
    const tr = list.reduce((s, b) => s + (b.dtr || 0), 0);
    return { w, l, tr, text: w + "–" + l + (tr ? " · " + signed(tr) + " trophies" : "") };
  }

  function rows(list) {
    return '<ul class="rr-list">' + list.map((b) => {
      const res = b.res === "W" ? "Win" : b.res === "L" ? "Loss" : "Draw";
      return '<li class="rr-b ' + b.res + '">' +
        '<span class="rr-res">' + res + "</span>" +
        '<span class="rr-who"><b>' + esc(b.oppName || "Opponent") + "</b>" +
        "<small>" + esc(b.arch) + " · " + when(b.t) + "</small></span>" +
        '<span class="rr-score">' + (b.mc ?? "?") + "–" + (b.oc ?? "?") + "</span>" +
        '<span class="rr-tr">' + (b.dtr ? signed(b.dtr) : "") + "</span></li>";
    }).join("") + "</ul>";
  }

  function render() {
    if (typeof DATA === "undefined" || !DATA || !RR.updates) return;
    const byTime = new Map(DATA.battles.map((b) => [b.t, b]));
    const updates = RR.updates.filter((u) => battlesFor(u, byTime).length);   // skips duels etc.
    const latest = updates.length ? updates[updates.length - 1].t : "";
    let seen = store((s) => s.getItem(SEEN_KEY));
    if (seen === null) {
      // First visit on this device: start counting from now instead of showing all history.
      store((s) => s.setItem(SEEN_KEY, latest));
      seen = latest;
    }
    const unseen = updates.filter((u) => u.t > seen);

    // History button in the top bar (refresh.js builds the bar first).
    const inner = document.querySelector(".rr-inner");
    const histBtn = document.createElement("button");
    histBtn.type = "button";
    histBtn.className = "rr-hist-btn";
    histBtn.title = "Refresh history";
    histBtn.setAttribute("aria-label", "Refresh history");
    histBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/>' +
      '<path d="M12 7.5V12l3 2"/></svg><span class="rr-dot" hidden></span>';
    if (inner) inner.insertBefore(histBtn, inner.querySelector(".rr-key"));
    const dot = histBtn.querySelector(".rr-dot");
    dot.hidden = !unseen.length;

    function markSeen() {
      store((s) => s.setItem(SEEN_KEY, latest));
      dot.hidden = true;
    }

    // ---- the popup ----
    if (unseen.length) {
      const list = unseen.flatMap((u) => battlesFor(u, byTime)).sort((a, b) => (a.t < b.t ? 1 : -1));
      const sum = summary(list);
      const box = document.createElement("section");
      box.className = "rr-news";
      box.setAttribute("role", "status");
      box.setAttribute("aria-label", "New battles");
      box.innerHTML =
        '<div class="rr-news-head"><div><h2>' + list.length + " new battle" + (list.length === 1 ? "" : "s") +
        '</h2><p class="rr-sum">' + sum.text + '</p></div>' +
        '<button type="button" class="rr-x" aria-label="Dismiss">×</button></div>' +
        rows(list.slice(0, 8)) +
        (list.length > 8 ? '<p class="rr-more">+' + (list.length - 8) + " more in the battle log</p>" : "") +
        '<button type="button" class="rr-dismiss">Got it</button>';
      document.body.appendChild(box);
      const close = () => { markSeen(); box.remove(); document.removeEventListener("keydown", onKey); };
      const onKey = (e) => { if (e.key === "Escape") close(); };
      box.querySelector(".rr-x").addEventListener("click", close);
      box.querySelector(".rr-dismiss").addEventListener("click", close);
      document.addEventListener("keydown", onKey);
    }

    // ---- the history sheet ----
    const dlg = document.createElement("dialog");
    dlg.className = "rr-history";
    dlg.setAttribute("aria-label", "Refresh history");
    const entries = updates.slice().reverse().map((u) => {
      const list = battlesFor(u, byTime);
      const sum = summary(list);
      return "<details><summary><span class=\"rr-when\">" + when(u.t) + "</span>" +
        '<span class="rr-sum">' + list.length + " new · " + sum.text + "</span></summary>" +
        rows(list) + "</details>";
    }).join("");
    dlg.innerHTML =
      '<div class="rr-news-head"><div><h2>Refresh history</h2>' +
      '<p class="rr-sum">Every refresh that found new battles, newest first.</p></div>' +
      '<button type="button" class="rr-x" aria-label="Close">×</button></div>' +
      (entries || '<p class="rr-empty">No refreshes with new battles yet. They\'ll show up here after the next one.</p>');
    document.body.appendChild(dlg);
    dlg.querySelector(".rr-x").addEventListener("click", () => dlg.close());
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });   // tap outside
    histBtn.addEventListener("click", () => {
      const first = dlg.querySelector("details");
      if (first) first.open = true;
      dlg.showModal();
      markSeen();
      const pop = document.querySelector(".rr-news");
      if (pop) pop.remove();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render);
  else render();
})();
