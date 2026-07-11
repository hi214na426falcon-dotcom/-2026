#!/usr/bin/env python3
"""フォワードテストのワンコマンド起動（手元PC用）。

やること:
1. forward_test.json が無い/7日より古い → run_wf_pick.py --emit で再生成
2. live_pull.py をバックグラウンド起動（ピックの全ペア。完了時間の裏埋め用）
3. predict_server.py をフォアグラウンド起動（Ctrl+C で全部止まる）

あとは Chrome に overlay/ を読み込んでザオプションを開くだけ。
画面のレート数字をパネルの「⌖ レート取得」でクリック指定すると、
遅延ゼロのライブ価格でシグナルが動く。

使い方:
    python3 start_forward_test.py
    python3 start_forward_test.py --port 8765
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
FWD = os.path.join(ROOT, "overlay", "server", "forward_test.json")


def ensure_picks() -> list:
    age_ok = (os.path.exists(FWD)
              and time.time() - os.path.getmtime(FWD) < 7 * 86400)
    if not age_ok:
        print("[start] ピックを再生成します（数分かかります）…")
        subprocess.run([sys.executable, os.path.join(ROOT, "run_wf_pick.py"),
                        "--emit"], cwd=ROOT, check=True)
    with open(FWD, encoding="utf-8") as f:
        picks = json.load(f).get("picks", [])
    print(f"[start] ピック {len(picks)} 本:",
          ", ".join(f"{p['pair']}({p['expiry_min']}分)" for p in picks))
    return picks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-live-pull", action="store_true",
                    help="Dukascopy裏埋めを起動しない（画面レート取得のみで運用）")
    args = ap.parse_args()

    picks = ensure_picks()
    pairs = sorted({p["pair"] for p in picks}) or ["CHFJPY"]

    procs = []
    if not args.no_live_pull:
        procs.append(subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "overlay", "server",
                                          "live_pull.py"), "--pair", *pairs],
            cwd=ROOT))
        print(f"[start] live_pull 起動: {pairs}")

    print(f"[start] 予測サーバー http://127.0.0.1:{args.port} — Ctrl+C で終了")
    try:
        subprocess.run([sys.executable,
                        os.path.join(ROOT, "overlay", "server",
                                     "predict_server.py"),
                        "--port", str(args.port)],
                       cwd=os.path.join(ROOT, "overlay", "server"))
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
