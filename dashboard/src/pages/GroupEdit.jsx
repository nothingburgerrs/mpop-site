import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../lib/api.js";
import EditForm from "../components/EditForm.jsx";
import ImageField from "../components/ImageField.jsx";

// Text fields go in EditForm (batched); image fields upload immediately.
const GROUP_FIELDS = [
  { key: "korean_name", label: "Korean name" },
  { key: "fandom_name", label: "Fandom name" },
  { key: "fandom_color", label: "Fandom color", placeholder: "#ff77aa", hint: "Hex color used for the fandom." },
  { key: "description", label: "Description", multiline: true },
];

const MEMBER_FIELDS = [
  { key: "name", label: "Name" },
  { key: "bio", label: "Bio", multiline: true },
];

export default function GroupEdit({ notify }) {
  const { name } = useParams();
  const [group, setGroup] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api.group(name).then(setGroup).catch((e) => setError(e.message));
  }, [name]);
  useEffect(load, [load]);

  if (error) return <p className="muted">{error}</p>;
  if (!group) return <p className="muted">Loading…</p>;

  const ro = group.readonly;

  const uploadGroupImage = (field) => async (blob) => {
    const updated = await api.uploadImage({ kind: "group", name, field, blob });
    setGroup(updated);
    notify({ message: "Image saved" });
  };

  return (
    <>
      <p className="muted"><Link to="/groups">← Groups</Link></p>
      <h2>{group.name}</h2>
      <p className="subtitle">Managed by {group.company}</p>

      <div className="readonly-grid">
        <div><div className="k">Tier</div><div className="v">{ro.tier}</div></div>
        <div><div className="k">Popularity</div><div className="v">{ro.popularity.toLocaleString()}</div></div>
        <div><div className="k">Wins</div><div className="v">{ro.wins}</div></div>
        <div><div className="k">Debut</div><div className="v">{ro.debut_date || "—"}</div></div>
      </div>

      <h3>Images</h3>
      <ImageField
        label="Profile picture" aspect={1} value={group.editable.profile_picture}
        hint="Square. Shown as the group's avatar."
        onUpload={uploadGroupImage("profile_picture")}
      />
      <ImageField
        label="Banner" aspect={3} value={group.editable.banner_url}
        hint="Wide banner across the group's profile."
        onUpload={uploadGroupImage("banner_url")}
      />

      <h3 style={{ marginTop: 32 }}>Details</h3>
      <EditForm
        fields={GROUP_FIELDS}
        initial={group.editable}
        onSave={async (changes) => {
          try {
            const updated = await api.saveGroup(name, changes);
            setGroup(updated);
            notify({ message: "Group saved" });
          } catch (e) {
            notify({ message: e.message, error: true });
          }
        }}
      />

      <h3 style={{ marginTop: 32 }}>Members ({group.members.length})</h3>
      {group.members.length === 0 ? (
        <p className="muted">No members. Add them with <code>/addmember</code> in Discord.</p>
      ) : (
        group.members.map((m) => (
          <div className="card" key={m.index} style={{ marginBottom: 14 }}>
            <div className="title" style={{ marginBottom: 12 }}>{m.name || `Member ${m.index + 1}`}</div>
            <ImageField
              label="Photo" aspect={3 / 4} value={m.image_url}
              hint="Portrait photo of the member."
              onUpload={async (blob) => {
                const updated = await api.uploadImage({
                  kind: "member", name, field: "image_url", index: m.index, blob,
                });
                setGroup(updated);
                notify({ message: "Member photo saved" });
              }}
            />
            <EditForm
              fields={MEMBER_FIELDS}
              initial={{ name: m.name, bio: m.bio }}
              onSave={async (changes) => {
                try {
                  const updated = await api.saveMember(name, m.index, changes);
                  setGroup(updated);
                  notify({ message: "Member saved" });
                } catch (e) {
                  notify({ message: e.message, error: true });
                }
              }}
            />
          </div>
        ))
      )}
    </>
  );
}
