# 動画文字起こし置き場

ここに動画ごとの**字幕/文字起こし**を1本1ファイルで置く（例 `2021-12-01_first-video.md`）。
私（Claude）は動画を直接視聴できないため、ここのテキストから手法を抽出する。

## 命名例
```
YYYY-MM-DD_短いタイトル.md
```

## 各ファイルの推奨ヘッダ（knowledge §22 準拠）
```markdown
---
title: 動画タイトル
url: https://youtube.com/...
published: YYYY-MM-DD
timeframe: 5分/30秒 など
---

（ここに文字起こし本文）
```

## 抽出後の流れ
1. 本文から手法を抽出し、`knowledge/extracted_rules/` に構造化して保存
   （「本人の明言ルール」と「第三者解釈」を分離）。
2. `config/strategies/*.json`（`type: alpaca_scoring` の重み/しきい値）に反映。
3. `python3 -m alpaca_clone.cli backtest ...` で検証。
```
