import { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api.js";
import ImageField from "../components/ImageField.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";

// Everything under one company: its logo, funds, groups — plus rename/delete.
export default function CompanyView({ notify }) {
  const { name } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);       // api.owned() — groups + funds
  const [company, setCompany] = useState(null); // api.company() — logo
  const [error, setError] = useState(null);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);

  useEffect(() => {
    setData(null); setCompany(null); setError(null);
    api.owned().then(setData).catch((e) => setError(e.message));
    api.company(name).then((c) => { setCompany(c); setNewName(c.name); }).catch(() => {});
  }, [name]);

  if (error) return <p className="muted">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  const funds = data.companies.find((c) => c.name === name)?.funds;
  const groups = data.groups.filter((g) => g.company === name);

  const rename = async () => {
    const n = newName.trim();
    if (!n || n === name) return;
    setSaving(true);
    try {
      await api.saveCompany(name, { name: n });
      notify?.({ message: "Company renamed" });
      navigate(`/companies/${encodeURIComponent(n)}`);
    } catch (e) {
      notify?.({ message: e.message, error: true });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <p className="muted"><Link to="/">← Overview</Link></p>

      <div className="company-head">
        {company?.logo
          ? <img className="company-logo" src={company.logo} alt="" />
          : <div className="company-logo company-logo-fallback"><span>{(name || "?").charAt(0)}</span></div>}
        <div>
          <h2 style={{ margin: 0 }}>{name}</h2>
          <p className="subtitle" style={{ margin: "4px 0 0" }}>
            {funds != null ? `Funds: ${funds.toLocaleString()}` : "Company"} · {groups.length} group{groups.length === 1 ? "" : "s"}
          </p>
        </div>
      </div>

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

      <h3 style={{ marginTop: 32 }}>Company settings</h3>
      <ImageField
        label="Logo" aspect={1} value={company?.logo}
        hint="Square logo shown on this company."
        onUpload={async (blob) => {
          const updated = await api.uploadCompanyLogo({ name, blob });
          setCompany(updated);
          notify?.({ message: "Logo saved" });
        }}
      />
      <div className="form-row">
        <label>Company name</label>
        <input type="text" value={newName} onChange={(e) => setNewName(e.target.value)} />
        <div className="hint">Renaming updates every group and record that points to this company.</div>
      </div>
      <button onClick={rename} disabled={saving || !newName.trim() || newName.trim() === name}>
        {saving ? "Saving…" : "Rename company"}
      </button>

      <div className="danger-zone">
        <h3>Danger zone</h3>
        <div className="danger-row">
          <div>
            <strong>Delete company</strong>
            <div className="muted" style={{ fontSize: 13 }}>
              Permanently deletes the company <strong>and all {groups.length} of its groups + their albums</strong>. Cannot be undone.
            </div>
          </div>
          <button className="danger" onClick={() => setConfirmDel(true)}>Delete company</button>
        </div>
      </div>

      {confirmDel && (
        <ConfirmDialog
          title={`Delete “${name}”?`}
          message={`This permanently deletes ${name}, its ${groups.length} group(s), and all their albums. This cannot be undone.`}
          confirmLabel="Delete forever" danger
          onCancel={() => setConfirmDel(false)}
          onConfirm={async () => {
            await api.deleteCompany(name);
            notify?.({ message: "Company deleted" });
            navigate("/");
          }}
        />
      )}
    </>
  );
}
