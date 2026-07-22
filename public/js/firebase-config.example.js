// Firebase 設定テンプレート
//
// 以下のいずれかの方法で設定してください：
//
// 【方法1】実際の Firebase プロジェクトを使う（推奨）
// ─────────────────────────────────
// 1. https://console.firebase.google.com でプロジェクト作成
// 2. プロジェクト設定 → マイアプリ → ウェブアプリ追加
// 3. 表示された firebaseConfig をコピー
// 4. 下記の YOUR_* を置き換え
//
// 【方法2】ローカルエミュレータを使う（開発用）
// ─────────────────────────────────
// 1. firebase emulators:start で起動
// 2. 下記をコメントアウト
// 3. コンソール出力の接続情報を使用
//

const firebaseConfig = {
  apiKey: "YOUR_API_KEY",
  authDomain: "YOUR_PROJECT_ID.firebaseapp.com",
  projectId: "YOUR_PROJECT_ID",
  storageBucket: "YOUR_PROJECT_ID.appspot.com",
  messagingSenderId: "YOUR_MESSAGING_SENDER_ID",
  appId: "YOUR_APP_ID"
};

// ローカルエミュレータ設定（開発時のみ）
// 以下のコメントを外すと localhost:8080 に接続します
/*
export { firebaseConfig };
export const useEmulator = {
  auth: true,        // Authentication Emulator
  firestore: true,   // Firestore Emulator
  storage: true,     // Storage Emulator
  host: 'localhost',
  ports: {
    auth: 9099,
    firestore: 8080,
    storage: 9199
  }
};
*/

export default firebaseConfig;
