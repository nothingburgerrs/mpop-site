import { useEffect, useState, useCallback } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { api } from "./lib/api.js";
import Layout from "./components/Layout.jsx";
import Toast from "./components/Toast.jsx";
import Overview from "./pages/Overview.jsx";
import Groups from "./pages/Groups.jsx";
import GroupEdit from "./pages/GroupEdit.jsx";
import Albums from "./pages/Albums.jsx";
import AlbumEdit from "./pages/AlbumEdit.jsx";
import CompanyView from "./pages/CompanyView.jsx";
import Videos from "./pages/Videos.jsx";
import VideoEdit from "./pages/VideoEdit.jsx";
import Prisms from "./pages/Prisms.jsx";
import PrismEdit from "./pages/PrismEdit.jsx";
import Explore from "./pages/Explore.jsx";
import PublicGroup from "./pages/PublicGroup.jsx";

export default function App() {
  const [auth, setAuth] = useState({ status: "loading" });
  const [toast, setToast] = useState(null);
  const notify = useCallback((t) => setToast(t), []);

  useEffect(() => {
    api.me()
      .then((u) => setAuth({ status: "in", user: u }))
      .catch(() => setAuth({ status: "out" }));
  }, []);

  if (auth.status === "loading") {
    return <div className="center"><p className="muted">Loading…</p></div>;
  }

  if (auth.status === "out") {
    // The callback redirects here with ?error=... on failure. Surface it, so a
    // silent bounce becomes a labelled reason instead of an invisible loop.
    const loginError = new URLSearchParams(window.location.search).get("error");
    return (
      <div className="center">
        <h1>mpopbot dashboard</h1>
        <p className="muted">Manage your companies, groups, albums and members.</p>
        {loginError && (
          <p style={{ color: "var(--danger)", fontWeight: 600 }}>
            Login failed: {loginError}
          </p>
        )}
        <a href="/auth/login"><button>Log in with Discord</button></a>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Layout user={auth.user}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/companies/:name" element={<CompanyView />} />
          <Route path="/groups" element={<Groups />} />
          <Route path="/groups/:name" element={<GroupEdit notify={notify} />} />
          <Route path="/albums" element={<Albums />} />
          <Route path="/albums/:name" element={<AlbumEdit notify={notify} />} />
          <Route path="/videos" element={<Videos notify={notify} />} />
          <Route path="/videos/:id" element={<VideoEdit notify={notify} />} />
          <Route path="/prisms" element={<Prisms />} />
          <Route path="/prisms/:name" element={<PrismEdit notify={notify} />} />
          <Route path="/explore" element={<Explore />} />
          <Route path="/explore/:name" element={<PublicGroup />} />
        </Routes>
      </Layout>
      <Toast toast={toast} onClear={() => setToast(null)} />
    </BrowserRouter>
  );
}
