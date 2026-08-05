// /api/* — authenticated proxy to the bot's in-process API.
//
// This is the only place the browser and the bot meet. The flow:
//   1. Verify our own session cookie -> the caller's Discord id.
//   2. Forward the request to the bot API (reachable via the Cloudflare Tunnel /
//      bridge Worker at BOT_API_URL), attaching the shared secret and the id.
//   3. The bot scopes the response to what that user owns.
//
// The browser never sees BOT_API_URL, DASHBOARD_API_SECRET, or the user's
// Discord token. Only "identify"-level data and owned game metadata cross.

import { currentUser, requireEnv } from "../_lib/session.js";
import { callBot } from "../_lib/bot.js";

const ALLOWED_METHODS = new Set(["GET", "PATCH", "POST", "DELETE"]);
const METHODS_WITH_BODY = new Set(["PATCH", "POST"]);

export async function onRequest({ request, env, params }) {
  if (!ALLOWED_METHODS.has(request.method)) {
    return json({ error: "method not allowed" }, 405);
  }

  const bad = requireEnv(env, ["SESSION_SECRET", "BOT_API_URL", "DASHBOARD_API_SECRET"]);
  if (bad) return bad;

  const user = await currentUser(request, env);
  if (!user) return json({ error: "not authenticated" }, 401);

  // params.path is the wildcard after /api/, e.g. ["groups", "WINGS"].
  const segments = Array.isArray(params.path) ? params.path : [params.path];
  const path = "/api/" + segments.map(encodeURIComponent).join("/");

  const body = METHODS_WITH_BODY.has(request.method)
    ? await request.json().catch(() => ({}))
    : undefined;

  let botRes;
  try {
    botRes = await callBot(env, user.id, request.method, path, body);
  } catch {
    return json({ error: "bot is unreachable" }, 502);
  }

  // Pass the bot's JSON and status straight through.
  const text = await botRes.text();
  return new Response(text, {
    status: botRes.status,
    headers: { "Content-Type": "application/json" },
  });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status, headers: { "Content-Type": "application/json" },
  });
}
