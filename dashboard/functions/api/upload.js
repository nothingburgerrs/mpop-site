// POST /api/upload?kind=&name=&field=&index= — store a cropped image, then set it.
//
// The browser sends already-cropped image bytes (see the crop editor). We store
// them in R2 and then call the bot's existing PATCH endpoint to point the field
// at the new URL — so ownership is enforced by the bot, exactly as for text
// edits. If the bot rejects the change, the stored object is removed so we don't
// leave orphans. No bot changes are needed for uploads.

import { currentUser } from "../_lib/session.js";
import { callBot } from "../_lib/bot.js";

// Only image fields, and only the ones the bot already allows editing.
const IMAGE_FIELDS = {
  group: new Set(["profile_picture", "banner_url"]),
  album: new Set(["image_url", "era_image_url"]),
  member: new Set(["image_url", "card_url", "special_url"]),
  video: new Set(["thumbnail_url", "channel_logo"]),
};

const ALLOWED_TYPES = { "image/webp": "webp", "image/jpeg": "jpg", "image/png": "png" };
const MAX_BYTES = 10 * 1024 * 1024;

export async function onRequestPost({ request, env }) {
  const user = await currentUser(request, env);
  if (!user) return json({ error: "not authenticated" }, 401);
  if (!env.MEDIA || !env.R2_PUBLIC_URL) {
    return json({ error: "image storage is not configured" }, 500);
  }

  const url = new URL(request.url);
  const kind = url.searchParams.get("kind");
  const name = url.searchParams.get("name");
  const field = url.searchParams.get("field");
  const index = url.searchParams.get("index");

  if (!IMAGE_FIELDS[kind] || !IMAGE_FIELDS[kind].has(field) || !name) {
    return json({ error: "invalid upload target" }, 400);
  }

  const contentType = (request.headers.get("Content-Type") || "").split(";")[0];
  const ext = ALLOWED_TYPES[contentType];
  if (!ext) return json({ error: "unsupported image type" }, 415);

  const bytes = await request.arrayBuffer();
  if (bytes.byteLength === 0) return json({ error: "empty upload" }, 400);
  if (bytes.byteLength > MAX_BYTES) return json({ error: "image too large" }, 413);

  const key = `media/${user.id}/${crypto.randomUUID()}.${ext}`;
  await env.MEDIA.put(key, bytes, { httpMetadata: { contentType } });
  const publicUrl = `${env.R2_PUBLIC_URL.replace(/\/$/, "")}/${key}`;

  // Persist through the bot, which enforces ownership. Roll back on failure.
  let botPath;
  if (kind === "member") {
    if (index === null || index === "") {
      await env.MEDIA.delete(key);
      return json({ error: "member index required" }, 400);
    }
    botPath = `/api/groups/${encodeURIComponent(name)}/members/${encodeURIComponent(index)}`;
  } else {
    botPath = `/api/${kind}s/${encodeURIComponent(name)}`;
  }

  let botRes;
  try {
    botRes = await callBot(env, user.id, "PATCH", botPath, { [field]: publicUrl });
  } catch {
    await env.MEDIA.delete(key);
    return json({ error: "bot is unreachable" }, 502);
  }

  if (!botRes.ok) {
    await env.MEDIA.delete(key); // don't keep an image we couldn't attach
    const text = await botRes.text();
    return new Response(text, { status: botRes.status, headers: { "Content-Type": "application/json" } });
  }

  // Return the bot's updated resource so the UI can refresh in place.
  const text = await botRes.text();
  return new Response(text, { status: 200, headers: { "Content-Type": "application/json" } });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}
