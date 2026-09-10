'use strict';
// LINEスタンプ用キャラクター描画エンジン（カワウソ／柴犬）
// 純粋なSVG（flat vector）で、表情・腕ポーズ・小物を差し替えて32種を生成する。

const OUT = '#4a3526';      // 主線
const OUTW = 6;             // 主線の太さ
const EYE = '#3b2a20';      // 目
const BLUSH = '#f2a07f';    // ほお

const PAL = {
  otter: { fur: '#a06e49', furD: '#8a5c3a', cream: '#f6e7d3', earIn: '#7d5236' },
  shiba: { fur: '#e4a24d', furD: '#d18f3c', cream: '#fbf3e6', earIn: '#f0d3ad' },
};

// ---- 汎用パーツ ------------------------------------------------------------
const g = (inner, attr = '') => `<g ${attr}>${inner}</g>`;

// 手足（太いカプセル）: 主線→毛→肉球先端
function limb(x1, y1, x2, y2, fur, w = 15) {
  return `<path d="M${x1} ${y1} L${x2} ${y2}" fill="none" stroke="${OUT}" stroke-width="${w + 5}" stroke-linecap="round"/>`
       + `<path d="M${x1} ${y1} L${x2} ${y2}" fill="none" stroke="${fur}" stroke-width="${w}" stroke-linecap="round"/>`;
}
function paw(x, y, fur, r = 12) {
  return `<circle cx="${x}" cy="${y}" r="${r}" fill="${fur}" stroke="${OUT}" stroke-width="${OUTW}"/>`;
}
// 完全な腕 = 手足＋肉球
function arm(x1, y1, x2, y2, fur, w = 15, pr = 12) {
  return limb(x1, y1, x2, y2, fur, w) + paw(x2, y2, fur, pr);
}

// ---- 顔（表情） ------------------------------------------------------------
// 目の基準
const EL = 163, ER = 207, EY = 96;   // 目中心
const NOSEY = 120;                    // 鼻

