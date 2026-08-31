import { CATEGORIES, catOf, detectPlatform } from './config.js';
import * as store from './store.js';
import * as geo from './geo.js';
import * as share from './share.js';
import * as mapView from './map.js';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const esc = (s = '') => String(s).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ---- transient UI state ----
let currentView = store.getSetting('view', 'list');
let activeFilter = null;              // category id or null
let editingId = null;                 // spot id being edited, or null for new
let editorState = { category: 'other', lat: null, lng: null, address: '' };

// =====================================================================
// Rendering
// =====================================================================
function render() {
  const col = store.getCurrent();
  const spots = col.spots;

  $('#collectionName').textContent = col.name;
  const visited = spots.filter(s => s.visited).length;
  $('#collectionMeta').textContent =
    `${spots.length} スポット${visited ? ` ・ ${visited} 訪問済み` : ''}`;

  renderFilterBar(spots);
  const shown = activeFilter ? spots.filter(s => s.category === activeFilter) : spots;

  renderList(shown);
  if (currentView === 'map') mapView.renderSpots(shown, openEditor);
  $('#emptyState').classList.toggle('hidden', spots.length > 0);
}

function renderFilterBar(spots) {
  const bar = $('#filterBar');
  const used = new Set(spots.map(s => s.category));
  if (spots.length === 0) { bar.innerHTML = ''; return; }
  const cats = CATEGORIES.filter(c => used.has(c.id));
  bar.innerHTML = '';
  const all = chip('すべて', activeFilter === null);
  all.onclick = () => { activeFilter = null; render(); };
  bar.appendChild(all);
  cats.forEach(c => {
    const el = chip(`${c.emoji} ${c.label}`, activeFilter === c.id);
    el.onclick = () => { activeFilter = activeFilter === c.id ? null : c.id; render(); };
    bar.appendChild(el);
  });
}

function chip(label, active) {
  const b = document.createElement('button');
  b.className = 'filter-chip' + (active ? ' active' : '');
  b.textContent = label;
  return b;
}

function renderList(spots) {
  const list = $('#spotList');
  list.innerHTML = '';
  spots.forEach(s => list.appendChild(spotCard(s)));
}

function spotCard(s) {
  const c = catOf(s.category);
  const card = document.createElement('div');
  card.className = 'spot-card' + (s.visited ? ' visited' : '');

  const plat = detectPlatform(s.sourceUrl);
  const hasLoc = typeof s.lat === 'number' && typeof s.lng === 'number';

  card.innerHTML = `
    <div class="spot-top">
      <span class="spot-cat-dot" style="background:${c.color}"></span>
      <span class="spot-name ${s.visited ? 'done' : ''}">${esc(s.name)}</span>
    </div>
    <div class="spot-badges">
      <span class="tag cat" style="background:${c.color}">${c.emoji} ${c.label}</span>
      ${s.sourceUrl ? `<span class="tag">${plat.emoji} ${plat.label}</span>` : ''}
      ${s.visited ? '<span class="tag">✓ 訪問済み</span>' : ''}
    </div>
    ${s.memo ? `<div class="spot-memo">${esc(s.memo)}</div>` : ''}
    ${s.address ? `<div class="spot-addr">📍 ${esc(s.address)}</div>` : ''}
    <div class="spot-actions"></div>
  `;

  const actions = card.querySelector('.spot-actions');
  if (s.sourceUrl) {
    const a = document.createElement('a');
    a.className = 'mini accent';
    a.href = s.sourceUrl; a.target = '_blank'; a.rel = 'noopener';
    a.innerHTML = `${plat.emoji} 元の投稿`;
    actions.appendChild(a);
  }
  if (hasLoc) {
    const b = document.createElement('button');
    b.className = 'mini';
    b.innerHTML = '🗺 地図で見る';
    b.onclick = () => { switchView('map'); setTimeout(() => mapView.focus(s.lat, s.lng), 60); };
    actions.appendChild(b);
  }
  const v = document.createElement('button');
  v.className = 'mini';
  v.innerHTML = s.visited ? '↩︎ 未訪問に' : '✓ 行った';
  v.onclick = () => { store.updateSpot(s.id, { visited: !s.visited }); render(); };
  actions.appendChild(v);

  const e = document.createElement('button');
  e.className = 'mini';
  e.innerHTML = '✏️ 編集';
  e.onclick = () => openEditor(s.id);
  actions.appendChild(e);

  return card;
}

