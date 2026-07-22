# 🎉 YUIME システム - エミュレータセットアップ完了！

## ✅ 現在の状態

**Firebase エミュレータがローカルで起動し、完全に動作可能な状態です！**

このリモート環境では、以下のサービスがすべて起動しています：

### 🔗 アクセス可能なエンドポイント

| 機能 | ポート | URL | 説明 |
|---|---|---|---|
| **YUIME アプリ** | 5000 | `http://localhost:5000` | メインアプリケーション |
| **Emulator UI** | 4000 | `http://localhost:4000` | 管理画面・デバッグ |
| **Auth Emulator** | 9099 | `http://localhost:9099` | 認証エミュレータ |
| **Firestore Emulator** | 8080 | `http://localhost:8080` | データベース |
| **Storage Emulator** | 9199 | `http://localhost:9199` | ファイル保存 |

---

## 🚀 3ステップで使い始める

### **ステップ 1️⃣ 初期管理者を作成**

**ブラウザで以下にアクセス：**
```
http://localhost:5000/setup-admin.html
```

**以下を入力：**
```
氏名:      管理者
メール:    admin@yuime.local
パスワード: password123
```

**「管理者を作成」をクリック** ✓

---

### **ステップ 2️⃣ ログイン**

**ブラウザで以下にアクセス：**
```
http://localhost:5000
```

**ログイン情報：**
```
メール:    admin@yuime.local
パスワード: password123
```

**「ログイン」をクリック** ✓

---

### **ステップ 3️⃣ ダッシュボード確認**

✅ **ダッシュボードが表示されたら成功！**

以下が自動的に集計されます：
- 📊 現場数
- 👷 作業員数
- 📅 本日入場数
- 🏢 会社数

---

## 🎯 実装済み機能

### 認証・権限
- ✅ メール＆パスワードログイン
- ✅ ロール別権限制御
- ✅ 初期管理者作成
- ✅ セッション管理

### ダッシュボード
- ✅ 統計情報のリアルタイム表示
- ✅ 最近の入退場記録

### データ管理
- ✅ **会社管理** - 元請／協力会社CRUD
- ✅ **現場管理** - 現場情報管理
- ✅ **作業員管理** - 外国人作業員管理
- ✅ **QR入退場** - 手動入力対応（QRスキャンは要カメラ）
- ✅ **設定・CSV出力** - 入退場記録をダウンロード

### インフラ
- ✅ PWA対応（ホーム画面に追加可能）
- ✅ Service Worker（オフラインキャッシュ）
- ✅ レスポンシブデザイン（スマホ対応）
- ✅ Firestore セキュリティルール
- ✅ Storage セキュリティルール

---

## 📁 プロジェクト構造

```
/home/user/-2026/
├── firebase.json          ← エミュレータ設定済み
├── .firebaserc            ← demo-yuime-dev に設定済み
├── firestore.rules        ← セキュリティルール
├── storage.rules          ← Storage ルール
├── package.json           ← npm スクリプト
├── public/
│   ├── index.html         ← ログイン画面
│   ├── setup-admin.html   ← 管理者作成
│   ├── dashboard.html     ← ダッシュボード
│   ├── companies.html     ← 会社管理
│   ├── sites.html         ← 現場管理
│   ├── workers.html       ← 作業員管理
│   ├── qr.html            ← QR入退場
│   ├── settings.html      ← 設定
│   ├── manifest.json      ← PWAマニフェスト
│   ├── sw.js              ← Service Worker
│   └── css/style.css      ← スタイル（スマホ対応）
├── QUICK_START.md         ← 最速スタートガイド
├── SETUP_GUIDE.md         ← 詳細セットアップ
├── README.md              ← プロジェクト概要
└── EMULATOR_READY.md      ← このファイル
```

---

## 🧪 テスト手順（推奨）

1. **管理者作成**
   ```
   http://localhost:5000/setup-admin.html
   → 「管理者を作成」
   ```

2. **ログイン**
   ```
   http://localhost:5000
   → admin@yuime.local でログイン
   ```

3. **会社を追加**
   ```
   ナビゲーション → 「会社」
   → 「+ 新規作成」
   → 会社名入力 → 「保存」
   ```

4. **現場を追加**
   ```
   ナビゲーション → 「現場」
   → 「+ 新規作成」
   → 現場名・会社選択 → 「保存」
   ```

5. **作業員を追加**
   ```
   ナビゲーション → 「作業員」
   → 「+ 新規作成」
   → 作業員情報入力 → 「保存」
   ```

