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

```bash
# パーサの自己テスト（ネット不要）
python3 data/fetch_dukascopy.py --self-test

# 1本の接続確認
python3 data/fetch_dukascopy.py --probe --pair EURJPY

# 期間指定でダウンロード（JSTの夜〜深夜に対応する GMT8-21 に絞ると軽い）
python3 data/fetch_dukascopy.py --pair EURJPY --from 2023-07-01 --to 2026-07-01 --hours 8-21
```

> ⚠️ **この Claude 実行環境では Dukascopy へのエグレスが遮断**されています
> （`datafeed.dukascopy.com` は proxy 許可リスト外 → 取得失敗）。
> `--self-test` はネット不要で通りますが、実ダウンロードは
> **通常ネットの手元PC**で行い、生成した `data/m1/<PAIR>.csv` をリポジトリに置いてください。
> （合成データは③のゲートで必ず不合格になります＝実データが無いと⑤には進めません。）

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
| ① 実データ取得 | ❌ 遮断 | Dukascopy egress ブロック。手元PCで実行しCSVを配置 |
| ① 自己テスト | ✅ | `--self-test` は 48 テスト同様グリーン |
| ② run_backtest | ✅ | 合成／持ち込みCSVの両方で動作 |
| ③ promote（合成） | ✅（=正しく不合格） | 合成データは仕様上どうしても不合格 |
| ③ promote（実データ） | 実データCSVがあれば可 | 上記②の CSV を置けばこの環境でも判定可 |
| ④ approved_strategy.json | 実データがOOS合格した時のみ | 捏造しない |
| ⑤ 予測方向ON | ④が在るときのみ | 事故防止のため無条件ONにはしない |

**結論**: ①の「実データCSV」を用意すれば、②〜⑤はこの環境でも通します。
CSV が無い状態で④⑤を無理に作ることは、設計思想（捏造しない・カーブフィッティング防止）に
反するため行いません。
