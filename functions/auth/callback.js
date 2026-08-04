// GET /auth/callback — completes Discord OAuth.
//
// Verifies the state, exchanges the code for a token (server-side, so the client
// secret never reaches the browser), reads the user's Discord id, and issues our
// own signed session cookie. The Discord token itself is discarded — we only
// needed the id.

import { createSession, sessionCookie, readSessionCookie, requireEnv } from "../_lib/session.js";

export async function onRequestGet({ request, env }) {
  const bad = requireEnv(env, ["DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "SESSION_SECRET"]);
  if (bad) return bad;

  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");

  const expectedState = cookieValue(request, "oauth_state");
  if (!code || !state || state !== expectedState) {
    return redirect(url.origin + "/?error=auth_failed");
  }

  const redirectUri = `${url.origin}/auth/callback`;
  const tokenRes = await fetch("https://discord.com/api/oauth2/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: env.DISCORD_CLIENT_ID,
      client_secret: env.DISCORD_CLIENT_SECRET,
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
    }),
  });
  if (!tokenRes.ok) return redirect(url.origin + "/?error=token_exchange");

  const token = await tokenRes.json();
  const userRes = await fetch("https://discord.com/api/users/@me", {
    headers: { Authorization: `Bearer ${token.access_token}` },
  });
  if (!userRes.ok) return redirect(url.origin + "/?error=user_fetch");

  const user = await userRes.json();
  const session = await createSession(
    { id: user.id, username: user.username, avatar: user.avatar },
    env.SESSION_SECRET
  );

  // Two cookies must be sent as two separate Set-Cookie headers. An array in the
  // object literal would be joined into one malformed value, so the session
  // cookie would never be stored — which sends the user straight back to login.
  const headers = new Headers({ Location: url.origin + "/" });
  headers.append("Set-Cookie", sessionCookie(session));
  headers.append("Set-Cookie", "oauth_state=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0");

  return new Response(null, { status: 302, headers });
}

function cookieValue(request, name) {
  const header = request.headers.get("Cookie") || "";
  for (const part of header.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return rest.join("=");
  }
  return null;
}

function redirect(location) {
  return new Response(null, { status: 302, headers: { Location: location } });
}
