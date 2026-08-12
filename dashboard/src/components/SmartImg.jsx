import { useState } from "react";

// An <img> that swaps to a fallback when the source is missing or fails to load.
// Many stored image URLs are old Discord CDN links that have since expired, so
// without this they render as broken/black boxes across the public pages.
export default function SmartImg({ src, alt = "", className, style, fallback = null }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return fallback;
  return (
    <img
      src={src} alt={alt} className={className} style={style} loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