// =====================================================================
// View switching
// =====================================================================
function switchView(view) {
  currentView = view;
  store.setSetting('view', view);
  $$('.seg').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $('#listView').classList.toggle('hidden', view !== 'list');
  $('#mapView').classList.toggle('hidden', view !== 'map');
  if (view === 'map') { mapView.refresh(); render(); }
}

// =====================================================================
// Drawer (collections)
// =====================================================================
function openDrawer() {
  renderCollections();
  $('#drawer').classList.remove('hidden');
}
function closeDrawer() { $('#drawer').classList.add('hidden'); }

function renderCollections() {
  const wrap = $('#collectionList');
  wrap.innerHTML = '';
  const curId = store.getCurrentId();
  store.getCollections().forEach(col => {
    const item = document.createElement('div');
    item.className = 'collection-item' + (col.id === curId ? ' active' : '');
    item.innerHTML = `
      <div class="ci-main">
        <div class="ci-name">${esc(col.name)}</div>
        <div class="ci-meta">${col.spots.length} スポット</div>
      </div>
      <button class="ci-menu">⋯</button>`;
    item.querySelector('.ci-main').onclick = () => {
      store.setCurrent(col.id); closeDrawer(); activeFilter = null; render();
      if (currentView === 'map') mapView.refresh();
    };
    item.querySelector('.ci-menu').onclick = (ev) => { ev.stopPropagation(); collectionMenu(col); };
    wrap.appendChild(item);
  });
}

function collectionMenu(col) {
  const action = prompt(
    `「${col.name}」\n\n1 = 名前を変更\n2 = 削除\n（キャンセルで閉じる）`, '1');
  if (action === '1') {
    const name = prompt('新しいリスト名', col.name);
    if (name && name.trim()) { store.renameCollection(col.id, name.trim()); renderCollections(); render(); }
  } else if (action === '2') {
    if (confirm(`「${col.name}」を削除しますか？この操作は取り消せません。`)) {
      store.deleteCollection(col.id); renderCollections(); render();
      toast('リストを削除しました');
    }
  }
}

// =====================================================================
// Editor (add / edit spot)
// =====================================================================
function openEditor(id = null) {
  editingId = id;
  const s = id ? store.getSpot(id) : null;
  editorState = {
    category: s ? s.category : 'other',
    lat: s ? s.lat : null,
    lng: s ? s.lng : null,
    address: s ? s.address : '',
  };

  $('#editorTitle').textContent = id ? 'スポットを編集' : 'スポットを追加';
  $('#f_url').value = s ? s.sourceUrl : '';
  $('#f_name').value = s ? s.name : '';
  $('#f_memo').value = s ? s.memo : '';
  $('#f_visited').checked = s ? s.visited : false;
  $('#f_search').value = '';
  $('#searchResults').innerHTML = '';
  updatePlatformBadge();
  renderCategoryPicker();
  updateLocStatus();
  $('#deleteSpotBtn').classList.toggle('hidden', !id);

  $('#editor').classList.remove('hidden');
  if (!id) setTimeout(() => $('#f_url').focus(), 200);
}
function closeEditor() { $('#editor').classList.add('hidden'); mapView.stopPick(); }

function renderCategoryPicker() {
  const wrap = $('#categoryPicker');
  wrap.innerHTML = '';
  CATEGORIES.forEach(c => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'cat-chip' + (editorState.category === c.id ? ' active' : '');
    if (editorState.category === c.id) b.style.background = c.color;
    b.innerHTML = `${c.emoji} ${c.label}`;
    b.onclick = () => { editorState.category = c.id; renderCategoryPicker(); };
    wrap.appendChild(b);
  });
}

function updatePlatformBadge() {
  const p = detectPlatform($('#f_url').value.trim());
  $('#platformBadge').textContent = p.emoji;
  $('#platformBadge').title = p.label;
}

