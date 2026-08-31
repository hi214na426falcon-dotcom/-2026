// CLOUD mode data adapter (Supabase). Same async API as localAdapter.
import { client, getUser } from './supa.js';
import { compress } from './img.js';

export const supportsSharing = true;
const BUCKET = 'whimo';

function db() { const c = client(); if (!c) throw new Error('Supabase 未設定'); return c; }

// ---- Collections (lists) ----
export async function listCollections() {
  const c = db();
  const me = (await getUser())?.id;
  const { data, error } = await c
    .from('lists')
    .select('id,name,description,owner, spots(count)')
    .order('created_at', { ascending: true });
  if (error) throw error;
  return (data || []).map(l => ({
    id: l.id, name: l.name, description: l.description || '',
    role: l.owner === me ? 'owner' : 'member',
    spotCount: l.spots?.[0]?.count ?? 0,
  }));
}
export async function createCollection(name) {
  const { data, error } = await db().from('lists').insert({ name }).select().single();
  if (error) throw error;
  return { id: data.id, name: data.name, description: '', role: 'owner', spotCount: 0 };
}
export async function renameCollection(id, name) {
  const { error } = await db().from('lists').update({ name }).eq('id', id);
  if (error) throw error;
}
export async function deleteCollection(id) {
  const { error } = await db().from('lists').delete().eq('id', id);
  if (error) throw error;
}
// Import: create list + bulk insert spots.
export async function importCollection(obj) {
  const c = db();
  const { data: list, error } = await c.from('lists')
    .insert({ name: obj.name || '取り込んだリスト', description: obj.description || '' })
    .select().single();
  if (error) throw error;
  const spots = (obj.spots || []).map(s => ({
    list_id: list.id, name: s.name || '(無題)', category: s.category || 'other',
    memo: s.memo || '', lat: numOrNull(s.lat), lng: numOrNull(s.lng),
    address: s.address || '', source_url: s.sourceUrl || '', visited: !!s.visited,
  }));
  if (spots.length) {
    const { error: e2 } = await c.from('spots').insert(spots);
    if (e2) throw e2;
  }
  return { id: list.id, name: list.name, description: list.description, role: 'owner', spotCount: spots.length };
}

// ---- Spots ----
export async function listSpots(colId) {
  const { data, error } = await db().from('spots')
    .select('*').eq('list_id', colId).order('created_at', { ascending: false });
  if (error) throw error;
  return (data || []).map(mapSpot);
}
export async function addSpot(colId, s) {
  const { data, error } = await db().from('spots').insert({
    list_id: colId, name: s.name, category: s.category, memo: s.memo,
    lat: numOrNull(s.lat), lng: numOrNull(s.lng), address: s.address,
    source_url: s.sourceUrl, visited: !!s.visited,
  }).select().single();
  if (error) throw error;
  return mapSpot(data);
}
export async function updateSpot(colId, id, patch) {
  const row = {};
  if ('name' in patch) row.name = patch.name;
  if ('category' in patch) row.category = patch.category;
  if ('memo' in patch) row.memo = patch.memo;
  if ('lat' in patch) row.lat = numOrNull(patch.lat);
  if ('lng' in patch) row.lng = numOrNull(patch.lng);
  if ('address' in patch) row.address = patch.address;
  if ('sourceUrl' in patch) row.source_url = patch.sourceUrl;
  if ('visited' in patch) row.visited = !!patch.visited;
  const { data, error } = await db().from('spots').update(row).eq('id', id).select().single();
  if (error) throw error;
  return mapSpot(data);
}
export async function deleteSpot(colId, id) {
  const { error } = await db().from('spots').delete().eq('id', id);
  if (error) throw error;
}

// ---- Members (sharing) ----
export async function listMembers(colId) {
  const { data, error } = await db().from('list_members')
    .select('email,role').eq('list_id', colId);
  if (error) throw error;
  return data || [];
}
export async function addMember(colId, email, role = 'editor') {
  const { error } = await db().from('list_members')
    .upsert({ list_id: colId, email: email.trim().toLowerCase(), role });
  if (error) throw error;
}
export async function removeMember(colId, email) {
  const { error } = await db().from('list_members')
    .delete().eq('list_id', colId).eq('email', email.trim().toLowerCase());
  if (error) throw error;
}

