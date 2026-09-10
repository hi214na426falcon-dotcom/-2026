'use strict';
// プレビューギャラリー(Artifact)用HTMLを生成。PNGをdata URIで埋め込み自己完結。
const fs = require('fs');
const path = require('path');
const { list, MAIN } = require('./stickers');

const ROOT = path.join(__dirname, '..');
const PNG = path.join(ROOT, 'stickers', 'png');
const b64 = (f) => 'data:image/png;base64,' + fs.readFileSync(path.join(PNG, f)).toString('base64');

const cap = (c) => (Array.isArray(c) ? c.join('') : c);

function cards(char) {
  return list.filter((s) => s.char === char).map((s) => `
      <figure class="card">
        <span class="num ${char}">${String(s.n).padStart(2, '0')}</span>
        <div class="stickerbox"><img src="${b64(s.file + '.png')}" alt="${cap(s.caption)}" loading="lazy"></div>
        <figcaption>${cap(s.caption)}</figcaption>
      </figure>`).join('');
}

// ステージ用（会話例）
const stageStickers = ['otter-04', 'shiba-15', 'otter-11', 'shiba-04'];

const html = `<title>塩対応スタンプ</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@500;700;800&family=Zen+Maru+Gothic:wght@400;500;700&display=swap">
<style>
  :root{
    --bg:#f2ebde;--surface:#fffaf1;--surface-2:#f7f0e3;
    --ink:#3a2a20;--muted:#93826f;--line:#e7dcc9;
    --otter:#8a5c3a;--shiba:#d9982f;--accent:#3f9e63;--accent-ink:#2c7a4a;
    --shadow:0 6px 18px rgba(58,42,32,.10);
    --stage:#a9c8d7;--stage-ink:#2a2f33;--stage-bubble:#ffffff;
  }
  @media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
    --bg:#221a15;--surface:#2e241d;--surface-2:#281f19;
    --ink:#f3e7d6;--muted:#b6a794;--line:#3c3028;
    --otter:#c08a5b;--shiba:#e9ad5c;--accent:#5cc07f;--accent-ink:#84d6a0;
    --shadow:0 8px 22px rgba(0,0,0,.35);
  }}
  :root[data-theme="dark"]{
    --bg:#221a15;--surface:#2e241d;--surface-2:#281f19;
    --ink:#f3e7d6;--muted:#b6a794;--line:#3c3028;
    --otter:#c08a5b;--shiba:#e9ad5c;--accent:#5cc07f;--accent-ink:#84d6a0;
    --shadow:0 8px 22px rgba(0,0,0,.35);
  }
  *{box-sizing:border-box}
  body{background:var(--bg);color:var(--ink);
    font-family:"Zen Maru Gothic","Hiragino Maru Gothic ProN",system-ui,sans-serif;
    line-height:1.6;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1080px;margin:0 auto;padding-block:0;padding-left:20px;padding-right:20px}
  .rounded{font-family:"M PLUS Rounded 1c","Zen Maru Gothic",system-ui,sans-serif}
  .eyebrow{font-family:"M PLUS Rounded 1c",sans-serif;font-weight:700;letter-spacing:.18em;
    text-transform:uppercase;font-size:.72rem;color:var(--accent-ink)}

  /* hero */
  header.hero{display:grid;grid-template-columns:auto 1fr;gap:28px;align-items:center;
    padding-block:40px 28px}
  .hero .badge{width:150px;height:150px;border-radius:26px;background:var(--surface);
    box-shadow:var(--shadow);display:grid;place-items:center;border:1px solid var(--line)}
  .hero .badge img{width:132px;height:132px}
  .hero h1{font-family:"M PLUS Rounded 1c",sans-serif;font-weight:800;margin:.1em 0 .15em;
    font-size:clamp(2rem,5.5vw,3.2rem);line-height:1.05;text-wrap:balance;letter-spacing:.01em}
  .hero p.lead{margin:.2em 0 0;color:var(--muted);max-width:46ch;font-size:1.02rem}
  .facts{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
  .chip{font-family:"M PLUS Rounded 1c",sans-serif;font-weight:700;font-size:.82rem;
    background:var(--surface-2);border:1px solid var(--line);border-radius:999px;padding:6px 13px}
  .chip b{color:var(--accent-ink)}

  /* stage */
  .stage-wrap{margin:8px 0 40px}
  .stage-head{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between;margin-bottom:12px}
  .stage-head h2{font-family:"M PLUS Rounded 1c",sans-serif;font-weight:800;font-size:1.15rem;margin:0}
  .toggle{display:inline-flex;background:var(--surface-2);border:1px solid var(--line);border-radius:999px;padding:4px;gap:2px}
  .toggle button{font-family:"M PLUS Rounded 1c",sans-serif;font-weight:700;font-size:.82rem;cursor:pointer;
    border:0;background:transparent;color:var(--muted);padding:6px 15px;border-radius:999px;line-height:1}
  .toggle button[aria-pressed="true"]{background:var(--accent);color:#fff}
  .toggle button:focus-visible{outline:2px solid var(--accent-ink);outline-offset:2px}
  .stage{border-radius:22px;border:1px solid var(--line);padding:22px;min-height:220px;
    background:var(--stage);transition:background .25s ease;overflow:hidden}
  .chatline{display:flex;gap:10px;align-items:flex-end;margin:0 0 14px}
  .chatline.me{justify-content:flex-end}
  .bubble{background:var(--stage-bubble);color:var(--stage-ink);border-radius:16px;padding:9px 14px;
    max-width:60%;box-shadow:0 1px 2px rgba(0,0,0,.12);font-size:.92rem}
  .stage .sticker{width:132px;height:114px;flex:0 0 auto}
  .stage .sticker img{width:100%;height:100%;object-fit:contain}
  .stage.dark{background:#191a1d}
  .stage.dark .bubble{background:#33363c;color:#eceff2}
  .stage .hint{color:rgba(0,0,0,.55);font-size:.8rem;font-family:"M PLUS Rounded 1c",sans-serif;font-weight:700}
  .stage.dark .hint{color:rgba(255,255,255,.6)}

  /* sections + grid */
  section.set{margin-bottom:40px}
  .set-head{display:flex;align-items:center;gap:12px;margin-bottom:16px;
    padding-bottom:10px;border-bottom:2px solid var(--line)}
  .set-head .dot{width:14px;height:14px;border-radius:50%}
  .set-head .dot.otter{background:var(--otter)}
  .set-head .dot.shiba{background:var(--shiba)}
  .set-head h2{font-family:"M PLUS Rounded 1c",sans-serif;font-weight:800;font-size:1.35rem;margin:0}
  .set-head .count{margin-left:auto;color:var(--muted);font-family:"M PLUS Rounded 1c",sans-serif;font-weight:700;font-size:.85rem}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(148px,1fr));gap:14px}
  .card{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:16px;
    padding:10px 10px 12px;position:relative;box-shadow:var(--shadow)}
  .stickerbox{aspect-ratio:370/320;display:grid;place-items:center;
    background:var(--surface-2);border-radius:11px;overflow:hidden}
  .stickerbox img{width:100%;height:100%;object-fit:contain}
  .card figcaption{margin-top:9px;font-size:.82rem;color:var(--ink);text-align:center;font-weight:500;line-height:1.35}
  .num{position:absolute;top:8px;left:8px;z-index:2;font-family:"M PLUS Rounded 1c",sans-serif;font-weight:800;
    font-size:.7rem;color:#fff;background:var(--otter);border-radius:999px;min-width:26px;height:20px;
    display:inline-grid;place-items:center;padding:0 7px}
  .num.shiba{background:var(--shiba)}

  /* footer */
  footer{border-top:1px solid var(--line);padding-block:26px 44px;color:var(--muted);font-size:.9rem}
  footer h3{font-family:"M PLUS Rounded 1c",sans-serif;font-weight:800;color:var(--ink);font-size:1rem;margin:0 0 8px}
  .spec{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-top:6px}
  .spec div{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
  .spec b{color:var(--ink);font-family:"M PLUS Rounded 1c",sans-serif}
  a{color:var(--accent-ink)}
  @media (max-width:560px){header.hero{grid-template-columns:1fr;text-align:center;justify-items:center}
    .hero p.lead{margin-inline:auto}.facts{justify-content:center}}
  @media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>

<div class="wrap">
  <header class="hero">
    <div class="badge"><img src="${b64('main-240.png')}" alt="メインキャラのカワウソ"></div>
    <div>
      <span class="eyebrow">LINE STICKERS · 32 pcs</span>
      <h1 class="rounded">塩対応スタンプ</h1>
      <p class="lead">カワウソと柴犬が、やる気なく塩対応してくれる毒舌ゆるスタンプ。日常のツッコミ・受け流し・現実逃避に。全32個、申請規格そのままの透過PNG。</p>
      <div class="facts">
        <span class="chip">🦦 カワウソ <b>16</b></span>
        <span class="chip">🐕 柴犬 <b>16</b></span>
        <span class="chip">合計 <b>32個</b>（案A）</span>
        <span class="chip">370×320px 透過PNG</span>
      </div>
    </div>
  </header>

  <div class="stage-wrap">
    <div class="stage-head">
      <h2 class="rounded">トーク画面プレビュー</h2>
      <div class="toggle" role="group" aria-label="チャット背景の切り替え">
        <button id="lt" aria-pressed="true">ライト背景</button>
        <button id="dk" aria-pressed="false">ダーク背景</button>
      </div>
    </div>
    <div class="stage" id="stage">
      <div class="chatline"><div class="bubble">レポートまだ？そろそろ締切だけど</div></div>
      <div class="chatline me"><div class="sticker"><img src="${b64(stageStickers[0] + '.png')}" alt="知らんけど"></div></div>
      <div class="chatline"><div class="bubble">今日みんなで残業だって！</div></div>
      <div class="chatline me"><div class="sticker"><img src="${b64(stageStickers[1] + '.png')}" alt="無理です（真顔）"></div></div>
      <p class="hint">白フチ入りなので、ライト／ダークどちらのトーク背景でも文字が読めます。</p>
    </div>
  </div>

  <section class="set">
    <div class="set-head"><span class="dot otter"></span><h2 class="rounded">カワウソ</h2><span class="count">16 stickers</span></div>
    <div class="grid">${cards('otter')}</div>
  </section>

  <section class="set">
    <div class="set-head"><span class="dot shiba"></span><h2 class="rounded">柴犬</h2><span class="count">16 stickers</span></div>
    <div class="grid">${cards('shiba')}</div>
  </section>

  <footer>
    <h3 class="rounded">申請メモ</h3>
    <div class="spec">
      <div><b>スタンプ本体</b><br>370×320px・透過PNG・各35KB前後</div>
      <div><b>メイン画像</b><br>240×240px</div>
      <div><b>タブ画像</b><br>96×74px</div>
      <div><b>フォント</b><br>M PLUS Rounded 1c / 白フチ7px</div>
    </div>
    <p style="margin-top:16px">個数は 8 / 16 / 24 / 32 / 40 のいずれか。本セットは <b>32個</b>（各キャラ16種）です。文字なし版・SVGソースも同梱。</p>
  </footer>
</div>

<script>
  (function(){
    var stage=document.getElementById('stage'),lt=document.getElementById('lt'),dk=document.getElementById('dk');
    function set(dark){stage.classList.toggle('dark',dark);
      lt.setAttribute('aria-pressed',String(!dark));dk.setAttribute('aria-pressed',String(dark));}
    lt.addEventListener('click',function(){set(false);});
    dk.addEventListener('click',function(){set(true);});
  })();
</script>`;

const outDir = path.join('/tmp/claude-0/-home-user--2026/6b6f2a40-4856-5c9b-a5b7-c220c53b62be/scratchpad');
fs.mkdirSync(outDir, { recursive: true });
const outPath = path.join(outDir, 'gallery.html');
fs.writeFileSync(outPath, html);
console.log('wrote', outPath, (Buffer.byteLength(html) / 1024 / 1024).toFixed(2), 'MB');