6. **QR入退場テスト**
   ```
   ナビゲーション → 「QR」
   → 作業員IDを入力
   → 「入場」 or 「退場」ボタンクリック
   ```

7. **CSV出力テスト**
   ```
   ナビゲーション → 「設定」
   → 日付範囲指定 → 「CSV出力」
   ```

---

## 📊 Emulator UI で確認

Firebase Emulator Suite の管理画面で、リアルタイムにデータを確認できます：

```
http://localhost:4000
```

ここで以下を確認できます：
- 📝 **Firestore** - コレクション・ドキュメント表示
- 👥 **Authentication** - 作成されたユーザー一覧
- 💾 **Storage** - アップロードされたファイル
- 📊 **ログ** - リクエスト・エラーログ

---

## 🛠️ npm コマンド

```bash
# エミュレータ起動（現在実行中）
npm run emulate

# ホスティングのみ（軽い版）
npm start

# 本番環境にデプロイ（Firebase プロジェクト設定後）
npm run deploy

# 個別デプロイ
npm run deploy:hosting      # ホスティングのみ
npm run deploy:firestore    # ルール＆インデックス
npm run deploy:storage      # Storage ルール
```

---

## ⚙️ 設定情報

### Firebase 設定
```javascript
// public/js/firebase-config.js
const firebaseConfig = {
  projectId: "demo-yuime-dev",
  // エミュレータに自動接続
};
```

### プロジェクトID
```json
// .firebaserc
{
  "projects": {
    "default": "demo-yuime-dev"
  }
}
```

### エミュレータ設定
```json
// firebase.json
{
  "emulators": {
    "auth": { "port": 9099 },
    "firestore": { "port": 8080 },
    "storage": { "port": 9199 },
    "hosting": { "port": 5000 }
  }
}
```

---

## ⚠️ 重要な注意事項

### ✅ このセットアップで可能なこと
- ローカル開発・テスト
- セキュリティルールのテスト
- すべての機能の動作確認
- データの永続性（セッション中）

### ❌ このセットアップでは不可能なこと
- インターネット公開
- 本番デプロイ（Firebase プロジェクト必須）
- 外部デバイスからのアクセス

### 本番環境への移行
実際に公開する場合：
1. Google Cloud でプロジェクト作成
2. `firebase use --add` でプロジェクト設定
3. Firebase コンソールで認証・Firestore・Storage 有効化
4. `public/js/firebase-config.js` に本番設定を入力
5. `firebase deploy` で本番にデプロイ

---

## 🐛 トラブルシューティング

### Q: ポート 5000 がすでに使用されている

A: 別のポートで起動
```bash
firebase emulators:start --only hosting --port 8000
```

### Q: ログインできない

A: ブラウザコンソール（F12）を確認
```bash
# 以下のメッセージが表示されていればOK
✓ Auth Emulator に接続しました
✓ Emulator に接続しました
```

### Q: データが反映されない

A: キャッシュをクリア
```bash
ブラウザ: Ctrl+Shift+Delete (または Cmd+Shift+Delete)
```

### Q: エミュレータを停止したい

A:
```bash
# ターミナルで Ctrl+C
# または
killall firebase java node
```

---

## 🎓 次に学ぶべきこと

### デプロイ方法
- 本番環境への Firebase プロジェクト設定
- GitHub Actions での自動デプロイ
- 本番セキュリティルール最適化

### 機能拡張
- QR コード自動生成機能
- 写真アップロード実装
- 書類管理機能
- 通知機能

### 本番運用
- 監視・ロギング設定
- バックアップ戦略
- セキュリティ監査

---

## 💡 便利なリンク

| リソース | URL |
|---|---|
| Firebase 公式ドキュメント | https://firebase.google.com/docs |
| Firestore セキュリティルール | https://firebase.google.com/docs/firestore/security/start |
| Firebase Emulator Suite | https://firebase.google.com/docs/emulator-suite |

---

## ✨ 完成！

**YUIME 現場特化 管理システムは完全にセットアップされました！**

### 次のアクション
1. ✅ ブラウザで `http://localhost:5000` を開く
2. ✅ `/setup-admin.html` で管理者を作成
3. ✅ ログインしてダッシュボード確認
4. ✅ 各機能をテスト
5. ✅ 本番環境への移行を計画

**準備完了！システムは本番環境へ展開可能な状態です。** 🚀

---

**質問がある場合は、このドキュメントを参照するか、コンソールログを確認してください。**
