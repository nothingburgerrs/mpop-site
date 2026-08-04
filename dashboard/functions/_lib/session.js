// Signed session cookies for the dashboard.
//
// After Discord OAuth we store the user's verified Discord id in an HMAC-signed,
// HttpOnly cookie. The signature (SESSION_SECRET) means the browser cannot forge
// or alter it, and HttpOnly keeps JavaScript from reading it. This is all the
// session state we need: the bot API is the source of truth for everything else.

// Fail early and clearly when a required Pages environment variable is missing,
// instead of forwarding "undefined" to Discord or the bot and getting a cryptic
// downstream error.
export function requireEnv(env, names) {
  const missing = names.filter((n) => !env[n]);
  if (missing.length) {
    return new Response(
      JSON.stringify({
        error: `Server not configured: missing ${missing.join(", ")}. ` +
          `Set these in Cloudflare Pages → Settings → Environment variables, then redeploy.`,
      }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
  return null;
}

const COOKIE_NAME = "mpb_session";
const MAX_AGE_SECONDS = 60 * 60 * 24 * 7; // 7 days

const encoder = new TextEncoder();

function base64url(bytes) {
  let str = btoa(String.fromCharCode(...new Uint8Array(bytes)));
  return str.replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function base64urlToBytes(str) {
  str = str.replaceAll("-", "+").replaceAll("_", "/");
  while (str.length % 4) str += "=";
  return Uint8Array.from(atob(str), (c) => c.charCodeAt(0));
}

async function hmacKey(secret) {
  return crypto.subtle.importKey(
    "raw", encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]
  );
}

// Token format: base64url(JSON payload) + "." + base64url(HMAC).
export async function createSession(payload, secret) {
  const body = base64url(encoder.encode(JSON.stringify({
    ...payload,
    exp: Math.floor(Date.now() / 1000) + MAX_AGE_SECONDS,
  })));
  const key = await hmacKey(secret);
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(body));
  return `${body}.${base64url(sig)}`;
}

export async function verifySession(token, secret) {
  if (!token || !token.includes(".")) return null;
  const [body, sig] = token.split(".");
  const key = await hmacKey(secret);
  const valid = await crypto.subtle.verify(
    "HMAC", key, base64urlToBytes(sig), encoder.encode(body)
  );
  if (!valid) return null;

  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(base64urlToBytes(body)));
  } catch {
    return null;
  }
  if (!payload.exp || payload.exp < Math.floor(Date.now() / 1000)) return null;
  return payload;
}

export function sessionCookie(token) {
  return `${COOKIE_NAME}=${token}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=${MAX_AGE_SECONDS}`;
}

export function clearCookie() {
  return `${COOKIE_NAME}=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0`;
}

export function readSessionCookie(request) {
  const header = request.headers.get("Cookie") || "";
  for (const part of header.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === COOKIE_NAME) return rest.join("=");
  }
  return null;
}

// Resolve the current user's Discord id from the request, or null.
export async function currentUser(request, env) {
  const token = readSessionCookie(request);
  if (!token) return null;
  return verifySession(token, env.SESSION_SECRET);
}
