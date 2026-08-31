import { CATEGORIES, catOf, detectPlatform } from './config.js';
import * as store from './store.js';
import * as data from './data.js';
import * as supa from './supa.js';
import * as geo from './geo.js';
import * as share from './share.js';
import * as mapView from './map.js';
import * as trips from './trips.js';

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const esc = (s = '') => String(s).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const yen = (n) => '¥' + (n || 0).toLocaleString('ja-JP');

// ---- state ----
let mode = 'local';
let user = null;
let collections = [];        // [{id,name,description,role,spotCount}]
let currentId = null;
let spots = [];              // spots of current collection
let activeFilter = null;
let currentView = store.getSetting('view', 'list');

let editingId = null;
let editorState = { category: 'other', lat: null, lng: null, address: '' };

let authMode = 'login';      // 'login' | 'signup'
let expenseVisibility = 'private';
let expenseReceiptFile = null;

function currentCollection() { return collections.find(c => c.id === currentId) || null; }
function busy(on) { document.body.style.cursor = on ? 'progress' : ''; }

// =====================================================================
// Load / reload
// =====================================================================
async function reload() {
  try {
    collections = await data.listCollections();
    if (!collections.length && mode === 'cloud') {
      collections = [await data.createCollection('マイリスト')];
    }
    if (!collections.some(c => c.id === currentId)) {
      const saved = store.getSetting('currentId:' + mode, null);
      currentId = (collections.find(c => c.id === saved) || collections[0])?.id || null;
    }
    await loadCurrent();
  } catch (e) {
    console.error(e); toast('データの読み込みに失敗しました');
  }
}

async function loadCurrent() {
  spots = currentId ? await data.listSpots(currentId) : [];
  if (currentId) store.setSetting('currentId:' + mode, currentId);
  render();
}

// =====================================================================
// Render
// =====================================================================
function render() {
  const col = currentCollection();
  $('#collectionName').textContent = col ? col.name : 'マイリスト';
  const visited = spots.filter(s => s.visited).length;
  const shared = col && col.role === 'member' ? ' ・ 共有' : '';
  $('#collectionMeta').textContent = `${spots.length} スポット${visited ? ` ・ ${visited} 訪問済み` : ''}${shared}`;

  renderFilterBar();
  const shown = activeFilter ? spots.filter(s => s.category === activeFilter) : spots;
  renderList(shown);
  if (currentView === 'map') mapView.renderSpots(shown, openEditor);
  $('#emptyState').classList.toggle('hidden', spots.length > 0);
}

function renderFilterBar() {
  const bar = $('#filterBar');
  if (!spots.length) { bar.innerHTML = ''; return; }
  const used = new Set(spots.map(s => s.category));
  bar.innerHTML = '';
  const all = chip('すべて', activeFilter === null);
  all.onclick = () => { activeFilter = null; render(); };
  bar.appendChild(all);
  CATEGORIES.filter(c => used.has(c.id)).forEach(c => {
    const el = chip(`${c.emoji} ${c.label}`, activeFilter === c.id);
    el.onclick = () => { activeFilter = activeFilter === c.id ? null : c.id; render(); };
    bar.appendChild(el);
  });
}
function chip(label, active) {
  const b = document.createElement('button');
  b.className = 'filter-chip' + (active ? ' active' : '');
  b.textContent = label; return b;
}

function renderList(list) {
  const wrap = $('#spotList');
  wrap.innerHTML = '';
  list.forEach(s => wrap.appendChild(spotCard(s)));
}

