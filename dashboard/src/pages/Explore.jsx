import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api.js";
import SmartImg from "../components/SmartImg.jsx";

// Public, kpopping-style directory: browse and search every group, not just the
// ones you own. Read-only.
export default function Explore() {
  const [groups, setGroups] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    api.publicGroups().then((d) => setGroups(d.groups)).catch((e) => setError(e.message));
  }, []);

  const filtered = useMemo(() => {
    if (!groups) return [];
    const s = q.trim().toLowerCase();
    if (!s) return groups;
    return groups.filter((g) =>
      (g.name || "").toLowerCase().includes(s) ||
      (g.korean_name || "").toLowerCase().includes(s) ||
      (g.company || "").toLowerCase().includes(s));
  }, [groups, q]);

  if (error) return <p className="muted">{error}</p>;
  if (!groups) return <p className="muted">Loading…</p>;

  return (
    <>
      <h2>Explore</h2>
      <p className="subtitle">Every group in the world — search by name, company, or Korean name.</p>

      <input
        className="explore-search" type="search" value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={`Search ${groups.length} groups…`} />

      {filtered.length === 0 ? (
        <p className="muted">No groups match “{q}”.</p>
      ) : (
        <div className="explore-grid">
          {filtered.map((g) => (
            <Link key={g.name} to={`/explore/${encodeURIComponent(g.name)}`} className="group-card">
              <div className="group-card-art">
                <SmartImg src={g.profile_picture} fallback={
                  <div className="group-card-fallback" style={{ background: g.fandom_color || "var(--accent-dim)" }}>
                    <span>{(g.name || "?").charAt(0)}</span>
                  </div>} />
                <span className={"tier-badge tier-" + (g.tier || "NUGU").toLowerCase()}>{g.tier}</span>
              </div>
              <div className="group-card-body">
                <div className="group-card-name">
                  {g.name}
                  {g.is_disbanded && <span className="badge" style={{ marginLeft: 6 }}>disbanded</span>}
                </div>
                <div className="group-card-meta">{g.korean_name || g.company}</div>
                <div className="group-card-sub">{g.member_count} members · {g.album_count} albums</div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
