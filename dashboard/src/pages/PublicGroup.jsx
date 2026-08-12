import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../lib/api.js";
import SmartImg from "../components/SmartImg.jsx";

const fmt = (n) => (n || 0).toLocaleString();

// Public, read-only group page — a fan-site view anyone signed in can open:
// hero, members, prism versions, discography, videos.
export default function PublicGroup() {
  const { name } = useParams();
  const [g, setG] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setG(null); setError(null);
    api.publicGroup(name).then(setG).catch((e) => setError(e.message));
  }, [name]);

  if (error) return <p className="muted"><Link to="/explore">← Explore</Link><br /><br />{error}</p>;
  if (!g) return <p className="muted">Loading…</p>;

  const accent = g.fandom_color || "var(--accent)";

  return (
    <div className="pg">
      <p className="muted"><Link to="/explore">← Explore</Link></p>

      <div className="hero" style={{ "--fc": accent }}>
        <SmartImg className="hero-bg" src={g.banner_url}
          fallback={<div className="hero-bg hero-bg-fallback" />} />
        <div className="hero-scrim" />
        <div className="hero-content">
          <SmartImg className="hero-avatar" src={g.profile_picture} />
          <div className="hero-text">
            <div className="hero-badges">
              <span className={"tier-badge tier-" + (g.tier || "NUGU").toLowerCase()}>{g.tier}</span>
              {g.is_disbanded && <span className="badge">disbanded</span>}
            </div>
            <h1 className="hero-name">{g.name}</h1>
            {g.korean_name && <div className="hero-korean">{g.korean_name}</div>}
            <div className="hero-stats">
              <span><strong>{g.members.length}</strong> members</span>
              <span><strong>{g.albums.length}</strong> albums</span>
              <span><strong>{fmt(g.wins)}</strong> wins</span>
              <span><strong>{fmt(g.popularity)}</strong> popularity</span>
            </div>
          </div>
        </div>
      </div>

      {(g.description || g.fandom_name) && (
        <p className="pg-desc">
          {g.fandom_name && <><span className="pg-fandom" style={{ background: accent }}>{g.fandom_name}</span> </>}
          {g.description}
        </p>
      )}

      {g.members.length > 0 && (
        <section className="pg-section">
          <h3>Members</h3>
          <div className="member-grid">
            {g.members.map((m, i) => (
              <div key={i} className="member-tile">
                <div className="member-photo">
                  <SmartImg src={m.image_url}
                    fallback={<div className="member-photo-fallback"><span>{(m.name || "?").charAt(0)}</span></div>} />
                </div>
                <div className="member-name">{m.name}</div>
                {m.bio && <div className="member-bio">{m.bio}</div>}
              </div>
            ))}
          </div>
        </section>
      )}

      {g.prism_versions.length > 0 && (
        <section className="pg-section">
          <h3>Prisms</h3>
          {g.prism_versions.map((v) => (
            <div key={v.id} className="pv">
              <div className="pv-head">
                <span className="prism-dot" style={{ background: v.color }} />
                <strong>{v.name}</strong>
                <span className="muted" style={{ fontSize: 13 }}>{v.cards.length} cards</span>
              </div>
              {v.cards.length > 0 && (
                <div className="pv-cards">
                  {v.cards.map((c, i) => (
                    <div key={i} className="pv-card" style={{ borderColor: v.color }} title={`${c.member} · ${c.class}`}>
                      <SmartImg src={c.art_url} fallback={<div className="pv-card-fallback" />} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </section>
      )}

      {g.albums.length > 0 && (
        <section className="pg-section">
          <h3>Discography</h3>
          <div className="album-grid">
            {g.albums.map((a) => (
              <div key={a.name} className="album-tile">
                <div className="album-cover">
                  <SmartImg src={a.image_url} fallback={<div className="album-cover-fallback" />} />
                </div>
                <div className="album-name">{a.name}</div>
                <div className="album-meta">{fmt(a.streams)} streams</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {g.videos.length > 0 && (
        <section className="pg-section">
          <h3>Videos</h3>
          <div className="video-grid">
            {g.videos.map((v) => (
              <div key={v.id} className="video-tile">
                <div className="video-thumb"><SmartImg src={v.thumbnail_url} fallback={<div className="album-cover-fallback" />} /></div>
                <div className="video-title">{v.title}</div>
                <div className="album-meta">{fmt(v.views)} views</div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
