# 中断→再開ガイド(トークン制限で止まったとき)

このループは **config 単位でチェックポイント**していて、`results/state_<run>.json` に
「どこまで終わったか」が入っている。git にも自動保存されるので、
**セッションが止まっても・コンテナが消えても、続きから再開できる。**

## いちばん簡単な再開(制限が解けて戻ってきたら)

Claude に「earesearch の続き回して」と言えば、下記を自動でやる。
手で回すなら:

```bash
cd ea-research/engine
bash resume.sh              # composite と atr を続きから完走
# 特定の run だけ: bash resume.sh composite
```

`resume.sh` は「最新を git pull → 依存を確保 → 各 run を起動」する。
runner は `state_<run>.json` を読んで **完了済み config を飛ばす**ので、
何度起動しても続きからになる(二重計算しない)。

## 仕組み(なぜ止まっても大丈夫か)

- `runner.py` は 1 config 評価するごとに `done_ids` に記録し、
  25件ごとに `results/state_<run>.json` へ書き出す。
- 200件ごとに `git add/commit/push`(`chore(ea): checkpoint ...`)。
  → 直近のチェックポイントまでは常に GitHub に載っている。
- 再起動時、state にある config は skip。**未評価のものだけ回す。**
- なので「トークン制限で急に落ちる」→「制限が解けて戻る」→
  `resume.sh` 一発、で失った計算は最大200件(数十秒)ぶんだけ。

## 自動ウェイクアップ(放置で進めたい場合)

Claude 側に **定期トリガ(Routine)** を仕込んであり、生きている間は
定期的にこのセッションを起こして「未完了の run があれば続きを回す」。
利用枠が回復していれば自動で進む(枠が尽きている間の発火は空振り)。
不要になったら Claude に「earesearch の自動再開トリガ止めて」と言えば消す。

## run の種類

| run | 中身 | config数 |
|-----|------|---------|
| `composite` | **本命**。ADX強度フィルタ × 時間帯(London/NY/Overlap/Asia) × トレンド系4型 | 11,520 |
| `atr` | ATR動的損切り/利確(固定pipsの代わり) | 1,440 |
| `baseline` | 単純指標の再現(全滅確認用) | 3,240 |

## 結果の見かた

- `results/survivors_<run>.json` … 生存候補(out-of-sample と3分割を通過)。
- **生存者が出ても喜ぶな。** README の「生存者が出たら」の裏取り手順
  (別データ / 実スプレッド / デモ3ヶ月フォワード)を必ず通す。
- 生存ゼロ = その階層にエッジ無し。次の階層(MTF等)へ。
