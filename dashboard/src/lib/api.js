// Tiny fetch wrapper for the dashboard's own /api and /auth endpoints.
// Everything is same-origin (Cloudflare Pages), so cookies ride along.

async function request(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const message = (data && data.error) || `request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

export const api = {
  me: () => request("/auth/me"),
  owned: () => request("/api/me"),
  // Public browsing (any signed-in user; not ownership-scoped).
  publicGroups: () => request("/api/public/groups"),
  publicGroup: (name) => request(`/api/public/groups/${encodeURIComponent(name)}`),
  group: (name) => request(`/api/groups/${encodeURIComponent(name)}`),
  saveGroup: (name, changes) =>
    request(`/api/groups/${encodeURIComponent(name)}`, {
      method: "PATCH", body: JSON.stringify(changes),
    }),
  album: (name) => request(`/api/albums/${encodeURIComponent(name)}`),
  saveAlbum: (name, changes) =>
    request(`/api/albums/${encodeURIComponent(name)}`, {
      method: "PATCH", body: JSON.stringify(changes),
    }),
  saveMember: (groupName, index, changes) =>
    request(`/api/groups/${encodeURIComponent(groupName)}/members/${index}`, {
      method: "PATCH", body: JSON.stringify(changes),
    }),

  // Reversible: mark a group inactive (or active again). Not a deletion.
  disbandGroup: (name, disbanded) =>
    request(`/api/groups/${encodeURIComponent(name)}/disband`, {
      method: "POST", body: JSON.stringify({ disbanded }),
    }),
  // Permanent: removes the group AND all its albums.
  deleteGroup: (name) =>
    request(`/api/groups/${encodeURIComponent(name)}`, { method: "DELETE" }),
  // Permanent: removes a single album.
  deleteAlbum: (name) =>
    request(`/api/albums/${encodeURIComponent(name)}`, { method: "DELETE" }),
  // Rename one song in an album's tracklist (keeps its streams/stats).
  renameSong: (albumName, oldName, newName) =>
    request(`/api/albums/${encodeURIComponent(albumName)}/songs/rename`, {
      method: "POST", body: JSON.stringify({ old: oldName, new: newName }),
    }),

  // --- Videos (the YouTube section) ---
  listVideos: () => request("/api/videos"),
  createVideo: (fields) =>
    request("/api/videos", { method: "POST", body: JSON.stringify(fields) }),
  saveVideo: (id, changes) =>
    request(`/api/videos/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
  deleteVideo: (id) => request(`/api/videos/${id}`, { method: "DELETE" }),
  // Upload a cropped image (thumbnail or channel logo) for a video, via R2.
  uploadVideoImage: ({ id, field, blob }) =>
    api.uploadImage({ kind: "video", name: String(id), field, blob }),
  // Upload a cropped member image (Prism card art / special prism), via R2.
  // Returns the refreshed group resource (the bot's member PATCH response).
  uploadMemberImage: ({ group, index, field, blob }) =>
    api.uploadImage({ kind: "member", name: group, field, index, blob }),

  // --- Prisms (Objekt-style versions on a group) ---
  listPrisms: (group) => request(`/api/groups/${encodeURIComponent(group)}/prisms`),
  createVersion: (group, fields) =>
    request(`/api/groups/${encodeURIComponent(group)}/prisms`, {
      method: "POST", body: JSON.stringify(fields),
    }),
  saveVersion: (group, vid, changes) =>
    request(`/api/groups/${encodeURIComponent(group)}/prisms/${vid}`, {
      method: "PATCH", body: JSON.stringify(changes),
    }),
  deleteVersion: (group, vid) =>
    request(`/api/groups/${encodeURIComponent(group)}/prisms/${vid}`, { method: "DELETE" }),
  saveCardClass: (group, vid, member, slot, cls) =>
    request(`/api/groups/${encodeURIComponent(group)}/prisms/${vid}/cards/${encodeURIComponent(member)}/${slot}`, {
      method: "PATCH", body: JSON.stringify({ class: cls }),
    }),
  // Returns the refreshed version (the bot's set_prism_card / set_prism_special response).
  uploadPrismCard: ({ group, vid, member, slot, blob }) =>
    api.uploadImage({ kind: "prismcard", name: group, field: "art_url", blob,
      extra: { version: vid, member, slot } }),
  uploadPrismSpecial: ({ group, vid, member, blob }) =>
    api.uploadImage({ kind: "prismspecial", name: group, field: "special_url", blob,
      extra: { version: vid, member } }),

  // Upload a cropped image blob for one field. The server stores it and points
  // the field at it (enforcing ownership), returning the refreshed resource.
  uploadImage: async ({ kind, name, field, index, extra, blob }) => {
    const params = new URLSearchParams({ kind, name, field });
    if (index !== undefined && index !== null) params.set("index", String(index));
    if (extra) {
      for (const [k, v] of Object.entries(extra)) {
        if (v !== undefined && v !== null) params.set(k, String(v));
      }
    }
    const res = await fetch(`/api/upload?${params.toString()}`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": blob.type },
      body: blob,
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) throw new Error((data && data.error) || `upload failed (${res.status})`);
    return data;
  },
};
