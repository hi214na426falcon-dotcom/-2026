// content script: webterminal の上に「表示専用」の予測パネルを描画する。
// ★ このスクリプトはブローカーの発注ボタン・入力欄には一切触れない（自動売買なし）。
//   ページ側の DOM は読まず、localhost の予測サーバーが返す情報だけを表示する。

(function () {
  "use strict";
  if (window.__binarySignOverlayLoaded) return;
  window.__binarySignOverlayLoaded = true;

  const POLL_MS = 2000;

  // --- パネル生成 -----------------------------------------------------------
  const panel = document.createElement("div");
  panel.id = "bin-sign-overlay";
  panel.innerHTML = `
    <div class="bso-header" id="bso-header">
      <span class="bso-dot" id="bso-dot"></span>
      <span class="bso-title">BINARY SIGN<span class="bso-sub">フォワードテスト</span></span>
      <span class="bso-min" id="bso-min" title="最小化">–</span>
    </div>
    <div class="bso-body" id="bso-body">

      <div class="bso-bank">
        <div class="bso-bank-row">
          <div>
            <div class="bso-label">残高</div>
            <div class="bso-balance" id="bso-balance">¥5,000</div>
          </div>
          <div class="bso-bank-right">
            <div class="bso-label">次のベット</div>
            <div class="bso-stake" id="bso-stake">¥1,000</div>
            <div class="bso-shots" id="bso-shots">残弾 5</div>
          </div>
        </div>
        <div class="bso-bar"><div class="bso-bar-fill" id="bso-bar-fill"></div></div>
      </div>

      <div class="bso-section">
        <div class="bso-label">今日のピック（WF生存ルール・検証中）</div>
        <div class="bso-pick" id="bso-pick">―</div>
        <div class="bso-pickmeta" id="bso-pickmeta"></div>
      </div>

      <div class="bso-signal-wrap">
        <div class="bso-signal" id="bso-signal">待機中</div>
        <div class="bso-signal-meta" id="bso-signal-meta"></div>
      </div>

      <div class="bso-section bso-fwd">
        <div class="bso-label">フォワードテスト成績</div>
        <div class="bso-score" id="bso-score">0勝 0敗</div>
        <div class="bso-meter">
          <div class="bso-meter-be" style="left:52.6%"></div>
          <div class="bso-meter-fill" id="bso-meter-fill"></div>
        </div>
        <div class="bso-meter-label" id="bso-meter-label">損益分岐 52.6%（@1.90）</div>
      </div>

      <div class="bso-section" id="bso-bonus-wrap">
        <span class="bso-streak" id="bso-streak">連勝 0</span>
        <span class="bso-bonus" id="bso-bonus"></span>
      </div>

      <div class="bso-btns">
        <button class="bso-btn bso-win" id="bso-win">勝ち</button>
        <button class="bso-btn bso-loss" id="bso-loss">負け</button>
        <button class="bso-btn bso-tie" id="bso-tie">同値</button>
        <button class="bso-btn bso-reset" id="bso-reset" title="残高と成績を初期化">↺</button>
      </div>

      <button class="bso-btn bso-capture" id="bso-capture"
        title="クリック後、画面上のレート表示（数字）をクリックすると、その価格を1秒ごとに読み取ってシグナル計算に使います（読み取り専用）">⌖ レート取得</button>

      <div class="bso-foot">検証中ルール（期待勝率53〜55%）／ペイアウト1.90未満では打たない<br>発注は必ず手動。自動売買機能はありません。</div>
    </div>
  `;
  document.documentElement.appendChild(panel);

  const $ = (id) => document.getElementById(id);
  const yen = (v) => "¥" + Math.round(v).toLocaleString("ja-JP");

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
    const online = state.connected !== false;
    $("bso-dot").className = "bso-dot " + (online ? "bso-dot-on" : "bso-dot-off");

    // 残高・ベット
    const bank = state.bank || {};
    const bal = bank.balance != null ? bank.balance : 5000;
    $("bso-balance").textContent = yen(bal);
    $("bso-balance").className = "bso-balance " +
      (bal > bank.bankroll_start ? "bso-plus" : bal < bank.bankroll_start ? "bso-minus" : "");
    $("bso-stake").textContent = yen(bank.next_stake != null ? bank.next_stake : 1000);
    $("bso-shots").textContent = `残弾 ${bank.shots_left != null ? bank.shots_left : 5}`;
    const pct = Math.max(0, Math.min(100, (bal / (bank.bankroll_start || 5000)) * 100));
    const fill = $("bso-bar-fill");
    fill.style.width = pct + "%";
    fill.className = "bso-bar-fill " + (pct >= 100 ? "bso-bar-up" : pct >= 40 ? "bso-bar-mid" : "bso-bar-low");
    if (!bank.can_trade) $("bso-shots").textContent = "残高不足 — 停止";

    // ピック
    const fwd = state.forward || {};
    const pick = fwd.pick;
    if (pick) {
      const inv = pick.invert ? "・反転" : "";
      const slot = pick.slot_jst === "all" ? "全夜間" : `${pick.slot_jst[0]}-${pick.slot_jst[1]}時`;
      const warn = pick.recommended === false ? "⚠ " : "";
      $("bso-pick").textContent = `${warn}${pick.pair} / ${pick.strategy}${inv} / 判定${pick.expiry_min}分`;
      const wf = pick.wf_oos && pick.wf_oos.win_rate != null
        ? `WF実績 ${(pick.wf_oos.win_rate * 100).toFixed(1)}%` : "WF未検証";
      $("bso-pickmeta").textContent =
        `JST ${slot}・${wf}・学習下限 ${(pick.train.lcb * 100).toFixed(1)}%` +
        (pick.recommended === false ? "・実績が損益分岐未満＝推奨外" : "");
    } else {
      $("bso-pick").textContent = "―";
      $("bso-pickmeta").textContent = "";
    }

    // シグナル
    const sig = $("bso-signal");
    if (fwd.direction === "UP") {
      sig.textContent = "▲ HIGH";
      sig.className = "bso-signal bso-up";
    } else if (fwd.direction === "DOWN") {
      sig.textContent = "▼ LOW";
      sig.className = "bso-signal bso-down";
    } else {
      sig.textContent = "待機中";
      sig.className = "bso-signal bso-wait";
    }
    $("bso-signal-meta").textContent = fwd.status || "";

    // フォワード成績
    $("bso-score").textContent =
      `${bank.w || 0}勝 ${bank.l || 0}敗` +
      (bank.t ? ` ${bank.t}分` : "") +
      (bank.pnl != null ? `　損益 ${bank.pnl >= 0 ? "+" : ""}${yen(bank.pnl).replace("¥", "¥")}` : "");
    const wr = bank.win_rate;
    const mf = $("bso-meter-fill");
    mf.style.width = wr != null ? Math.min(100, wr * 100) + "%" : "0%";
    mf.className = "bso-meter-fill " + (wr != null && wr > (bank.breakeven || 0.526) ? "bso-bar-up" : "bso-bar-low");
    $("bso-meter-label").textContent = wr != null
      ? `勝率 ${(wr * 100).toFixed(1)}%（損益分岐 52.6% @1.90）`
      : "損益分岐 52.6%（@1.90）";

    // 連勝・ボーナス
    const mm = state.money || {};
    $("bso-streak").textContent = `連勝 ${mm.streak || 0}`;
    if (mm.bonus_active) {
      $("bso-bonus").textContent = `🎉 ボーナス Lv.${mm.bonus_level}`;
      panel.classList.add("bso-bonus-on");
    } else {
      const need = (mm.bonus_threshold || 3) - (mm.streak || 0);
      $("bso-bonus").textContent = need > 0 ? `あと${need}連勝でボーナス` : "";
      panel.classList.remove("bso-bonus-on");
    }
  }

  async function refresh() {
    const resp = await call("/state", "GET");
    if (resp.ok && resp.data) {
      render(resp.data);
    } else {
      $("bso-dot").className = "bso-dot bso-dot-off";
      $("bso-signal").textContent = "サーバー未起動";
      $("bso-signal").className = "bso-signal bso-wait";
      $("bso-signal-meta").textContent = "predict_server.py を起動してください";
    }
  }

  async function report(result) {
    const resp = await call("/result", "POST", { result });
    if (resp.ok && resp.data) render(resp.data);
  }
  async function reset() {
    if (!window.confirm("残高と成績を初期化します（記録はアーカイブされます）")) return;
    const resp = await call("/reset", "POST", {});
    if (resp.ok && resp.data) render(resp.data);
  }

  $("bso-win").addEventListener("click", () => report("win"));
  $("bso-loss").addEventListener("click", () => report("loss"));
  $("bso-tie").addEventListener("click", () => report("tie"));
  $("bso-reset").addEventListener("click", reset);

  // --- 画面レート読み取り（読み取り専用・発注要素には触れない） -------------
  // 「⌖ レート取得」→ 画面上のレート数字をクリックで指定 → 1秒ごとに
  // textContent を読み、現在ピックのペアの価格として /tick に送る。
  // 指定クリックは capture 段階で吸収するため、ページ側のボタンは発火しない。
  let capEl = null;
  let capTimer = null;
  let currentPickPair = null;

  function parsePrice(el) {
    if (!el || !el.isConnected) return null;
    const m = (el.textContent || "").replace(/[,\s]/g, "").match(/\d+(?:\.\d+)?/);
    if (!m) return null;
    const v = parseFloat(m[0]);
    return Number.isFinite(v) && v > 0 ? v : null;
  }

  function startCaptureLoop() {
    if (capTimer) clearInterval(capTimer);
    capTimer = setInterval(async () => {
      const price = parsePrice(capEl);
      if (price == null || !currentPickPair) return;
      $("bso-capture").textContent = `⌖ 取得中 ${price}`;
      await call("/tick", "POST", { pair: currentPickPair, price });
    }, 1000);
  }

  $("bso-capture").addEventListener("click", () => {
    $("bso-capture").textContent = "⌖ レート数字をクリック…";
    const onPick = (e) => {
      // パネル自身のクリックは無視して選び直し
      if (panel.contains(e.target)) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      document.removeEventListener("click", onPick, true);
      capEl = e.target;
      const price = parsePrice(capEl);
      if (price == null) {
        $("bso-capture").textContent = "⌖ 数字が読めません — 別の場所を";
        capEl = null;
        return;
      }
      capEl.style.outline = "2px solid #7dd3fc";
      setTimeout(() => { if (capEl) capEl.style.outline = ""; }, 1500);
      startCaptureLoop();
    };
    document.addEventListener("click", onPick, true);
  });

  const origRender = render;
  render = function (state) {
    currentPickPair = state.forward && state.forward.pick
      ? state.forward.pick.pair : null;
    origRender(state);
  };

  refresh();
  setInterval(refresh, POLL_MS);
})();
