// Local persistence (localStorage). Source of truth for LOCAL mode and
// offline cache. Holds collections -> spots -> photos, plus expenses.
const KEY = 'whimo:data:v2';
const SETTINGS_KEY = 'whimo:settings:v1';

export function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function emptyData() {
  const c = newCollection('マイリスト');
  return { version: 2, collections: [c] };
}

export function newCollection(name = '新しいリスト') {
  return { id: uid(), name, description: '', createdAt: Date.now(),
           spots: [], expenses: [] };
}

export function newSpot(partial = {}) {
  return {
    id: uid(), name: '', category: 'other', memo: '',
    lat: null, lng: null, address: '', sourceUrl: '',
    visited: false, createdAt: Date.now(), photos: [], ...partial,
  };
}

let data = load();

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const p = JSON.parse(raw);
      if (p.collections && p.collections.length) {
        p.collections.forEach(c => { c.expenses ||= []; c.spots ||= []; c.spots.forEach(s => s.photos ||= []); });
        return p;
      }
    }
    // migrate from v1 if present
    const v1 = localStorage.getItem('whimo:data:v1');
    if (v1) {
      const p = JSON.parse(v1);
      if (p.collections && p.collections.length) {
        p.collections.forEach(c => { c.expenses ||= []; c.spots ||= []; c.spots.forEach(s => s.photos ||= []); });
        return { version: 2, collections: p.collections };
      }
    }
  } catch {}
  return emptyData();
}

export function save() {
  try { localStorage.setItem(KEY, JSON.stringify(data)); }
  catch (e) { console.warn('保存に失敗しました', e); }
}

// ---- Settings ----
export function getSetting(k, fb) {
  try { const s = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}'); return k in s ? s[k] : fb; }
  catch { return fb; }
}
export function setSetting(k, v) {
  try {
    const s = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    s[k] = v; localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  } catch {}
}

// ---- Collections ----
export function collections() { return data.collections; }
export function collectionById(id) { return data.collections.find(c => c.id === id); }
export function addCollection(name) { const c = newCollection(name); data.collections.push(c); save(); return c; }
export function renameCollection(id, name) { const c = collectionById(id); if (c) { c.name = name; save(); } }
export function deleteCollection(id) {
  data.collections = data.collections.filter(c => c.id !== id);
  if (!data.collections.length) data.collections.push(newCollection('マイリスト'));
  save();
}
export function importCollection(obj) {
  const c = newCollection(obj.name || '取り込んだリスト');
  c.description = obj.description || '';
  c.spots = (obj.spots || []).map(s => newSpot({
    name: s.name || '(無題)', category: s.category || 'other', memo: s.memo || '',
    lat: typeof s.lat === 'number' ? s.lat : null, lng: typeof s.lng === 'number' ? s.lng : null,
    address: s.address || '', sourceUrl: s.sourceUrl || '', visited: !!s.visited,
  }));
  data.collections.push(c); save(); return c;
}

// ---- Spots ----
export function spotsOf(colId) { const c = collectionById(colId); return c ? c.spots : []; }
export function spotById(colId, id) { return spotsOf(colId).find(s => s.id === id); }
export function addSpot(colId, spot) { const c = collectionById(colId); if (c) { c.spots.unshift(spot); save(); } return spot; }
export function updateSpot(colId, id, patch) { const s = spotById(colId, id); if (s) { Object.assign(s, patch); save(); } return s; }
export function deleteSpot(colId, id) { const c = collectionById(colId); if (c) { c.spots = c.spots.filter(s => s.id !== id); save(); } }

// ---- Photos (local: stored as data URLs on the spot) ----
export function addPhoto(colId, spotId, dataUrl) {
  const s = spotById(colId, spotId); if (!s) return null;
  const p = { id: uid(), url: dataUrl }; s.photos.push(p); save(); return p;
}
export function deletePhoto(colId, spotId, photoId) {
  const s = spotById(colId, spotId); if (!s) return;
  s.photos = s.photos.filter(p => p.id !== photoId); save();
}

// ---- Expenses ----
export function expensesOf(colId) { const c = collectionById(colId); return c ? c.expenses : []; }
export function addExpense(colId, exp) {
  const c = collectionById(colId); if (!c) return null;
  const e = { id: uid(), createdAt: Date.now(), ...exp }; c.expenses.unshift(e); save(); return e;
}
export function deleteExpense(colId, id) {
  const c = collectionById(colId); if (c) { c.expenses = c.expenses.filter(e => e.id !== id); save(); }
}
