// GET /auth/login — kicks off Discord OAuth.
//
// Redirects the user to Discord's consent screen. We only request the "identify"
// scope: all we need is their Discord id, which the bot uses to scope data. A
// random state value is stored in a short-lived cookie and checked on callback
// to prevent CSRF.

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  const redirectUri = `${url.origin}/auth/callback`;
  const state = crypto.randomUUID();

  const authorize = new URL("https://discord.com/api/oauth2/authorize");
  authorize.searchParams.set("client_id", env.DISCORD_CLIENT_ID);
  authorize.searchParams.set("redirect_uri", redirectUri);
  authorize.searchParams.set("response_type", "code");
  authorize.searchParams.set("scope", "identify");
  authorize.searchParams.set("state", state);
  authorize.searchParams.set("prompt", "none");

  return new Response(null, {
    status: 302,
    headers: {
      Location: authorize.toString(),
      "Set-Cookie": `oauth_state=${state}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=600`,
    },
  });
}
