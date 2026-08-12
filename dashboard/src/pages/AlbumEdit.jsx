import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { api } from "../lib/api.js";
import EditForm from "../components/EditForm.jsx";
import ImageField from "../components/ImageField.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";

const ALBUM_FIELDS = [
  { key: "title_track", label: "Title track" },
  { key: "release_date", label: "Release date", type: "date", hint: "When the album released. Affects charts, age decay, and 'first 24h'." },
];

// One editable song row: rename in place, keeping its streams/stats.
function SongRow({ song, onRename }) {
  const [value, setValue] = useState(song.name);
  const [busy, setBusy] = useState(false);
  const changed = value.trim() && value.trim() !== song.name;

  const save = async () => {
    setBusy(true);
    try {
      await onRename(song.name, value.trim());
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="song-row">
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && changed && !busy) save(); }}
      />
      {song.is_title && <span className="title-tag">title track</span>}
      <button className="secondary" onClick={save} disabled={!changed || busy}>
        {busy ? "…" : "Rename"}
      </button>
    </div>
  );
}

export default function AlbumEdit({ notify }) {
  const { name } = useParams();
  const navigate = useNavigate();
  const [album, setAlbum] = useState(null);
  const [error, setError] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(() => {
    api.album(name).then(setAlbum).catch((e) => setError(e.message));
  }, [name]);
  useEffect(load, [load]);

  if (error) return <p className="muted">{error}</p>;
  if (!album) return <p className="muted">Loading…</p>;

  const ro = album.readonly;
  const songs = album.songs || [];

  const uploadAlbumImage = (field) => async (blob) => {
    const updated = await api.uploadImage({ kind: "album", name, field, blob });
    setAlbum(updated);
    notify({ message: "Image saved" });
  };

  const renameSong = async (oldName, newName) => {
    try {
      const updated = await api.renameSong(name, oldName, newName);
      setAlbum(updated);
      notify({ message: "Song renamed" });
    } catch (e) {
      notify({ message: e.message, error: true });
    }
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

      <h3 style={{ marginTop: 32 }}>Songs ({songs.length})</h3>
      {songs.length === 0 ? (
        <p className="muted">No songs on this album. Add them with <code>/addsongs</code> in Discord.</p>
      ) : (
        <>
          <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
            Rename a song without losing its streams. To change which song is the
            title track, edit “Title track” above.
          </p>
          {songs.map((s) => (
            <SongRow key={s.name} song={s} onRename={renameSong} />
          ))}
        </>
      )}

      {/* Destructive action. */}
      <div className="danger-zone">
        <h3>Danger zone</h3>
        <p>Deleting an album is permanent and removes its stats.</p>
        <div className="danger-row">
          <div>
            <strong>Delete album</strong>
            <div className="muted" style={{ fontSize: 13 }}>
              Permanently removes {album.name} from {album.group}.
            </div>
          </div>
          <button className="danger" onClick={() => setConfirmDelete(true)}>Delete album</button>
        </div>
      </div>

      {confirmDelete && (
        <ConfirmDialog
          title={`Delete ${album.name}?`}
          message={`This permanently deletes the album and its stats (streams, sales, wins). This cannot be undone.`}
          confirmLabel="Delete forever"
          confirmPhrase={album.name}
          danger
          onCancel={() => setConfirmDelete(false)}
          onConfirm={async () => {
            await api.deleteAlbum(name);
            notify({ message: `Deleted ${album.name}` });
            navigate("/albums");
          }}
        />
      )}
    </>
  );
}
