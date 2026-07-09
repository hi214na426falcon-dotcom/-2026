#!/usr/bin/env python3
"""Dukascopy の無料ティックデータを取得し、1分足CSV(data/m1/<PAIR>.csv)に整形する。

MASTER_PROMPT が指定するデータ元（Dukascopy）に対応。ティック(.bi5, LZMA圧縮)を
ダウンロード → 1分足 OHLC に集約 → close/price 列付きCSVで保存する。

【この環境について】組織のエグレスポリシーで datafeed.dukascopy.com への接続は
遮断されています（403）。そのため実ダウンロードは **ひなの手元PC（通常のネット）**
で実行してください。パースロジックはネット不要の自己テスト(--self-test)で検証済みです。

使い方（手元PCで）:
    # まずパーサの自己テスト（ネット不要）
    python3 data/fetch_dukascopy.py --self-test

    # 1本の接続確認
    python3 data/fetch_dukascopy.py --probe --pair EURUSD

    # 期間を指定してダウンロード（JSTの夜＋深夜に対応するGMT時間帯だけでも可）
    python3 data/fetch_dukascopy.py --pair EURJPY --from 2023-07-01 --to 2026-07-01
    python3 data/fetch_dukascopy.py --pair EURJPY --from 2026-04-01 --to 2026-07-01 \
        --hours 8-21           # GMT8-21 ≒ JST17-翌6時の範囲に絞って軽量化
"""

from __future__ import annotations

import argparse
import lzma
import os
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
REC = struct.Struct(">IIIff")  # ms_offset, ask, bid, ask_vol, bid_vol（ビッグエンディアン）
CA_BUNDLE = os.environ.get("CCR_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")


def pair_scale(pair: str) -> int:
    """整数価格→実価格の割り算スケール。JPYクロスは1e3、それ以外1e5。"""
    return 1000 if pair.upper().endswith("JPY") else 100000


def decompress_bi5(data: bytes) -> bytes:
    """.bi5（LZMA alone）を展開。空データは空バイト列。"""
    if not data:
        return b""
    try:
        return lzma.decompress(data)  # FORMAT_AUTO
    except lzma.LZMAError:
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        return dec.decompress(data)


def parse_ticks(raw: bytes, scale: int) -> List[Tuple[int, float, float]]:
    """展開済みバイト列を (ms_offset, mid_price, volume) のリストに変換。"""
    out = []
    for off in range(0, len(raw) - REC.size + 1, REC.size):
        ms, ask, bid, av, bv = REC.unpack_from(raw, off)
        mid = (ask + bid) / 2.0 / scale
        out.append((ms, mid, float(av) + float(bv)))
    return out


def ticks_to_minute_bars(
    ticks: List[Tuple[int, float, float]], hour_start: datetime
) -> List[Dict]:
    """1時間ぶんのティックを1分足OHLCに集約する。"""
    buckets: Dict[int, List] = {}
    for ms, price, vol in ticks:
        minute = ms // 60000
        buckets.setdefault(minute, []).append((ms, price, vol))
    bars = []
    for minute in sorted(buckets):
        rows = sorted(buckets[minute])
        prices = [p for _, p, _ in rows]
        t = hour_start + timedelta(minutes=minute)
        bars.append({
            "time": t.isoformat(),
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": sum(v for _, _, v in rows),
        })
    return bars


