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

  // Upload a cropped image blob for one field. The server stores it and points
  // the field at it (enforcing ownership), returning the refreshed resource.
  uploadImage: async ({ kind, name, field, index, blob }) => {
    const params = new URLSearchParams({ kind, name, field });
    if (index !== undefined && index !== null) params.set("index", String(index));
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