function spotCard(s) {
  const c = catOf(s.category);
  const plat = detectPlatform(s.sourceUrl);
  const hasLoc = typeof s.lat === 'number' && typeof s.lng === 'number';
  const card = document.createElement('div');
  card.className = 'spot-card' + (s.visited ? ' visited' : '');
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
    <div class="spot-actions"></div>`;
  const actions = card.querySelector('.spot-actions');
  if (s.sourceUrl) {
    const a = document.createElement('a');
    a.className = 'mini accent'; a.href = s.sourceUrl; a.target = '_blank'; a.rel = 'noopener';
    a.innerHTML = `${plat.emoji} 元の投稿`; actions.appendChild(a);
  }
  if (hasLoc) {
    const b = document.createElement('button');
    b.className = 'mini'; b.innerHTML = '🗺 地図で見る';
    b.onclick = () => { switchView('map'); setTimeout(() => mapView.focus(s.lat, s.lng), 60); };
    actions.appendChild(b);
  }
  const v = document.createElement('button');
  v.className = 'mini'; v.innerHTML = s.visited ? '↩︎ 未訪問に' : '✓ 行った';
  v.onclick = async () => { await mutate(() => data.updateSpot(currentId, s.id, { visited: !s.visited })); await loadCurrent(); };
  actions.appendChild(v);
  const e = document.createElement('button');
  e.className = 'mini'; e.innerHTML = '✏️ 編集';
  e.onclick = () => openEditor(s.id);
  actions.appendChild(e);
  return card;
}

async function mutate(fn) {
  try { busy(true); await fn(); }
  catch (e) { console.error(e); toast(errMsg(e)); }
  finally { busy(false); }
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
  $('#tripsView').classList.toggle('hidden', view !== 'trips');
  $('#filterBar').style.display = view === 'trips' ? 'none' : '';
  $('#addBtn').classList.toggle('hidden', view === 'trips');
  if (view === 'map') { mapView.refresh(); render(); }
  if (view === 'trips') renderTrips();
}

// =====================================================================
// Account / auth
// =====================================================================
function renderAccount() {
  const box = $('#accountBox');
  if (!supa.isConfigured()) {
    box.innerHTML = `<div><span class="badge-mode">ローカルモード</span></div>
      <div class="muted small">この端末にのみ保存されます。同期・共有を使うには <code>js/env.js</code> にSupabaseの鍵を設定してください。</div>`;
  } else if (user) {
    box.innerHTML = `<div class="acc-row"><span class="badge-mode cloud">クラウド同期中</span></div>
      <div class="acc-email">${esc(user.email || '')}</div>
      <button id="logoutBtn" class="btn ghost small">ログアウト</button>`;
    $('#logoutBtn').onclick = doLogout;
  } else {
    box.innerHTML = `<div><span class="badge-mode">未ログイン</span></div>
      <div class="muted small">ログインするとクラウドに保存され、共有・写真の同期が使えます。</div>
      <button id="loginBtn" class="btn primary small">ログイン / 新規登録</button>`;
    $('#loginBtn').onclick = openAuth;
  }
  $('#modeNote').textContent = mode === 'cloud'
    ? 'クラウド保存（Supabase）。複数端末で同期されます。'
    : 'ローカル保存。この端末のブラウザにのみ保存されます。';
}

function openAuth() { authMode = 'login'; syncAuthUI(); $('#authError').classList.add('hidden'); $('#authModal').classList.remove('hidden'); }
function closeAuth() { $('#authModal').classList.add('hidden'); }
function syncAuthUI() {
  const login = authMode === 'login';
  $('#authTitle').textContent = login ? 'ログイン' : '新規登録';
  $('#authSubmit').textContent = login ? 'ログイン' : '登録する';
  $('#authToggle').textContent = login ? '新規登録はこちら' : 'ログインはこちら';
  $('#authPass').autocomplete = login ? 'current-password' : 'new-password';
}
async function submitAuth() {
  const email = $('#authEmail').value.trim();
  const pass = $('#authPass').value;
  if (!email || !pass) { authErr('メールとパスワードを入力してください'); return; }
  try {
    busy(true);
    if (authMode === 'signup') {
      const res = await supa.signUp(email, pass);
      if (!res.session) { closeAuth(); toast('確認メールを送信しました。メール内のリンクを開くと登録完了です'); return; }
    } else {
      await supa.signIn(email, pass);
    }
    closeAuth();
    // onAuthChange handles reload
  } catch (e) { authErr(errMsg(e)); }
  finally { busy(false); }
}
function authErr(m) { const el = $('#authError'); el.textContent = m; el.classList.remove('hidden'); }
async function doLogout() { await supa.signOut(); toast('ログアウトしました'); }

// =====================================================================
// Drawer (collections)
// =====================================================================
async function openDrawer() {
  renderAccount();
  try { collections = await data.listCollections(); } catch {}
  renderCollections();
  $('#drawer').classList.remove('hidden');
}
function closeDrawer() { $('#drawer').classList.add('hidden'); }

function renderCollections() {
  const wrap = $('#collectionList');
  wrap.innerHTML = '';
  collections.forEach(col => {
    const item = document.createElement('div');
    item.className = 'collection-item' + (col.id === currentId ? ' active' : '');
    item.innerHTML = `
      <div class="ci-main">
        <div class="ci-name">${esc(col.name)} ${col.role === 'member' ? '<span class="badge-mode">共有</span>' : ''}</div>
        <div class="ci-meta">${col.spotCount} スポット</div>
      </div>
      <button class="ci-menu">⋯</button>`;
    item.querySelector('.ci-main').onclick = async () => {
      currentId = col.id; activeFilter = null; closeDrawer();
      await loadCurrent(); if (currentView === 'map') mapView.refresh();
    };
    item.querySelector('.ci-menu').onclick = (ev) => { ev.stopPropagation(); collectionMenu(col); };
    wrap.appendChild(item);
  });
}

function collectionMenu(col) {
  const isOwner = col.role === 'owner';
  const canShare = mode === 'cloud' && isOwner;
  const lines = [];
  if (isOwner) { lines.push('1 = 名前を変更'); lines.push('2 = 削除'); }
  if (canShare) lines.push('3 = 共有（相手を招待）');
  if (!isOwner) lines.push('※共有されたリストです（編集は可能・削除/共有はオーナーのみ）');
  const a = prompt(`「${col.name}」\n\n${lines.join('\n')}\n（キャンセルで閉じる）`, isOwner ? '1' : '');
  if (a === '1' && isOwner) {
    const name = prompt('新しいリスト名', col.name);
    if (name && name.trim()) mutate(async () => { await data.renameCollection(col.id, name.trim()); await openDrawer(); if (col.id === currentId) render(); });
  } else if (a === '2' && isOwner) {
    if (confirm(`「${col.name}」を削除しますか？取り消せません。`))
      mutate(async () => { await data.deleteCollection(col.id); if (col.id === currentId) currentId = null; await reload(); await openDrawer(); toast('削除しました'); });
  } else if (a === '3' && canShare) {
    openMembers(col);
  }
}

// =====================================================================
// Members (sharing)
// =====================================================================
let membersCol = null;
async function openMembers(col) {
  membersCol = col;
  $('#memberEmail').value = '';
  $('#membersModal').classList.remove('hidden');
  await refreshMembers();
}
function closeMembers() { $('#membersModal').classList.add('hidden'); membersCol = null; }
async function refreshMembers() {
  const wrap = $('#memberList');
  wrap.innerHTML = '<div class="member-empty">読み込み中…</div>';
  try {
    const members = await data.listMembers(membersCol.id);
    if (!members.length) { wrap.innerHTML = '<div class="member-empty">まだ誰とも共有していません。</div>'; return; }
    wrap.innerHTML = '';
    members.forEach(m => {
      const el = document.createElement('div');
      el.className = 'member-item';
      el.innerHTML = `<span class="mi-email">${esc(m.email)}</span><button class="mi-remove">解除</button>`;
      el.querySelector('.mi-remove').onclick = () =>
        mutate(async () => { await data.removeMember(membersCol.id, m.email); await refreshMembers(); });
      wrap.appendChild(el);
    });
  } catch (e) { wrap.innerHTML = `<div class="member-empty">${esc(errMsg(e))}</div>`; }
}
async function addMember() {
  const email = $('#memberEmail').value.trim();
  if (!email || !email.includes('@')) { toast('メールアドレスを入力してください'); return; }
  await mutate(async () => {
    await data.addMember(membersCol.id, email);
    $('#memberEmail').value = '';
    await refreshMembers();
    toast(`${email} を招待しました`);
  });
}

// =====================================================================
// Editor (add / edit spot)
// =====================================================================
function openEditor(id = null) {
  editingId = id;
  const s = id ? spots.find(x => x.id === id) : null;
  editorState = { category: s ? s.category : 'other', lat: s ? s.lat : null, lng: s ? s.lng : null, address: s ? s.address : '' };

  $('#editorTitle').textContent = id ? 'スポットを編集' : 'スポットを追加';
  $('#f_url').value = s ? s.sourceUrl : '';
  $('#f_name').value = s ? s.name : '';
  $('#f_memo').value = s ? s.memo : '';
  $('#f_visited').checked = s ? s.visited : false;
  $('#f_search').value = '';
  $('#searchResults').innerHTML = '';
  updatePlatformBadge(); renderCategoryPicker(); updateLocStatus();
  $('#deleteSpotBtn').classList.toggle('hidden', !id);

  // photos only when editing an existing spot
  const pf = $('#photoField');
  if (id) { pf.classList.remove('hidden'); loadPhotos(id); }
  else { pf.classList.add('hidden'); $('#photoGrid').innerHTML = ''; }

  $('#editor').classList.remove('hidden');
  if (!id) setTimeout(() => $('#f_url').focus(), 200);
}
function closeEditor() { $('#editor').classList.add('hidden'); mapView.stopPick(); }

function renderCategoryPicker() {
  const wrap = $('#categoryPicker'); wrap.innerHTML = '';
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
  $('#platformBadge').textContent = p.emoji; $('#platformBadge').title = p.label;
}
function updateLocStatus() {
  const el = $('#locStatus');
  if (typeof editorState.lat === 'number') {
    el.innerHTML = `✅ 場所を設定しました${editorState.address ? `：${esc(editorState.address)}` : ''} <button type="button" id="clearLocBtn" class="mini" style="margin-left:6px;">クリア</button>`;
    $('#clearLocBtn').onclick = () => { editorState.lat = editorState.lng = null; editorState.address = ''; updateLocStatus(); };
  } else {
    el.textContent = '場所は未設定です。検索するか、下の「地図で指定」で選べます。';
  }
}

// ---- photos ----
async function loadPhotos(spotId) {
  const grid = $('#photoGrid');
  grid.innerHTML = '<div class="muted small">読み込み中…</div>';
  try {
    const photos = await data.listPhotos(currentId, spotId);
    grid.innerHTML = '';
    photos.forEach(p => {
      const cell = document.createElement('div');
      cell.className = 'photo-thumb';
      cell.innerHTML = `<img src="${p.url}" alt="" /><button class="ph-del" title="削除">✕</button>`;
      cell.querySelector('.ph-del').onclick = () =>
        mutate(async () => { await data.deletePhoto(currentId, spotId, p.id, p.path); await loadPhotos(spotId); });
      grid.appendChild(cell);
    });
    $('#photoHint').textContent = photos.length ? '' : 'まだ写真がありません。';
  } catch (e) { grid.innerHTML = ''; $('#photoHint').textContent = errMsg(e); }
}
async function onPhotoPick(ev) {
  const files = Array.from(ev.target.files || []);
  ev.target.value = '';
  if (!files.length || !editingId) return;
  await mutate(async () => {
    for (const f of files) await data.addPhoto(currentId, editingId, f);
    await loadPhotos(editingId);
    toast(`写真を${files.length}枚追加しました`);
  });
}

async function doSearch() {
  const q = $('#f_search').value.trim(); if (!q) return;
  const box = $('#searchResults');
  box.innerHTML = '<div class="muted small">検索中…</div>';
  try {
    const results = await geo.search(q);
    box.innerHTML = '';
    if (!results.length) { box.innerHTML = '<div class="muted small">見つかりませんでした</div>'; return; }
    results.forEach(r => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'search-result';
      b.innerHTML = `<strong>${esc(r.name)}</strong><br><span class="muted">${esc(r.address)}</span>`;
      b.onclick = () => {
        editorState.lat = r.lat; editorState.lng = r.lng; editorState.address = r.address;
        if (!$('#f_name').value.trim()) $('#f_name').value = r.name;
        box.innerHTML = ''; updateLocStatus();
      };
      box.appendChild(b);
    });
  } catch { box.innerHTML = '<div class="muted small">検索に失敗しました。時間をおいて再度お試しください。</div>'; }
}

function pickOnMap() {
  const draft = { sourceUrl: $('#f_url').value.trim(), name: $('#f_name').value.trim(), memo: $('#f_memo').value, visited: $('#f_visited').checked, category: editorState.category };
  const restore = () => {
    $('#editor').classList.remove('hidden');
    $('#f_url').value = draft.sourceUrl; $('#f_name').value = draft.name; $('#f_memo').value = draft.memo;
    $('#f_visited').checked = draft.visited; editorState.category = draft.category;
    renderCategoryPicker(); updatePlatformBadge(); updateLocStatus();
  };
  $('#editor').classList.add('hidden');
  switchView('map');
  const ok = mapView.startPick(async (lat, lng) => {
    mapView.stopPick(); $('#mapHint').classList.add('hidden');
    editorState.lat = lat; editorState.lng = lng; editorState.address = await geo.reverse(lat, lng);
    restore();
  });
  if (ok) { $('#mapHint').classList.remove('hidden'); toast('地図をタップして場所を指定してください'); }
  else { restore(); toast('地図を読み込めませんでした。場所の検索をご利用ください'); }
}

async function saveSpot() {
  const name = $('#f_name').value.trim();
  if (!name) { toast('スポット名を入力してください'); $('#f_name').focus(); return; }
  const patch = {
    name, sourceUrl: $('#f_url').value.trim(), memo: $('#f_memo').value.trim(),
    visited: $('#f_visited').checked, category: editorState.category,
    lat: editorState.lat, lng: editorState.lng, address: editorState.address,
  };
  await mutate(async () => {
    if (editingId) { await data.updateSpot(currentId, editingId, patch); toast('保存しました'); }
    else { await data.addSpot(currentId, patch); toast('スポットを追加しました'); }
    closeEditor(); await loadCurrent();
  });
}
async function deleteCurrentSpot() {
  if (!editingId) return;
  if (!confirm('このスポットを削除しますか？')) return;
  await mutate(async () => { await data.deleteSpot(currentId, editingId); closeEditor(); await loadCurrent(); toast('削除しました'); });
}

// =====================================================================
// Share (link) / import
// =====================================================================
function openShare() {
  const col = currentCollection();
  if (!col || !spots.length) { toast('共有するスポットがありません'); return; }
  const url = share.buildShareUrl({ name: col.name, description: col.description, spots });
  $('#shareUrl').value = url;
  $('#shareInfo').textContent = `「${col.name}」（${spots.length}スポット）を、閲覧用リンクとして共有します。`;
  $('#shareModal').classList.remove('hidden');
}
async function copyShare() {
  const url = $('#shareUrl').value;
  try { if (navigator.share) { await navigator.share({ title: currentCollection()?.name || 'Whimo', url }); return; } } catch {}
  try { await navigator.clipboard.writeText(url); toast('リンクをコピーしました'); }
  catch { $('#shareUrl').select(); document.execCommand('copy'); toast('リンクをコピーしました'); }
}
function handleImportFromInput() {
  const input = prompt('共有リンク（またはコード）を貼り付けてください'); if (!input) return;
  let code = input.trim(); const m = code.match(/share=([^&]+)/); if (m) code = m[1];
  try { finishImport(share.decodeCollection(code)); } catch { toast('リンクを読み取れませんでした'); }
}
async function finishImport(obj) {
  await mutate(async () => {
    const c = await data.importCollection(obj);
    closeDrawer(); currentId = c.id; activeFilter = null; await reload();
    if (currentView === 'map') mapView.refresh();
    toast(`「${c.name}」を取り込みました（${c.spotCount}スポット）`);
  });
}
function checkShareOnLoad() {
  const obj = share.readShareFromHash(); if (!obj) return;
  share.clearShareHash();
  if (confirm(`共有リスト「${obj.name}」（${obj.spots.length}スポット）が見つかりました。\n自分のWhimoに取り込みますか？`)) finishImport(obj);
}

// =====================================================================
// Hidden budget (receipts & spending)
// =====================================================================
async function openBudget() {
  $('#budgetScreen').classList.remove('hidden');
  await refreshBudget();
}
function closeBudget() { $('#budgetScreen').classList.add('hidden'); }

async function refreshBudget() {
  const list = $('#budgetList');
  const col = currentCollection();
  $('#budgetMeta').textContent = col ? col.name : '';
  list.innerHTML = '<div class="muted small" style="padding:12px">読み込み中…</div>';
  try {
    const expenses = currentId ? await data.listExpenses(currentId) : [];
    const total = expenses.reduce((a, e) => a + (e.amount || 0), 0);
    $('#budgetTotal').innerHTML = `${yen(total)}<small>${col ? col.name : ''} の合計（${expenses.length}件）</small>`;
    if (!expenses.length) { list.innerHTML = '<div class="muted small" style="padding:16px;text-align:center">まだ記録がありません。右上の「＋」から追加できます。</div>'; return; }
    list.innerHTML = '';
    expenses.forEach(e => list.appendChild(expenseCard(e)));
  } catch (err) { list.innerHTML = `<div class="muted small" style="padding:12px">${esc(errMsg(err))}</div>`; }
}
function expenseCard(e) {
  const spot = spots.find(s => s.id === e.spotId);
  const card = document.createElement('div');
  card.className = 'expense-card';
  const vis = e.visibility === 'shared' ? '👫 共有' : '🔒 自分だけ';
  const who = e.mine ? '' : ' ・ 相手の記録';
  card.innerHTML = `
    ${e.receiptUrl ? `<img class="ex-thumb" src="${e.receiptUrl}" alt="レシート" />` : ''}
    <div class="ex-main">
      <div class="ex-amount">${yen(e.amount)}</div>
      <div class="ex-sub">${esc(e.memo || '(メモなし)')}${spot ? ' ・ ' + esc(spot.name) : ''}</div>
      <div class="ex-sub">${esc(e.spentAt || '')} ・ ${vis}${who}</div>
    </div>
    ${e.mine ? '<button class="ex-del">削除</button>' : ''}`;
  const del = card.querySelector('.ex-del');
  if (del) del.onclick = () => { if (confirm('この記録を削除しますか？')) mutate(async () => { await data.deleteExpense(currentId, e.id, e.receiptPath); await refreshBudget(); }); };
  return card;
}

function openExpenseSheet() {
  if (!currentId) { toast('先にリストを選んでください'); return; }
  $('#ex_amount').value = ''; $('#ex_memo').value = '';
  $('#ex_date').value = new Date().toISOString().slice(0, 10);
  expenseVisibility = 'private'; expenseReceiptFile = null;
  $('#ex_receiptPreview').innerHTML = '';
  $$('#ex_visibility .vis-chip').forEach(b => b.classList.toggle('active', b.dataset.vis === 'private'));
  // spot options
  const sel = $('#ex_spot');
  sel.innerHTML = '<option value="">（なし）</option>' + spots.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
  $('#expenseSheet').classList.remove('hidden');
}
function closeExpenseSheet() { $('#expenseSheet').classList.add('hidden'); }
async function onReceiptPick(ev) {
  const f = (ev.target.files || [])[0];
  if (!f) return;
  expenseReceiptFile = f;
  const { compressToDataUrl } = await import('./img.js');
  const url = await compressToDataUrl(f, 800, 0.7);
  $('#ex_receiptPreview').innerHTML = `<img src="${url}" alt="レシートプレビュー" />`;
}
async function saveExpense() {
  const amount = parseInt($('#ex_amount').value, 10);
  if (!amount && amount !== 0) { toast('金額を入力してください'); return; }
  await mutate(async () => {
    await data.addExpense(currentId, {
      amount: amount || 0, memo: $('#ex_memo').value.trim(), spentAt: $('#ex_date').value,
      spotId: $('#ex_spot').value || null, visibility: expenseVisibility, receiptFile: expenseReceiptFile,
    });
    closeExpenseSheet(); await refreshBudget(); toast('記録を保存しました');
  });
}

// gesture on the logo
function setupGesture() {
  const el = $('#brandMark');
  let taps = 0, tapTimer = null, pressTimer = null;
  const g = () => store.getSetting('hiddenGesture', 'tap7');
  el.style.userSelect = 'none';
  el.addEventListener('click', () => {
    const m = g(); if (m !== 'tap7' && m !== 'both') return;
    taps++; clearTimeout(tapTimer); tapTimer = setTimeout(() => (taps = 0), 1500);
    if (taps >= 7) { taps = 0; openBudget(); }
  });
  const start = () => { const m = g(); if (m !== 'long' && m !== 'both') return; pressTimer = setTimeout(() => openBudget(), 600); };
  const cancel = () => clearTimeout(pressTimer);
  el.addEventListener('pointerdown', start);
  ['pointerup', 'pointerleave', 'pointercancel'].forEach(ev => el.addEventListener(ev, cancel));
}

// =====================================================================
// Trips (route recording + slideshow)
// =====================================================================
let recTripId = null;
let recStop = null;
let recTimer = null;
let recMode = 'live';
let currentTripId = null;
let tripMapInst = null;
let slideMapInst = null;
let slide = { photos: [], idx: 0, timer: null, playing: false };

function renderTrips() {
  $('#recIdle').classList.toggle('hidden', !!recTripId);
  $('#recActive').classList.toggle('hidden', !recTripId);
  const arr = trips.list();
  const list = $('#tripList');
  $('#tripEmpty').classList.toggle('hidden', arr.length > 0 || !!recTripId);
  list.innerHTML = '';
  arr.forEach(t => list.appendChild(tripCard(t)));
}

function tripCard(t) {
  const card = document.createElement('div');
  card.className = 'trip-card';
  const d = new Date(t.startedAt || t.createdAt);
  const meta = `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ・ ${trips.fmtDistance(t.distance || 0)} ・ 写真${t.photos.length}枚`;
  card.innerHTML = `
    <div class="tc-thumb placeholder">🧳</div>
    <div class="tc-main">
      <div class="tc-name">${esc(t.name)}</div>
      <div class="tc-meta">${meta}</div>
      ${t.status === 'recording' ? '<div class="tc-badge">● 記録中</div>' : ''}
    </div>`;
  card.onclick = () => { if (t.status === 'recording' && t.id === recTripId) toast('記録中です。ゴールで終了してください'); else openTrip(t.id); };
  if (t.photos.length) trips.photoUrl(t.photos[0]).then(url => {
    if (!url) return;
    const img = document.createElement('img'); img.className = 'tc-thumb'; img.src = url;
    const ph = card.querySelector('.tc-thumb'); if (ph) ph.replaceWith(img);
  });
  return card;
}

// ---- recording ----
function startRecording(mode) {
  recMode = mode;
  const t = trips.create('', mode);
  recTripId = t.id;
  $('#recName').textContent = t.name + '（記録中）';
  $('#recPointsUI').classList.toggle('hidden', mode !== 'points');
  renderTrips();
  recClock(true);
  updateRecStats(t);
  if (mode === 'live') {
    recStop = trips.startLive(t.id, (trip) => updateRecStats(trip), (err) => toast(geoErr(err)));
    toast('GPSで記録開始。移動するとルートが記録されます');
  } else {
    toast('スタート／ゴールを指定してください');
  }
}
function updateRecStats(t) {
  if (!t) return;
  $('#recDist').textContent = trips.fmtDistance(t.distance || 0);
  $('#recPts').textContent = t.track.length;
  $('#recPhotos').textContent = t.photos.length;
}
function recClock(on) {
  clearInterval(recTimer); recTimer = null;
  if (!on) return;
  recTimer = setInterval(() => {
    const t = trips.get(recTripId);
    if (t) $('#recTime').textContent = trips.fmtDuration(Date.now() - t.startedAt);
  }, 1000);
}
async function recSetPoint(which) {
  try {
    busy(true);
    const p = await trips.currentPosition();
    if (which === 'start') { trips.setStart(recTripId, p); toast('スタート地点を設定しました'); }
    else { trips.setGoal(recTripId, p); toast('ゴール地点を設定しました'); }
    updateRecStats(trips.get(recTripId));
  } catch (e) { toast(geoErr(e)); }
  finally { busy(false); }
}
async function recAddPhotos(ev) {
  const files = Array.from(ev.target.files || []); ev.target.value = '';
  if (!files.length || !recTripId) return;
  let pos = null;
  const t = trips.get(recTripId);
  if (t && t.track.length) pos = t.track[t.track.length - 1];
  else pos = await trips.currentPosition().catch(() => null);
  await mutate(async () => {
    for (const f of files) await trips.addPhoto(recTripId, f, pos);
    updateRecStats(trips.get(recTripId));
    toast(`写真を${files.length}枚追加しました`);
  });
}
function finishRecording() {
  if (!recTripId) return;
  if (recStop) { recStop(); recStop = null; }
  const t = trips.finish(recTripId);
  recClock(false);
  const id = recTripId; recTripId = null;
  renderTrips();
  toast('記録を終了しました');
  if (t && t.track.length < 1) return;
  openTrip(id);
}
function cancelRecording() {
  if (!recTripId) return;
  if (!confirm('この記録を破棄しますか？')) return;
  if (recStop) { recStop(); recStop = null; }
  trips.remove(recTripId); recTripId = null; recClock(false);
  renderTrips(); toast('破棄しました');
}

// ---- trip detail ----
async function openTrip(id) {
  const t = trips.get(id); if (!t) return;
  currentTripId = id;
  $('#tripTitle').textContent = t.name;
  const dur = t.endedAt ? trips.fmtDuration(t.endedAt - t.startedAt) : '—';
  $('#tripSub').textContent = `${trips.fmtDistance(t.distance || 0)} ・ ${dur}`;
  $('#tripStats').innerHTML = `
    <div class="st"><b>${trips.fmtDistance(t.distance || 0)}</b>距離</div>
    <div class="st"><b>${dur}</b>時間</div>
    <div class="st"><b>${t.photos.length}</b>写真</div>
    <div class="st"><b>${t.track.length}</b>地点</div>`;
  $('#tripScreen').classList.remove('hidden');
  if (tripMapInst) { mapView.disposeMap(tripMapInst); tripMapInst = null; }
  tripMapInst = mapView.makeRouteMap('tripMap', t.track, t.photos);
  await renderTripPhotos(t);
  $('#tripPlay').disabled = t.photos.length === 0;
}
function closeTrip() {
  $('#tripScreen').classList.add('hidden');
  if (tripMapInst) { mapView.disposeMap(tripMapInst); tripMapInst = null; }
  currentTripId = null;
  renderTrips();
}
async function renderTripPhotos(t) {
  const grid = $('#tripPhotoGrid'); grid.innerHTML = '';
  for (const p of t.photos) {
    const url = await trips.photoUrl(p);
    const cell = document.createElement('div');
    cell.className = 'photo-thumb';
    cell.innerHTML = `${url ? `<img src="${url}" alt="" />` : ''}<button class="ph-del">✕</button>`;
    cell.querySelector('.ph-del').onclick = () => {
      if (!confirm('この写真を削除しますか？')) return;
      trips.deletePhoto(t.id, p.id); openTrip(t.id);
    };
    grid.appendChild(cell);
  }
}
async function tripAddPhotos(ev) {
  const files = Array.from(ev.target.files || []); ev.target.value = '';
  if (!files.length || !currentTripId) return;
  await mutate(async () => {
    for (const f of files) await trips.addPhoto(currentTripId, f, null);
    await openTrip(currentTripId);
    toast(`写真を${files.length}枚追加しました`);
  });
}
function deleteTrip() {
  if (!currentTripId) return;
  if (!confirm('この旅の記録を削除しますか？取り消せません。')) return;
  trips.remove(currentTripId); closeTrip(); toast('削除しました');
}

// ---- slideshow ----
async function playSlideshow() {
  const t = trips.get(currentTripId); if (!t || !t.photos.length) { toast('写真がありません'); return; }
  const loaded = [];
  for (const p of t.photos) { const url = await trips.photoUrl(p); if (url) loaded.push({ meta: p, url }); }
  if (!loaded.length) { toast('写真を読み込めませんでした'); return; }
  slide = { photos: loaded, idx: 0, timer: null, playing: true };
  $('#slideshow').classList.remove('hidden');
  if (slideMapInst) { mapView.disposeMap(slideMapInst); slideMapInst = null; }
  slideMapInst = mapView.makeRouteMap('slideMap', t.track, t.photos);
  buildProgress(loaded.length);
  showSlide(0);
  startSlideTimer();
}
function buildProgress(n) {
  const wrap = $('#slideProgress'); wrap.innerHTML = '';
  for (let i = 0; i < n; i++) { const pip = document.createElement('div'); pip.className = 'pip'; wrap.appendChild(pip); }
}
function showSlide(i) {
  slide.idx = i;
  const s = slide.photos[i];
  const img = $('#slideImg');
  img.classList.remove('show');
  setTimeout(() => { img.src = s.url; img.classList.add('show'); }, 60);
  const d = new Date(s.meta.at);
  const time = `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
  $('#slideCaption').textContent = `${i + 1} / ${slide.photos.length}　・　${time}${s.meta.caption ? '　' + s.meta.caption : ''}`;
  $$('#slideProgress .pip').forEach((p, k) => p.classList.toggle('active', k <= i));
  if (slideMapInst && typeof s.meta.lat === 'number') mapView.highlightOnMap(slideMapInst, s.meta.lat, s.meta.lng);
}
function startSlideTimer() {
  stopSlideTimer(); slide.playing = true; $('#slidePlayPause').textContent = '⏸';
  slide.timer = setInterval(() => {
    if (slide.idx + 1 >= slide.photos.length) { stopSlideTimer(); slide.playing = false; $('#slidePlayPause').textContent = '↺'; return; }
    showSlide(slide.idx + 1);
  }, 3000);
}
function stopSlideTimer() { clearInterval(slide.timer); slide.timer = null; }
function toggleSlide() {
  if (slide.playing) { stopSlideTimer(); slide.playing = false; $('#slidePlayPause').textContent = '▶'; }
  else { if (slide.idx + 1 >= slide.photos.length) showSlide(0); startSlideTimer(); }
}
function nextSlide() { stopSlideTimer(); slide.playing = false; $('#slidePlayPause').textContent = '▶'; showSlide(Math.min(slide.idx + 1, slide.photos.length - 1)); }
function prevSlide() { stopSlideTimer(); slide.playing = false; $('#slidePlayPause').textContent = '▶'; showSlide(Math.max(slide.idx - 1, 0)); }
function closeSlideshow() {
  stopSlideTimer();
  $('#slideshow').classList.add('hidden');
  slide.photos.forEach(p => { if (p.url && p.url.startsWith('blob:')) URL.revokeObjectURL(p.url); });
  slide = { photos: [], idx: 0, timer: null, playing: false };
  if (slideMapInst) { mapView.disposeMap(slideMapInst); slideMapInst = null; }
}