function eyesOpen(hl = true) {
  const eye = (cx) =>
    `<ellipse cx="${cx}" cy="${EY}" rx="12.5" ry="15.5" fill="${EYE}"/>`
    + (hl ? `<circle cx="${cx - 4}" cy="${EY - 5}" r="4" fill="#fff"/><circle cx="${cx + 4}" cy="${EY + 4}" r="2" fill="#fff" opacity="0.8"/>` : '');
  return eye(EL) + eye(ER);
}
function eyesWide() {
  const eye = (cx) =>
    `<ellipse cx="${cx}" cy="${EY}" rx="14" ry="18" fill="#fff" stroke="${OUT}" stroke-width="3"/>`
    + `<circle cx="${cx}" cy="${EY + 2}" r="8.5" fill="${EYE}"/><circle cx="${cx - 3}" cy="${EY - 2}" r="3" fill="#fff"/>`;
  return eye(EL) + eye(ER);
}
function eyesHalf() {
  const eye = (cx) =>
    `<path d="M${cx - 13} ${EY - 2} Q${cx} ${EY - 8} ${cx + 13} ${EY - 2}" fill="none" stroke="${OUT}" stroke-width="4.5" stroke-linecap="round"/>`
    + `<ellipse cx="${cx}" cy="${EY + 4}" rx="11" ry="9" fill="${EYE}"/>`;
  return eye(EL) + eye(ER);
}
function eyesDead() { // 無感情のフラットな点
  const eye = (cx) => `<ellipse cx="${cx}" cy="${EY + 2}" rx="9" ry="10" fill="${EYE}"/>`;
  return eye(EL) + eye(ER);
}
function eyesClosedHappy() { // ^ ^
  const eye = (cx) => `<path d="M${cx - 12} ${EY + 4} Q${cx} ${EY - 12} ${cx + 12} ${EY + 4}" fill="none" stroke="${OUT}" stroke-width="5" stroke-linecap="round"/>`;
  return eye(EL) + eye(ER);
}
function eyesClosedCalm() { // ‿ ‿ 穏やか
  const eye = (cx) => `<path d="M${cx - 11} ${EY} Q${cx} ${EY + 11} ${cx + 11} ${EY}" fill="none" stroke="${OUT}" stroke-width="5" stroke-linecap="round"/>`;
  return eye(EL) + eye(ER);
}
function eyesSide(dir = 1) { // 目を横に流す
  const eye = (cx) =>
    `<ellipse cx="${cx}" cy="${EY}" rx="12.5" ry="15.5" fill="#fff" stroke="${OUT}" stroke-width="3"/>`
    + `<circle cx="${cx + dir * 5}" cy="${EY + 2}" r="7.5" fill="${EYE}"/>`;
  return eye(EL) + eye(ER);
}
function eyesAngry() { // つり目
  const eye = (cx, s) =>
    `<path d="M${cx - 13} ${EY - 9} L${cx + 12} ${EY - 3}" fill="none" stroke="${OUT}" stroke-width="4.5" stroke-linecap="round" transform="scale(${s},1)" transform-origin="${cx} ${EY}"/>`
    + `<ellipse cx="${cx}" cy="${EY + 2}" rx="10" ry="12" fill="${EYE}"/>`;
  // mirror for right
  return `<ellipse cx="${EL}" cy="${EY + 2}" rx="10" ry="12" fill="${EYE}"/>`
    + `<ellipse cx="${ER}" cy="${EY + 2}" rx="10" ry="12" fill="${EYE}"/>`
    + `<path d="M${EL - 14} ${EY - 10} L${EL + 11} ${EY - 3}" fill="none" stroke="${OUT}" stroke-width="4.5" stroke-linecap="round"/>`
    + `<path d="M${ER + 14} ${EY - 10} L${ER - 11} ${EY - 3}" fill="none" stroke="${OUT}" stroke-width="4.5" stroke-linecap="round"/>`;
}
function eyesTeary() { // うるうる下がり目
  const eye = (cx) =>
    `<ellipse cx="${cx}" cy="${EY + 2}" rx="12" ry="15" fill="#fff" stroke="${OUT}" stroke-width="3"/>`
    + `<circle cx="${cx}" cy="${EY + 5}" r="8.5" fill="${EYE}"/><circle cx="${cx - 3}" cy="${EY}" r="3.5" fill="#fff"/>`
    + `<ellipse cx="${cx + 11}" cy="${EY + 15}" rx="4" ry="6" fill="#8fd0ff" stroke="${OUT}" stroke-width="1.5"/>`;
  return eye(EL) + eye(ER);
}
function eyesSparkle() { // キラキラ
  const eye = (cx) =>
    `<ellipse cx="${cx}" cy="${EY}" rx="13" ry="16" fill="${EYE}"/>`
    + `<circle cx="${cx - 4}" cy="${EY - 5}" r="5" fill="#fff"/><circle cx="${cx + 5}" cy="${EY + 5}" r="3" fill="#fff"/>`;
  const star = (x, y) => `<path d="M${x} ${y - 6} L${x + 1.6} ${y - 1.6} L${x + 6} ${y} L${x + 1.6} ${y + 1.6} L${x} ${y + 6} L${x - 1.6} ${y + 1.6} L${x - 6} ${y} L${x - 1.6} ${y - 1.6} Z" fill="#ffd94a"/>`;
  return eye(EL) + eye(ER) + star(EL - 20, EY - 14) + star(ER + 20, EY - 12);
}
function eyeWink() { // 右ウインク
  return `<ellipse cx="${EL}" cy="${EY}" rx="12.5" ry="15.5" fill="${EYE}"/><circle cx="${EL - 4}" cy="${EY - 5}" r="4" fill="#fff"/>`
    + `<path d="M${ER - 12} ${EY + 3} Q${ER} ${EY - 11} ${ER + 12} ${EY + 3}" fill="none" stroke="${OUT}" stroke-width="5" stroke-linecap="round"/>`;
}

// 眉
function browRaise() { return `<path d="M${ER - 12} ${EY - 22} Q${ER} ${EY - 28} ${ER + 12} ${EY - 22}" fill="none" stroke="${OUT}" stroke-width="4" stroke-linecap="round"/>`; }
function browsWorry() {
  return `<path d="M${EL - 12} ${EY - 20} L${EL + 10} ${EY - 24}" stroke="${OUT}" stroke-width="4" stroke-linecap="round"/>`
    + `<path d="M${ER + 12} ${EY - 20} L${ER - 10} ${EY - 24}" stroke="${OUT}" stroke-width="4" stroke-linecap="round"/>`;
}