function updateLocStatus() {
  const el = $('#locStatus');
  if (typeof editorState.lat === 'number') {
    el.innerHTML = `✅ 場所を設定しました${editorState.address ? `：${esc(editorState.address)}` : ''} ` +
      `<button type="button" id="clearLocBtn" class="mini" style="margin-left:6px;">クリア</button>`;
    $('#clearLocBtn').onclick = () => {
      editorState.lat = editorState.lng = null; editorState.address = ''; updateLocStatus();
    };
  } else {
    el.textContent = '場所は未設定です。検索するか、下の「地図で指定」で選べます。';
  }
}

async function doSearch() {
  const q = $('#f_search').value.trim();
  if (!q) return;
  const box = $('#searchResults');
  box.innerHTML = '<div class="muted small">検索中…</div>';
  try {
    const results = await geo.search(q);
    box.innerHTML = '';
    if (!results.length) { box.innerHTML = '<div class="muted small">見つかりませんでした</div>'; return; }
    results.forEach(r => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'search-result';
      b.innerHTML = `<strong>${esc(r.name)}</strong><br><span class="muted">${esc(r.address)}</span>`;
      b.onclick = () => {
        editorState.lat = r.lat; editorState.lng = r.lng; editorState.address = r.address;
        if (!$('#f_name').value.trim()) $('#f_name').value = r.name;
        box.innerHTML = '';
        updateLocStatus();
      };
      box.appendChild(b);
    });
  } catch (e) {
    box.innerHTML = '<div class="muted small">検索に失敗しました。時間をおいて再度お試しください。</div>';
  }
}

// Pick a location by tapping on the map.
function pickOnMap() {
  const draft = {
    sourceUrl: $('#f_url').value.trim(),
    name: $('#f_name').value.trim(),
    memo: $('#f_memo').value,
    visited: $('#f_visited').checked,
    category: editorState.category,
  };
  $('#editor').classList.add('hidden');
  switchView('map');
  const ok = mapView.startPick(async (lat, lng) => {
    mapView.stopPick();
    $('#mapHint').classList.add('hidden');
    editorState.lat = lat; editorState.lng = lng;
    editorState.address = await geo.reverse(lat, lng);
    // restore editor with the draft the user had typed
    $('#editor').classList.remove('hidden');
    $('#f_url').value = draft.sourceUrl;
    $('#f_name').value = draft.name;
    $('#f_memo').value = draft.memo;
    $('#f_visited').checked = draft.visited;
    editorState.category = draft.category;
    renderCategoryPicker();
    updatePlatformBadge();
    updateLocStatus();
  });
  if (ok) {
    $('#mapHint').classList.remove('hidden');
    toast('地図をタップして場所を指定してください');
  } else {
    // Map unavailable — reopen the editor so the user doesn't lose their input.
    $('#editor').classList.remove('hidden');
    $('#f_url').value = draft.sourceUrl;
    $('#f_name').value = draft.name;
    $('#f_memo').value = draft.memo;
    $('#f_visited').checked = draft.visited;
    editorState.category = draft.category;
    renderCategoryPicker();
    updatePlatformBadge();
    updateLocStatus();
    toast('地図を読み込めませんでした。場所の検索をご利用ください');
  }
}

function saveSpot() {
  const name = $('#f_name').value.trim();
  if (!name) { toast('スポット名を入力してください'); $('#f_name').focus(); return; }
  const patch = {
    name,
    sourceUrl: $('#f_url').value.trim(),
    memo: $('#f_memo').value.trim(),
    visited: $('#f_visited').checked,
    category: editorState.category,
    lat: editorState.lat,
    lng: editorState.lng,
    address: editorState.address,
  };
  if (editingId) {
    store.updateSpot(editingId, patch);
    toast('保存しました');
  } else {
    store.addSpot(store.newSpot(patch));
    toast('スポットを追加しました');
  }
  closeEditor();
  render();
}

function deleteCurrentSpot() {
  if (!editingId) return;
  if (confirm('このスポットを削除しますか？')) {
    store.deleteSpot(editingId);
    closeEditor(); render();
    toast('削除しました');
  }
}

