import { useEffect, useState } from "react";

// A small confirmation modal. For dangerous, permanent actions pass
// `confirmPhrase` — the user must type it exactly before the confirm button
// enables. For softer actions (like disband) leave it out.
export default function ConfirmDialog({
  title,
  message,
  confirmLabel = "Confirm",
  confirmPhrase = null,
  danger = false,
  onConfirm,
  onCancel,
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Close on Escape for keyboard users.
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !busy) onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  const ready = !confirmPhrase || typed.trim() === confirmPhrase;

  const run = async () => {
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (e) {
      setError(e.message || "Something went wrong");
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onCancel(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h3 style={{ marginTop: 0 }}>{title}</h3>
        <p className="muted" style={{ marginTop: 0 }}>{message}</p>

        {confirmPhrase && (
          <div className="form-row">
            <label>Type <code>{confirmPhrase}</code> to confirm</label>
            <input
              type="text"
              value={typed}
              autoFocus
              onChange={(e) => setTyped(e.target.value)}
              placeholder={confirmPhrase}
            />
          </div>
        )}

        {error && <p style={{ color: "var(--danger)", fontWeight: 600 }}>{error}</p>}

        <div className="modal-actions">
          <button className="secondary" onClick={onCancel} disabled={busy}>Cancel</button>
          <button
            className={danger ? "danger" : ""}
            onClick={run}
            disabled={!ready || busy}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