// 口
function mouth(name) {
  const cx = 185, y = NOSEY + 12;
  switch (name) {
    case 'smsmile': return `<path d="M${cx - 9} ${y} Q${cx} ${y + 7} ${cx + 9} ${y}" fill="none" stroke="${OUT}" stroke-width="4" stroke-linecap="round"/>`;
    case 'flat': return `<path d="M${cx - 9} ${y + 2} L${cx + 9} ${y + 2}" stroke="${OUT}" stroke-width="4" stroke-linecap="round"/>`;
    case 'frown': return `<path d="M${cx - 9} ${y + 5} Q${cx} ${y - 3} ${cx + 9} ${y + 5}" fill="none" stroke="${OUT}" stroke-width="4" stroke-linecap="round"/>`;
    case 'open': return `<path d="M${cx - 12} ${y - 2} Q${cx} ${y + 16} ${cx + 12} ${y - 2} Q${cx} ${y + 4} ${cx - 12} ${y - 2} Z" fill="#7a3b32" stroke="${OUT}" stroke-width="3.5"/>`;
    case 'bigopen': return `<path d="M${cx - 15} ${y - 3} Q${cx} ${y + 24} ${cx + 15} ${y - 3} Q${cx} ${y + 6} ${cx - 15} ${y - 3} Z" fill="#7a3b32" stroke="${OUT}" stroke-width="3.5"/>`
      + `<path d="M${cx - 9} ${y + 9} Q${cx} ${y + 18} ${cx + 9} ${y + 9} Z" fill="#f2907f"/>`; // tongue
    case 'o': return `<ellipse cx="${cx}" cy="${y + 3}" rx="6" ry="8" fill="#7a3b32" stroke="${OUT}" stroke-width="3.5"/>`;
    case 'squiggle': return `<path d="M${cx - 11} ${y} q4 -6 7 0 q3 6 7 0 q3 -5 6 0" fill="none" stroke="${OUT}" stroke-width="3.5" stroke-linecap="round"/>`;
    case 'smirk': return `<path d="M${cx - 10} ${y} Q${cx - 2} ${y + 6} ${cx + 12} ${y - 4}" fill="none" stroke="${OUT}" stroke-width="4" stroke-linecap="round"/>`;
    case 'tongue': return `<path d="M${cx - 10} ${y - 1} Q${cx} ${y + 5} ${cx + 10} ${y - 1}" fill="none" stroke="${OUT}" stroke-width="4" stroke-linecap="round"/>`
      + `<path d="M${cx - 2} ${y + 1} q-3 12 5 12 q7 0 4 -11 Z" fill="#f2907f" stroke="${OUT}" stroke-width="3"/>`;
    case 'worry': return `<ellipse cx="${cx}" cy="${y + 4}" rx="7" ry="9" fill="#7a3b32" stroke="${OUT}" stroke-width="3.5"/>`;
    case 'grin': return `<path d="M${cx - 13} ${y - 2} Q${cx} ${y + 14} ${cx + 13} ${y - 2} Z" fill="#7a3b32" stroke="${OUT}" stroke-width="3.5"/>`;
    default: return '';
  }
}

// 小物・エフェクト
function sweat(x = 232, y = 72) { return `<path d="M${x} ${y} q-7 10 0 15 q7 -5 0 -15 Z" fill="#8fd0ff" stroke="${OUT}" stroke-width="2"/>`; }
function qmarks() { return `<text x="252" y="70" font-family="'Rounded Mplus 1c'" font-size="34" font-weight="700" fill="${OUT}">?</text><text x="278" y="52" font-family="'Rounded Mplus 1c'" font-size="24" font-weight="700" fill="${OUT}">?</text>`; }
function tearsLaugh() {
  return `<path d="M143 100 q-10 8 -3 16" fill="none" stroke="#8fd0ff" stroke-width="4" stroke-linecap="round"/>`
    + `<path d="M227 100 q10 8 3 16" fill="none" stroke="#8fd0ff" stroke-width="4" stroke-linecap="round"/>`;
}
function blush() { return `<ellipse cx="143" cy="118" rx="11" ry="7" fill="${BLUSH}" opacity="0.85"/><ellipse cx="227" cy="118" rx="11" ry="7" fill="${BLUSH}" opacity="0.85"/>`; }

