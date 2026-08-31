// Road-following route between two points via the free OSRM demo server
// (no API key). Falls back to a straight line when offline/unavailable.
const OSRM = 'https://router.project-osrm.org/route/v1/driving/';

export async function getRoute(a, b) {
  const url = `${OSRM}${a.lng},${a.lat};${b.lng},${b.lat}?overview=full&geometries=geojson`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('route http ' + res.status);
  const j = await res.json();
  if (!j.routes || !j.routes.length) throw new Error('no route');
  const r = j.routes[0];
  const coords = (r.geometry.coordinates || []).map(([lng, lat]) => ({ lat, lng, t: 0 }));
  return { coords, distance: Math.round(r.distance) };
}
