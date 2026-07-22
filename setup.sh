#!/bin/bash

# YUIME 現場特化 管理システム セットアップスクリプト

echo "=========================================="
echo "YUIME 現場特化 管理システム"
echo "セットアップを開始します"
echo "=========================================="
echo ""

# Firebase CLI 確認
echo "▶ Firebase CLI を確認中..."
if ! command -v firebase &> /dev/null; then
  echo "❌ Firebase CLI がインストールされていません"
  echo "   npm install -g firebase-tools を実行してください"
  exit 1
fi
echo "✓ Firebase CLI: $(firebase --version)"
echo ""

# Node.js 確認
echo "▶ Node.js を確認中..."
if ! command -v node &> /dev/null; then
  echo "❌ Node.js がインストールされていません"
  exit 1
fi
echo "✓ Node.js: $(node -v)"
echo "✓ npm: $(npm -v)"
echo ""

# Firebase ログイン
echo "▶ Firebase ログイン状態を確認中..."
if ! firebase projects:list &> /dev/null; then
  echo "⚠️  Firebase にログインが必要です"
  echo "   'firebase login' を実行してください"
  exit 1
fi
echo "✓ Firebase ログイン済み"
echo ""

# Firebase プロジェクト確認
echo "▶ Firebase プロジェクト設定を確認中..."
PROJECT_ID=$(grep '"default"' .firebaserc | grep -oP ':\s*"\K[^"]+')

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "YOUR_PROJECT_ID" ]; then
  echo ""
  echo "❌ Firebase プロジェクトの設定が必要です"
  echo ""
  echo "以下の手順を実行してください："
  echo ""
  echo "1️⃣  https://console.firebase.google.com にアクセス"
  echo "2️⃣  新規プロジェクトを作成（例：yuime-dev）"
  echo "3️⃣  次のコマンドでプロジェクトを設定："
  echo ""
  echo "    firebase use --add"
  echo ""
  echo "4️⃣  Firebase Console で以下を有効化："
  echo "    • Authentication → メール/パスワード"
  echo "    • Firestore Database → 本番モード"
  echo "    • Cloud Storage"
  echo ""
  echo "5️⃣  プロジェクト設定から firebaseConfig をコピーし、"
  echo "    public/js/firebase-config.js に貼り付け"
  echo ""
  exit 1
fi

echo "✓ プロジェクトID: $PROJECT_ID"
echo ""

# ローカル環境変数
echo "▶ 環境設定中..."
export GOOGLE_APPLICATION_CREDENTIALS=""
echo "✓ 環境変数設定完了"
echo ""

echo "=========================================="
echo "セットアップ完了！"
echo "=========================================="
echo ""
echo "次のコマンドで開発サーバーを起動できます："
echo ""
echo "  npm start              # ホスティングのみ"
echo "  npm run emulate        # エミュレータ（完全なローカル環境）"
echo "  npm run deploy         # デプロイ"
echo ""
echo "初回のみ、管理者アカウント作成が必要です："
echo "  http://localhost:5000/setup-admin.html"
echo ""
