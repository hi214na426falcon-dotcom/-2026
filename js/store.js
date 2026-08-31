// Data model + persistence (localStorage).
const KEY = 'whimo:data:v1';
const SETTINGS_KEY = 'whimo:settings:v1';

export function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function emptyData() {
  const c = newCollection('マイリスト');
  return { version: 1, collections: [c], currentId: c.id };
}

export function newCollection(name = '新しいリスト') {
  return {
    id: uid(),
    name,
    description: '',
    createdAt: Date.now(),
    spots: [],
  };
}

export function newSpot(partial = {}) {
  return {
    id: uid(),
    name: '',
    category: 'other',
    memo: '',
    lat: null,
    lng: null,
    address: '',
    sourceUrl: '',
    visited: false,
    createdAt: Date.now(),
    ...partial,
  };
}

let data = load();

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return emptyData();
    const parsed = JSON.parse(raw);
    if (!parsed.collections || !parsed.collections.length) return emptyData();
    if (!parsed.currentId || !parsed.collections.some(c => c.id === parsed.currentId)) {
      parsed.currentId = parsed.collections[0].id;
    }
    return parsed;
  } catch {
    return emptyData();
  }
}

export function save() {
  try { localStorage.setItem(KEY, JSON.stringify(data)); }
  catch (e) { console.warn('保存に失敗しました', e); }
}

// ---- Settings (small UI prefs) ----
export function getSetting(k, fallback) {
  try {
    const s = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    return k in s ? s[k] : fallback;
  } catch { return fallback; }
}
export function setSetting(k, v) {
  try {
    const s = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    s[k] = v;
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  } catch {}
}

// ---- Collections ----
export function getCollections() { return data.collections; }
export function getCurrent() {
  return data.collections.find(c => c.id === data.currentId) || data.collections[0];
}
export function getCurrentId() { return data.currentId; }
export function setCurrent(id) {
  if (data.collections.some(c => c.id === id)) { data.currentId = id; save(); }
}
export function addCollection(name) {
  const c = newCollection(name);
  data.collections.push(c);
  data.currentId = c.id;
  save();
  return c;
}
export function renameCollection(id, name) {
  const c = data.collections.find(c => c.id === id);
  if (c) { c.name = name; save(); }
}
export function deleteCollection(id) {
  data.collections = data.collections.filter(c => c.id !== id);
  if (!data.collections.length) data.collections.push(newCollection('マイリスト'));
  if (!data.collections.some(c => c.id === data.currentId)) {
    data.currentId = data.collections[0].id;
  }
  save();
}

// Import a collection object (from a share link). Always create a new collection.
export function importCollection(obj) {
  const c = newCollection(obj.name || '取り込んだリスト');
  c.description = obj.description || '';
  c.spots = (obj.spots || []).map(s => newSpot({
    name: s.name || '(無題)',
    category: s.category || 'other',
    memo: s.memo || '',
    lat: typeof s.lat === 'number' ? s.lat : null,
    lng: typeof s.lng === 'number' ? s.lng : null,
    address: s.address || '',
    sourceUrl: s.sourceUrl || '',
    visited: !!s.visited,
  }));
  data.collections.push(c);
  data.currentId = c.id;
  save();
  return c;
}

// ---- Spots ----
export function addSpot(spot) {
  getCurrent().spots.unshift(spot);
  save();
}
export function updateSpot(id, patch) {
  const s = getCurrent().spots.find(s => s.id === id);
  if (s) { Object.assign(s, patch); save(); }
  return s;
}
export function deleteSpot(id) {
  const c = getCurrent();
  c.spots = c.spots.filter(s => s.id !== id);
  save();
}
export function getSpot(id) {
  return getCurrent().spots.find(s => s.id === id);
}
