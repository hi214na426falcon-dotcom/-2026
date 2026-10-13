# Mr.2 Gold 運用ツール

XAUUSD 1分足EA「Mr.2 Gold」（MT4 / HFM専用）を安全に運用するためのツール集です。

| フォルダ | 内容 |
|---|---|
| `notifier/` | 毎朝 6:00 ごろ、当日の米国経済指標と金のボラティリティから「稼働 / 時間帯停止 / 終日停止」を判定して Discord に通知 |
| `backtest/` | MT4 のバックテスト・取引履歴を読み込み、最大ドローダウン・シャープレシオ・PF・ウォークフォワード・モンテカルロ・推奨ロットを計算 |
| `docs/` | ロットと資金量の考え方、ウォークフォワードテストの手順 |

> EA 本体（.ex4）や付属 PDF は販売元の配布物なので、このリポジトリ（公開）には置いていません。

---

## 1. Discord 毎朝通知のセットアップ（約5分）

GitHub Actions で平日（月〜金）の朝に自動実行します。パソコンの電源を入れておく必要はありません。

### ① Discord の Webhook URL を作る
1. 通知を受け取りたいチャンネルの「⚙ チャンネルの編集」→「連携サービス」→「ウェブフック」→「新しいウェブフック」
2. 「ウェブフックURLをコピー」

### ② GitHub に登録する
リポジトリの **Settings → Secrets and variables → Actions**

- **Secrets** タブ →「New repository secret」
  - Name: `DISCORD_WEBHOOK_URL` / Secret: ①でコピーしたURL
- **Variables** タブ →「New repository variable」（任意。通知の「想定リスク」の計算に使います）
  - `EA_CAPITAL_JPY` = 運用資金（例: `140000`）
  - `EA_LOT` = 運用ロット（例: `0.01`）

Webhook URL を知っている人は誰でもそのチャンネルに投稿できます。コードやチャットに直接書かず、必ず Secrets に入れてください。

### ③ 動作テスト
**Actions → Gold EA daily brief → Run workflow**
- `dry_run` にチェックあり：Discord に送らず、ログに内容を表示
- `dry_run` のチェックを外す：実際に Discord に送信

以後は平日の朝、05:58 JST ごろに自動で届きます。

### 通知の判定ルール（`notifier/config.json` で変更可）

| 判定 | 条件 | EA の操作 |
|---|---|---|
| 🔴 停止推奨 | 米雇用統計(NFP)・CPI・FOMC（政策金利／声明／会見／経済見通し） | 発表の **2時間前〜3時間後** は新規エントリー停止 |
| 🔴 終日停止 | 感謝祭などの指定日・12/23〜1/3・ボラティリティ急拡大 | 「自動売買」ボタンをOFF |
| 🟡 時間帯停止 | 上記以外の米国「High」指標（PPI・小売売上高・ISM・FRB議長発言など） | 発表の **30分前〜60分後** は停止 |
| 🟡 注意 | 米国の祝日（薄商い）、ボラティリティ高め | 稼働可。ロットは上げない |
| 🟢 通常稼働 | 米国の重要指標なし | そのまま稼働 |

- 時刻は **日本時間** と **HFM MT4 サーバー時間**（GMT+2、欧州夏時間中は GMT+3）の両方で表示します。
- Mr.2 Gold v2.0 の「新規エントリー不可時間帯」は時差補正なしのため、**サーバー時間で設定するもの**と想定しています（販売元への確認を推奨）。
- ボラティリティは金先物（Yahoo Finance の `GC=F`）の ATR14 で代用しています。取得できない日は指標だけで判定します。
- 経済指標の取得に失敗した日は、予備スケジュール（`notifier/key_events.json`：FOMC・CPI・雇用統計）で判定し、通知に警告を付けます。**このファイルと `config.json` の `stop_dates` は年に1回更新してください。**

### ローカルで試す
```bash
python notifier/daily_brief.py --dry-run --force                       # 今日の内容を表示
python -m unittest discover -s notifier/tests -v                      # テスト
```

### 注意
- GitHub の定期実行は混雑時に遅れることがあります。05:07 JST に起動し、05:58 JST まで待ってから送信する作りなので、通常は 6:00 前後に届きます。
- 公開リポジトリでは、60日間更新がないと定期実行が自動停止されます。これを防ぐため、毎回の実行時にワークフローを再有効化しています。止まってしまった場合は Actions 画面から「Enable workflow」を押してください。
- 経済指標データは ForexFactory の公開フィードを個人利用の範囲で使っています。

---

## 2. ロットと資金量
→ [docs/lot_sizing.md](docs/lot_sizing.md)

## 3. ウォークフォワードテスト・成績分析
→ [docs/walkforward.md](docs/walkforward.md)
