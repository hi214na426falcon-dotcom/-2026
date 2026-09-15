# alpaca_clone

バイナリーオプションの「考え方（売買ルール）」を宣言的な設定で再現し、
**バックテスト → ペーパートレード → (任意で)実弾** の順で検証・運用するための土台。

標準ライブラリのみで動きます（依存パッケージ不要）。

---

## ⚠️ 先に読んでください（重要）

- これは**教育・検証目的**のツールです。利益を保証するものではありません。
- **バイナリーオプションは高リスク**の金融商品で、地域によっては個人向けに規制/禁止されています。
- **ブラウザ型業者の多くは自動売買を利用規約で禁止**しています。実弾の自動発注は
  アカウント凍結・出金拒否・法的リスクにつながり得ます。
- 本リポジトリでは、検知回避・規約回避・不正アクセスの類は実装しません。
  実弾接続は「利用者が自分の口座・自己責任で配線する明示的な差込口」として分離しています
  （`alpaca_clone/execution/browser_adapter.py`、既定は無効）。
- まずは `backtest` と `paper`（仮想口座）で手法の妥当性を必ず確認してください。

---

## 「アルパカの考え方」はどこにある？

動画から手法を取り込む流れはこうです（私＝Claude は動画を直接視聴できないため）:

1. あなたが動画の**字幕/文字起こし**を貼る
2. 私がそこから**ロジック**を抽出し、`config/strategies/*.json` のルールに変換する
3. `backtest` で検証 → `paper` で運用模擬 → 必要なら実弾差込口を配線

詳しい渡し方は **[docs/STRATEGY_TEMPLATE.md](docs/STRATEGY_TEMPLATE.md)** を参照。

ルールはコードではなく JSON なので、手法の差し替え・微調整はコードを触らずにできます。

---

## クイックスタート

```bash
# 1) 検証用データを作る（実データが無いとき）
python3 -m alpaca_clone.cli gen-data data.csv --n 1000 --mode cycle

# 2) 戦略をバックテスト
python3 -m alpaca_clone.cli backtest config/strategies/example_rsi_reversal.json --csv data.csv

# 3) 常駐ペーパー運用（ダッシュボード） → http://127.0.0.1:8787
python3 -m alpaca_clone.cli serve config/strategies/example_rsi_reversal.json --tick 0.5 --autostart

# テスト
python3 -m unittest discover -s tests
```

実データ CSV は `timestamp,open,high,low,close,volume` の列があればOK
（`time`/`date`/`o,h,l,c,v` など緩い列名も受け付けます）。

---

## 構成

```
alpaca_clone/
├── core/         データ型(Candle, Signal, Trade…) と 指標(SMA/EMA/RSI/BB/ATR/…)
├── strategy/     ルールエンジン ← 「アルパカの考え方」の中身(宣言的JSON)
├── data/         CSV読込・検証用の合成データ生成
├── backtest/     過去データ検証（勝率/損益分岐/PF/期待値/DD/最大連敗）
├── paper/        ペーパートレード（仮想口座で1本ずつ処理）
├── execution/    PaperBroker（実装済） / BrowserBrokerAdapter（差込口・既定無効）
├── server/       常駐Botの制御ダッシュボード（stdlibのHTTPサーバ）
└── cli.py        gen-data / backtest / serve
config/strategies/ 戦略JSON（example_* は動作確認用の仮ルール）
docs/              文字起こし→ルール化テンプレート
tests/             単体テスト
```

---

## 実行モードと段階（安全のための順序）

1. **バックテスト** … 手法が過去データで機能するかを数値で確認（今ここが中心）
2. **ペーパー** … 仮想口座でライブ挙動を確認（`serve` のダッシュボードで start/stop）
3. **実弾（任意・利用者責任）** … `execution/browser_adapter.py` を各自が実装して有効化
   - 可能な限り業者の**公式API**を使う（最も安全）
   - 公式APIが無い場合のみ Playwright 等でブラウザ操作を実装（規約要確認）

「Chromeオーバレイ」構成にしたい場合も、判断ロジック（`strategy`）はこのまま共通で使えます。
UIをブラウザ拡張側に持たせ、シグナルだけをこのエンジンから受け取る形にできます。

---

## ロードマップ（相談しながら進める部分）

- [ ] あなたの文字起こしから実戦略を作成 → バックテスト
- [ ] 実データ(対象業者/銘柄の過去足)での検証
- [ ] 資金管理（固定/％/上限付き）とリスク警告の強化
- [ ] （希望に応じて）Chrome拡張オーバレイ or サーバー実弾差込口の具体化
