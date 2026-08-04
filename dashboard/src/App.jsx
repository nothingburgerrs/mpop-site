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
    return (
      <div className="center">
        <h1>mpopbot dashboard</h1>
        <p className="muted">Manage your companies, groups, albums and members.</p>
        <a href="/auth/login"><button>Log in with Discord</button></a>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Layout user={auth.user}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/groups" element={<Groups />} />
          <Route path="/groups/:name" element={<GroupEdit notify={notify} />} />
          <Route path="/albums" element={<Albums />} />
          <Route path="/albums/:name" element={<AlbumEdit notify={notify} />} />
        </Routes>
      </Layout>
      <Toast toast={toast} onClear={() => setToast(null)} />
    </BrowserRouter>
  );
}