const FACES = {
  calm:      () => eyesHalf() + mouth('smsmile'),
  bored:     () => eyesHalf() + mouth('flat'),
  skeptical: () => eyesOpen() + browRaise() + mouth('frown'),
  away:      () => eyesSide(1) + mouth('flat'),
  smug:      () => eyesHalf() + browRaise() + mouth('smirk'),
  deadpan:   () => eyesDead() + mouth('flat'),
  greedy:    () => eyesSparkle() + mouth('grin'),
  clueless:  () => eyesWide() + mouth('o') + qmarks(),
  laugh:     () => eyesClosedHappy() + mouth('bigopen') + tearsLaugh(),
  amused:    () => eyesClosedHappy() + mouth('open'),
  awkward:   () => eyesSide(-1) + sweat() + mouth('squiggle'),
  whiny:     () => eyesTeary() + browsWorry() + mouth('frown'),
  hopeful:   () => eyesSparkle() + blush() + mouth('open'),
  cheer:     () => eyesOpen() + mouth('bigopen'),
  monotone:  () => eyesDead() + mouth('smirk'),
  refuse:    () => eyesAngry() + mouth('frown'),
  silly:     () => eyesClosedHappy() + mouth('tongue'),
  smirk:     () => eyesHalf() + mouth('smirk'),
  distressed:() => eyesOpen() + browsWorry() + sweat() + mouth('worry'),
  relaxed:   () => eyesClosedCalm() + mouth('smsmile'),
  shocked:   () => eyesWide() + mouth('o'),
  wink:      () => eyeWink() + blush() + mouth('smirk'),
  content:   () => eyesClosedCalm() + blush() + mouth('smsmile'),
};

// ---- 腕ポーズ --------------------------------------------------------------
// 肩の付け根
const LS = [148, 184], RS = [222, 184];
function ARMS(name, fur) {
  const L = LS, R = RS;
  switch (name) {
    case 'rest': return arm(L[0], L[1], 140, 222, fur) + arm(R[0], R[1], 230, 222, fur);
    case 'limp': return arm(L[0], L[1], 138, 230, fur) + arm(R[0], R[1], 232, 230, fur);
    case 'outPalms': return arm(L[0], L[1], 108, 205, fur) + arm(R[0], R[1], 262, 205, fur);
    case 'shrug': return arm(L[0], L[1], 112, 170, fur) + arm(R[0], R[1], 258, 170, fur);
    case 'pointSelf': return arm(R[0], R[1], 232, 224, fur) + arm(L[0], L[1], 176, 205, fur, 15, 10);
    case 'pointFwd': return arm(L[0], L[1], 138, 224, fur) + arm(R[0], R[1], 268, 158, fur, 15, 10);
    case 'busy': return arm(L[0], L[1], 132, 214, fur) /*phone hand*/ + arm(R[0], R[1], 258, 150, fur);
    case 'apology': return arm(L[0], L[1], 178, 214, fur) + arm(R[0], R[1], 192, 214, fur);
    case 'clap': return arm(L[0], L[1], 176, 196, fur) + arm(R[0], R[1], 194, 196, fur);
    case 'cheek': return arm(L[0], L[1], 140, 222, fur) + limb(R[0], R[1], 214, 132, fur) + paw(214, 132, fur, 13);
    case 'greedy': return arm(L[0], L[1], 250, 206, fur) + arm(R[0], R[1], 250, 176, fur, 15, 10);
    case 'onHead': return arm(L[0], L[1], 140, 222, fur) + limb(R[0], R[1], 210, 52, fur) + paw(210, 52, fur, 13);
    case 'patHead': return arm(L[0], L[1], 140, 222, fur) + limb(R[0], R[1], 196, 46, fur) + paw(196, 46, fur, 13);
    case 'laughHold': return limb(L[0], L[1], 160, 128, fur) + paw(160, 128, fur, 12) + arm(R[0], R[1], 228, 214, fur);
    case 'coverMouth': return arm(L[0], L[1], 138, 220, fur) + limb(R[0], R[1], 190, 132, fur) + paw(190, 132, fur, 14);
    case 'clasp': return limb(L[0], L[1], 176, 138, fur) + limb(R[0], R[1], 194, 138, fur) + paw(185, 132, fur, 15);
    case 'upCheer': return arm(L[0], L[1], 138, 222, fur) + limb(R[0], R[1], 250, 70, fur) + paw(250, 70, fur, 13);
    case 'wave': return arm(L[0], L[1], 140, 222, fur) + limb(R[0], R[1], 258, 150, fur) + paw(258, 150, fur, 12);
    case 'crossX': return limb(L[0], L[1], 210, 210, fur) + limb(R[0], R[1], 160, 210, fur) + paw(210, 210, fur, 12) + paw(160, 210, fur, 12);
    case 'coverEars': return limb(L[0] - 4, L[1] - 6, 128, 92, fur) + paw(128, 92, fur, 15) + limb(R[0] + 4, R[1] - 6, 242, 92, fur) + paw(242, 92, fur, 15);
    case 'objection': return arm(L[0], L[1], 138, 224, fur) + limb(R[0], R[1], 250, 96, fur) + paw(250, 96, fur, 12);
    case 'lazy': return limb(L[0], L[1], 250, 120, fur) + paw(250, 120, fur, 12) + arm(R[0], R[1], 240, 214, fur);
    case 'coin': return limb(L[0], L[1], 172, 176, fur) + limb(R[0], R[1], 198, 176, fur);
    case 'palmStop': return arm(L[0], L[1], 138, 224, fur) + limb(R[0], R[1], 210, 120, fur) + paw(210, 120, fur, 16);
    case 'cupEar': return arm(L[0], L[1], 140, 222, fur) + limb(R[0], R[1], 238, 78, fur) + paw(238, 78, fur, 13);
    case 'phone2': return limb(L[0], L[1], 172, 172, fur) + limb(R[0], R[1], 198, 172, fur);
    case 'okhand': return arm(L[0], L[1], 138, 222, fur) + limb(R[0], R[1], 256, 176, fur) + paw(256, 176, fur, 13);
    default: return arm(L[0], L[1], 140, 222, fur) + arm(R[0], R[1], 230, 222, fur);
  }
}

