import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../lib/api.js";
import ImageField from "../components/ImageField.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";

// Prism card art is a tall portrait card, like a real photocard (~2:3).
const CARD_ASPECT = 2 / 3;

// A preview of one member's grid: the card designs in a plus around the center
// Special Prism (top / left / right / bottom), echoing the in-Discord /grid
// image. Empty slots show a "?" (collectors pull them to fill).
const POS = ["pos-n", "pos-w", "pos-e", "pos-s"];
function GridPreview({ slots, special, color, gridSize }) {
  return (
    <div className="prism-grid">
      {slots.slice(0, gridSize).map((c, i) => (
        <div key={i} className={"prism-cell " + (POS[i] || "")} style={c && c.art_url ? { borderColor: color } : undefined}>
          {c && c.art_url
            ? <img src={c.art_url} alt="" />
            : <span className="prism-num">{101 + i}</span>}
        </div>
      ))}
      <div className="prism-cell prism-center pos-c" style={{ borderColor: color }}>
        {special ? <img src={special} alt="Special Prism" /> : <span className="prism-q">?</span>}
      </div>
    </div>
  );
}

function MemberGrid({ group, version, member, gridSize, onVersion, notify }) {
  const mentry = (version.members && version.members[member]) || {};
  const cards = mentry.cards || [];
  const bySlot = {};
  for (const c of cards) bySlot[c.slot] = c;

  const uploadCard = (slot) => async (blob) => {
    const updated = await api.uploadPrismCard({ group, vid: version.id, member, slot, blob });
    onVersion(updated);
    notify({ message: `Slot ${slot} art saved` });
  };
  const uploadSpecial = async (blob) => {
    const updated = await api.uploadPrismSpecial({ group, vid: version.id, member, blob });
    onVersion(updated);
    notify({ message: "Special Prism saved" });
  };
  const slotArr = Array.from({ length: gridSize }, (_, i) => bySlot[i + 1] || null);
  const filled = slotArr.filter((c) => c && c.art_url).length;

  return (
    <details className="card" style={{ marginBottom: 14 }}>
      <summary className="prism-member-summary">
        <strong>{member}</strong>
        <span className="muted" style={{ fontSize: 13 }}>{filled}/{gridSize} cards{mentry.special_url ? " · special ✓" : ""}</span>
      </summary>

      <div className="prism-editor" style={{ marginTop: 14 }}>
        <div className="prism-fields">
          {slotArr.map((c, i) => {
            const slot = i + 1;
            return (
              <div key={slot} className="prism-slot-row">
                <div className="prism-slot-label">#{slot}</div>
                <ImageField
                  label="" aspect={CARD_ASPECT} value={c ? c.art_url : ""}
                  hint="" onUpload={uploadCard(slot)}
                />
              </div>
            );
          })}
          <div className="prism-slot-row" style={{ marginTop: 6 }}>
            <div className="prism-slot-label">★</div>
            <ImageField
              label="" aspect={CARD_ASPECT} value={mentry.special_url || ""}
              hint="Center Special Prism — revealed when a collector completes this member's grid."
              onUpload={uploadSpecial}
            />
          </div>
        </div>
        <div className="prism-preview">
          <div className="hint" style={{ marginBottom: 6 }}>Grid preview</div>
          <GridPreview slots={slotArr} special={mentry.special_url} color={version.color} gridSize={gridSize} />
        </div>
      </div>
    </details>
  );
}

export default function PrismEdit({ notify }) {
  const { name } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [creating, setCreating] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);

  const load = useCallback(() => {
    api.listPrisms(name)
      .then((d) => {
        setData(d);
        setSelectedId((cur) => cur ?? (d.versions[0]?.id ?? null));
      })
      .catch((e) => setError(e.message));
  }, [name]);
  useEffect(load, [load]);

  if (error) return <p className="muted">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  const replaceVersion = (v) =>
    setData((d) => ({ ...d, versions: d.versions.map((x) => (x.id === v.id ? v : x)) }));

  const version = data.versions.find((v) => v.id === selectedId) || null;

  const createNew = async () => {
    setCreating(true);
    try {
      const v = await api.createVersion(name, { name: "New version", color: "#8b5cf6" });
      setData((d) => ({ ...d, versions: [...d.versions, v] }));
      setSelectedId(v.id);
    } catch (e) {
      notify({ message: e.message, error: true });
    } finally {
      setCreating(false);
    }
  };

  const saveMeta = async (changes) => {
    try {
      const v = await api.saveVersion(name, version.id, changes);
      replaceVersion(v);
    } catch (e) {
      notify({ message: e.message, error: true });
    }
  };

  return (
    <>
      <p className="muted"><Link to="/prisms">← Prisms</Link></p>
      <h2>{data.group} — Prisms</h2>
      <p className="subtitle">
        Build <strong>versions</strong> (like Objekt seasons). Each member gets a{" "}
        {data.grid_size}-card grid; collectors who pull all {data.grid_size} of a member's
        cards reveal the center Special Prism.
      </p>

      <div className="prism-version-bar">
        {data.versions.map((v) => (
          <button key={v.id}
            className={"prism-version-pill" + (v.id === selectedId ? " active" : "")}
            onClick={() => setSelectedId(v.id)}>
            <span className="prism-dot" style={{ background: v.color }} />
            {v.name}
          </button>
        ))}
        <button className="secondary" onClick={createNew} disabled={creating}>
          {creating ? "Creating…" : "+ New version"}
        </button>
      </div>

      {data.members.length === 0 ? (
        <p className="muted">This group has no members yet.</p>
      ) : !version ? (
        <p className="muted">Create a version to start adding card art.</p>
      ) : (
        <>
          <div className="prism-version-head">
            <input type="text" defaultValue={version.name} key={`n-${version.id}`}
              onBlur={(e) => e.target.value.trim() && e.target.value !== version.name && saveMeta({ name: e.target.value.trim() })}
              className="prism-version-name" />
            <label className="prism-color" title="Accent color">
              <input type="color" value={version.color}
                onChange={(e) => saveMeta({ color: e.target.value })} />
            </label>
            <button className="danger" onClick={() => setConfirmDel(true)}>Delete version</button>
          </div>

          {data.members.map((m) => (
            <MemberGrid key={m} group={name} version={version} member={m}
              gridSize={data.grid_size}
              onVersion={replaceVersion} notify={notify} />
          ))}
        </>
      )}

      {confirmDel && version && (
        <ConfirmDialog
          title={`Delete version “${version.name}”?`}
          message="This removes the version and all its card art for every member. Collectors keep any cards they already pulled. This cannot be undone."
          confirmLabel="Delete version" danger
          onCancel={() => setConfirmDel(false)}
          onConfirm={async () => {
            await api.deleteVersion(name, version.id);
            setData((d) => ({ ...d, versions: d.versions.filter((x) => x.id !== version.id) }));
            setSelectedId(null);
            setConfirmDel(false);
            notify({ message: "Version deleted" });
          }}
        />
      )}
    </>
  );
}
