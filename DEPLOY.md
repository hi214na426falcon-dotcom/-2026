# YUIME 本番デプロイ手順

実際の現場で使えるように、Firebase 本番環境へ公開する手順です。
公開後は `https://＜プロジェクトID＞.web.app` として、PCからもスマホからもアクセスできます。

> **所要時間の目安：約30分**（うち大半は Firebase コンソールでの操作）

---

## 前提

- Google アカウント（無料）
- このリポジトリを自分のPCに取得済み
- Node.js（LTS）インストール済み

Firebase CLI は次でインストールします。
```bash
npm install -g firebase-tools
```

---

## ステップ1：Firebase プロジェクトを作成

1. https://console.firebase.google.com を開く
2. **プロジェクトを追加**
   - プロジェクト名：`yuime`（任意）
   - Google アナリティクス：オフでOK
3. 作成後、以下を有効化：

   **① Authentication（認証）**
   - 左メニュー → Authentication → 「始める」
   - 「ログイン方法」→ **メール/パスワード** を有効化して保存

   **② Firestore Database**
   - 左メニュー → Firestore Database → 「データベースの作成」
   - ロケーション：`asia-northeast1（東京）`
   - **本番環境モード**で開始（ルールは後でこのリポジトリのものを反映します）

   **③ Storage**（写真・書類を使う場合）
   - 左メニュー → Storage → 「始める」

---

## ステップ2：ウェブアプリ設定を取得

1. コンソール左上の **⚙️ → プロジェクトの設定**
2. 「マイアプリ」→ **ウェブ `</>`** を追加
   - アプリのニックネーム：`yuime`
3. 表示される `firebaseConfig` の値を控える：
   ```js
   const firebaseConfig = {
     apiKey: "AIza...",
     authDomain: "yuime-xxxx.firebaseapp.com",
     projectId: "yuime-xxxx",
     storageBucket: "yuime-xxxx.appspot.com",
     messagingSenderId: "1234567890",
     appId: "1:1234567890:web:abcdef"
   };
   ```

---

## ステップ3：設定ファイルを書き換え

### `public/js/firebase-config.js`
`firebaseConfig` の各値を、ステップ2で取得した**実際の値**に置き換えます。

```js
const firebaseConfig = {
  apiKey: "＜あなたの値＞",
  authDomain: "＜あなたの値＞",
  projectId: "＜あなたの値＞",
  storageBucket: "＜あなたの値＞",
  messagingSenderId: "＜あなたの値＞",
  appId: "＜あなたの値＞"
};
```

> `useEmulator` の部分はそのままで構いません。
> 公開後のドメイン（`*.web.app`）では自動的にエミュレータを使わず、本番のFirebaseに接続します。
> `localhost` で開いたときだけエミュレータに繋がります。

### `.firebaserc`
`default` をあなたのプロジェクトIDに変更します。
```json
{
  "projects": {
    "default": "yuime-xxxx"
  }
}
```

---

## ステップ4：Firebase にログイン＆デプロイ

リポジトリのルートで実行します。

```bash
firebase login          # ブラウザでGoogleログイン
firebase use yuime-xxxx # ↑のプロジェクトIDを指定

# セキュリティルール＋ホスティングをまとめて公開
firebase deploy
```

成功すると次のように表示されます：
```
Hosting URL: https://yuime-xxxx.web.app
```

---

## ステップ5：初期管理者を作成

1. ブラウザで **`https://yuime-xxxx.web.app/setup-admin.html`** を開く
2. 氏名・メール・パスワード（6文字以上）を入力し「管理者を作成」
3. 完了したら **セキュリティのため setup-admin.html を無効化**します。
   一度セットアップすると自動で「セットアップ済み」表示になりますが、
   念のためファイル自体を削除して再デプロイするのが安全です：
   ```bash
   rm public/setup-admin.html
   firebase deploy --only hosting
   ```

---

## ステップ6：ログインして利用開始

1. `https://yuime-xxxx.web.app` を開く
2. 作成した管理者でログイン
3. 会社 → 現場 → 作業員 の順に登録し、作業員に**配属現場**を設定
4. 「現場」画面の「◯人 の名簿」から、その現場で働く人を確認できます

スマホでは、ブラウザの「ホーム画面に追加」でアプリのように使えます（PWA）。

---

## 追加ユーザー（管理者以外）の作り方

本アプリはセキュリティ上、管理者アカウントの一括作成をブラウザから行いません。
追加ユーザーは次の手順で作成します。

1. **Firebase コンソール → Authentication → ユーザーを追加**（メール・パスワード）
2. **Firestore → `users` コレクション** に、そのユーザーの**ドキュメントID＝ユーザーのUID**で以下を作成：
   ```
   uid:       （AuthのUIDと同じ）
   email:     ユーザーのメール
   name:      表示名
   role:      admin / prime / manager / partner / worker のいずれか
   companyId: （所属会社のドキュメントID、無ければ空）
   ```

> ロールの意味：admin=全権限 / prime=元請 / manager=現場管理者 / partner=協力会社 / worker=作業員

---

## 更新のたびに再デプロイ

コードを直したら、都度：
```bash
firebase deploy --only hosting          # 画面だけ更新
firebase deploy --only firestore:rules  # ルールだけ更新
firebase deploy                         # まとめて更新
```

---

## うまくいかないとき

| 症状 | 対処 |
|---|---|
| ログイン画面が真っ白 | `firebase-config.js` の値が正しいか確認（特に apiKey / projectId） |
| ログインできない | Authentication で「メール/パスワード」が有効か確認 |
| 「権限がありません」表示 | `firebase deploy --only firestore:rules` でルールを反映したか確認 |
| データが出ない | ブラウザの検証ツール（F12）→ Console のエラーを確認 |

---

## ローカルで試したいとき（任意）

Firebase プロジェクトを使わず、自分のPC内だけで動作確認できます。
```bash
npm install
firebase emulators:start
```
→ `http://localhost:5000/setup-admin.html` で管理者を作成して確認。
（`localhost` のときだけローカルのエミュレータに接続します）
