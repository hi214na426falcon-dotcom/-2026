# yo-writing-style — 小村陽 note文体プロファイル一式

Claude Codeに渡して、note記事を「小村陽本人が書いた文章」として生成するための資料一式。

## 渡し方（Claude Codeで）

このフォルダごとプロジェクトに置いて、最初にこう指示する：

```
yo-writing-style/yo_writing_style.md を読んで。
これが俺の文体プロファイル。これに従ってnoteを書く。
reference/ の中身は素の口調の参照用。
語りの手本はプロファイル本体のサンプルA/Bを使って。
```

## 構成

```
yo-writing-style/
├── README.md                          ← これ
├── yo_writing_style.md                ← 司令塔（最初に読ませる・上位ルール）
└── reference/
    ├── 01_persona_complete.md         ← 総合ペルソナ
    ├── 02_tone_cheatsheet.md          ← 口調チートシート
    ├── 03_conversation_examples.md    ← 関係別の会話例
    └── 04_line_system_prompt.md       ← LINE会話用システムプロンプト
```

## 一番大事な注意

reference の4ファイルは全部 **LINEの会話モード**（短文・テンポ・いじり）。
note は **語りモード**（自分の物語を読ませる長文）。

→ LINEノリをそのまま長文に引き伸ばさない。
→ 語りの正解は `yo_writing_style.md` のサンプルA/B。
→ 詳しくは司令塔ファイルの「⚠️最重要：声を2層で扱う」を読む。
