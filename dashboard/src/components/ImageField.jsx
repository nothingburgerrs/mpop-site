import { useRef, useState } from "react";
import CropModal from "./CropModal.jsx";
import { fileToDataURL } from "../lib/cropImage.js";

// A single image slot: shows the current image, lets the user pick one from
// their device/gallery, crop it to the right shape, and upload. Saving happens
// on crop-confirm via onUpload(blob), which returns the refreshed resource.
export default function ImageField({ label, value, aspect, hint, onUpload }) {
  const inputRef = useRef(null);
  const [src, setSrc] = useState(null); // data URL being cropped
  const [error, setError] = useState(null);

  async function onPick(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("Please choose an image file.");
      return;
    }
    setError(null);
    setSrc(await fileToDataURL(file));
  }

  async function onConfirm(blob) {
    try {
      await onUpload(blob);
      setSrc(null);
    } catch (err) {
      setError(err.message);
      setSrc(null);
    }
  }

  const previewStyle = {
    aspectRatio: String(aspect),
    maxWidth: aspect >= 2 ? 320 : 160,
  };

  return (
    <div className="form-row">
      <label>{label}</label>
      <div className="image-field">
        <div className="image-preview" style={previewStyle}>
          {value ? <img src={value} alt="" /> : <span className="muted">No image</span>}
        </div>
        <div>
          <button type="button" className="secondary" onClick={() => inputRef.current?.click()}>
            {value ? "Change image" : "Upload image"}
          </button>
          {hint && <div className="hint">{hint}</div>}
          {error && <div className="hint" style={{ color: "var(--danger)" }}>{error}</div>}
        </div>
        <input
          ref={inputRef} type="file" accept="image/*"
          style={{ display: "none" }} onChange={onPick}
        />
      </div>

      {src && (
        <CropModal
          src={src}
          aspect={aspect}
          onCancel={() => setSrc(null)}
          onConfirm={onConfirm}
        />
      )}
    </div>
  );
}
