// Geocoding via OpenStreetMap Nominatim (free, no API key).
// Usage policy: https://operations.osmfoundation.org/policies/nominatim/
const BASE = 'https://nominatim.openstreetmap.org';

export async function search(query) {
  if (!query || !query.trim()) return [];
  const url = `${BASE}/search?format=jsonv2&addressdetails=1&limit=6&accept-language=ja&q=${encodeURIComponent(query.trim())}`;
  const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
  if (!res.ok) throw new Error('検索に失敗しました');
  const rows = await res.json();
  return rows.map(r => ({
    name: shortName(r),
    address: r.display_name,
    lat: parseFloat(r.lat),
    lng: parseFloat(r.lon),
  }));
}

export async function reverse(lat, lng) {
  const url = `${BASE}/reverse?format=jsonv2&accept-language=ja&lat=${lat}&lon=${lng}`;
  try {
    const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
    if (!res.ok) return '';
    const r = await res.json();
    return r.display_name || '';
  } catch {
    return '';
  }
}

function shortName(r) {
  const n = r.name || (r.address && (r.address.shop || r.address.amenity || r.address.building)) || '';
  if (n) return n;
  // Fall back to the first chunk of the display name.
  return (r.display_name || '').split(',')[0];
}
