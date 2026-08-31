// Client-side image downscale/compress to keep storage small.
// Falls back to the original file if the browser can't decode/re-encode it.
export async function compress(file, maxDim = 1280, quality = 0.82) {
  try {
    const bitmap = await loadBitmap(file);
    let width = bitmap.width, height = bitmap.height;
    if (!width || !height) throw new Error('decode failed');
    const scale = Math.min(1, maxDim / Math.max(width, height));
    width = Math.max(1, Math.round(width * scale));
    height = Math.max(1, Math.round(height * scale));
    const canvas = document.createElement('canvas');
    canvas.width = width; canvas.height = height;
    canvas.getContext('2d').drawImage(bitmap, 0, 0, width, height);
    if (bitmap.close) bitmap.close();
    const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', quality));
    return blob && blob.size ? blob : file;
  } catch {
    return file;
  }
}

export async function compressToDataUrl(file, maxDim = 1280, quality = 0.82) {
  const blob = await compress(file, maxDim, quality);
  return await blobToDataUrl(blob);
}

function loadBitmap(file) {
  if ('createImageBitmap' in window) return createImageBitmap(file);
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

export function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(blob);
  });
}
