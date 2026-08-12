import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api.js";

export default function Albums() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.owned().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="muted">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <>
      <h2>Albums</h2>
      <p className="subtitle">Select an album to edit its cover and era image.</p>
      {data.albums.length === 0 ? (
        <p className="muted">You don't have any albums yet.</p>
      ) : (
        <table>
          <thead>
            <tr><th>Album</th><th>Group</th><th>Streams</th><th>Sales</th><th>Wins</th></tr>
          </thead>
          <tbody>
            {data.albums.map((a) => (
              <tr key={a.name}>
                <td>
                  <Link to={`/albums/${encodeURIComponent(a.name)}`}>{a.name}</Link>
                  {a.is_active_promotion && <span className="badge" style={{ marginLeft: 8 }}>promoting</span>}
                </td>
                <td>{a.group}</td>
                <td>{a.streams.toLocaleString()}</td>
                <td>{a.sales.toLocaleString()}</td>
                <td>{a.wins}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
