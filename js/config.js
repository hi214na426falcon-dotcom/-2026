// Category definitions (id -> label / emoji / color)
export const CATEGORIES = [
  { id: 'cafe',        label: 'カフェ',      emoji: '☕', color: '#b6803d' },
  { id: 'restaurant',  label: 'グルメ',      emoji: '🍽', color: '#e5744a' },
  { id: 'sweets',      label: 'スイーツ',    emoji: '🍰', color: '#e26aa5' },
  { id: 'sightseeing', label: '観光',        emoji: '⛩', color: '#2fa84f' },
  { id: 'nature',      label: '自然・景色',  emoji: '🌿', color: '#4a9d7f' },
  { id: 'shopping',    label: 'ショッピング', emoji: '🛍', color: '#8163d4' },
  { id: 'hotel',       label: '宿泊',        emoji: '🏨', color: '#3d7fd4' },
  { id: 'other',       label: 'その他',      emoji: '📍', color: '#7b857f' },
];

export const CAT_MAP = Object.fromEntries(CATEGORIES.map(c => [c.id, c]));

export function catOf(id) {
  return CAT_MAP[id] || CAT_MAP.other;
}

// Detect the SNS platform from a URL.
export function detectPlatform(url) {
  if (!url) return { id: 'none', label: 'リンクなし', emoji: '🌐' };
  let host = '';
  try { host = new URL(url).hostname.replace(/^www\./, '').toLowerCase(); }
  catch { return { id: 'web', label: 'リンク', emoji: '🌐' }; }

  if (host.includes('instagram.com')) return { id: 'instagram', label: 'Instagram', emoji: '📸' };
  if (host.includes('tiktok.com'))    return { id: 'tiktok',    label: 'TikTok',    emoji: '🎵' };
  if (host.includes('x.com') || host.includes('twitter.com')) return { id: 'x', label: 'X', emoji: '🐦' };
  if (host.includes('youtube.com') || host.includes('youtu.be')) return { id: 'youtube', label: 'YouTube', emoji: '▶️' };
  if (host.includes('maps.google') || host.includes('goo.gl') || host.includes('maps.app')) return { id: 'gmaps', label: 'Google マップ', emoji: '🗺' };
  if (host.includes('tabelog.com')) return { id: 'tabelog', label: '食べログ', emoji: '🍴' };
  if (host.includes('facebook.com')) return { id: 'facebook', label: 'Facebook', emoji: '📘' };
  return { id: 'web', label: 'Webリンク', emoji: '🌐' };
}

export const DEFAULT_CENTER = [35.681236, 139.767125]; // Tokyo Station
export const DEFAULT_ZOOM = 12;
