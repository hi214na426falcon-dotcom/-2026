# バイナリーオプション バックテスト＆調査

バイナリーオプション（High/Low・固定時間 Up/Down）の戦略を **正直な指標** で検証するための、
依存パッケージ不要（Python 標準ライブラリのみ）のバックテスターと調査レポートです。

> **このリポジトリのスタンス（重要）**
> ご依頼は「勝率が8割に近づくようにバックテスト」でしたが、**勝率8割は過剰最適化や小サンプルで
> “演出”はできても、再現性のある目標にはなりません。** このツールはその数字を**捏造しません**。
> 代わりに、追うべき本当の指標＝**損益分岐勝率（= 1 / ペイアウト率）をどれだけ上回れるか（エッジ）**を、
> 信頼区間つきで正直に表示します。詳しい背景は [`docs/binary-options-research.md`](docs/binary-options-research.md) を参照。
>
> なお、NotebookLM の操作や、theoption / babaoption のデモ口座への自動ログイン・自動売買は
> この環境では行いません。デモ口座は「過去検証(バックテスト)」ではなく「フォワードテスト」であり、
> 自分で規律をもって行う手順を調査レポート第7章にまとめています。

---

## クイックスタート

インストール不要。Python 3.8 以上があれば動きます。

```bash
# 既定: 合成データ(ランダムウォーク)で全戦略を比較 + 過剰最適化の実証
python3 run_backtest.py

# 単一戦略を指定（rsi / ma_cross / bollinger / macd / random）
python3 run_backtest.py --strategy rsi

# ペイアウト率・判定足数・投資額を指定
python3 run_backtest.py --strategy bollinger --payout 1.90 --expiry 3 --stake 1000

# 実データ / デモ取引ログ CSV を評価（ヘッダーに close もしくは price 列が必須）
python3 run_backtest.py --data path/to/USDJPY_M5.csv --strategy rsi

# 合成データの性質を変える（逆張りがわずかに有利な平均回帰系）
python3 run_backtest.py --process meanrevert --strategy rsi

# 戦略一覧
python3 run_backtest.py --list-strategies
```

### テスト

```bash
python3 -m unittest discover -s tests -v
```

---

## 出力の読み方

各戦略についてこう表示されます（例）:

```
=== rsi ===
  ペイアウト率        : 1.85 倍   (損益分岐勝率 = 54.1%)
  取引回数            : 158 回 (勝 73 / 負 85 / 引分 0)
  勝率                : 46.2%  (95%信頼区間 38.4〜54.0%)
  損益分岐との差(edge): -7.9 ポイント
  総損益              : -22,950 円  (ROI -22.9%)
  ...
  判定                : 負け越し（統計的に有意）
```

- **損益分岐勝率 = 1 / ペイアウト率**。これを超えて初めて利益が出る。
- **95%信頼区間** に損益分岐勝率が含まれるなら、その「勝ち/負け」は**誤差範囲**＝偶然かもしれない、
  という意味。優位を主張するには信頼区間が損益分岐勝率を**明確に上回る**必要がある。
- **過剰最適化の実証** セクションは、「学習区間で高勝率の設定を選んでも、検証区間で崩れる」ことを
  毎回数値で示します。これが “勝率8割が出るまで設定をいじる” ことに意味がない理由です。

---

## ディレクトリ構成