function geoErr(e) {
  if (!e) return '位置情報を取得できませんでした';
  if (e.code === 1) return '位置情報の利用が許可されていません（設定から許可してください）';
  if (e.code === 2) return '現在地を取得できませんでした（電波状況をご確認ください）';
  if (e.code === 3) return '位置情報の取得がタイムアウトしました';
  return e.message || '位置情報を取得できませんでした';
}

// =====================================================================
// Settings
// =====================================================================
function openSettings() {
  $('#gestureSelect').value = store.getSetting('hiddenGesture', 'tap7');
  $('#settingsModal').classList.remove('hidden');
}
function closeSettings() { $('#settingsModal').classList.add('hidden'); }

// =====================================================================
// Toast + errors
// =====================================================================
let toastTimer = null;
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.remove('hidden');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add('hidden'), 2400);
}
function errMsg(e) {
  if (!e) return 'エラーが発生しました';
  if (e.code === 'NEED_CLOUD') return 'この機能はログイン（クラウド）が必要です';
  const m = e.message || String(e);
  if (/Invalid login/i.test(m)) return 'メールまたはパスワードが違います';
  if (/already registered/i.test(m)) return 'このメールは登録済みです。ログインしてください';
  if (/Password should be/i.test(m)) return 'パスワードは6文字以上にしてください';
  if (/Email not confirmed/i.test(m)) return 'メール確認が未完了です。確認メールのリンクを開いてください';
  return m;
}

