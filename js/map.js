// Leaflet map wrapper: renders spot pins and supports click-to-pick.
import { catOf, DEFAULT_CENTER, DEFAULT_ZOOM } from './config.js';

let map = null;
let markerLayer = null;
let pickMode = false;
let pickMarker = null;
let onPick = null;

function pinIcon(color, emoji) {
  const html = `
    <svg width="30" height="40" viewBox="0 0 30 40" xmlns="http://www.w3.org/2000/svg">
      <path d="M15 39C15 39 28 24 28 14A13 13 0 1 0 2 14C2 24 15 39 15 39Z"
            fill="${color}" stroke="#ffffff" stroke-width="2"/>
      <circle cx="15" cy="14" r="7.5" fill="#ffffff"/>
    </svg>
    <span style="position:absolute;top:6px;left:0;width:30px;text-align:center;font-size:12px;">${emoji}</span>`;
  return L.divIcon({
    className: 'pin-marker',
    html,
    iconSize: [30, 40],
    iconAnchor: [15, 39],
    popupAnchor: [0, -36],
  });
}

function leafletReady() { return typeof window !== 'undefined' && typeof window.L !== 'undefined'; }

function showMapUnavailable() {
  const el = document.getElementById('map');
  if (el && !el.querySelector('.map-unavailable')) {
    el.innerHTML = `<div class="map-unavailable" style="padding:40px 24px;text-align:center;color:#7b857f;">
      🗺 地図を読み込めませんでした。<br>ネットワーク接続を確認して、ページを再読み込みしてください。<br>
      <small>（リスト表示・保存・共有は引き続き利用できます）</small></div>`;
  }
}

export function ensureMap() {
  if (map) return map;
  if (!leafletReady()) { showMapUnavailable(); return null; }
  map = L.map('map', { zoomControl: true, attributionControl: true })
    .setView(DEFAULT_CENTER, DEFAULT_ZOOM);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);
  markerLayer = L.layerGroup().addTo(map);

  map.on('click', (e) => {
    if (!pickMode) return;
    setPickMarker(e.latlng.lat, e.latlng.lng);
    if (onPick) onPick(e.latlng.lat, e.latlng.lng);
  });
  return map;
}

// Call after the map container becomes visible (Leaflet needs a size recalc).
export function refresh() {
  if (map) setTimeout(() => map.invalidateSize(), 50);
}

export function renderSpots(spots, onSpotClick) {
  if (!ensureMap()) return;
  markerLayer.clearLayers();
  const pts = [];
  spots.forEach((s) => {
    if (typeof s.lat !== 'number' || typeof s.lng !== 'number') return;
    const c = catOf(s.category);
    const m = L.marker([s.lat, s.lng], { icon: pinIcon(c.color, c.emoji) });
    const linkHtml = s.sourceUrl
      ? `<div><a class="popup-link" href="${escapeAttr(s.sourceUrl)}" target="_blank" rel="noopener">元の投稿を開く ↗</a></div>` : '';
    m.bindPopup(`
      <div class="popup-name">${escapeHtml(s.name)}</div>
      <div>${c.emoji} ${c.label}${s.visited ? ' ・ 訪問済み' : ''}</div>
      ${s.memo ? `<div style="margin-top:4px;">${escapeHtml(s.memo)}</div>` : ''}
      ${linkHtml}
      <div style="margin-top:6px;"><button class="popup-edit" data-id="${s.id}" style="border:none;background:#0e9f8e;color:#fff;padding:5px 10px;border-radius:8px;">編集</button></div>
    `);
    m.on('popupopen', (ev) => {
      const btn = ev.popup.getElement().querySelector('.popup-edit');
      if (btn) btn.addEventListener('click', () => onSpotClick && onSpotClick(s.id));
    });
    m.addTo(markerLayer);
    pts.push([s.lat, s.lng]);
  });
  if (pts.length) {
    try { map.fitBounds(pts, { padding: [50, 50], maxZoom: 16 }); } catch {}
  }
}

export function startPick(handler) {
  if (!ensureMap()) return false;
  pickMode = true;
  onPick = handler;
  return true;
}
export function stopPick() {
  pickMode = false;
  onPick = null;
  if (pickMarker) { map.removeLayer(pickMarker); pickMarker = null; }
}
export function setPickMarker(lat, lng) {
  if (!ensureMap()) return;
  if (pickMarker) pickMarker.setLatLng([lat, lng]);
  else pickMarker = L.marker([lat, lng], { icon: pinIcon('#0e9f8e', '📍') }).addTo(map);
  map.panTo([lat, lng]);
}
export function focus(lat, lng, zoom = 16) {
  if (!ensureMap()) return;
  map.setView([lat, lng], zoom);
}

function escapeHtml(s = '') {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function escapeAttr(s = '') { return escapeHtml(s); }

// ---------------------------------------------------------------------
// Standalone route map (trip detail / slideshow). Independent of the main map.
// ---------------------------------------------------------------------
function dot(color, label) {
  return L.divIcon({
    className: 'route-dot',
    html: `<div style="width:22px;height:22px;border-radius:50%;background:${color};color:#fff;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);display:grid;place-items:center;font-size:11px;font-weight:700;">${label}</div>`,
    iconSize: [22, 22], iconAnchor: [11, 11],
  });
}

export function makeRouteMap(containerId, track = [], photos = []) {
  if (!leafletReady()) return null;
  const el = document.getElementById(containerId);
  if (!el) return null;
  const map = L.map(containerId, { zoomControl: false, attributionControl: false });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);
  const pts = track.filter(p => typeof p.lat === 'number').map(p => [p.lat, p.lng]);
  if (pts.length > 1) L.polyline(pts, { color: '#0e9f8e', weight: 5, opacity: 0.85 }).addTo(map);
  if (track[0]) L.marker([track[0].lat, track[0].lng], { icon: dot('#2fa84f', 'S') }).addTo(map);
  if (track.length > 1) { const g = track[track.length - 1]; L.marker([g.lat, g.lng], { icon: dot('#e5484d', 'G') }).addTo(map); }
  photos.forEach((p, i) => {
    if (typeof p.lat === 'number') L.marker([p.lat, p.lng], { icon: dot('#8163d4', String(i + 1)) }).addTo(map);
  });
  const all = pts.concat(photos.filter(p => typeof p.lat === 'number').map(p => [p.lat, p.lng]));
  if (all.length) { try { map.fitBounds(all, { padding: [30, 30], maxZoom: 16 }); } catch { map.setView(all[0], 14); } }
  else map.setView(DEFAULT_CENTER, DEFAULT_ZOOM);
  setTimeout(() => map.invalidateSize(), 60);
  return map;
}

let _hi = null;
export function highlightOnMap(map, lat, lng) {
  if (!map || typeof lat !== 'number') return;
  if (_hi) { map.removeLayer(_hi); _hi = null; }
  _hi = L.circleMarker([lat, lng], { radius: 11, color: '#fff', weight: 3, fillColor: '#8163d4', fillOpacity: 1 }).addTo(map);
  map.panTo([lat, lng]);
}
export function disposeMap(map) { if (map) { try { map.remove(); } catch {} } }
