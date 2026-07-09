// バックグラウンド サービスワーカー。
// 役割: content script からの依頼を受けて localhost の予測サーバーへ通信する
//       「フェッチ橋渡し」。ページ側の CSP(connect-src) に縛られずに localhost へ
//       アクセスできるため、この経路を使う。ブローカーの発注には一切触れない。

const ALLOWED_HOSTS = ["localhost:8765", "127.0.0.1:8765"];
const BASE = "http://localhost:8765";

function isAllowed(url) {
  try {
    const u = new URL(url);
    return u.protocol === "http:" && ALLOWED_HOSTS.includes(u.host);
  } catch (e) {
    return false;
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const path = (msg && msg.path) || "/state";
  const url = BASE + path;
  if (!isAllowed(url)) {
    sendResponse({ ok: false, error: "許可されていない宛先" });
    return true;
  }
  const opts = { method: msg.method || "GET" };
  if (msg.method === "POST") {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(msg.body || {});
  }
  fetch(url, opts)
    .then((r) => r.json())
    .then((data) => sendResponse({ ok: true, data }))
    .catch((err) => sendResponse({ ok: false, error: String(err) }));
  return true; // 非同期レスポンスを保持
});
