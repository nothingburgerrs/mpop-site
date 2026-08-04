// Single place that talks to the bot's in-process API over the Cloudflare Tunnel.
// Attaches the shared secret (proving the call is from us) and the verified
// Discord id (which the bot uses to scope data). See dashboard/README.md.

export function callBot(env, userId, method, path, body) {
  const target = `${env.BOT_API_URL.replace(/\/$/, "")}${path}`;
  const headers = {
    Authorization: `Bearer ${env.DASHBOARD_API_SECRET}`,
    "X-User-Id": userId,
  };
  let payload;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  return fetch(target, { method, headers, body: payload });
}
