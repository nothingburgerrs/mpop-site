import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api.js";

export default function Groups() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.owned().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="muted">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <>
      <h2>Groups</h2>
      <p className="subtitle">Select a group to edit its details, fandom, and members.</p>
      {data.groups.length === 0 ? (
        <p className="muted">You don't manage any groups yet.</p>
      ) : (
        <table>
          <thead>
            <tr><th>Group</th><th>Company</th><th>Tier</th><th>Albums</th><th>Members</th></tr>
          </thead>
          <tbody>
            {data.groups.map((g) => (
              <tr key={g.name}>
                <td>
                  <Link to={`/groups/${encodeURIComponent(g.name)}`}>{g.name}</Link>
                  {g.is_disbanded && <span className="badge" style={{ marginLeft: 8 }}>disbanded</span>}
                </td>
                <td>{g.company}</td>
                <td>{g.tier}</td>
                <td>{g.album_count}</td>
                <td>{g.member_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
