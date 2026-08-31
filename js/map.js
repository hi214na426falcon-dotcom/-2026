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