// ---- Photos ----
export async function listPhotos(colId, spotId) {
  const c = db();
  const { data, error } = await c.from('spot_photos')
    .select('id,path').eq('spot_id', spotId).order('created_at', { ascending: true });
  if (error) throw error;
  const out = [];
  for (const row of data || []) {
    const url = await signed(row.path);
    out.push({ id: row.id, url, path: row.path });
  }
  return out;
}
export async function addPhoto(colId, spotId, file) {
  const c = db();
  const blob = await compress(file, 1280, 0.82);
  const path = `photos/${colId}/${spotId}/${crypto.randomUUID()}.jpg`;
  const up = await c.storage.from(BUCKET).upload(path, blob, { contentType: 'image/jpeg', upsert: false });
  if (up.error) throw up.error;
  const { data, error } = await c.from('spot_photos')
    .insert({ spot_id: spotId, list_id: colId, path }).select().single();
  if (error) throw error;
  return { id: data.id, url: await signed(path), path };
}
export async function deletePhoto(colId, spotId, photoId, path) {
  const c = db();
  if (path) await c.storage.from(BUCKET).remove([path]);
  const { error } = await c.from('spot_photos').delete().eq('id', photoId);
  if (error) throw error;
}

// ---- Expenses ----
export async function listExpenses(colId) {
  const c = db();
  const me = (await getUser())?.id;
  const { data, error } = await c.from('expenses')
    .select('*').eq('list_id', colId).order('spent_at', { ascending: false });
  if (error) throw error;
  const out = [];
  for (const e of data || []) {
    const mine = e.created_by === me;
    out.push({
      id: e.id, spotId: e.spot_id, amount: e.amount, memo: e.memo,
      spentAt: e.spent_at, visibility: e.visibility,
      receiptUrl: e.receipt_path && mine ? await signed(e.receipt_path) : null,
      receiptPath: mine ? e.receipt_path : null,
      mine,
    });
  }
  return out;
}
export async function addExpense(colId, d) {
  const c = db();
  const me = (await getUser())?.id;
  let receipt_path = null;
  if (d.receiptFile) {
    const blob = await compress(d.receiptFile, 1400, 0.8);
    receipt_path = `receipts/${me}/${crypto.randomUUID()}.jpg`;
    const up = await c.storage.from(BUCKET).upload(receipt_path, blob, { contentType: 'image/jpeg' });
    if (up.error) throw up.error;
  }
  const { data, error } = await c.from('expenses').insert({
    list_id: colId, spot_id: d.spotId || null, amount: d.amount || 0,
    memo: d.memo || '', spent_at: d.spentAt || today(),
    visibility: d.visibility || 'private', receipt_path,
  }).select().single();
  if (error) throw error;
  return {
    id: data.id, spotId: data.spot_id, amount: data.amount, memo: data.memo,
    spentAt: data.spent_at, visibility: data.visibility,
    receiptUrl: receipt_path ? await signed(receipt_path) : null,
    receiptPath: receipt_path, mine: true,
  };
}
export async function deleteExpense(colId, id, receiptPath) {
  const c = db();
  if (receiptPath) await c.storage.from(BUCKET).remove([receiptPath]).catch(() => {});
  const { error } = await c.from('expenses').delete().eq('id', id);
  if (error) throw error;
}

// ---- helpers ----
async function signed(path) {
  if (!path) return null;
  const { data } = await db().storage.from(BUCKET).createSignedUrl(path, 60 * 60);
  return data?.signedUrl || null;
}
function mapSpot(s) {
  return {
    id: s.id, name: s.name, category: s.category, memo: s.memo,
    lat: s.lat, lng: s.lng, address: s.address, sourceUrl: s.source_url,
    visited: s.visited, createdAt: new Date(s.created_at).getTime(),
  };
}
function numOrNull(n) { return typeof n === 'number' && !Number.isNaN(n) ? n : null; }
function today() { return new Date().toISOString().slice(0, 10); }