```
.
├── run_backtest.py              # バックテスト CLI（--jst-sessions / --money-mgmt 対応）
├── run_scout.py                 # 通貨ペア・スカウト CLI（schedule.json 生成）
├── backtest/
│   ├── __init__.py
│   ├── data.py                  # 価格データ生成 / CSV 読み込み
│   ├── indicators.py            # SMA / EMA / RSI / MACD / Bollinger
│   ├── strategies.py            # シグナル生成戦略
│   ├── engine.py                # バックテスト本体・成績指標（信頼区間/有意性つき）
│   ├── sessions.py              # JST時間帯（夜17-24/深夜0-6）別の集計
│   ├── money_mgmt.py            # 1000円固定＋3連勝ボーナス（逆マーチン）＋シミュレータ
│   ├── inference.py             # 合格戦略から現在バーの方向を推論（先読みなし）
│   ├── promote_strategy.py      # OOS合格ゲート→approved_strategy.json（合格時のみ）
│   └── optimize.py              # 学習/検証分割による過剰最適化の実証
├── data/
│   └── fetch_dukascopy.py       # Dukascopy 1分足の取得・整形（自己テスト付き）
├── agents/                      # 通貨ペア・スカウト（マルチエージェント）
│   ├── pair_stats.py            # ペア×時間帯の勝率/エッジを決定論的に計算
│   ├── schedule_schema.py       # time→pair スケジュールのスキーマ・検証・現在スロット判定
│   ├── scout.py                 # Fable5(指示)→Opus4.8(実作業)。API無ければオフライン
│   └── requirements.txt         # anthropic（任意。未導入でもオフライン動作）
├── overlay/                     # Chrome拡張（表示専用）+ ローカル予測サーバー
│   ├── manifest.json            # Manifest V3
│   ├── background.js            # localhostへのフェッチ橋渡し（発注には触れない）
│   ├── content.js              # webterminal上のオーバーレイ描画（DOM発注なし）
│   ├── overlay.css
│   └── server/
│       ├── predict_server.py    # 推奨ペア/連勝/ボーナス/予測方向を配信（ポート8765）
│       ├── live_feed.py         # 直近1分足の供給（data/m1のCSV末尾から）
│       └── schedule.json        # run_scout.py が生成
├── .github/workflows/ci.yml     # CI（全テスト＋自己テスト＋スモーク）
├── tests/                       # 48件（全緑）
│   ├── test_engine.py test_sessions.py test_money_mgmt.py test_scout.py
│   └── test_inference.py test_promote.py test_datafeed.py test_predict_server.py
└── docs/
    ├── binary-options-research.md  # 徹底調査レポート
    └── overlay-and-scout.md        # オーバーレイ＋スカウトの設計・運用手順
```

---

## モデルの前提（正直な明示）

- エントリーはシグナルの出たバーの**終値**、判定は `expiry` 本後の**終値**。
- 勝ち = `投資額 × (ペイアウト − 1)`、負け = `−投資額`、同値 = 既定で負け（保守的・変更可）。
- **スプレッド・約定遅延は 0 と仮定**しているため、本ツールの数値は実運用よりやや楽観的です。
- 合成データ（既定 = ランダムウォーク）は**特定戦略が勝つように作っていません**。
  これは「優位はそう簡単には出ない」という現実を体感するための意図的な設計です。

---

## CSV データの形式

ヘッダー行が必要です。列名は大文字小文字を無視して柔軟に判定します。

```csv
time,open,high,low,close,volume
2024-01-01T00:00:00,150.10,150.20,150.05,150.15,0
2024-01-01T00:05:00,150.15,150.25,150.12,150.22,0
...
```

- 最低限 `close`（または `price`）列があれば動作します。
- データ入手先は調査レポート第10章を参照（MetaTrader / Dukascopy / 各種 API）。

---

## サインツール（Chrome オーバーレイ・表示専用）

`overlay/` は webterminal（babaoption / theoption）の上に浮かぶ**予測表示専用**の
Chrome 拡張（Manifest V3）です。**発注ボタン・入力欄には一切触れません。自動売買もしません。**

パネルの表示内容（フォワードテスト・モード）:
- **残高**（既定 5,000 円スタート）・**次のベット**（1,000 円固定＋3連勝ボーナス、
  残高を超えない）・**残弾**（あと何回打てるか）
- **今日のピック** — ウォークフォワード生存ルールが直近84日から選んだ
  ペア×戦略×判定時間×JST時間帯（`run_wf_pick.py --emit` が生成）
- **シグナル** ▲HIGH / ▼LOW / 待機中（時間帯外・条件不成立では出ない）
- **フォワードテスト成績** — 勝敗・損益・勝率メーター（損益分岐52.6%ライン付き）
- 勝ち/負け/同値の記録ボタン（サーバー側に永続化。再起動しても消えない）
- 予測方向の**合格戦略チャネル**は別枠のまま（approved_strategy.json が無い限り非表示）

フォワードテスト起動手順（2ステップ）:

```bash
# 1) 全部まとめて起動（ピック生成→ライブ取り込み→予測サーバー）
python3 start_forward_test.py

# 2) Chrome → chrome://extensions → デベロッパーモードON
#    → 「パッケージ化されていない拡張機能を読み込む」→ overlay フォルダを選択
#    → babaoption / theoption の webterminal を開くと右上にパネルが出る
```

**ライブ価格は「⌖ レート取得」が本命**: パネルのボタンを押して、画面上の
レート数字（ピックのペアのもの）をクリックすると、その表示を1秒ごとに読み取って
シグナル計算に使う（遅延ゼロ・読み取り専用・発注要素には触れない）。
Dukascopy 経由の `live_pull.py` は完了時間の裏埋め用で、遅延があるため
シグナルの鮮度が3分を超えると「鮮度不足のため打たない」と表示される。

