import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { api } from "../lib/api.js";
import EditForm from "../components/EditForm.jsx";
import ImageField from "../components/ImageField.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";

// Text fields go in EditForm (batched); image fields upload immediately.
const GROUP_FIELDS = [
  { key: "korean_name", label: "Korean name" },
  { key: "fandom_name", label: "Fandom name" },
  { key: "fandom_color", label: "Fandom color", placeholder: "#ff77aa", hint: "Hex color used for the fandom." },
  { key: "debut_date", label: "Debut date", type: "date", hint: "The group's official debut date." },
  { key: "description", label: "Description", multiline: true },
];

const MEMBER_FIELDS = [
  { key: "name", label: "Name" },
  { key: "bio", label: "Bio", multiline: true },
];

export default function GroupEdit({ notify }) {
  const { name } = useParams();
  const navigate = useNavigate();
  const [group, setGroup] = useState(null);
  const [error, setError] = useState(null);
  const [dialog, setDialog] = useState(null); // "disband" | "delete" | null

  const load = useCallback(() => {
    api.group(name).then(setGroup).catch((e) => setError(e.message));
  }, [name]);
  useEffect(load, [load]);

  if (error) return <p className="muted">{error}</p>;
  if (!group) return <p className="muted">Loading…</p>;

  const ro = group.readonly;
  const disbanded = ro.is_disbanded;

  const uploadGroupImage = (field) => async (blob) => {
    const updated = await api.uploadImage({ kind: "group", name, field, blob });
    setGroup(updated);
    notify({ message: "Image saved" });
  };

  return (
    <>
      <p className="muted"><Link to="/groups">← Groups</Link></p>
      <h2>{group.name}{disbanded && <span className="badge" style={{ marginLeft: 10 }}>disbanded</span>}</h2>
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

      {/* Destructive actions, kept apart at the bottom. */}
      <div className="danger-zone">
        <h3>Danger zone</h3>
        <p>Disbanding is reversible. Deleting is permanent.</p>

        <div className="danger-row">
          <div>
            <strong>{disbanded ? "Reactivate group" : "Disband group"}</strong>
            <div className="muted" style={{ fontSize: 13 }}>
              {disbanded
                ? "Bring the group back to active status."
                : "Mark inactive — the group stops releasing new music. Can be undone."}
            </div>
          </div>
          <button className="secondary" onClick={() => setDialog("disband")}>
            {disbanded ? "Reactivate" : "Disband"}
          </button>
        </div>

        <div className="danger-row">
          <div>
            <strong>Delete group</strong>
            <div className="muted" style={{ fontSize: 13 }}>
              Permanently removes {group.name} and all {group.albums.length} of its albums.
            </div>
          </div>
          <button className="danger" onClick={() => setDialog("delete")}>Delete group</button>
        </div>
      </div>

      {dialog === "disband" && (
        <ConfirmDialog
          title={disbanded ? `Reactivate ${group.name}?` : `Disband ${group.name}?`}
          message={disbanded
            ? "The group will be active again and can release music."
            : "The group will be marked inactive. You can reactivate it any time."}
          confirmLabel={disbanded ? "Reactivate" : "Disband"}
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            const updated = await api.disbandGroup(name, !disbanded);
            setGroup(updated);
            setDialog(null);
            notify({ message: disbanded ? "Group reactivated" : "Group disbanded" });
          }}
        />
      )}

      {dialog === "delete" && (
        <ConfirmDialog
          title={`Delete ${group.name}?`}
          message={`This permanently deletes the group and all ${group.albums.length} of its albums, including their stats. This cannot be undone.`}
          confirmLabel="Delete forever"
          confirmPhrase={group.name}
          danger
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            await api.deleteGroup(name);
            notify({ message: `Deleted ${group.name}` });
            navigate("/groups");
          }}
        />
      )}
    </>
  );
}
