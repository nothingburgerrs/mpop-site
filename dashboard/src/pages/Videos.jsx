import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api.js";

// Your YouTube-style videos: MVs, vlogs, or whole made-up channels
// (drama/fan accounts). These are what show up in /youtube sidebars.
export default function Videos({ notify }) {
  const [videos, setVideos] = useState(null);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api.listVideos().then((d) => setVideos(d.videos)).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="muted">{error}</p>;
  if (!videos) return <p className="muted">Loading…</p>;

  const createNew = async () => {
    setCreating(true);
    try {
      const v = await api.createVideo({ title: "Untitled video", channel: "", type: "MV" });
      navigate(`/videos/${v.id}`);
    } catch (e) {
      notify({ message: e.message, error: true });
      setCreating(false);
    }
  };

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <h2 style={{ margin: 0 }}>Videos</h2>
        <button onClick={createNew} disabled={creating}>
          {creating ? "Creating…" : "New video"}
        </button>
      </div>
      <p className="subtitle" style={{ marginTop: 6 }}>
        Open a channel for a group, or make a drama/fan channel — upload MVs and vlogs.
        They appear in <code>/youtube</code> sidebars.
      </p>

      {videos.length === 0 ? (
        <p className="muted">No videos yet. Click <strong>New video</strong> to make one.</p>
      ) : (
        <table>
          <thead>
            <tr><th></th><th>Title</th><th>Channel</th><th>Type</th><th>Views</th></tr>
          </thead>
          <tbody>
            {videos.map((v) => (
              <tr key={v.id}>
                <td style={{ width: 116 }}>
                  <Link to={`/videos/${v.id}`}>
                    {v.thumbnail_url ? (
                      <img src={v.thumbnail_url} alt=""
                        style={{ width: 100, aspectRatio: "16/9", objectFit: "cover", borderRadius: 6, display: "block" }} />
                    ) : (
                      <span className="muted" style={{ fontSize: 12 }}>no thumbnail</span>
                    )}
                  </Link>
                </td>
                <td><Link to={`/videos/${v.id}`}>{v.title || "Untitled video"}</Link></td>
                <td>{v.channel || "—"}</td>
                <td>{v.type}</td>
                <td>{v.views.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
