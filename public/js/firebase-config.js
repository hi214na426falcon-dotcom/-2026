// Firebase 設定
// ローカル開発用: エミュレータを使用
// 本番用: 実際の Firebase プロジェクト設定に置き換え

const firebaseConfig = {
  apiKey: "AIzaSyDummyKeyForDevelopment",
  authDomain: "localhost",
  projectId: "demo-yuime-dev",
  storageBucket: "demo-yuime-dev.appspot.com",
  messagingSenderId: "000000000000",
  appId: "1:000000000000:web:0000000000000000"
};

// エミュレータに接続
export const useEmulator = {
  enabled: true,
  auth: {
    host: "localhost",
    port: 9099
  },
  firestore: {
    host: "localhost",
    port: 8080
  },
  storage: {
    host: "localhost",
    port: 9199
  }
};

export default firebaseConfig;
