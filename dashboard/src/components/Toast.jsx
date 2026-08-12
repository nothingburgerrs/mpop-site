import { useEffect } from "react";

// Minimal transient notification, auto-dismissing after a few seconds.
export default function Toast({ toast, onClear }) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onClear, 3000);
    return () => clearTimeout(t);
  }, [toast, onClear]);

  if (!toast) return null;
  return <div className={`toast ${toast.error ? "error" : ""}`}>{toast.message}</div>;
}
