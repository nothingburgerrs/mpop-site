import { NavLink } from "react-router-dom";

// The left sidebar + content frame. Navigation is deliberately flat and short.
export default function Layout({ user, children }) {
  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>mpopbot</h1>
        <nav className="nav">
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/explore">Explore</NavLink>
          <NavLink to="/groups">Groups</NavLink>
          <NavLink to="/albums">Albums</NavLink>
          <NavLink to="/videos">Videos</NavLink>
          <NavLink to="/prisms">Prisms</NavLink>
        </nav>
        <div className="user">
          {user?.username && <div>Signed in as {user.username}</div>}
          <form method="POST" action="/auth/logout">
            <button className="secondary" style={{ marginTop: 8, width: "100%" }}>Log out</button>
          </form>
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