def _http_get(url: str, timeout: int = 30) -> bytes:
    ctx = ssl.create_default_context()
    if os.path.exists(CA_BUNDLE):
        try:
            ctx.load_verify_locations(CA_BUNDLE)
        except Exception:
            pass
    req = urllib.request.Request(url, headers={"User-Agent": "binary-overlay/0.2"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def hour_url(pair: str, dt: datetime) -> str:
    # ★ Dukascopy の月は 0 始まり（1月=00）
    return (f"{BASE_URL}/{pair.upper()}/{dt.year:04d}/{dt.month - 1:02d}/"
            f"{dt.day:02d}/{dt.hour:02d}h_ticks.bi5")


def fetch_hour(pair: str, dt: datetime, retries: int = 3) -> Optional[List[Dict]]:
    """1時間ぶんを取得して1分足に。取得不可なら None。"""
    url = hour_url(pair, dt)
    for attempt in range(retries):
        try:
            data = _http_get(url)
            raw = decompress_bi5(data)
            return ticks_to_minute_bars(parse_ticks(raw, pair_scale(pair)),
                                        dt.replace(minute=0, second=0, microsecond=0))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []  # その時間は取引なし（週末等）
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    return None


def parse_hours_arg(s: Optional[str]) -> List[int]:
    if not s:
        return list(range(24))
    if "-" in s:
        a, b = s.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


def download(pair: str, dt_from: datetime, dt_to: datetime, hours: List[int],
             out_path: str, delay: float = 0.1) -> int:
    """期間×時間帯をダウンロードしCSVに追記保存。書けた行数を返す。"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    write_header = not os.path.exists(out_path) or os.path.getsize(out_path) == 0
    total = 0
    blocked = 0
    with open(out_path, "a", encoding="utf-8") as f:
        if write_header:
            f.write("time,open,high,low,close,volume\n")
        day = dt_from
        while day < dt_to:
            for h in hours:
                dt = day.replace(hour=h)
                bars = fetch_hour(pair, dt)
                if bars is None:
                    blocked += 1
                    if blocked <= 1:
                        print(f"  [取得失敗] {hour_url(pair, dt)}", file=sys.stderr)
                    continue
                for b in bars:
                    f.write(f"{b['time']},{b['open']:.5f},{b['high']:.5f},"
                            f"{b['low']:.5f},{b['close']:.5f},{b['volume']:.0f}\n")
                    total += 1
                time.sleep(delay)
            day += timedelta(days=1)
            print(f"  {day.date()} まで完了 / 累計 {total} 本", file=sys.stderr)
    if blocked and total == 0:
        print("[警告] 1本も取得できませんでした。この環境ではエグレスが遮断されています。"
              "通常ネットのPCで実行してください。", file=sys.stderr)
    return total


# --- 自己テスト（ネット不要） ------------------------------------------------

def self_test() -> int:
    scale = 100000
    ticks = [
        (1000, 110000, 110000, 1.0, 1.0),    # min0 1.10000
        (30000, 110050, 110050, 1.0, 1.0),   # min0 1.10050
        (61000, 110100, 110100, 2.0, 0.0),   # min1 1.10100
        (121000, 110080, 110080, 0.0, 3.0),  # min2 1.10080
    ]
    raw = b"".join(REC.pack(*t) for t in ticks)
    comp = lzma.compress(raw, format=lzma.FORMAT_ALONE)  # bi5 相当
    parsed = parse_ticks(decompress_bi5(comp), scale)
    assert len(parsed) == 4, parsed
    bars = ticks_to_minute_bars(parsed, datetime(2024, 1, 1, 10, tzinfo=timezone.utc))
    assert len(bars) == 3, bars
    b0, b1, b2 = bars
    assert abs(b0["open"] - 1.10000) < 1e-9 and abs(b0["close"] - 1.10050) < 1e-9, b0
    assert abs(b0["high"] - 1.10050) < 1e-9 and abs(b0["low"] - 1.10000) < 1e-9, b0
    assert abs(b1["close"] - 1.10100) < 1e-9, b1
    assert abs(b2["close"] - 1.10080) < 1e-9, b2
    assert abs(b0["volume"] - 4.0) < 1e-9, b0
    # 空データも安全
    assert ticks_to_minute_bars(parse_ticks(decompress_bi5(b""), scale),
                                datetime(2024, 1, 1)) == []
    print("=== fetch_dukascopy 自己テスト成功 ===")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Dukascopy 1分足ダウンローダ/整形")
    p.add_argument("--pair", default="EURUSD")
    p.add_argument("--from", dest="dfrom", help="開始日 YYYY-MM-DD")
    p.add_argument("--to", dest="dto", help="終了日 YYYY-MM-DD（排他）")
    p.add_argument("--hours", help="GMT時間帯 例 8-21 または 8,9,10（既定 全24時間）")
    p.add_argument("--out", help="出力CSV（既定 data/m1/<PAIR>.csv）")
    p.add_argument("--self-test", action="store_true", help="パーサの自己テスト（ネット不要）")
    p.add_argument("--probe", action="store_true", help="1時間ぶんの接続確認だけ行う")
    args = p.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.probe:
        dt = datetime(2024, 1, 2, 10, tzinfo=timezone.utc)
        print(f"[接続確認] {hour_url(args.pair, dt)}")
        bars = fetch_hour(args.pair, dt)
        if bars is None:
            print("  → 取得失敗（この環境ではエグレス遮断の可能性）", file=sys.stderr)
            return 1
        print(f"  → 成功: {len(bars)} 本の1分足を取得")
        return 0

    if not (args.dfrom and args.dto):
        p.error("ダウンロードには --from と --to が必要です（または --self-test）")
    dt_from = datetime.strptime(args.dfrom, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    dt_to = datetime.strptime(args.dto, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "m1", f"{args.pair.upper()}.csv")
    hours = parse_hours_arg(args.hours)
    print(f"[DL] {args.pair} {args.dfrom}..{args.dto} hours={hours[0]}-{hours[-1]} → {out}")
    n = download(args.pair, dt_from, dt_to, hours, out)
    print(f"[DL] 書き出し {n} 本 → {out}")
    return 0 if n > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
