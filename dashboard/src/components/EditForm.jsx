import { useState } from "react";

// A generic editor for an object's string fields. `fields` describes each one;
// only changed fields are sent on save, so we never overwrite what we didn't touch.
export default function EditForm({ fields, initial, onSave }) {
  const [values, setValues] = useState(() => ({ ...initial }));
  const [saving, setSaving] = useState(false);

  const dirty = Object.keys(values).some((k) => (values[k] || "") !== (initial[k] || ""));

  function update(key, value) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  async function submit(e) {
    e.preventDefault();
    const changes = {};
    for (const k of Object.keys(values)) {
      if ((values[k] || "") !== (initial[k] || "")) changes[k] = values[k];
    }
    if (Object.keys(changes).length === 0) return;
    setSaving(true);
    try {
      await onSave(changes);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit}>
      {fields.map((f) => (
        <div className="form-row" key={f.key}>
          <label htmlFor={f.key}>{f.label}</label>
          {f.multiline ? (
            <textarea id={f.key} value={values[f.key] || ""}
              onChange={(e) => update(f.key, e.target.value)} />
          ) : (
            <input id={f.key} type={f.type || "text"} value={values[f.key] || ""}
              placeholder={f.placeholder || ""}
              onChange={(e) => update(f.key, e.target.value)} />
          )}
          {f.hint && <div className="hint">{f.hint}</div>}
        </div>
      ))}
      <button type="submit" disabled={!dirty || saving}>
        {saving ? "Saving…" : "Save changes"}
      </button>
    </form>
  );
}