// ---- 小物（前面） ----------------------------------------------------------
function PROP(name) {
  switch (name) {
    case 'phone': return `<g transform="rotate(-12 132 210)"><rect x="118" y="188" width="30" height="46" rx="6" fill="#3a3f4a" stroke="${OUT}" stroke-width="4"/><rect x="122" y="194" width="22" height="30" rx="2" fill="#bfe3ff"/></g>`;
    case 'phone2': return `<rect x="168" y="150" width="34" height="52" rx="7" fill="#3a3f4a" stroke="${OUT}" stroke-width="4"/><rect x="173" y="157" width="24" height="34" rx="2" fill="#bfe3ff"/>`;
    case 'coin': return `<circle cx="185" cy="172" r="16" fill="#ffd24a" stroke="${OUT}" stroke-width="4"/><text x="185" y="180" text-anchor="middle" font-family="'Rounded Mplus 1c'" font-size="18" font-weight="700" fill="${OUT}">¥</text>`;
    default: return '';
  }
}

// ---- キャラ本体 ------------------------------------------------------------
function otterBody(faceKey, armsKey, prop, propBehind) {
  const p = PAL.otter;
  const tail = `<path d="M206 232 Q262 236 266 268 Q266 286 250 280 Q256 266 234 256 Q214 248 206 232 Z" fill="${p.furD}" stroke="${OUT}" stroke-width="${OUTW}" stroke-linejoin="round"/>`;
  const feet = paw(166, 246, p.fur, 15) + paw(204, 246, p.fur, 15);
  const body = `<ellipse cx="185" cy="200" rx="54" ry="52" fill="${p.fur}" stroke="${OUT}" stroke-width="${OUTW}"/>`
    + `<ellipse cx="185" cy="208" rx="34" ry="38" fill="${p.cream}"/>`;
  const ears = `<circle cx="139" cy="58" r="17" fill="${p.fur}" stroke="${OUT}" stroke-width="${OUTW}"/><circle cx="231" cy="58" r="17" fill="${p.fur}" stroke="${OUT}" stroke-width="${OUTW}"/>`
    + `<circle cx="139" cy="58" r="7" fill="${p.earIn}"/><circle cx="231" cy="58" r="7" fill="${p.earIn}"/>`;
  const head = `<ellipse cx="185" cy="95" rx="62" ry="58" fill="${p.fur}" stroke="${OUT}" stroke-width="${OUTW}"/>`
    + `<ellipse cx="185" cy="118" rx="42" ry="34" fill="${p.cream}"/>`; // muzzle patch
  const nose = `<ellipse cx="185" cy="112" rx="9" ry="6.5" fill="${OUT}"/>`
    + `<path d="M185 118 v6" stroke="${OUT}" stroke-width="3" stroke-linecap="round"/>`;
  const whisk = `<circle cx="150" cy="126" r="1.8" fill="${OUT}"/><circle cx="158" cy="132" r="1.8" fill="${OUT}"/><circle cx="220" cy="126" r="1.8" fill="${OUT}"/><circle cx="212" cy="132" r="1.8" fill="${OUT}"/>`;
  const face = FACES[faceKey]();
  const arms = ARMS(armsKey, p.fur);
  return [
    tail,
    (propBehind && prop ? PROP(prop) : ''),
    feet,
    body,
    ears, head, nose, whisk,
    face,
    arms,
    (!propBehind && prop ? PROP(prop) : ''),
  ].join('');
}

