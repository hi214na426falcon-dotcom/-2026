#!/usr/bin/env python3
"""ライブ価格の取り込み（手元PC用・表示専用フォワードテストの燃料）。

Dukascopy の「現在のGMT時間」のティックファイルを60秒ごとに取得し、
1分足にして data/m1/<PAIR>_live.csv に上書き保存する。
live_feed.recent_bars は最終更新が最新のファイルを優先するため、
これを回しておくだけで predict_server のシグナルが現在値で動く。

※ Dukascopy の配信は数十秒〜数分の遅延がある。判定1分のピックには不向きで、
   判定3〜5分のピック向け（runbook の注意どおり）。

使い方（オーバーレイを使う間、別ターミナルで回しっぱなし）:
    python3 overlay/server/live_pull.py --pair CHFJPY
    python3 overlay/server/live_pull.py --pair CHFJPY USDJPY --interval 60
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "data"))

from fetch_dukascopy import fetch_hour  # noqa: E402

DATA_DIR = os.path.join(REPO_ROOT, "data", "m1")


def pull_once(pair: str) -> int:
    """現在時間と直前1時間ぶんを取得して <PAIR>_live.csv を書き直す。"""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    rows = []
    for dt in (now - timedelta(hours=1), now):
        bars = fetch_hour(pair, dt)
        if bars:
            rows.extend(bars)
    if not rows:
        return 0
    out = os.path.join(DATA_DIR, f"{pair}_live.csv")
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("time,open,high,low,close,volume\n")
        for b in rows:
            f.write(f"{b['time']},{b['open']:.5f},{b['high']:.5f},"
                    f"{b['low']:.5f},{b['close']:.5f},{b['volume']:.0f}\n")
    os.replace(tmp, out)
    return len(rows)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Dukascopy ライブ1分足の取り込み")
    p.add_argument("--pair", nargs="+", default=["CHFJPY"])
    p.add_argument("--interval", type=int, default=60, help="取得間隔 秒（既定60）")
    p.add_argument("--once", action="store_true", help="1回だけ取得して終了")
    args = p.parse_args(argv)
    pairs = [x.upper() for x in args.pair]
    print(f"[live] {pairs} を {args.interval} 秒ごとに取得 → data/m1/<PAIR>_live.csv")
    while True:
        for pair in pairs:
            try:
                n = pull_once(pair)
                stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
                print(f"[live {stamp}Z] {pair}: {n} 本", flush=True)
            except Exception as e:
                print(f"[live] {pair}: 取得失敗 {e}", file=sys.stderr, flush=True)
        if args.once:
            return 0
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
