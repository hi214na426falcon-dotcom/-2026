# 文字起こし → 「アルパカの考え方」ルール化テンプレート

私（Claude）は動画を視聴・解析できません。そこで、あなたが動画の**字幕/文字起こし**を貼り、
私がそこから**手法(ロジック)**を抽出して、このリポジトリのルールエンジン設定
(`config/strategies/*.json`) に落とし込みます。文言をそのまま転載するのではなく、
「判断の中身」を再実装します。

## 渡し方(おすすめ)

動画1本ごとに、以下のいずれかを貼ってください。

1. **字幕/文字起こしのテキスト**（丸ごとでOK。長ければ分割で）
2. すでに要点をまとめたメモ（下の「最低限ほしい項目」を埋めたもの）

複数動画にまたがる場合は「動画①はこれ、②はこれ」と順番に貼ってもらえれば、
私が共通ルールと例外を整理して1つの戦略にまとめます。

## 最低限ほしい項目（動画から拾ってほしいこと）

| 項目 | 例 | エンジンの対応 |
|---|---|---|
| 時間足 | 1分足 / 5分足 | `timeframe` |
| 満期（判定までの時間） | 1本後 / 5分後 | `expiry_bars` |
| 使う指標 | RSI(14), 移動平均, ボリンジャー, MACD等 | `indicators` |
| エントリー(上/CALL)条件 | 「RSIが30以下でBB下限を上抜け」 | `call.conditions` |
| エントリー(下/PUT)条件 | 「RSIが70以上でBB上限を下抜け」 | `put.conditions` |
| 見送り条件/フィルタ | 「重要指標発表前後は入らない」「レンジ中のみ」 | `filters` |
| 連続エントリーの間隔 | 「1回入ったら数本待つ」 | `cooldown_bars` |
| 資金管理 | 固定額 / 残高の◯% / マーチンの有無 | `stake`, `stake_mode` |
| ペイアウト率 | 例: 1.85倍(=0.85) | `payout_rate` |

> 資金管理で「マーチンゲール(負けたら倍賭け)」が出てくる場合は、リスクが跳ね上がるため
> 実装時に必ず上限とドローダウン警告を入れます（そのまま無制限には作りません）。

## 対応している条件の書き方（私が変換します）

- 比較: `>` `<` `>=` `<=` `==` `!=`
- クロス: `cross_above`（下から上抜け） / `cross_below`（上から下抜け）
- 範囲: `between`（例: RSIが40〜60）
- 傾き: `rising` / `falling`（直近との比較）

被演算子に使えるもの:
- 価格: `open` `high` `low` `close` `volume`
- 指標名: `rsi14`, `sma50` など（`indicators` で定義した名前）
- サブ系列: ボリンジャーは `bb.upper` `bb.mid` `bb.lower`、ストキャスは `stoch.k` `stoch.d`
- 数値: `30`, `1.5` など

## 例（RSI逆張り）

「1分足。RSI(14)が30以下まで下がって、終値がボリンジャー下限を上抜けたらCALL。
逆に70以上で上限を下抜けたらPUT。満期は次の足。1回入ったら2本は待つ。」

↓ これを私が次の JSON にします（`config/strategies/example_rsi_reversal.json` と同じ形）:

```json
{
  "name": "RSI reversal",
  "timeframe": "M1",
  "expiry_bars": 1,
  "cooldown_bars": 2,
  "payout_rate": 0.85,
  "indicators": {
    "rsi14": {"type": "rsi", "period": 14},
    "bb": {"type": "bollinger", "period": 20, "mult": 2.0}
  },
  "call": {"logic": "all", "conditions": [
    {"left": "rsi14", "op": "<", "right": 30},
    {"left": "close", "op": "cross_above", "right": "bb.lower"}
  ]},
  "put": {"logic": "all", "conditions": [
    {"left": "rsi14", "op": ">", "right": 70},
    {"left": "close", "op": "cross_below", "right": "bb.upper"}
  ]}
}
```

作成後は必ずバックテストにかけ、勝率・損益分岐・最大連敗・ドローダウンを確認します。

```bash
python3 -m alpaca_clone.cli backtest config/strategies/あなたの戦略.json --csv 実データ.csv
```
