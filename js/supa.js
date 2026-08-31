// Thin wrapper around the Supabase JS client + auth helpers.
// Loads only when configured (window.WHIMO_ENV filled in).

let _client = null;

export function isConfigured() {
  const e = window.WHIMO_ENV || {};
  return !!(e.SUPABASE_URL && e.SUPABASE_ANON_KEY && window.supabase);
}

export function client() {
  if (_client) return _client;
  if (!isConfigured()) return null;
  const e = window.WHIMO_ENV;
  _client = window.supabase.createClient(e.SUPABASE_URL, e.SUPABASE_ANON_KEY, {
    auth: { persistSession: true, autoRefreshToken: true },
  });
  return _client;
}

// ---- Auth ----
export async function getUser() {
  const c = client(); if (!c) return null;
  const { data } = await c.auth.getUser();
  return data?.user || null;
}

export async function signUp(email, password) {
  const c = client(); if (!c) throw new Error('未設定');
  const { data, error } = await c.auth.signUp({ email, password });
  if (error) throw error;
  return data;
}

export async function signIn(email, password) {
  const c = client(); if (!c) throw new Error('未設定');
  const { data, error } = await c.auth.signInWithPassword({ email, password });
  if (error) throw error;
  return data;
}

export async function signOut() {
  const c = client(); if (!c) return;
  await c.auth.signOut();
}

export function onAuthChange(cb) {
  const c = client(); if (!c) return () => {};
  const { data } = c.auth.onAuthStateChange((_evt, session) => cb(session?.user || null));
  return () => data?.subscription?.unsubscribe();
}
