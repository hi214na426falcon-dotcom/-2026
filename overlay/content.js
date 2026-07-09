// content script: webterminal の上に「表示専用」の予測パネルを描画する。
// ★ このスクリプトはブローカーの発注ボタン・入力欄には一切触れない（自動売買なし）。
//   ページ側の DOM は読まず、localhost の予測サーバーが返す情報だけを表示する。

(function () {
  "use strict";
  if (window.__binarySignOverlayLoaded) return;
  window.__binarySignOverlayLoaded = true;

  const POLL_MS = 2500;

  // --- パネル生成 -----------------------------------------------------------
  const panel = document.createElement("div");
  panel.id = "bin-sign-overlay";
  panel.innerHTML = `
    <div class="bso-header" id="bso-header">
      <span class="bso-title">サインツール（表示専用）</span>
      <span class="bso-min" id="bso-min" title="最小化">▁</span>
    </div>
    <div class="bso-body" id="bso-body">
      <div class="bso-conn" id="bso-conn">接続待ち…</div>

      <div class="bso-section">
        <div class="bso-label">この時間帯の推奨ペア（JST）</div>
        <div class="bso-pair" id="bso-pair">―</div>
        <div class="bso-winrate" id="bso-winrate"></div>
        <div class="bso-slotmeta" id="bso-slotmeta"></div>
      </div>

      <div class="bso-section">
        <div class="bso-label">予測</div>
        <div class="bso-dir" id="bso-dir">検証済み戦略なし</div>
        <div class="bso-rationale" id="bso-rationale"></div>
      </div>

      <div class="bso-section" id="bso-bonus-wrap">
        <div class="bso-streak" id="bso-streak">連勝: 0</div>
        <div class="bso-bonus" id="bso-bonus"></div>
      </div>

      <div class="bso-section">
        <div class="bso-label">結果を記録（手動）</div>
        <div class="bso-btns">
          <button class="bso-btn bso-win" id="bso-win">勝ち</button>
          <button class="bso-btn bso-loss" id="bso-loss">負け</button>
          <button class="bso-btn bso-reset" id="bso-reset">リセット</button>
        </div>
      </div>

      <div class="bso-foot">発注は必ず手動。自動売買機能はありません。</div>
    </div>
  `;
  document.documentElement.appendChild(panel);

  const $ = (id) => document.getElementById(id);

  // --- 最小化 --------------------------------------------------------------
  $("bso-min").addEventListener("click", (e) => {
    e.stopPropagation();
    panel.classList.toggle("bso-collapsed");
  });

  // --- ドラッグ移動 --------------------------------------------------------
  (function makeDraggable() {
    const header = $("bso-header");
    let dragging = false, ox = 0, oy = 0;
    header.addEventListener("mousedown", (e) => {
      if (e.target.id === "bso-min") return;
      dragging = true;
      const r = panel.getBoundingClientRect();
      ox = e.clientX - r.left;
      oy = e.clientY - r.top;
      e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      panel.style.left = Math.max(0, e.clientX - ox) + "px";
      panel.style.top = Math.max(0, e.clientY - oy) + "px";
      panel.style.right = "auto";
    });
    document.addEventListener("mouseup", () => (dragging = false));
  })();

  // --- サーバー通信（背景SW経由） -----------------------------------------
  function call(path, method, body) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ path, method: method || "GET", body }, (resp) => {
          if (chrome.runtime.lastError || !resp) {
            resolve({ ok: false });
          } else {
            resolve(resp);
          }
        });
      } catch (e) {
        resolve({ ok: false });
      }
    });
  }

  // --- 描画 ----------------------------------------------------------------
  function render(state) {
    const feed = state.feed_status || (state.connected === false ? "オフライン" : "オンライン");
    $("bso-conn").textContent = "接続: " + feed;
    $("bso-conn").className = "bso-conn " + (feed === "オンライン" ? "bso-ok" : "bso-warn");

    const slot = state.current_slot;
    if (slot) {
      $("bso-pair").textContent = slot.recommended_pair || "―";
      const wr = slot.expected_win_rate;
      $("bso-winrate").textContent =
        wr != null ? `想定勝率 ${(wr * 100).toFixed(1)}%（信頼度 ${slot.confidence || "―"}）` : "";
      $("bso-slotmeta").textContent =
        `${slot.window} / サンプル ${slot.sample || 0}件 / ` +
        (slot.go ? "実弾GO可" : "見送り推奨");
      $("bso-slotmeta").className = "bso-slotmeta " + (slot.go ? "bso-ok" : "bso-warn");
      $("bso-rationale").textContent = slot.rationale || "";
    } else {
      $("bso-pair").textContent = "―（対象時間帯外）";
      $("bso-winrate").textContent = "";
      $("bso-slotmeta").textContent = "推奨時間帯（夜17〜24時・深夜0〜6時）外です";
    }

    // 予測（検証済み戦略があるときだけ方向を出す）
    if (state.direction) {
      const up = state.direction === "UP";
      $("bso-dir").textContent = (up ? "▲ 上（High）" : "▼ 下（Low）") +
        (state.confidence != null ? `  ${(state.confidence * 100).toFixed(0)}%` : "");
      $("bso-dir").className = "bso-dir " + (up ? "bso-up" : "bso-down");
    } else {
      $("bso-dir").textContent = state.status || "検証済み戦略なし（方向は非表示）";
      $("bso-dir").className = "bso-dir";
    }

    // 連勝・ボーナスステージ
    const mm = state.money || {};
    $("bso-streak").textContent = `連勝: ${mm.streak || 0}`;
    if (mm.bonus_active) {
      $("bso-bonus").textContent = `🎉 ボーナスステージ（逆マーチン Lv.${mm.bonus_level}）`;
      $("bso-bonus").style.display = "block";
      panel.classList.add("bso-bonus-on");
    } else {
      const need = (mm.bonus_threshold || 3) - (mm.streak || 0);
      $("bso-bonus").textContent = need > 0 ? `あと${need}連勝でボーナス` : "";
      $("bso-bonus").style.display = mm.bonus_active === undefined ? "none" : "block";
      panel.classList.remove("bso-bonus-on");
    }
  }

  async function refresh() {
    const resp = await call("/state", "GET");
    if (resp.ok && resp.data) {
      render(resp.data);
    } else {
      $("bso-conn").textContent = "接続: サーバー未起動（predict_server.py を起動してください）";
      $("bso-conn").className = "bso-conn bso-warn";
    }
  }

  async function report(result) {
    const resp = await call("/result", "POST", { result });
    if (resp.ok && resp.data) render(resp.data);
  }
  async function reset() {
    const resp = await call("/reset", "POST", {});
    if (resp.ok && resp.data) render(resp.data);
  }

  $("bso-win").addEventListener("click", () => report("win"));
  $("bso-loss").addEventListener("click", () => report("loss"));
  $("bso-reset").addEventListener("click", reset);

  refresh();
  setInterval(refresh, POLL_MS);
})();
