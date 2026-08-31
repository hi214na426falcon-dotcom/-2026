// LOCAL mode data adapter (single user, this device). Async API mirrors
// the cloud adapter so the app code is identical in both modes.
import * as store from './store.js';
import { compressToDataUrl } from './img.js';

const NEED_CLOUD = () => { const e = new Error('cloud-only'); e.code = 'NEED_CLOUD'; return e; };

export const supportsSharing = false;

export async function listCollections() {
  return store.collections().map(c => ({
    id: c.id, name: c.name, description: c.description || '',
    role: 'owner', spotCount: c.spots.length,
  }));
}
export async function createCollection(name) {
  const c = store.addCollection(name);
  return { id: c.id, name: c.name, description: '', role: 'owner', spotCount: 0 };
}
export async function renameCollection(id, name) { store.renameCollection(id, name); }
export async function deleteCollection(id) { store.deleteCollection(id); }
export async function importCollection(obj) {
  const c = store.importCollection(obj);
  return { id: c.id, name: c.name, description: c.description, role: 'owner', spotCount: c.spots.length };
}

export async function listSpots(colId) {
  return store.spotsOf(colId).map(mapSpot);
}
export async function addSpot(colId, data) {
  const s = store.addSpot(colId, store.newSpot(data));
  return mapSpot(s);
}
export async function updateSpot(colId, id, patch) {
  return mapSpot(store.updateSpot(colId, id, patch));
}
export async function deleteSpot(colId, id) { store.deleteSpot(colId, id); }

// Members — not available locally.
export async function listMembers() { return []; }
export async function addMember() { throw NEED_CLOUD(); }
export async function removeMember() { throw NEED_CLOUD(); }

// Photos — stored as data URLs on the device.
export async function listPhotos(colId, spotId) {
  const s = store.spotById(colId, spotId);
  return (s?.photos || []).map(p => ({ id: p.id, url: p.url }));
}
export async function addPhoto(colId, spotId, file) {
  const dataUrl = await compressToDataUrl(file, 1280, 0.82);
  const p = store.addPhoto(colId, spotId, dataUrl);
  return { id: p.id, url: p.url };
}
export async function deletePhoto(colId, spotId, photoId) { store.deletePhoto(colId, spotId, photoId); }

// Expenses — stored locally (single user; visibility kept for parity).
export async function listExpenses(colId) {
  return store.expensesOf(colId).map(e => ({
    id: e.id, spotId: e.spotId || null, amount: e.amount || 0, memo: e.memo || '',
    spentAt: e.spentAt || '', visibility: e.visibility || 'private',
    receiptUrl: e.receiptUrl || null, mine: true,
  }));
}
export async function addExpense(colId, data) {
  let receiptUrl = null;
  if (data.receiptFile) receiptUrl = await compressToDataUrl(data.receiptFile, 1400, 0.8);
  const e = store.addExpense(colId, {
    spotId: data.spotId || null, amount: data.amount || 0, memo: data.memo || '',
    spentAt: data.spentAt || today(), visibility: data.visibility || 'private', receiptUrl,
  });
  return { id: e.id, ...data, receiptUrl, mine: true };
}
export async function deleteExpense(colId, id) { store.deleteExpense(colId, id); }

function mapSpot(s) {
  if (!s) return null;
  return {
    id: s.id, name: s.name, category: s.category, memo: s.memo,
    lat: s.lat, lng: s.lng, address: s.address, sourceUrl: s.sourceUrl,
    visited: s.visited, createdAt: s.createdAt,
  };
}
function today() { return new Date().toISOString().slice(0, 10); }
