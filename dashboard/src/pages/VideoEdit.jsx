import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { api } from "../lib/api.js";
import ImageField from "../components/ImageField.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";

const TYPES = ["MV", "Vlog", "Other"];

export default function VideoEdit({ notify }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [video, setVideo] = useState(null);
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);

  const load = useCallback(() => {
    api.listVideos()
      .then((d) => {
        const v = d.videos.find((x) => String(x.id) === String(id));
        if (!v) { setError("Video not found (or it isn't yours)."); return; }
        setVideo(v);
        setForm({
          title: v.title, channel: v.channel, type: v.type,
          views: v.views, likes: v.likes, dislikes: v.dislikes, date: v.date || "",
          group: v.group || "", album: v.album || "",
        });
      })
      .catch((e) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);

  if (error) return <p className="muted">{error}</p>;
  if (!video || !form) return <p className="muted">Loading…</p>;

  const set = (k, val) => setForm((f) => ({ ...f, [k]: val }));

  const uploadImg = (field) => async (blob) => {
    const updated = await api.uploadVideoImage({ id: video.id, field, blob });
    setVideo(updated);
    notify({ message: "Image saved" });
  };

  const save = async () => {
    setSaving(true);
    try {
      const updated = await api.saveVideo(video.id, {
        title: form.title, channel: form.channel, type: form.type,
        views: form.views, likes: form.likes, dislikes: form.dislikes, date: form.date,
        group: form.group, album: form.album,
      });
      setVideo(updated);
      setForm((f) => ({ ...f, ...updated }));
      notify({ message: "Video saved" });
    } catch (e) {
      notify({ message: e.message, error: true });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <p className="muted"><Link to="/videos">← Videos</Link></p>
      <h2>{video.title || "Untitled video"}</h2>
      <p className="subtitle">{video.channel || "No channel yet"} · {video.type}</p>

      <h3>Images</h3>
      <ImageField
        label="Thumbnail" aspect={16 / 9} value={video.thumbnail_url}
        hint="The video thumbnail (16:9). Shown as the main video and in sidebars."
        onUpload={uploadImg("thumbnail_url")}
      />
      <ImageField
        label="Channel logo" aspect={1} value={video.channel_logo}
        hint="Round channel avatar. Square image."
        onUpload={uploadImg("channel_logo")}
      />

      <h3 style={{ marginTop: 32 }}>Details</h3>
      <div className="form-row">
        <label>Title</label>
        <input type="text" value={form.title} onChange={(e) => set("title", e.target.value)}
          placeholder="GROUP (그룹) 'Song' Official MV" />
      </div>
      <div className="form-row">
        <label>Channel</label>
        <input type="text" value={form.channel} onChange={(e) => set("channel", e.target.value)}
          placeholder="ROM.COM · Wings · a drama channel…" />
        <div className="hint">Free text — the uploader shown on the video.</div>
      </div>
      <div className="form-row">
        <label>Type</label>
        <select value={form.type} onChange={(e) => set("type", e.target.value)}>
          {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      <div className="card-grid" style={{ marginBottom: 16 }}>
        <div className="form-row" style={{ marginBottom: 0 }}>
          <label>Views</label>
          <input type="number" min="0" value={form.views} onChange={(e) => set("views", e.target.value)} />
        </div>
        <div className="form-row" style={{ marginBottom: 0 }}>
          <label>Likes</label>
          <input type="number" min="0" value={form.likes} onChange={(e) => set("likes", e.target.value)} />
        </div>
        <div className="form-row" style={{ marginBottom: 0 }}>
          <label>Dislikes</label>
          <input type="number" min="0" value={form.dislikes} onChange={(e) => set("dislikes", e.target.value)} />
        </div>
      </div>

      <div className="form-row">
        <label>Upload date</label>
        <input type="date" value={form.date || ""} onChange={(e) => set("date", e.target.value)} />
        <div className="hint">Used for the “X ago” shown under the video.</div>
      </div>

      <div className="form-row">
        <label>Link to a game MV (optional)</label>
        <div className="hint" style={{ marginTop: 0, marginBottom: 6 }}>
          Fill both to make <code>/youtube {form.group || "group"} {form.album || "album"}</code> render
          <strong> this</strong> video — with the album’s real views.
        </div>
        <input type="text" value={form.group} onChange={(e) => set("group", e.target.value)}
          placeholder="Group (e.g. ROM.COM)" style={{ marginBottom: 8 }} />
        <input type="text" value={form.album} onChange={(e) => set("album", e.target.value)}
          placeholder="Album (e.g. Girl Of The Year)" />
      </div>

      <button onClick={save} disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>

      <div className="danger-zone">
        <h3>Danger zone</h3>
        <div className="danger-row">
          <div>
            <strong>Delete video</strong>
            <div className="muted" style={{ fontSize: 13 }}>Permanently removes this video.</div>
          </div>
          <button className="danger" onClick={() => setConfirmDel(true)}>Delete video</button>
        </div>
      </div>

      {confirmDel && (
        <ConfirmDialog
          title={`Delete “${video.title || "this video"}”?`}
          message="This permanently deletes the video. This cannot be undone."
          confirmLabel="Delete forever" danger
          onCancel={() => setConfirmDel(false)}
          onConfirm={async () => {
            await api.deleteVideo(video.id);
            notify({ message: "Video deleted" });
            navigate("/videos");
          }}
        />
      )}
    </>
  );
}
