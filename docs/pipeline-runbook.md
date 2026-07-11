# パイプライン実行手順書（runbook）

> **セッションが消えても、このパイプラインは失われません。**
> コードはリモートに push 済みで、この手順書どおりに再実行できます。
> このファイルは「実データ取得 → run_backtest（時間帯＋資金管理）→ promote_strategy
> （OOS合格ゲート）→ 合格なら `approved_strategy.json` 生成 → 予測方向ON」までの
> 一連の流れを、いつでも同じ順序で再現するためのものです。

---

## 全体の流れ

```
① 実データ取得        data/fetch_dukascopy.py  →  data/m1/<PAIR>.csv
② バックテスト        run_backtest.py --jst-sessions --money-mgmt
③ 昇格ゲート(OOS)     backtest.promote_strategy
④ 合格した時だけ生成  backtest/results/approved_strategy.json
⑤ 予測方向ON          approved_strategy.json が在れば predict_server が方向配信を開始
```

**③で不合格なら④は生成されず、⑤は非表示のまま**です。これは事故防止と
カーブフィッティング防止のための設計で、「惜しいからパラメータを弄って再判定」は
禁止です（`docs/binary-options-research.md` / README 参照）。

---

## ① 実データ取得

**推奨: GitHub Actions 経由（`.github/workflows/fetch-histdata.yml`）。**
ワークフローファイルを（触るだけでも）このブランチに push すると起動し、
HistData.com の月次/年次 M1 アーカイブを取得 → EST→UTC 変換 → GMT8-21 時に
フィルタ → `data/m1/<PAIR>.csv` をブランチに自動コミットします（所要数分）。

手元PCで実行する場合:

```bash
pip install histdata
python3 data/fetch_histdata.py EURJPY          # 推奨（一括zip・数分）

# Dukascopy 直接取得も可能だが、環境によっては約21秒/時間ファイルに
# スロットリングされ 3 年分で十数時間かかる（2026-07-10 実測）
python3 data/fetch_dukascopy.py --pair EURJPY --from 2023-07-01 --to 2026-07-01 --hours 8-21
```

> 経緯（2026-07-10 実測）:
> - この Claude 実行環境は市場データ系ホストへのエグレスが全遮断（CONNECT 403）。
> - GitHub Actions ランナーは通常ネットに出られるため取得をそちらへ委譲。
> - Dukascopy は取得自体は正常だが約 21.5 秒/ファイルに絞られ、6 時間のジョブ制限内に
>   3 年分を完走できないため、同じ実データ源の HistData 一括 zip に切替。
> - 合成データは③のゲートで必ず不合格＝実データが無いと⑤には進めません。

CSV は最低限 `close`（または `price`）列があれば動きます。

## ② バックテスト（時間帯＋資金管理）

```bash
python3 run_backtest.py --strategy bollinger --expiry 3 --payout 1.90 \
    --jst-sessions --money-mgmt --data data/m1/EURJPY.csv
```

- `--jst-sessions` … 夜17〜24時＋深夜0〜6時(JST)にエントリー限定＋時間帯別成績
- `--money-mgmt`  … フラット固定 vs 3連勝ボーナス（逆マーチン）を同じ勝敗列で比較
- データ未指定なら合成データ（感触確認用）

## ③ 昇格ゲート（OOS合格判定）

```bash
python3 -m backtest.promote_strategy --pair EURJPY --strategy bollinger \
    --expiry 3 --payout 1.90 --data-dir data/m1
```

合格基準（すべて OOS で判定）:

| 条件 | しきい値 |
| --- | --- |
| エッジ（損益分岐勝率超過） | `+2.0pt 以上` |
| サンプル数 | `1,000 回以上` |
| 最大ドローダウン | `資金の 20% 以内` |
| データ | **実データのみ**（合成は不合格） |

## ④ approved_strategy.json（合格時のみ自動生成）

合格すると `backtest/results/approved_strategy.json` が書き出されます。
不合格なら**書きません**（方向は非表示のまま）。

## ⑤ 予測方向ON

```bash
cd overlay/server && python3 predict_server.py     # http://localhost:8765
```

`approved_strategy.json` が存在するときだけ、`backtest/inference.py` が直近1分足に
合格戦略を適用して方向（▲/▼）を配信します（先読みなし。シグナルが無ければ「待機中」）。

---

## この環境で今できること / できないこと

| ステップ | この Claude 環境 | 備考 |
| --- | --- | --- |
| ① 実データ取得 | ✅ Actions 経由 | 直接エグレスは遮断だが、fetch-histdata.yml が代行 |
| ② run_backtest | ✅ | 実データ 64 万本で実行確認済み |
| ③ promote（実データ） | ✅ | OOS 13,651 件で判定済み |
| ④ approved_strategy.json | 実データがOOS合格した時のみ | 捏造しない |
| ⑤ 予測方向ON | ④が在るときのみ | 事故防止のため無条件ONにはしない |

