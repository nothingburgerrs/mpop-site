// GET /auth/me — returns the logged-in user, or 401. The frontend calls this on
// load to decide between the login screen and the dashboard.
import { currentUser, requireEnv } from "../_lib/session.js";

export async function onRequestGet({ request, env }) {
  const bad = requireEnv(env, ["SESSION_SECRET"]);
  if (bad) return bad;

  const user = await currentUser(request, env);
  if (!user) return new Response(JSON.stringify({ authenticated: false }), {
    status: 401, headers: { "Content-Type": "application/json" },
  });
  return new Response(
    JSON.stringify({ authenticated: true, id: user.id, username: user.username }),
    { headers: { "Content-Type": "application/json" } }
  );
}
