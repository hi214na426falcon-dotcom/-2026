# オーバーレイ・サインツール ＆ 通貨ペア・スカウト 設計・運用ガイド

このドキュメントは、`overlay/`（表示専用サインツール）と `agents/`（通貨ペア・スカウト）の
設計と運用手順をまとめたものです。プロジェクト全体の基準は `MASTER_PROMPT.md` / `README.md`。

---

## 1. 全体像

```
                ┌─────────────────────────────────────────────┐
                │  通貨ペア・スカウト（マルチエージェント）      │
   実測          │                                             │
 バックテスト ──▶│  Fable 5（指示・計画）  ──▶  Opus 4.8（精査） │──▶ schedule.json
 （pair_stats）  │   ・時間帯ごとに担当ペアを決定                │   （time→pair）
                │   ・各時間帯を1体ずつ委譲（コスパ重視）         │
                └─────────────────────────────────────────────┘
                                     │ 読み込み
                                     ▼
   Chrome拡張(content.js) ◀── background.js ◀── predict_server.py(:8765)
        │  （表示専用）                              │  ・現在時間帯の推奨ペア/勝率
        │                                          │  ・連勝/ボーナス（money_mgmt）
   webterminal の上にパネル表示                      │  ・予測方向（合格戦略がある時のみ）
   （発注ボタンには一切触れない）
```

**設計の芯**: LLM は「実測統計に説明を付ける」だけ。勝率の数値は必ず
`pair_stats`（バックテスト）由来で、モデルが創作しない。合格戦略が無い間は
予測方向を一切出さない（事故防止）。

---

## 2. マルチエージェント構成（Fable5 → Opus4.8）

`agents/scout.py`：

1. **`analyze_pairs`（決定論）**: 各ペア×各時間帯（JST）の勝率・エッジ・サンプル数・
   信頼区間を実測する。実データ `data/m1/<PAIR>.csv` があれば実測、無ければ合成
   （`is_synthetic=true` を明示）。
2. **オーケストレーター（`claude-fable-5`）**: 各時間帯の候補統計を俯瞰し、
   時間帯ごとに `focus_pair` と短い調査指示を出す（1 回の呼び出し）。
   - 迷いにくいよう構造化出力（`output_config.format`）を使用。
   - Fable5 は稀に拒否応答を返すため、サーバー側フォールバック
     （`server-side-fallback-2026-06-01` → `claude-opus-4-8`）を既定で付与。
3. **ワーカー（`claude-opus-4-8`）**: 指示された 1 時間帯だけを担当し、
   推奨ペア・GO/見送り・根拠を返す（`effort: low` で安価に）。
4. **フォールバック**: `anthropic` 未導入／鍵無し／通信失敗のいずれでも、
   例外を投げずに決定論的な `schedule.json` を生成（`mode: "offline"`）。

コスト設計: 頭脳（Fable5）は計画 1 回だけ、実作業（各時間帯の精査）は安価な
Opus4.8 に分散。時間帯が 4 つなら「Fable5×1 + Opus4.8×4」で 1 スケジュール。

---

## 3. `schedule.json` スキーマ（`agents/schedule_schema.py`）

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-07-09T...Z",
  "tz": "JST",
  "mode": "offline",              // "offline" | "llm"
  "orchestrator_model": "claude-fable-5",
  "worker_model": "claude-opus-4-8",
  "strategy": {"name": "bollinger", "expiry_min": 3, "payout": 1.90},
  "slots": [
    {
      "window": "20:00-24:00",
      "hours": [20, 21, 22, 23],
      "recommended_pair": "EURJPY",
      "expected_win_rate": 0.56,
      "edge_pt": 3.4,
      "sample": 1200,
      "ci_low": 0.53, "ci_high": 0.59,
      "confidence": "中",           // 高/中/低/デモ(合成データ)
      "go": true,                   // 実弾GO可（統計的にプラスか）
      "rationale": "…",
      "ranking": [ {"pair": "...", "win_rate": ..., "edge_pt": ...}, ... ]
    }
  ],
  "disclaimer": "…"
}
```

`current_slot(sched)` が現在の JST 時刻に該当するスロットを返す。

---

## 4. 予測サーバー（`overlay/server/predict_server.py`）

- ポート 8765（標準ライブラリのみ）。CORS 許可済み。
- `GET /state` … 現在時間帯の推奨ペア＋連勝/ボーナス＋予測方向（下記）をまとめて返す。
- `GET /schedule` … `schedule.json` 全体。
- `POST /result {result: "win"|"loss"|"tie"}` … 連勝を更新して新しい状態を返す。
- `POST /reset` … 連勝をリセット。
- `GET /prediction?pair=EURJPY` … 予測方向（後方互換）。

**予測方向のゲート**: `backtest/results/approved_strategy.json` が存在し、必須キー
（`pair, strategy, expiry_min, payout, oos_passed`）を満たし `oos_passed: true` の
場合のみ `direction`/`confidence` を出す設計。現状ファイルは無いので常に `null`
（＝方向は表示しない）。推論の接続は `get_prediction()` の TODO に実装する。

---

## 5. オーバーレイ拡張（`overlay/`）

- `manifest.json`（MV3）: babaoption / theoption の webterminal にマッチ。
  `host_permissions` に `http://localhost:8765/*`。
- `background.js`: content script からの依頼で **localhost にのみ** フェッチする橋渡し。
  ページの CSP(connect-src) に縛られず、かつ宛先を localhost:8765 に限定。
- `content.js`: パネルを描画（ドラッグ移動・最小化可）。2.5 秒ごとに `/state` を取得し、
  推奨ペア・勝率・連勝・ボーナスステージを表示。勝ち/負け/リセットボタンで結果を記録。
  **ブローカーの DOM（発注ボタン・入力欄）は読み書きしない。**

---

## 6. 資金管理（`backtest/money_mgmt.py`）

- 基本 1,000 円固定。**3 連勝でボーナスステージ**（`bonus_active=true`）。
- ボーナス中は逆マーチン（`bonus_ladder = [1.5, 2.0, 3.0]` 倍、勝つほど 1 段ずつ上昇）。
  最高段で勝つと利食いして通常へ（`cash_out_at_top`）。
- **負けたら即 1,000 円に戻る**（負け時に増額しない＝通常マーチン禁止を担保）。
- `simulate_money_management()` で「フラット vs ボーナス」を同じ勝敗列で比較可能。
  UI 表示上は金額を出さず、`bonus_active` / `bonus_level` だけで演出できる。

---

## 7. 運用チェックリスト

- [ ] `python3 -m unittest discover -s tests` が全緑
- [ ] `python3 run_scout.py` で `schedule.json` 生成（実データがあれば `--data-dir data/m1`）
- [ ] `predict_server.py` 起動 → `curl http://localhost:8765/state` が返る
- [ ] 拡張を読み込み、webterminal 右上にパネル表示
- [ ] 予測方向は「検証済み戦略なし」のまま（合格戦略が確定するまで正しい挙動）
- [ ] 実弾は必ずデモ→最小額→段階増額。ボーナスは勝ち越し時の利益伸ばしにのみ使う
