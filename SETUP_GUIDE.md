# YUIME セットアップガイド

YUIME 現場特化 管理システムをローカルで動作させるための完全ガイドです。

## 📋 前提条件

✅ 確認：
```bash
node -v       # Node.js v18 以上
npm -v        # npm 10 以上
firebase --version  # Firebase CLI 15 以上
```

すべてインストール済みです！

## 🚀 クイックスタート（5分）

### ステップ 1: Firebase プロジェクト作成

1. **Firebase Console にアクセス**
   - https://console.firebase.google.com
   - Google アカウントでログイン

2. **新規プロジェクト作成**
   ```
   プロジェクト名: yuime-dev（任意）
   リージョン: asia-northeast1（東京）
   ```

3. **認証設定**
   - 左メニュー → Authentication
   - 「始める」→「メール/パスワード」を有効化

4. **Firestore 設定**
   - 左メニュー → Firestore Database
   - 「データベースの作成」
   - 本番モード → asia-northeast1

5. **Storage 設定**
   - 左メニュー → Storage
   - 「始める」

### ステップ 2: Firebase 設定をコピー

1. **プロジェクト設定へ移動**
   - 左上の歯車アイコン → プロジェクト設定

2. **マイアプリ セクション**
   - ウェブアプリ `</>` を追加
   - アプリニックネーム: yuime（任意）

3. **Firebase SDK 設定をコピー**
   ```javascript
   const firebaseConfig = {
     apiKey: "AIza...",
     authDomain: "yuime-dev.firebaseapp.com",
     projectId: "yuime-dev",
     storageBucket: "yuime-dev.appspot.com",
     messagingSenderId: "123456789",
     appId: "1:123456789:web:abc..."
   };
   ```

### ステップ 3: 設定ファイルに反映

**`public/js/firebase-config.js` を編集：**

```javascript
const firebaseConfig = {
  apiKey: "AIza...",              // ← コピーした値に置き換え
  authDomain: "yuime-dev.firebaseapp.com",
  projectId: "yuime-dev",
  storageBucket: "yuime-dev.appspot.com",
  messagingSenderId: "123456789",
  appId: "1:123456789:web:abc..."
};

export default firebaseConfig;
```

**`.firebaserc` を編集：**

```json
{
  "projects": {
    "default": "yuime-dev"        // ← プロジェクトIDに変更
  }
}
```

### ステップ 4: Firebase にログイン

```bash
firebase login
```

ブラウザが開き、Google アカウントでログインします。

### ステップ 5: 開発サーバー起動

```bash
npm start
# または
firebase serve --only hosting
```

**出力例：**
```
Project Console: https://console.firebase.google.com/project/yuime-dev/overview
Hosting URL: http://localhost:5000
```

### ステップ 6: ブラウザで開く

```
http://localhost:5000
```

### ステップ 7: 初期管理者作成

1. **セットアップページへ移動**
   ```
   http://localhost:5000/setup-admin.html
   ```

2. **管理者情報を入力**
   - 氏名: 任意（例：山田太郎）
   - メール: 任意（例：admin@example.com）
   - パスワード: 6文字以上

3. **「管理者を作成」をクリック**

### ステップ 8: ログイン

1. `http://localhost:5000` へアクセス
2. 作成した管理者のメール＆パスワードでログイン
3. ✅ ダッシュボードが表示されれば成功！

---

## 🛠️ 開発コマンド

```bash
# ホスティングのみ（軽い）
npm start

# 完全なエミュレータ（本格開発用）
npm run emulate

# デプロイ
npm run deploy

# 個別デプロイ
npm run deploy:hosting      # ホスティングのみ
npm run deploy:firestore    # Firestore ルール
npm run deploy:storage      # Storage ルール
```

---

## 🔌 ローカルエミュレータ（オプション）

Firebase プロジェクトがない場合、エミュレータで完全にローカル環境を構築できます。

### インストール

```bash
npm install -g firebase-tools  # 済み
firebase emulators:start
```

### 接続設定

`public/index.html` 等で：

```javascript
import { connectAuthEmulator, getAuth } from "...";
import { connectFirestoreEmulator, getFirestore } from "...";

const auth = getAuth();
const db = getFirestore();

if (location.hostname === 'localhost') {
  connectAuthEmulator(auth, 'http://localhost:9099', { disableWarnings: true });
  connectFirestoreEmulator(db, 'localhost', 8080);
}
```

---

## 📱 PWA として使用

### 前提条件

- HTTPS または localhost で実行
- Service Worker が自動登録

### インストール方法

**Chrome / Edge:**
- アドレスバー右の「インストール」ボタン
- または「その他」→「アプリをインストール」

**iOS Safari:**
- 共有 → ホーム画面に追加

---

## 🐛 トラブルシューティング

### Firebase プロジェクトが見つからない

```bash
firebase projects:list
firebase use --add
```

### ポート 5000 が既に使用されている

```bash
# 別のポートで起動
firebase serve --only hosting --port 8000
```

### CORS エラーが出る

Firestore のセキュリティルールを確認：

```
firestore.rules を確認し、正しい権限が設定されているか確認
```

### ログインできない

1. Authentication で「メール/パスワード」が有効か確認
2. `setup-admin.html` で管理者を再作成
3. ブラウザのキャッシュをクリア

---

## 📚 ファイル構成

```
yuime-genba/
├── public/                    # 公開ファイル（Hosting 対象）
│   ├── index.html            # ログイン
│   ├── dashboard.html        # ダッシュボード
│   ├── companies.html        # 会社管理
│   ├── sites.html            # 現場管理
│   ├── workers.html          # 作業員管理
│   ├── qr.html               # QR入退場
│   ├── settings.html         # 設定
│   ├── setup-admin.html      # 初期管理者作成
│   ├── manifest.json         # PWAマニフェスト
│   ├── sw.js                 # Service Worker
│   ├── css/style.css         # スタイル
│   └── js/
│       └── firebase-config.js # Firebase 設定 ⚠️ 編集必須
├── firebase.json             # Firebase 設定
├── .firebaserc               # プロジェクトID ⚠️ 編集必須
├── firestore.rules           # Firestore セキュリティルール
├── storage.rules             # Storage セキュリティルール
├── firestore.indexes.json    # インデックス定義
├── package.json              # npm スクリプト
└── README.md                 # プロジェクト概要
```

---

## ✅ チェックリスト

- [ ] Firebase CLI インストール済み
- [ ] Firebase プロジェクト作成済み
- [ ] Authentication 有効化
- [ ] Firestore Database 作成
- [ ] Cloud Storage 有効化
- [ ] firebase-config.js に設定値を入力
- [ ] .firebaserc にプロジェクトID を入力
- [ ] firebase login で認証
- [ ] npm start で開発サーバー起動
- [ ] setup-admin.html で管理者作成
- [ ] ダッシュボードでログイン確認

---

## 📞 サポート

- Firebase 公式ドキュメント: https://firebase.google.com/docs
- 問題が発生した場合は、ブラウザの開発者ツール（F12）でコンソールエラーを確認してください

---

**準備ができたら、セットアップスクリプトを実行：**

```bash
bash setup.sh
```

Happy coding! 🎉
