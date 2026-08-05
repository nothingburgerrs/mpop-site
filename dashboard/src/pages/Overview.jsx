import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api.js";

// Landing view: a quick count of what you own, and your companies.
export default function Overview() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.owned().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="muted">Could not load your data: {error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <>
      <h2>Overview</h2>
      <p className="subtitle">Everything registered to your Discord account.</p>

      <div className="card-grid" style={{ marginBottom: 28 }}>
        <div className="card">
          <div className="title">{data.companies.length}</div>
          <div className="meta">Companies</div>
        </div>
        <Link className="card" to="/groups">
          <div className="title">{data.groups.length}</div>
          <div className="meta">Groups</div>
        </Link>
        <Link className="card" to="/albums">
          <div className="title">{data.albums.length}</div>
          <div className="meta">Albums</div>
        </Link>
      </div>

      <h3>Companies</h3>
      {data.companies.length === 0 ? (
        <p className="muted">You don't own any companies yet.</p>
      ) : (
        <table>
          <thead><tr><th>Company</th><th>Funds</th></tr></thead>
          <tbody>
            {data.companies.map((c) => (
              <tr key={c.name}>
                <td><Link to={`/companies/${encodeURIComponent(c.name)}`}>{c.name}</Link></td>
                <td>{c.funds.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