// =====================================================================
// Wiring + boot
// =====================================================================
function wire() {
  $$('.seg').forEach(b => b.onclick = () => switchView(b.dataset.view));
  $('#addBtn').onclick = () => { if (!currentId) { toast('リストを準備中です'); return; } openEditor(null); };
  $('#menuBtn').onclick = openDrawer;
  $('#drawerClose').onclick = closeDrawer;
  $$('[data-close-drawer]').forEach(el => el.onclick = closeDrawer);
  $('#newCollectionBtn').onclick = () => {
    const name = prompt('新しいリストの名前', '新しいリスト');
    if (name && name.trim()) mutate(async () => { const c = await data.createCollection(name.trim()); currentId = c.id; await reload(); await openDrawer(); toast('リストを作成しました'); });
  };
  $('#importBtn').onclick = handleImportFromInput;
  $('#settingsBtn').onclick = openSettings;

  // editor
  $('#f_url').addEventListener('input', updatePlatformBadge);
  $('#searchBtn').onclick = doSearch;
  $('#f_search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); doSearch(); } });
  $('#saveSpotBtn').onclick = saveSpot;
  $('#cancelEditBtn').onclick = closeEditor;
  $('#deleteSpotBtn').onclick = deleteCurrentSpot;
  $$('[data-close-editor]').forEach(el => el.onclick = closeEditor);
  $('#photoInput').addEventListener('change', onPhotoPick);

  const pickBtn = document.createElement('button');
  pickBtn.type = 'button'; pickBtn.className = 'btn ghost small'; pickBtn.style.marginTop = '4px';
  pickBtn.textContent = '🗺 地図で指定'; pickBtn.onclick = pickOnMap;
  $('#locStatus').parentElement.appendChild(pickBtn);

  // share
  $('#shareBtn').onclick = openShare;
  $('#copyShareBtn').onclick = copyShare;
  $$('[data-close-share]').forEach(el => el.onclick = () => $('#shareModal').classList.add('hidden'));

  // auth
  $('#authSubmit').onclick = submitAuth;
  $('#authToggle').onclick = () => { authMode = authMode === 'login' ? 'signup' : 'login'; syncAuthUI(); };
  $$('[data-close-auth]').forEach(el => el.onclick = closeAuth);

  // members
  $('#memberAddBtn').onclick = addMember;
  $('#memberEmail').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addMember(); } });
  $$('[data-close-members]').forEach(el => el.onclick = closeMembers);

  // settings
  $('#gestureSelect').addEventListener('change', (e) => store.setSetting('hiddenGesture', e.target.value));
  $$('[data-close-settings]').forEach(el => el.onclick = closeSettings);

  // budget
  $('#budgetClose').onclick = closeBudget;
  $('#budgetAddBtn').onclick = openExpenseSheet;
  $('#ex_save').onclick = saveExpense;
  $('#ex_receipt').addEventListener('change', onReceiptPick);
  $$('[data-close-expense]').forEach(el => el.onclick = closeExpenseSheet);
  $$('#ex_visibility .vis-chip').forEach(b => b.onclick = () => {
    expenseVisibility = b.dataset.vis;
    $$('#ex_visibility .vis-chip').forEach(x => x.classList.toggle('active', x === b));
  });

  // trips
  $('#recStartLive').onclick = () => startRecording('live');
  $('#recStartPoints').onclick = () => startRecording('points');
  $('#recSetStart').onclick = () => recSetPoint('start');
  $('#recSetGoal').onclick = () => recSetPoint('goal');
  $('#recPhotoInput').addEventListener('change', recAddPhotos);
  $('#recFinish').onclick = finishRecording;
  $('#recCancel').onclick = cancelRecording;
  $('#tripBack').onclick = closeTrip;
  $('#tripDelete').onclick = deleteTrip;
  $('#tripPlay').onclick = playSlideshow;
  $('#tripPhotoInput').addEventListener('change', tripAddPhotos);
  // slideshow
  $('#slideClose').onclick = closeSlideshow;
  $('#slidePlayPause').onclick = toggleSlide;
  $('#slideNext').onclick = nextSlide;
  $('#slidePrev').onclick = prevSlide;

  setupGesture();
  window.addEventListener('hashchange', checkShareOnLoad);
}

async function initAuth() {
  if (!supa.isConfigured()) { mode = 'local'; data.useLocal(); return; }
  try {
    user = await supa.getUser();
    if (user) { mode = 'cloud'; data.useCloud(); } else { mode = 'local'; data.useLocal(); }
  } catch { mode = 'local'; data.useLocal(); }
  supa.onAuthChange(async (u) => {
    const was = mode;
    user = u; mode = u ? 'cloud' : 'local';
    u ? data.useCloud() : data.useLocal();
    currentId = null;
    await reload(); renderAccount();
    if (was !== mode) toast(mode === 'cloud' ? 'ログインしました' : 'ローカルモードに戻りました');
  });
}

async function boot() {
  wire();
  await initAuth();
  renderAccount();
  switchView(currentView);
  await reload();
  checkShareOnLoad();
  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  }
}

boot();
