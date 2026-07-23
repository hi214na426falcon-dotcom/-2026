# YUIME 現場特化 管理システム
建設・農業等の現場管理を効率化するWebアプリ。フロントは HTML / CSS / Vanilla JS（ES Modules）、バックエンドは Firebase（Authentication / Cloud Firestore / Storage / Hosting）で構成された、ビルド不要・サーバーレスの PWA です。
---
## 主な機能
| 機能 | 内容 |
|---|---|
| 認証 | メール＋パスワードログイン、ロール別権限制御 |
| ダッシュボード | 現場数・作業員数・配属済み人数・現場別の配属人数を集計表示 |
| 会社管理 | 元請／協力会社の登録・編集・削除（管理者のみ） |
| 現場管理 | 現場の登録・状態管理、元請会社への紐付け |
| 協力会社管理 | 協力会社の管理 |
| 外国人作業員管理 | 氏名・国籍・在留資格・在留期限・職能・配属現場の管理 |
| 現場配属名簿 | 作業員を現場に配属し、現場ごとに「誰が働いているか」を一覧表示 |
| 写真 | 現場写真のアップロード・一覧・削除（Storage連携） |
| 書類 | 書類ファイルのアップロード・ダウンロード・削除 |
| お知らせ | 現場管理者以上が投稿、全員が閲覧 |
| 検索 | 各一覧画面での即時フィルタ検索 |
| 帳票 | 作業員名簿のCSV出力（現場別・Excel対応・BOM付きUTF-8） |
| ユーザー管理 | 管理者によるユーザー作成・ロール割当 |
### 権限（ロール）
- **admin（システム管理者）**：全権限
- **prime（元請会社）**：自社現場・作業員
- **manager（現場管理者）**：担当現場
- **partner（協力会社）**：所属データのみ
- **worker（作業員）**：自分の情報
---
## フォルダ構成
```
yuime-genba/
├── firebase.json              … Hosting / Firestore / Storage 設定
├── .firebaserc                … プロジェクトID
├── firestore.rules            … Firestore セキュリティルール（権限制御）
├── firestore.indexes.json     … 複合インデックス定義
├── storage.rules              … Storage セキュリティルール
├── README.md
└── public/                    … デプロイ対象（Hosting public）
    ├── index.html             … ログイン
    ├── setup-admin.html       … 初期管理者作成（初回のみ）
    ├── dashboard.html         … ダッシュボード
    ├── companies.html         … 会社管理
    ├── sites.html             … 現場管理
    ├── partners.html          … 協力会社
    ├── workers.html           … 作業員（配属現場の設定）
    ├── photos.html            … 写真
    ├── documents.html         … 書類
    ├── notices.html           … お知らせ
    ├── settings.html          … 設定・ユーザー管理・CSV出力
    ├── manifest.json          … PWAマニフェスト
    ├── sw.js                  … Service Worker
    ├── icons/                 … PWAアイコン
    ├── css/
    │   └── style.css          … 全画面共通スタイル（スマホファースト）
    ├── vendor/firebase/       … Firebase SDK（同梱・CDN非依存）
    └── js/
        ├── firebase-config.js … Firebase設定値（★要編集）
        └── app-firebase.js    … Firebase共有初期化（認証・DB・エミュレータ接続）
```

> **デプロイ手順は [DEPLOY.md](./DEPLOY.md) を参照してください。**
> Firebase SDK は `public/vendor/firebase/` に同梱しており、CDN（gstatic.com）に依存しません。
> 社内・現場の制限が強いネットワークでも動作し、接続はロングポーリング自動検出で安定化しています。
---
## セットアップ（Windows PowerShell）
### 1. 前提ツールのインストール
Node.js（LTS）をインストール済みであることを確認します。
```powershell
node -v
npm -v
```
未インストールの場合は https://nodejs.org/ からLTS版を入れてください。
Firebase CLI をインストールします。
```powershell
npm install -g firebase-tools
firebase --version
```
> **PowerShell 実行ポリシーでエラーが出る場合：**
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```
### 2. Firebaseプロジェクトの作成
1. https://console.firebase.google.com/ で新規プロジェクトを作成
2. **Authentication** →「始める」→「メール/パスワード」を有効化
3. **Firestore Database** →「データベースの作成」→本番モードで開始
4. **Storage** →「始める」で有効化
5. プロジェクト設定 →「マイアプリ」→ ウェブアプリ（`</>`）を追加し、表示される `firebaseConfig` をコピー
### 3. 設定値の反映
`public/js/firebase-config.js` を開き、コピーした値に置き換えます。
```javascript
const firebaseConfig = {
  apiKey: "＜あなたの値＞",
  authDomain: "＜あなたの値＞",
  projectId: "＜あなたの値＞",
  storageBucket: "＜あなたの値＞",
  messagingSenderId: "＜あなたの値＞",
  appId: "＜あなたの値＞",
};
```
`.firebaserc` の `YOUR_PROJECT_ID` も実際のプロジェクトIDに変更します。
### 4. Firebaseへログイン＆プロジェクト紐付け
```powershell
cd path\to\yuime-genba
firebase login
firebase use --add
```
### 5. ローカル動作確認
```powershell
firebase emulators:start
# もしくは Hosting だけを配信
firebase serve --only hosting
```
ブラウザで表示されたローカルURL（例 http://localhost:5000 ）を開きます。
> ※ `localhost` で開いたときは自動的にローカルのエミュレータに接続します。
### 6. 初期管理者の作成
1. `http://localhost:5000/setup-admin.html` を開く
2. 氏名・メール・パスワードを入力し「管理者を作成」
3. 作成後 `index.html` からログイン
> セキュリティのため、管理者作成後は `public/setup-admin.html` を削除するか、公開しないようにしてください。
### 7. デプロイ
セキュリティルールとホスティングをまとめて反映します。
```powershell
firebase deploy
```
個別に反映する場合：
```powershell
firebase deploy --only firestore:rules
firebase deploy --only storage
firebase deploy --only hosting
```
デプロイ完了後、`https://＜プロジェクトID＞.web.app` で公開されます。
---
## データモデル（Firestore コレクション）
| コレクション | 主なフィールド |
|---|---|
| `users` | uid, email, name, role, companyId |
| `companies` | name, type(prime/partner), tel, address, contact, trade |
| `sites` | name, companyId, address, manager, status, startDate |
| `workers` | name, nameKana, companyId, **siteId（配属現場）**, nationality, visaType, visaExpiry, tel, skill |
| `documents` | url, path, name, size, type, uploadedBy |
| `photos` | url, path, name, uploadedBy |
| `notices` | title, body, author |

> 勤怠（入退場の打刻）機能は搭載していません。作業員は `siteId` で現場に配属し、現場ごとの名簿として「誰が働いているか」を管理します。
---
## 技術メモ
- ビルドツール不要。ES Modules を CDN 経由で直接読み込み
- スマホファースト・レスポンシブ・PWA（オフラインシェルキャッシュ）
- 権限制御はクライアント表示制御 **＋ Firestore セキュリティルール** の二重構造
- 入力バリデーション・エラーハンドリング・トースト通知を全画面で実装
