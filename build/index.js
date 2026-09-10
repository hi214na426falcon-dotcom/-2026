'use strict';
const fs = require('fs');
const path = require('path');
const { sticker, portrait } = require('./characters');
const { list, MAIN, TAB } = require('./stickers');
const { renderAll } = require('./render');

const ROOT = path.join(__dirname, '..');
const SVGDIR = path.join(ROOT, 'stickers', 'svg');
const PNGDIR = path.join(ROOT, 'stickers', 'png');
const NOTEXTDIR = path.join(ROOT, 'stickers', 'png-notext');
fs.mkdirSync(SVGDIR, { recursive: true });
fs.mkdirSync(PNGDIR, { recursive: true });
fs.mkdirSync(NOTEXTDIR, { recursive: true });

const items = [];

// 32 個のスタンプ本体（370x320）: 文字入り（完成版）＋ 文字なし（Canva編集用）
for (const s of list) {
  const svg = sticker(s);
  fs.writeFileSync(path.join(SVGDIR, s.file + '.svg'), svg);
  items.push({ svg, out: path.join(PNGDIR, s.file + '.png') });
  const svgNoText = sticker(Object.assign({}, s, { caption: null }));
  items.push({ svg: svgNoText, out: path.join(NOTEXTDIR, s.file + '.png') });
}

// メイン画像 240x240（テキストなし）
{
  const svg = portrait(MAIN, 240, 240, [72, 26, 226, 226]);
  fs.writeFileSync(path.join(SVGDIR, 'main-240.svg'), svg);
  items.push({ svg, out: path.join(PNGDIR, 'main-240.png') });
}

// トークルームタブ 96x74（顔アップ・テキストなし）
{
  const svg = portrait(TAB, 96, 74, [110, 40, 150, 116]);
  fs.writeFileSync(path.join(SVGDIR, 'tab-96x74.svg'), svg);
  items.push({ svg, out: path.join(PNGDIR, 'tab-96x74.png') });
}

// レビュー用コンタクトシート（全32枚を1枚に）
function contactSheet() {
  const cells = list.map((s) => {
    const label = (Array.isArray(s.caption) ? s.caption.join('') : s.caption);
    return `<div class="cell"><div class="no">${s.char === 'otter' ? '🦦' : '🐕'} ${String(s.n).padStart(2, '0')}</div>${sticker(s)}</div>`;
  }).join('');
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    body{margin:0;background:#dfe4ea;font-family:'Rounded Mplus 1c',sans-serif}
    .grid{display:grid;grid-template-columns:repeat(8,1fr);gap:6px;padding:10px}
    .cell{background:#fff;border-radius:10px;position:relative;overflow:hidden}
    .cell svg{width:100%;height:auto;display:block}
    .no{position:absolute;top:3px;left:6px;font-size:12px;color:#555;font-weight:700}
  </style></head><body><div class="grid">${cells}</div></body></html>`;
}
fs.writeFileSync(path.join(__dirname, 'contactsheet.html'), contactSheet());

renderAll(items).then(async () => {
  // コンタクトシートを別途フルページで撮影
  const { chromium } = require('playwright');
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1520, height: 900 }, deviceScaleFactor: 1 });
  await p.goto('file://' + path.join(__dirname, 'contactsheet.html'));
  await p.evaluate(() => document.fonts.ready);
  await p.screenshot({ path: path.join(PNGDIR, '_contactsheet.png'), fullPage: true });
  await b.close();
  console.log('contact sheet done');
});
