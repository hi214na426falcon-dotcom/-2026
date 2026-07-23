// Firebase 共有初期化モジュール
// 全ページはここから { auth, db } を import して利用します。
// ・初期化を一箇所に集約（重複排除）
// ・ロングポーリング自動検出を有効化
//   → 企業・現場の制限が強いネットワーク／プロキシ環境でも接続が安定します
// ・ローカル開発時はエミュレータへ自動接続
import { initializeApp } from '/vendor/firebase/firebase-app.js';
import { getAuth, connectAuthEmulator } from '/vendor/firebase/firebase-auth.js';
import { initializeFirestore, connectFirestoreEmulator } from '/vendor/firebase/firebase-firestore.js';
import firebaseConfig, { useEmulator } from './firebase-config.js';

const app = initializeApp(firebaseConfig);

export const auth = getAuth(app);
export const db = initializeFirestore(app, {
  experimentalAutoDetectLongPolling: true,
});

if (useEmulator && useEmulator.enabled && location.hostname === 'localhost') {
  try {
    connectAuthEmulator(auth, `http://${useEmulator.auth.host}:${useEmulator.auth.port}`, { disableWarnings: true });
    connectFirestoreEmulator(db, useEmulator.firestore.host, useEmulator.firestore.port);
  } catch (error) {
    console.warn('Emulator 接続:', error.message);
  }
}

export { app };
