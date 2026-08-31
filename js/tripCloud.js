// Optional cloud sync & album sharing for trips (Supabase).
// A finished local trip can be uploaded, then shared with specific people
// by email. Recipients open it read-only (route map + photo slideshow).
import { client } from './supa.js';
import * as trips from './trips.js';

const BUCKET = 'whimo';
function db() { const c = client(); if (!c) throw new Error('Supabase 未設定'); return c; }

// Upload (create or update) a local trip to the cloud, plus new photos.
export async function upload(local) {
  const c = db();
  const row = {
    name: local.name, mode: local.mode,
    started_at: local.startedAt ? new Date(local.startedAt).toISOString() : null,
    ended_at: local.endedAt ? new Date(local.endedAt).toISOString() : null,
    distance: local.distance || 0, track: local.track || [], spend: local.spend || [],
  };
  let cloudId = local.cloudId;
  if (cloudId) {
    const { error } = await c.from('trips').update(row).eq('id', cloudId);
    if (error) throw error;
  } else {
    const { data, error } = await c.from('trips').insert(row).select().single();
    if (error) throw error;
    cloudId = data.id; trips.setCloudId(local.id, cloudId);
  }
  for (const p of local.photos) {
    if (p.cloudPath) continue;
    const blob = await trips.photoBlob(p);
    if (!blob) continue;
    const path = `trips/${cloudId}/${crypto.randomUUID()}.jpg`;
    const up = await c.storage.from(BUCKET).upload(path, blob, { contentType: 'image/jpeg' });
    if (up.error) throw up.error;
    const { error } = await c.from('trip_photos').insert({
      trip_id: cloudId, path, lat: p.lat, lng: p.lng,
      at: p.at ? new Date(p.at).toISOString() : null, caption: p.caption || '',
    });
    if (error) throw error;
    trips.markPhotoUploaded(local.id, p.id, path);
  }
  return cloudId;
}

// Trips I own or that were shared with me.
export async function listCloud() {
  const c = db();
  const { data, error } = await c.from('trips')
    .select('id,name,owner,distance,started_at,ended_at, trip_photos(count)')
    .order('started_at', { ascending: false });
  if (error) throw error;
  const me = (await c.auth.getUser()).data?.user?.id;
  return (data || []).map(t => ({
    cloudId: t.id, name: t.name, distance: t.distance,
    startedAt: t.started_at ? new Date(t.started_at).getTime() : 0,
    photoCount: t.trip_photos?.[0]?.count ?? 0,
    mine: t.owner === me,
  }));
}

// Download a cloud trip into a local-shaped, read-only object.
export async function download(cloudId) {
  const c = db();
  const { data: t, error } = await c.from('trips').select('*').eq('id', cloudId).single();
  if (error) throw error;
  const { data: photos } = await c.from('trip_photos').select('*').eq('trip_id', cloudId).order('at', { ascending: true });
  const ph = [];
  for (const p of photos || []) {
    const { data: s } = await c.storage.from(BUCKET).createSignedUrl(p.path, 60 * 60);
    ph.push({ id: p.id, at: p.at ? new Date(p.at).getTime() : Date.now(), lat: p.lat, lng: p.lng, caption: p.caption || '', url: s?.signedUrl || null });
  }
  return {
    id: 'cloud:' + cloudId, cloudId, readonly: true,
    name: t.name, mode: t.mode,
    startedAt: t.started_at ? new Date(t.started_at).getTime() : 0,
    endedAt: t.ended_at ? new Date(t.ended_at).getTime() : null,
    distance: t.distance || 0, track: t.track || [], spend: t.spend || [], photos: ph,
  };
}

export async function remove(cloudId) {
  const c = db();
  const { data: photos } = await c.from('trip_photos').select('path').eq('trip_id', cloudId);
  const paths = (photos || []).map(p => p.path);
  if (paths.length) await c.storage.from(BUCKET).remove(paths).catch(() => {});
  const { error } = await c.from('trips').delete().eq('id', cloudId);
  if (error) throw error;
}

// Sharing
export async function listMembers(cloudId) {
  const { data, error } = await db().from('trip_members').select('email,role').eq('trip_id', cloudId);
  if (error) throw error;
  return data || [];
}
export async function addMember(cloudId, email) {
  const { error } = await db().from('trip_members')
    .upsert({ trip_id: cloudId, email: email.trim().toLowerCase(), role: 'viewer' });
  if (error) throw error;
}
export async function removeMember(cloudId, email) {
  const { error } = await db().from('trip_members')
    .delete().eq('trip_id', cloudId).eq('email', email.trim().toLowerCase());
  if (error) throw error;
}
