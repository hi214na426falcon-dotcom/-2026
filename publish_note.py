#!/usr/bin/env python3
"""
note.com 下書き自動入力スクリプト

使い方:
  python publish_note.py drafts/01_原体験.md

仕組み:
  - 初回だけ、開いたブラウザで自分でnote.comにログインする（手動）。
  - ログイン状態は .note_browser_data フォルダに保存されるので、
    2回目以降はログイン不要で、いきなり記事入力まで自動で進む。
  - タイトルと本文を自動入力 → 「公開する」ボタンを押すだけの状態で止まる。

メール/パスワードをスクリプトに渡す必要はありません。
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# ログイン状態を保存するフォルダ（このフォルダがあればログイン継続）
USER_DATA_DIR = str(Path(__file__).parent / ".note_browser_data")


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


def type_body(page, body: str):
    """本文を1行ずつ入力する（ProseMirrorエディタに段落として入る）"""
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if line:
            page.keyboard.insert_text(line)
        if i < len(lines) - 1:
            page.keyboard.press("Enter")


def main():
    if len(sys.argv) < 2:
        print("使い方: python publish_note.py <下書きファイルのパス>")
        print("例:     python publish_note.py drafts/01_原体験.md")
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
        context = p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()

        # 新規記事ページを開く
        page.goto("https://note.com/notes/new")
        time.sleep(4)

        # ログインしているか確認（ログインページに飛ばされたら手動ログイン）
        if "login" in page.url or "signup" in page.url:
            print("\n" + "="*54)
            print("【初回のみ】開いたブラウザでnote.comにログインしてください。")
            print("ログインが終わったら、この画面で Enter を押してください。")
            print("（次回からはログイン不要で自動で進みます）")
            print("="*54)
            input("\nログインが終わったら Enter を押す > ")
            page.goto("https://note.com/notes/new")
            time.sleep(4)

        # タイトル入力
        title_ok = False
        for sel in [
            'textarea[placeholder="記事タイトル"]',
            'textarea[placeholder*="タイトル"]',
            'input[placeholder*="タイトル"]',
            '[data-testid="editor-title"]',
        ]:
            try:
                el = page.locator(sel).first
                el.wait_for(state="visible", timeout=3000)
                el.click()
                page.keyboard.insert_text(title)
                title_ok = True
                print("タイトル入力完了")
                break
            except Exception:
                continue
        if not title_ok:
            print("※ タイトルを自動入力できませんでした。手動で入力してください。")

        time.sleep(1)

        # 本文入力
        body_ok = False
        for sel in [
            '.ProseMirror',
            '[contenteditable="true"]',
        ]:
            try:
                el = page.locator(sel).first
                el.wait_for(state="visible", timeout=3000)
                el.click()
                time.sleep(0.5)
                type_body(page, body)
                body_ok = True
                print("本文入力完了")
                break
            except Exception:
                continue
        if not body_ok:
            print("※ 本文を自動入力できませんでした。手動で貼り付けてください。")

        print("\n" + "="*54)
        print("✅ 準備完了！")
        print("内容を確認して「公開する」ボタンを押してください。")
        print("（このPowerShell画面で Enter を押すとブラウザを閉じます）")
        print("="*54)
        input("\n投稿が終わったら Enter を押す > ")
        context.close()


if __name__ == "__main__":
    main()