function shibaBody(faceKey, armsKey, prop, propBehind) {
  const p = PAL.shiba;
  const tail = `<path d="M230 232 q50 -20 40 -58 q-4 -16 -20 -8 q12 6 6 22 q-6 20 -34 30 Z" fill="${p.fur}" stroke="${OUT}" stroke-width="${OUTW}"/>`;
  const feet = paw(166, 246, p.cream, 15) + paw(204, 246, p.cream, 15);
  const body = `<ellipse cx="185" cy="200" rx="54" ry="52" fill="${p.fur}" stroke="${OUT}" stroke-width="${OUTW}"/>`
    + `<path d="M185 156 q30 6 30 44 q0 34 -30 44 q-30 -10 -30 -44 q0 -38 30 -44 Z" fill="${p.cream}"/>`; // chest/belly urajiro
  // 尖った三角耳
  const ears = `<path d="M120 78 L128 22 L166 62 Z" fill="${p.fur}" stroke="${OUT}" stroke-width="${OUTW}" stroke-linejoin="round"/>`
    + `<path d="M250 78 L242 22 L204 62 Z" fill="${p.fur}" stroke="${OUT}" stroke-width="${OUTW}" stroke-linejoin="round"/>`
    + `<path d="M131 66 L134 38 L153 60 Z" fill="${p.earIn}"/><path d="M239 66 L236 38 L217 60 Z" fill="${p.earIn}"/>`;
  const head = `<ellipse cx="185" cy="95" rx="62" ry="58" fill="${p.fur}" stroke="${OUT}" stroke-width="${OUTW}"/>`
    + `<path d="M185 74 q34 4 34 40 q0 30 -34 36 q-34 -6 -34 -36 q0 -36 34 -40 Z" fill="${p.cream}"/>` // urajiro muzzle
    + `<ellipse cx="152" cy="104" rx="13" ry="10" fill="${p.cream}"/><ellipse cx="218" cy="104" rx="13" ry="10" fill="${p.cream}"/>`; // cheeks
  const nose = `<ellipse cx="185" cy="110" rx="8.5" ry="6" fill="${OUT}"/>`
    + `<path d="M185 116 v6" stroke="${OUT}" stroke-width="3" stroke-linecap="round"/>`;
  const face = FACES[faceKey]();
  const arms = ARMS(armsKey, p.fur);
  return [
    tail,
    (propBehind && prop ? PROP(prop) : ''),
    feet,
    body,
    ears, head, nose,
    face,
    arms,
    (!propBehind && prop ? PROP(prop) : ''),
  ].join('');
}

// ---- テキスト --------------------------------------------------------------
function captionSVG(caption, opt = {}) {
  const lines = Array.isArray(caption) ? caption : [caption];
  const maxLen = Math.max(...lines.map((s) => s.length));
  let fs = opt.fs || (maxLen <= 5 ? 34 : maxLen <= 7 ? 30 : maxLen <= 9 ? 26 : maxLen <= 11 ? 23 : 21);
  const lh = fs + 6;
  const startY = 300 - (lines.length - 1) * lh;
  return lines.map((s, i) =>
    `<text x="185" y="${startY + i * lh}" text-anchor="middle" font-family="'Rounded Mplus 1c','IPAGothic',sans-serif" font-weight="700" font-size="${fs}" fill="#3a2a20" stroke="#ffffff" stroke-width="7" stroke-linejoin="round" paint-order="stroke fill">${escapeXml(s)}</text>`
  ).join('');
}
function escapeXml(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

// ---- 組み立て --------------------------------------------------------------
function buildInner(char, o) {
  return char === 'otter'
    ? otterBody(o.face, o.arms, o.prop, o.propBehind)
    : shibaBody(o.face, o.arms, o.prop, o.propBehind);
}

function sticker(o) {
  const inner = buildInner(o.char, o);
  const text = o.caption ? captionSVG(o.caption, o) : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 370 320" width="370" height="320">${inner}${text}</svg>`;
}

// メイン画像 240x240 / タブ 96x74 用（テキストなし・キャラのみを再フレーム）
function portrait(o, w, h, box) {
  const inner = buildInner(o.char, o);
  // box = [x,y,vw,vh] 元キャンバスの切り出し範囲
  const [x, y, vw, vh] = box;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${x} ${y} ${vw} ${vh}" width="${w}" height="${h}">${inner}</svg>`;
}

module.exports = { sticker, portrait, PAL };
