/* The Royale Report refresh service: a Cloudflare Worker at royale-refresh.ecomte.workers.dev.
 *
 * It keeps the one GitHub token (the GITHUB_TOKEN secret, set in the Worker's settings) so
 * nobody's browser needs one. The page's Refresh button calls it:
 *
 *   POST /refresh        start build.yml on main, or join the build already running.
 *                        If one finished in the last 5 minutes, hand that one back instead.
 *   GET  /status         the latest build on main (open it in a browser to check the Worker).
 *   GET  /status?run=ID  one build's progress, which the page asks for every few seconds.
 *
 * It also starts the daily 3 AM Eastern build, from two Cron Triggers set in Cloudflare
 * (royale-refresh › Settings › Trigger events): 0 7 * * * and 0 8 * * *. Cloudflare's crons are
 * in UTC, so one is 3 AM in summer (EDT) and the other in winter (EST); scheduled() below starts
 * the build only on the one that's 3 AM in New York. GitHub's own schedule in build.yml is just
 * a backup, since GitHub can start scheduled runs hours late or skip them.
 *
 * It can only start that one workflow and read builds, and /refresh only answers the site's
 * own pages, so the worst anyone can do with the address is start a build every 5 minutes.
 * This file lives in the repo so it's versioned; the copy that runs is the one pasted into
 * Cloudflare (Workers & Pages › royale-refresh › Edit code).
 */
const REPO = "ecomte/royale-report";
const WORKFLOW = "build.yml";
const BRANCH = "main";
const ORIGINS = ["https://ecomte.github.io", "http://localhost:8000"];   // pages allowed to refresh
const RECENT_MS = 5 * 60 * 1000;   // a build that finished this recently counts as fresh
const API = "https://api.github.com/repos/" + REPO + "/actions";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function gh(env, path, opts) {
  const res = await fetch(API + path, Object.assign({
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: "Bearer " + env.GITHUB_TOKEN,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "royale-refresh-worker",   // GitHub refuses requests without one
    },
  }, opts || {}));
  if (res.status === 401) throw new Error("The Worker's GitHub token expired or is wrong");
  if (res.status === 403 || res.status === 404) throw new Error("The Worker's GitHub token can't run builds for " + REPO);
  if (!res.ok) throw new Error("GitHub said " + res.status);
  return res.status === 204 ? null : res.json();
}

const dispatch = (env) => gh(env, "/workflows/" + WORKFLOW + "/dispatches", {
  method: "POST",
  body: JSON.stringify({ ref: BRANCH }),
});

// Only what the page needs from a run.
const brief = (r) => ({ id: r.id, status: r.status, conclusion: r.conclusion,
  created_at: r.created_at, updated_at: r.updated_at });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin");
    const allowed = ORIGINS.includes(origin);
    const cors = allowed ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" } : {};
    const reply = (body, status = 200) => new Response(JSON.stringify(body), {
      status,
      headers: Object.assign({ "Content-Type": "application/json", "Cache-Control": "no-store" }, cors),
    });

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: Object.assign({
        "Access-Control-Allow-Methods": "GET, POST", "Access-Control-Max-Age": "86400" }, cors) });
    }
    if (!env.GITHUB_TOKEN) return reply({ message: "The Worker's GITHUB_TOKEN secret isn't set" }, 500);

    const runs = () => gh(env, "/workflows/" + WORKFLOW + "/runs?branch=" + BRANCH + "&per_page=10")
      .then((d) => d.workflow_runs);

    try {
      if (url.pathname === "/status" && request.method === "GET") {
        const id = url.searchParams.get("run");
        if (id && !/^\d+$/.test(id)) return reply({ message: "Bad run id" }, 400);
        if (id) return reply({ run: brief(await gh(env, "/runs/" + id)) });
        const [latest] = await runs();
        return reply({ run: latest ? brief(latest) : null });
      }

      if (url.pathname === "/refresh" && request.method === "POST") {
        if (!allowed) return reply({ message: "Refresh only works from the Royale Report pages" }, 403);
        const before = await runs();
        // Someone else tapped, or the daily build is going: join it instead of queueing another.
        const active = before.find((r) => r.status !== "completed");
        if (active) return reply({ run: brief(active), joined: true });
        const last = before[0];
        if (last && last.conclusion === "success" && Date.now() - Date.parse(last.updated_at) < RECENT_MS) {
          return reply({ run: brief(last), recent: true });
        }
        await dispatch(env);
        // GitHub doesn't return the new run, so watch for it to appear.
        const seen = new Set(before.map((r) => r.id));
        for (let i = 0; i < 15; i++) {
          await sleep(2000);
          const run = (await runs()).find((r) => !seen.has(r.id));
          if (run) return reply({ run: brief(run), started: true });
        }
        return reply({ message: "GitHub didn't start the build" }, 504);
      }

      return reply({ message: "Not found" }, 404);
    } catch (e) {
      return reply({ message: e.message }, 502);
    }
  },

  // The daily build, from the Cron Triggers above. A failure shows in the Worker's logs.
  async scheduled(event, env) {
    const hour = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", hour: "numeric", hourCycle: "h23",
    }).format(new Date(event.scheduledTime));
    if (Number(hour) !== 3) return;   // the other cron, the one that isn't 3 AM today
    await dispatch(env);
  },
};
