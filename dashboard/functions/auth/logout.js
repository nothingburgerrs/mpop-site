// POST /auth/logout — clears the session cookie.
import { clearCookie } from "../_lib/session.js";

export async function onRequestPost({ request }) {
  const url = new URL(request.url);
  return new Response(null, {
    status: 302,
    headers: { Location: url.origin + "/", "Set-Cookie": clearCookie() },
  });
}