> フォワードテストの鉄則: **ペイアウト1.90以上の商品・時間帯のみ**（1.80では
> 全戦略が構造的に負ける）。期待勝率は53〜55%域（学習側の6割超は将来の数字では
> ない）。5,000円＝5回分の負けで終わる薄い資金なので、判定はピックの時間帯内のみ、
> シグナル発生時のみ、1,000円固定で。発注は必ず手動。

詳細な設計・運用手順は [`docs/overlay-and-scout.md`](docs/overlay-and-scout.md)。

## 通貨ペア・スカウト（Fable5 → Opus4.8 マルチエージェント）

「**どの時間帯にどの通貨ペアが有利か**」をバックテスト統計から調べ、`schedule.json` を生成します。

- **オーケストレーター = Claude Fable 5**：統計を俯瞰し、各時間帯で精査すべきペアと
  調査指示を決める（頭脳。呼び出しは最小限）。
- **ワーカー = Claude Opus 4.8**：指示された 1 時間帯だけを担当し、根拠と GO/見送りを返す
  （安価なモデルに実作業を寄せてコストパフォーマンスを出す）。
- **API 鍵が無い環境では、例外を出さず決定論的な統計計算に自動フォールバック**します。
  数値（勝率）は常に実測バックテスト由来で、モデルが創作することはありません。

```bash
python3 run_scout.py                 # 既定（オフラインでも動く）
python3 run_scout.py --no-llm        # LLM を使わず決定論のみ
python3 run_scout.py --strategy bollinger --expiry 3 --payout 1.90 --data-dir data/m1
```

有効化（任意）: `pip install -r agents/requirements.txt` して
`ANTHROPIC_API_KEY` を設定（または `ant auth login`）すると LLM 経路が自動で有効になります。

## 資金管理（1,000 円固定 ＋ 3 連勝ボーナス ＝ 逆マーチン）

`backtest/money_mgmt.py` は、ひなの運用ルールを検証可能な形にしたものです。

- 基本は **1 回 1,000 円の固定額**。
- **3 連勝でボーナスステージに入り、逆マーチン**（勝った直後だけ増額）で勝ち分を伸ばす。
- **負けたら即 1,000 円に戻る。** ＝ 負けを取り返す通常のマーチンゲール（倍賭け）は
  構造的に発生しない（MASTER_PROMPT の絶対制約を担保）。増額は上限で頭打ち。

バックテストで「フラット固定 vs 3連勝ボーナス」を同じ勝敗列で比較できます:

```bash
python3 run_backtest.py --strategy bollinger --expiry 3 --payout 1.90 \
    --process meanrevert --jst-sessions --money-mgmt
```

> **正直な注意**: 逆マーチンは**勝率を上げません**。勝ち越している（勝率が損益分岐を
> 上回っている）戦略の利益を伸ばす道具であり、負け越す戦略に使えば資金は減ります。

## セットアップの流れ（今日 → 明日 → 土曜）

1. **今日**: オーバーレイ導入（`run_scout.py` → `predict_server.py` → 拡張読み込み）。
   実データ `data/m1/<PAIR>.csv` があればスカウトが実測エッジを算出。無ければデモ表示。
2. **明日**: `python3 -m unittest discover -s tests` で全テスト緑を確認 →
   実データ取得 `python3 data/fetch_dukascopy.py --pair EURJPY --from … --to …` →
   `run_backtest.py --jst-sessions --money-mgmt` で感触を見る →
   `python3 -m backtest.promote_strategy --pair EURJPY --strategy bollinger …` で
   **OOS 合格ゲート**（+2pt/1000回/DD20%）を通す。合格した時だけ
   `backtest/results/approved_strategy.json` が生成され、予測方向の配信が有効化される
   （不合格ならパラメータを弄らず棄却＝カーブフィッティング防止）。
2. **土曜〜**: まず**デモ（または最小額）**で運用開始。オーバーレイの推奨ペアで
   1,000 円固定 → 3 連勝でボーナスステージ。実弾増額は 4 週連続で損益分岐を上回ってから。

## 免責

本リポジトリは**教育・検証目的**のものであり、投資勧誘・投資助言ではありません。
バイナリーオプションは原理的に参加者に不利で、多くの人が損失を出します。とりわけ海外無登録
業者には出金・保護上のリスクがあります（調査レポート第4章）。利用と投資判断は自己責任で行ってください。
