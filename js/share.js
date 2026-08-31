// Encode / decode a collection into a URL-safe string carried in the hash.
// This lets people share a list "by link only" — no server required.

function toBase64Url(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = '';
  bytes.forEach(b => (bin += String.fromCharCode(b)));
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(str) {
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  const bin = atob(str);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

// Keep the payload small: only the fields worth sharing, rounded coords.
function slimSpot(s) {
  const o = { n: s.name, c: s.category };
  if (s.memo) o.m = s.memo;
  if (typeof s.lat === 'number') o.la = round(s.lat);
  if (typeof s.lng === 'number') o.lo = round(s.lng);
  if (s.address) o.a = s.address;
  if (s.sourceUrl) o.u = s.sourceUrl;
  if (s.visited) o.v = 1;
  return o;
}
function fatSpot(o) {
  return {
    name: o.n || '(無題)',
    category: o.c || 'other',
    memo: o.m || '',
    lat: typeof o.la === 'number' ? o.la : null,
    lng: typeof o.lo === 'number' ? o.lo : null,
    address: o.a || '',
    sourceUrl: o.u || '',
    visited: !!o.v,
  };
}
function round(n) { return Math.round(n * 1e6) / 1e6; }

export function encodeCollection(collection) {
  const payload = {
    t: collection.name || 'リスト',
    d: collection.description || '',
    s: (collection.spots || []).map(slimSpot),
  };
  return toBase64Url(JSON.stringify(payload));
}

export function decodeCollection(code) {
  const payload = JSON.parse(fromBase64Url(code));
  return {
    name: payload.t || '取り込んだリスト',
    description: payload.d || '',
    spots: (payload.s || []).map(fatSpot),
  };
}

export function buildShareUrl(collection) {
  const code = encodeCollection(collection);
  const base = location.origin + location.pathname;
  return `${base}#share=${code}`;
}

// Read a shared collection from the current URL hash, if present.
export function readShareFromHash() {
  const m = location.hash.match(/share=([^&]+)/);
  if (!m) return null;
  try { return decodeCollection(m[1]); }
  catch { return null; }
}

export function clearShareHash() {
  history.replaceState(null, '', location.pathname + location.search);
}
