import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../lib/api.js";
import ImageField from "../components/ImageField.jsx";

// Prism card art is a tall portrait card, like a real photocard (~2:3).
const CARD_ASPECT = 2 / 3;
// Mirrors GRID_SIZE in the bot: how many of the SAME member complete their grid.
const GRID_SIZE = 5;

// A preview of a member's completed grid: the card art tiled around the center
// Special Prism — the same shape collectors see in Discord. Empty slots show
// their card number, exactly like an unpulled grid.
function GridPreview({ card, special }) {
  const slots = [101, 102, 103, 104, /* center */ 105, 106, 107, 108];
  const cells = [];
  for (let pos = 0; pos < 9; pos++) {
    if (pos === 4) {
      cells.push(
        <div key="center" className="prism-cell prism-center">
          {special
            ? <img src={special} alt="Special Prism" />
            : <span className="prism-q">?</span>}
        </div>
      );
    } else {
      const n = slots[pos < 4 ? pos : pos - 1];
      cells.push(
        <div key={pos} className="prism-cell">
          {card
            ? <img src={card} alt="" />
            : <span className="prism-num">{n}</span>}
        </div>
      );
    }
  }
  return <div className="prism-grid">{cells}</div>;
}

export default function PrismEdit({ notify }) {
  const { name } = useParams();
  const [group, setGroup] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api.group(name).then(setGroup).catch((e) => setError(e.message));
  }, [name]);
  useEffect(load, [load]);

  if (error) return <p className="muted">{error}</p>;
  if (!group) return <p className="muted">Loading…</p>;

  const upload = (index, field) => async (blob) => {
    const updated = await api.uploadMemberImage({ group: name, index, field, blob });
    setGroup(updated);
    notify({ message: "Prism art saved" });
  };

  return (
    <>
      <p className="muted"><Link to="/prisms">← Prisms</Link></p>
      <h2>{group.name} — Prisms</h2>
      <p className="subtitle">
        Give each member custom card art. Collectors pull these with <code>/pull</code>;
        collecting <strong>{GRID_SIZE}</strong> of the same member completes their grid
        and reveals the Special Prism in the center.
      </p>

      {group.members.length === 0 ? (
        <p className="muted">This group has no members yet.</p>
      ) : (
        group.members.map((m) => (
          <div className="card" key={m.index} style={{ marginBottom: 20 }}>
            <div className="title" style={{ marginBottom: 12 }}>
              {m.name || `Member ${m.index + 1}`}
            </div>
            <div className="prism-editor">
              <div className="prism-fields">
                <ImageField
                  label="Card art" aspect={CARD_ASPECT} value={m.card_url}
                  hint="The Prism shown on /pull. Portrait card (2:3). Falls back to the member's photo if unset."
                  onUpload={upload(m.index, "card_url")}
                />
                <ImageField
                  label="Special Prism (center)" aspect={CARD_ASPECT} value={m.special_url}
                  hint="Revealed in the center once a collector completes this member's grid."
                  onUpload={upload(m.index, "special_url")}
                />
              </div>
              <div className="prism-preview">
                <div className="hint" style={{ marginBottom: 6 }}>Completed-grid preview</div>
                <GridPreview card={m.card_url || m.image_url} special={m.special_url} />
              </div>
            </div>
          </div>
        ))
      )}
    </>
  );
}
