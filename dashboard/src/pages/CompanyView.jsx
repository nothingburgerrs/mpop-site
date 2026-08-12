import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../lib/api.js";

// Everything under one company: its funds and the groups it manages.
export default function CompanyView() {
  const { name } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.owned().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="muted">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  const company = data.companies.find((c) => c.name === name);
  const groups = data.groups.filter((g) => g.company === name);

  return (
    <>
      <p className="muted"><Link to="/">← Overview</Link></p>
      <h2>{name}</h2>
      <p className="subtitle">
        {company ? `Funds: ${company.funds.toLocaleString()}` : "Company"} · {groups.length} group{groups.length === 1 ? "" : "s"}
      </p>

      {groups.length === 0 ? (
        <p className="muted">This company doesn't manage any groups yet.</p>
      ) : (
        <table>
          <thead>
            <tr><th>Group</th><th>Tier</th><th>Popularity</th><th>Albums</th><th>Members</th></tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr key={g.name}>
                <td>
                  <Link to={`/groups/${encodeURIComponent(g.name)}`}>{g.name}</Link>
                  {g.is_disbanded && <span className="badge" style={{ marginLeft: 8 }}>disbanded</span>}
                </td>
                <td>{g.tier}</td>
                <td>{g.popularity.toLocaleString()}</td>
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