## 実測結果の記録（2026-07-10・実データで全工程実行）

- データ: `data/m1/EURJPY.csv` = **640,796 本**の実 1 分足
  （HistData 由来、2023-07-03〜2026-06-26 UTC、GMT8-21 時、OHLC 整合性エラー 0。
  独立ソースの Dukascopy 実取得値と価格水準一致を確認）
- ② bollinger / expiry 3 分 / payout 1.90 / JST 夜間セッション:
  取引 34,192 回、勝率 52.5%（95%CI 52.0〜53.1）、エッジ **-0.1pt**、
  時間帯別でも -0.6〜+0.7pt（全て誤差範囲）
- ③ OOS 判定: 勝率 53.48%、エッジ **+0.84pt**（基準 +2.0pt 未達）、
  サンプル 13,651 件（基準クリア）、最大 DD **117.1%**（基準 20% 超過）
- 判定: **不合格** → ④は生成せず、⑤の方向配信は OFF のまま。

**これは失敗ではなくパイプラインの正常動作。** 3 年分の実データにおいて、この戦略に
損益分岐+2pt を超える再現性あるエッジは存在しなかった、という検証結果が成果物です。
「惜しいから」とパラメータや期間を弄って再判定することはカーブフィッティングであり、
本リポジトリの設計上禁止（README・調査レポート参照）。次に試すなら、**事前に決めた**
別ペア・別戦略を各 1 回だけ OOS 判定するのが正しい手順（fetch-histdata.yml は
workflow_dispatch 入力 or 実行行の編集で他ペアも取得可能）。

## 14ペア一括OOS判定（2026-07-10・事前登録設定で各ペア1回のみ）

ザオプション系の主要FX 14ペア × 3年分の実1分足（各約64万本、検証済み）に対し、
**事前登録した同一設定**（bollinger既定・expiry3分・payout1.90・JST夜間）で
OOS判定を各ペア1回だけ実行した結果:

| ペア | OOS勝率 | edge@1.90 | edge@1.80 | 件数 | 最大DD | 判定 |
|---|---|---|---|---|---|---|
| EURJPY | 53.48% | +0.84pt | -2.08pt | 13,651 | 117% | 不合格 |
| AUDJPY | 53.36% | +0.73pt | -2.20pt | 13,554 | 88% | 不合格 |
| GBPJPY | 53.22% | +0.59pt | -2.34pt | 13,599 | 103% | 不合格 |
| CHFJPY | 53.02% | +0.39pt | -2.54pt | 13,531 | 84% | 不合格 |
| EURGBP | 52.61% | -0.02pt | -2.95pt | 13,479 | 124% | 不合格 |
| CADJPY | 52.04% | -0.59pt | -3.52pt | 13,715 | 180% | 不合格 |
| NZDJPY | 51.40% | -1.23pt | -4.16pt | 13,549 | 307% | 不合格 |
| GBPUSD | 51.35% | -1.28pt | -4.21pt | 13,767 | 269% | 不合格 |
| USDJPY | 51.18% | -1.45pt | -4.38pt | 13,543 | 406% | 不合格 |
| USDCHF | 50.84% | -1.79pt | -4.72pt | 13,671 | 410% | 不合格 |
| AUDUSD | 50.58% | -2.05pt | -4.98pt | 13,575 | 509% | 不合格 |
| EURUSD | 50.45% | -2.18pt | -5.11pt | 13,489 | 525% | 不合格 |
| NZDUSD | 50.04% | -2.59pt | -5.52pt | 13,642 | 572% | 不合格 |
| USDCAD | 50.04% | -2.60pt | -5.52pt | 13,754 | 652% | 不合格 |

読み方（正直に）:
- **14/14 不合格**。approved_strategy.json は生成されず、方向配信はOFFのまま。
- **payout 1.80 なら全ペアがマイナス**（3分取引で1.8倍が多いという運用実態なら
  なおさら勝てない）。1.90でも最良 +0.84pt は基準 +2.0pt に届かず、DDは全ペアで
  基準20%を大幅超過。
- JPYクロス上位・USDメジャー下位という並びは「JST夜間の逆張りはJPYクロスで
  相対的にマシ」という傾向を示すが、**14ペアの最良値は選択バイアス込み**
  （多重比較）なので、+0.84pt をそのまま将来の期待値と見なしてはいけない。
- スカウトの schedule.json も同じ実データ由来になった（全スロット GO=×、
  信頼度「低(有意でない)」が現状の正直な表示）。

## 15秒取引（実質ペイアウト2.05倍）の検証（進行中）

15秒判定は1分足では検証不能のため、Dukascopy ティックを15秒足に集約した
直近3週間分（EURJPY/USDJPY, fetch-ticks.yml）で、同値負け率・スプレッド感応度
込みの損益構造を分析する。ペイアウト2.05倍の損益分岐勝率は 48.78% と50%を
下回るため、「同値・スプレッド・約定ずれがどれだけ食うか」が争点。