// =====================================================================
// Share / import
// =====================================================================
function openShare() {
  const col = store.getCurrent();
  if (!col.spots.length) { toast('共有するスポットがありません'); return; }
  const url = share.buildShareUrl(col);
  $('#shareUrl').value = url;
  $('#shareInfo').textContent =
    `「${col.name}」（${col.spots.length}スポット）を共有します。リンクの長さ：約${Math.round(url.length / 100) / 10}KB`;
  $('#shareModal').classList.remove('hidden');
}

async function copyShare() {
  const url = $('#shareUrl').value;
  try {
    if (navigator.share) {
      await navigator.share({ title: store.getCurrent().name, url });
      return;
    }
  } catch { /* fall through to clipboard */ }
  try {
    await navigator.clipboard.writeText(url);
    toast('リンクをコピーしました');
  } catch {
    $('#shareUrl').select();
    document.execCommand('copy');
    toast('リンクをコピーしました');
  }
}

function handleImportFromInput() {
  const input = prompt('共有リンク（またはコード）を貼り付けてください');
  if (!input) return;
  let code = input.trim();
  const m = code.match(/share=([^&]+)/);
  if (m) code = m[1];
  try {
    const obj = share.decodeCollection(code);
    finishImport(obj);
  } catch {
    toast('リンクを読み取れませんでした');
  }
}

function finishImport(obj) {
  const c = store.importCollection(obj);
  closeDrawer();
  activeFilter = null;
  render();
  if (currentView === 'map') mapView.refresh();
  toast(`「${c.name}」を取り込みました（${c.spots.length}スポット）`);
}

// If the page was opened via a share link, offer to import it.
function checkShareOnLoad() {
  const obj = share.readShareFromHash();
  if (!obj) return;
  share.clearShareHash();
  const n = obj.spots.length;
  if (confirm(`共有リスト「${obj.name}」（${n}スポット）が見つかりました。\n自分のWhimoに取り込みますか？`)) {
    finishImport(obj);
  }
}

// =====================================================================
// Toast
// =====================================================================
let toastTimer = null;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), 2200);
}

// =====================================================================
// Wiring
// =====================================================================
function wire() {
  $$('.seg').forEach(b => b.onclick = () => switchView(b.dataset.view));
  $('#addBtn').onclick = () => openEditor(null);
  $('#menuBtn').onclick = openDrawer;
  $('#drawerClose').onclick = closeDrawer;
  $$('[data-close-drawer]').forEach(el => el.onclick = closeDrawer);
  $('#newCollectionBtn').onclick = () => {
    const name = prompt('新しいリストの名前', '新しいリスト');
    if (name && name.trim()) { store.addCollection(name.trim()); renderCollections(); render(); toast('リストを作成しました'); }
  };
  $('#importBtn').onclick = handleImportFromInput;

  // editor
  $('#f_url').addEventListener('input', updatePlatformBadge);
  $('#searchBtn').onclick = doSearch;
  $('#f_search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); doSearch(); } });
  $('#saveSpotBtn').onclick = saveSpot;
  $('#cancelEditBtn').onclick = closeEditor;
  $('#deleteSpotBtn').onclick = deleteCurrentSpot;
  $$('[data-close-editor]').forEach(el => el.onclick = closeEditor);

  // a "地図で指定" affordance appended under the search field
  const pickBtn = document.createElement('button');
  pickBtn.type = 'button';
  pickBtn.className = 'btn ghost small';
  pickBtn.style.marginTop = '4px';
  pickBtn.textContent = '🗺 地図で指定';
  pickBtn.onclick = pickOnMap;
  $('#locStatus').parentElement.appendChild(pickBtn);

  // share
  $('#shareBtn').onclick = openShare;
  $('#copyShareBtn').onclick = copyShare;
  $$('[data-close-share]').forEach(el => el.onclick = () => $('#shareModal').classList.add('hidden'));

  window.addEventListener('hashchange', checkShareOnLoad);
}

// =====================================================================
// Boot
// =====================================================================
function boot() {
  wire();
  switchView(currentView);
  render();
  checkShareOnLoad();

  // Register service worker (installable PWA) only over http(s).
  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  }
}

boot();
