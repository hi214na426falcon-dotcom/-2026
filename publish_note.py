#!/usr/bin/env python3
"""
note.com 下書き自動入力スクリプト

使い方:
  python publish_note.py drafts/01_原体験.md

事前準備:
  同じフォルダの .env ファイルに以下を書く
    NOTE_EMAIL=your@email.com
    NOTE_PASSWORD=yourpassword

動作:
  ブラウザが開いてnote.comにログイン → タイトルと本文を自動入力 →
  「公開する」ボタンを押すだけの状態で止まる（自分でクリックして投稿）
"""

import sys
import os
import time
from pathlib import Path

# .envファイルを自動で読み込む
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv未インストールの場合は環境変数から読む

from playwright.sync_api import sync_playwright


def extract_title_and_body(filepath: str) -> tuple:
    content = Path(filepath).read_text(encoding="utf-8")
    lines = content.strip().split("\n")

    title = ""
    body_lines = []

    for line in lines:
        if not title and line.startswith("# "):
            title = line[2:].strip()
        elif title:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    return title, body


def main():
    if len(sys.argv) < 2:
        print("使い方: python publish_note.py <下書きファイルのパス>")
        print("例:     python publish_note.py drafts/01_原体験.md")
        sys.exit(1)

    email = os.environ.get("NOTE_EMAIL")
    password = os.environ.get("NOTE_PASSWORD")

    if not email or not password:
        print("エラー: .envファイルにNOTE_EMAILとNOTE_PASSWORDを設定してください。")
        sys.exit(1)

    draft_path = sys.argv[1]
    if not Path(draft_path).exists():
        print(f"エラー: ファイルが見つかりません → {draft_path}")
        sys.exit(1)

    title, body = extract_title_and_body(draft_path)
    print(f"\nタイトル: {title}")
    print(f"本文冒頭: {body[:40]}...\n")
    print("ブラウザを起動しています...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # ログイン
        page.goto("https://note.com/login")
        page.wait_for_selector('input[name="email"]', timeout=10000)
        page.fill('input[name="email"]', email)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_url("**/note.com/**", timeout=15000)
        time.sleep(2)
        print("ログイン完了")

        # 新規記事作成ページへ
        page.goto("https://note.com/notes/new")
        time.sleep(3)

        # タイトル入力
        try:
            title_el = page.locator(
                'textarea[placeholder*="タイトル"], '
                'input[placeholder*="タイトル"], '
                '[data-testid="editor-title"]'
            ).first
            title_el.click()
            title_el.fill(title)
            time.sleep(1)
            print("タイトル入力完了")
        except Exception:
            print("警告: タイトル欄を自動入力できませんでした。手動でタイトルを入力してください。")

        # 本文入力（クリップボード経由でペースト）
        try:
            body_el = page.locator(
                '.ProseMirror, '
                '[contenteditable="true"]:not([data-testid="editor-title"])'
            ).first
            body_el.click()
            page.evaluate(f"navigator.clipboard.writeText({repr(body)})")
            time.sleep(0.5)
            body_el.press("Control+a")
            body_el.press("Control+v")
            time.sleep(2)
            print("本文入力完了")
        except Exception:
            print("警告: 本文を自動入力できませんでした。手動で本文を貼り付けてください。")

        print("\n" + "="*50)
        print("✅ 準備完了！")
        print("「公開する」ボタンを押して投稿してください。")
        print("（ウィンドウを閉じるとスクリプトが終了します）")
        print("="*50 + "\n")

        # ユーザーが投稿操作するまでウィンドウを保持（最大10分）
        page.wait_for_timeout(600000)
        browser.close()


if __name__ == "__main__":
    main()
