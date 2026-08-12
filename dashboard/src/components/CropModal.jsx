import { useState, useCallback } from "react";
import Cropper from "react-easy-crop";
import { getCroppedBlob } from "../lib/cropImage.js";

// Drag-to-position, scroll/pinch-to-zoom crop editor with a fixed aspect ratio,
// like Tupperbox's avatar picker. Confirms to a WebP blob.
export default function CropModal({ src, aspect, onCancel, onConfirm }) {
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [pixels, setPixels] = useState(null);
  const [busy, setBusy] = useState(false);

  const onCropComplete = useCallback((_area, areaPixels) => setPixels(areaPixels), []);

  async function confirm() {
    if (!pixels) return;
    setBusy(true);
    try {
      const blob = await getCroppedBlob(src, pixels);
      await onConfirm(blob);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal">
        <div className="crop-stage">
          <Cropper
            image={src}
            crop={crop}
            zoom={zoom}
            aspect={aspect}
            onCropChange={setCrop}
            onZoomChange={setZoom}
            onCropComplete={onCropComplete}
            restrictPosition
          />
        </div>
        <div className="crop-controls">
          <label>Zoom</label>
          <input
            type="range" min={1} max={3} step={0.01} value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
          />
        </div>
        <div className="modal-actions">
          <button className="secondary" onClick={onCancel} disabled={busy}>Cancel</button>
          <button onClick={confirm} disabled={busy || !pixels}>
            {busy ? "Uploading…" : "Save image"}
          </button>
        </div>
      </div>
    </div>
  );
}
