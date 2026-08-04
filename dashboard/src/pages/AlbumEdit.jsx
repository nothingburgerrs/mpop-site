import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../lib/api.js";
import EditForm from "../components/EditForm.jsx";
import ImageField from "../components/ImageField.jsx";

const ALBUM_FIELDS = [
  { key: "title_track", label: "Title track" },
];

export default function AlbumEdit({ notify }) {
  const { name } = useParams();
  const [album, setAlbum] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api.album(name).then(setAlbum).catch((e) => setError(e.message));
  }, [name]);
  useEffect(load, [load]);

  if (error) return <p className="muted">{error}</p>;
  if (!album) return <p className="muted">Loading…</p>;

  const ro = album.readonly;

  const uploadAlbumImage = (field) => async (blob) => {
    const updated = await api.uploadImage({ kind: "album", name, field, blob });
    setAlbum(updated);
    notify({ message: "Image saved" });
  };

  return (
    <>
      <p className="muted"><Link to="/albums">← Albums</Link></p>
      <h2>{album.name}</h2>
      <p className="subtitle">By {album.group}</p>

      <div className="readonly-grid">
        <div><div className="k">Streams</div><div className="v">{ro.streams.toLocaleString()}</div></div>
        <div><div className="k">Sales</div><div className="v">{ro.sales.toLocaleString()}</div></div>
        <div><div className="k">Wins</div><div className="v">{ro.wins}</div></div>
        <div><div className="k">Released</div><div className="v">{ro.release_date || "—"}</div></div>
      </div>

      <h3>Images</h3>
      <ImageField
        label="Cover" aspect={1} value={album.editable.image_url}
        hint="Square album cover shown across the bot."
        onUpload={uploadAlbumImage("image_url")}
      />
      <ImageField
        label="Era image" aspect={16 / 9} value={album.editable.era_image_url}
        hint="Landscape image for music show boards. Falls back to the cover if unset."
        onUpload={uploadAlbumImage("era_image_url")}
      />

      <h3 style={{ marginTop: 32 }}>Details</h3>
      <EditForm
        fields={ALBUM_FIELDS}
        initial={album.editable}
        onSave={async (changes) => {
          try {
            const updated = await api.saveAlbum(name, changes);
            setAlbum(updated);
            notify({ message: "Album saved" });
          } catch (e) {
            notify({ message: e.message, error: true });
          }
        }}
      />
    </>
  );
}
