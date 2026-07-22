# 🚀 YUIME クイックスタート（3ステップで開始）

現在、システムは以下の状態です：

✅ **準備完了：**
- Node.js v22.22.2
- npm 10.9.7
- Firebase CLI 15.24.0

⏳ **次のステップ：** Firebase プロジェクトの作成と設定

---

## ステップ 1️⃣ Firebase プロジェクト作成（3分）

### A. Firebase コンソールにアクセス
```
https://console.firebase.google.com
```

### B. 新規プロジェクト作成
- **プロジェクト名：** `yuime-dev`（または任意の名前）
- **Google Analytics：** 無効でOK
- リージョン：`asia-northeast1（東京）`

### C. 有効化する機能（Firebase の各ページから）

#### 1. **Authentication** を有効化
```
左メニュー → Authentication
「始める」 → 「メール/パスワード」を有効化
```

#### 2. **Firestore Database** を作成
```
左メニュー → Firestore Database
「データベースの作成」 → 「本番モード」で開始
リージョン：asia-northeast1
```

#### 3. **Cloud Storage** を有効化
```
左メニュー → Storage
「始める」
```

---

## ステップ 2️⃣ Firebase 設定をコピー（2分）

### A. プロジェクト設定を開く
```
歯車アイコン ⚙️  → プロジェクト設定
```

### B. マイアプリセクション
```
「ウェブアプリを追加」 </> 
アプリニックネーム：yuime（任意）
→ 登録
```

### C. SDK スニペットをコピー
以下のような情報が表示されます：

```javascript
const firebaseConfig = {
  apiKey: "AIza...",
  authDomain: "yuime-dev.firebaseapp.com",
  projectId: "yuime-dev",
  storageBucket: "yuime-dev.appspot.com",
  messagingSenderId: "123...",
  appId: "1:123...:web:abc..."
};
```

---

## ステップ 3️⃣ コードに設定を反映（1分）

### A. `public/js/firebase-config.js` を編集

**置き換え前：**
```javascript
const firebaseConfig = {
  apiKey: "YOUR_API_KEY",
  authDomain: "YOUR_PROJECT_ID.firebaseapp.com",
  projectId: "YOUR_PROJECT_ID",
  storageBucket: "YOUR_PROJECT_ID.appspot.com",
  messagingSenderId: "YOUR_MESSAGING_SENDER_ID",
  appId: "YOUR_APP_ID"
};
```

**置き換え後（ステップ2でコピーした値に）：**
```javascript
const firebaseConfig = {
  apiKey: "AIza...",
  authDomain: "yuime-dev.firebaseapp.com",
  projectId: "yuime-dev",
  storageBucket: "yuime-dev.appspot.com",
  messagingSenderId: "123...",
  appId: "1:123...:web:abc..."
};
```

### B. `.firebaserc` を編集

**置き換え前：**
```json
{
  "projects": {
    "default": "YOUR_PROJECT_ID"
  }
}
```

**置き換え後：**
```json
{
  "projects": {
    "default": "yuime-dev"
  }
}
```

---

## 🏃 開発サーバー起動

すべての設定が完了したら、以下を実行：

```bash
# ターミナルで以下を実行
firebase login

# ブラウザでログイン完了後

npm start
```

**出力例：**
```
✔  Hosting URL: http://localhost:5000
```

---

## 🔑 初回ログイン

1. **ブラウザで開く：**
   ```
   http://localhost:5000/setup-admin.html
   ```

2. **管理者情報を入力：**
   - 氏名：`山田太郎`（例）
   - メール：`admin@yuime.local`（例）
   - パスワード：`password123`（6文字以上）

3. **「管理者を作成」をクリック**

4. **ダッシュボードへ移動：**
   ```
   http://localhost:5000
   ```

5. **作成した管理者で ログイン：**
   - メール：入力したメール
   - パスワード：入力したパスワード

✅ **ダッシュボードが表示されたら成功！**

---

## 📋 チェックリスト

- [ ] Firebase プロジェクト作成済み
- [ ] Authentication（メール/パスワード）有効化
- [ ] Firestore Database 作成済み
- [ ] Cloud Storage 有効化
- [ ] firebaseConfig をコピー
- [ ] `public/js/firebase-config.js` に貼り付け
- [ ] `.firebaserc` にプロジェクトID を入力
- [ ] `firebase login` でログイン
- [ ] `npm start` で開発サーバー起動
- [ ] `http://localhost:5000/setup-admin.html` で管理者作成
- [ ] ダッシュボードでログイン確認

---

## 🎯 次のステップ

開発サーバーが起動したら、以下の機能をテスト：

- ✅ ダッシュボード - 統計情報表示
- ✅ 会社管理 - 会社CRUD
- ✅ 現場管理 - 現場CRUD
- ✅ 作業員管理 - 作業員CRUD
- ✅ QR入退場 - 手動入力での打刻
- ✅ 設定 - CSV出力

---

## 🆘 トラブル？

**Firebase ログインエラー：**
```bash
firebase login --no-localhost
```

**ポート 5000 が使用中：**
```bash
firebase serve --only hosting --port 8000
```

**キャッシュをクリア：**
```bash
ブラウザ：Ctrl+Shift+Delete（または Cmd+Shift+Delete）
```

---

**完了したら、プロジェクトを git push！** 🎉

```bash
git push -u origin claude/yuime-genba-system-wf2qes
```
