#!/usr/bin/env python3
"""
note.com 下書き自動入力スクリプト（普段使いのChromeに後から接続する方式）

なぜこの方式か:
  note.comはログイン時にreCAPTCHAを出す。自動操作で立ち上げたブラウザは
  ロボット判定されてログインできない。そこで「自分で普通にログインした
  Chrome」に、このスクリプトを後から接続して記事だけ入力する。

使い方:
  ① start_chrome.bat をダブルクリック
     → デバッグ用Chromeが開く。note.comに普通にログインする（初回だけ）。
  ② PowerShellで実行:
       python publish_note.py drafts/01_原体験.md
     → ①のChromeに接続し、タイトルと本文を自動入力。
       あとは「公開する」を押すだけの状態で止まる。
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"


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

    with sync_playwright() as p:
        # 先に起動済みのChrome（start_chrome.bat）に接続する
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception:
            print("="*54)
            print("Chromeに接続できませんでした。")
            print("先に start_chrome.bat をダブルクリックしてChromeを開き、")
            print("note.comにログインしてから、もう一度実行してください。")
            print("="*54)
            sys.exit(1)

        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()

        # 新規記事ページを開く
        page.goto("https://note.com/notes/new")
        time.sleep(4)

        # ログインしているか確認
        if "login" in page.url or "signup" in page.url:
            print("="*54)
            print("まだログインしていないようです。")
            print("開いているChromeでnote.comにログインしてから、")
            print("このPowerShellで Enter を押してください。")
            print("="*54)
            input("\nログインが終わったら Enter > ")
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
        for sel in ['.ProseMirror', '[contenteditable="true"]']:
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
        print("="*54)


if __name__ == "__main__":
    main()
