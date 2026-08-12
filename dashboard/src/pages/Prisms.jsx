import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api.js";

// Prisms are the collectible member cards pulled with /pull in Discord. Here a
// group owner uploads custom card art per member, plus the "Special Prism" that
// unlocks in the center of a member's grid once it's completed. Pick a group to
// edit its members' cards.
export default function Prisms() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.owned().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="muted">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  const groups = data.groups.filter((g) => g.member_count > 0);

  return (
    <>
      <h2>Prisms</h2>
      <p className="subtitle">
        Upload custom card art for each member. When a collector completes a
        member's grid in <code>/pull</code>, the Special Prism you set is revealed
        in the center.
      </p>

      {groups.length === 0 ? (
        <p className="muted">
          No groups with members yet. Add members with <code>/addmember</code> in
          Discord first, then come back to give them card art.
        </p>
      ) : (
        <table>
          <thead>
            <tr><th>Group</th><th>Company</th><th>Members</th></tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr key={g.name}>
                <td>
                  <Link to={`/prisms/${encodeURIComponent(g.name)}`}>{g.name}</Link>
                  {g.is_disbanded && <span className="badge" style={{ marginLeft: 8 }}>disbanded</span>}
                </td>
                <td>{g.company}</td>
                <td>{g.member_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
