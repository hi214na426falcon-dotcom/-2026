'use strict';
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

async function renderAll(items) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  for (const it of items) {
    const html = `<!doctype html><html><head><meta charset="utf-8"><style>*{margin:0;padding:0}html,body{background:transparent}</style></head><body>${it.svg}</body></html>`;
    await page.setContent(html, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    const el = await page.$('svg');
    await el.screenshot({ path: it.out, omitBackground: true });
    process.stdout.write('.');
  }
  await browser.close();
  console.log('\nrendered', items.length, 'images');
}

module.exports = { renderAll };

// CLI: node render.js test
if (require.main === module && process.argv[2] === 'test') {
  const { sticker } = require('./characters');
  const OUT = path.join(__dirname, '..', 'stickers', 'png');
  fs.mkdirSync(OUT, { recursive: true });
  const items = [
    { svg: sticker({ char: 'otter', face: 'calm', arms: 'rest', caption: 'カワウソ ベース' }), out: path.join(OUT, '_test_otter.png') },
    { svg: sticker({ char: 'shiba', face: 'calm', arms: 'rest', caption: '柴犬 ベース' }), out: path.join(OUT, '_test_shiba.png') },
    { svg: sticker({ char: 'otter', face: 'laugh', arms: 'laughHold', caption: '草生える' }), out: path.join(OUT, '_test_laugh.png') },
    { svg: sticker({ char: 'shiba', face: 'smirk', arms: 'pointFwd', caption: ['それ、あなたの', '感想ですよね'] }), out: path.join(OUT, '_test_smirk.png') },
  ];
  renderAll(items);
}
