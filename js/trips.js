// Trip recording: GPS route tracking + geotagged photos + slideshow data.
// Stored on-device: metadata/track in localStorage, photo blobs in IndexedDB.
import { uid } from './store.js';
import * as idb from './idb.js';
import { compress, blobToDataUrl } from './img.js';

const KEY = 'whimo:trips:v1';

function loadAll() {
  try { const p = JSON.parse(localStorage.getItem(KEY) || '{}'); return p.trips || []; }
  catch { return []; }
}
function saveAll(trips) {
  try { localStorage.setItem(KEY, JSON.stringify({ version: 1, trips })); } catch (e) { console.warn(e); }
}

let trips = loadAll();

export function list() {
  return trips.slice().sort((a, b) => (b.startedAt || b.createdAt) - (a.startedAt || a.createdAt));
}
export function get(id) { return trips.find(t => t.id === id) || null; }

export function create(name, mode = 'live') {
  const t = {
    id: uid(), name: name || defaultName(), mode, status: 'recording',
    createdAt: Date.now(), startedAt: Date.now(), endedAt: null,
    start: null, goal: null, track: [], photos: [], distance: 0,
  };
  trips.push(t); saveAll(trips); return t;
}
export function update(id, patch) { const t = get(id); if (t) { Object.assign(t, patch); saveAll(trips); } return t; }
export function remove(id) {
  const t = get(id);
  if (t) t.photos.forEach(p => idb.delBlob(p.id).catch(() => {}));
  trips = trips.filter(x => x.id !== id); saveAll(trips);
}
export function finish(id) {
  const t = get(id); if (!t) return null;
  t.status = 'done'; t.endedAt = Date.now();
  t.distance = trackDistance(t.track);
  if (!t.start && t.track.length) t.start = t.track[0];
  if (!t.goal && t.track.length) t.goal = t.track[t.track.length - 1];
  saveAll(trips); return t;
}

export function setStart(id, point) { const t = get(id); if (t) { t.start = stamp(point); if (!t.track.length) t.track.push(t.start); saveAll(trips); } }
export function setGoal(id, point) { const t = get(id); if (t) { t.goal = stamp(point); t.track.push(t.goal); saveAll(trips); } }

// Append a track point, skipping near-duplicates (<8m).
export function addPoint(id, point) {
  const t = get(id); if (!t) return;
  const p = stamp(point);
  const last = t.track[t.track.length - 1];
  if (last && haversine(last, p) < 8) return;
  t.track.push(p);
  t.distance = trackDistance(t.track);
  saveAll(trips);
}

// ---- Live GPS recording ----
export function startLive(id, onUpdate, onError) {
  if (!navigator.geolocation) { onError && onError(new Error('この端末は位置情報に対応していません')); return () => {}; }
  const watchId = navigator.geolocation.watchPosition(
    (pos) => { addPoint(id, { lat: pos.coords.latitude, lng: pos.coords.longitude }); onUpdate && onUpdate(get(id)); },
    (err) => { onError && onError(err); },
    { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 }
  );
  return () => navigator.geolocation.clearWatch(watchId);
}

export function currentPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error('位置情報に非対応'));
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      (err) => reject(err),
      { enableHighAccuracy: true, timeout: 15000 }
    );
  });
}

// ---- Photos (blob in IndexedDB, meta on the trip) ----
export async function addPhoto(id, file, point) {
  const t = get(id); if (!t) return null;
  const blob = await compress(file, 1280, 0.78);
  const photoId = uid();
  let url;
  if (idb.available()) { await idb.putBlob(photoId, blob); url = URL.createObjectURL(blob); }
  else { url = await blobToDataUrl(blob); }               // fallback
  const meta = { id: photoId, at: Date.now(), lat: point?.lat ?? null, lng: point?.lng ?? null,
                 caption: '', inline: idb.available() ? null : url };
  t.photos.push(meta); saveAll(trips);
  return { ...meta, url };
}
export async function photoUrl(meta) {
  if (meta.inline) return meta.inline;
  if (idb.available()) { const b = await idb.getBlob(meta.id); if (b) return URL.createObjectURL(b); }
  return null;
}
export function deletePhoto(id, photoId) {
  const t = get(id); if (!t) return;
  t.photos = t.photos.filter(p => p.id !== photoId);
  idb.delBlob(photoId).catch(() => {});
  saveAll(trips);
}

// ---- helpers ----
function stamp(p) { return { lat: p.lat, lng: p.lng, t: p.t || Date.now() }; }
function defaultName() {
  const d = new Date();
  return `${d.getMonth() + 1}/${d.getDate()} の旅`;
}
export function trackDistance(track) {
  let d = 0;
  for (let i = 1; i < track.length; i++) d += haversine(track[i - 1], track[i]);
  return Math.round(d);
}
function haversine(a, b) {
  const R = 6371000, toRad = (x) => x * Math.PI / 180;
  const dLat = toRad(b.lat - a.lat), dLng = toRad(b.lng - a.lng);
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}
export function fmtDistance(m) { return m >= 1000 ? (m / 1000).toFixed(2) + ' km' : Math.round(m) + ' m'; }
export function fmtDuration(ms) {
  const s = Math.floor(ms / 1000), h = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return (h ? h + ':' : '') + String(mm).padStart(h ? 2 : 1, '0') + ':' + String(ss).padStart(2, '0');
}
