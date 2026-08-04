// Render the user's crop selection to a compressed WebP blob, entirely in the
// browser. react-easy-crop gives us the crop rectangle in source-image pixels;
// we draw just that rectangle onto a canvas, scaled down so the long edge never
// exceeds MAX_EDGE, and export it.

const MAX_EDGE = 1280;

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

export async function getCroppedBlob(src, cropPixels) {
  const image = await loadImage(src);

  let outW = Math.round(cropPixels.width);
  let outH = Math.round(cropPixels.height);
  const longest = Math.max(outW, outH);
  if (longest > MAX_EDGE) {
    const scale = MAX_EDGE / longest;
    outW = Math.round(outW * scale);
    outH = Math.round(outH * scale);
  }

  const canvas = document.createElement("canvas");
  canvas.width = outW;
  canvas.height = outH;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(
    image,
    cropPixels.x, cropPixels.y, cropPixels.width, cropPixels.height,
    0, 0, outW, outH
  );

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("could not encode image"))),
      "image/webp",
      0.9
    );
  });
}

// Read a picked File into a data URL for the cropper to display.
export function fileToDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
