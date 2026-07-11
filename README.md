# APIキーのセットアップ

Nano Banana 2(Gemini API)にアクセスするためのAPIキーの保存手順です。

## 手順

1. [Google AI Studio](https://aistudio.google.com/apikey) でAPIキーを作成する
2. テンプレートをコピーして `.env` ファイルを作る

   ```bash
   cp .env.example .env
   ```

3. `.env` を開いて、取得したキーを記入する

   ```
   GEMINI_API_KEY=AIzaSy...(自分のキー)
   ```

`.env` は `.gitignore` に登録済みのため、Gitにコミットされることはありません。

## 注意

- APIキーをソースコードに直接書かないでください
- キーを誤って公開した場合は、Google AI Studio ですぐに無効化して再発行してください
