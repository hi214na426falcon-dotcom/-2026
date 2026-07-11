#!/usr/bin/env python3
"""Coinbase Exchange 公開APIから暗号資産の1分足を取得し data/m1/<NAME>.csv.gz を作る。

ザオプションの土日取引（BTC/ETH）検証用。認証不要・標準ライブラリのみ。
- 期間 [2023-07-01, 現在)、GMT 8-21時（JST 17-翌6時）にフィルタ（FXと同一条件）
- 1リクエスト300本まで → 300分窓で分割取得（レート制限対策のスリープ付き）
- 出力はFXと同じスキーマ（time,open,high,low,close,volume・UTC ISO・gzip）

注意（正直に）: ザオプションの判定レートは業者自身の配信で、Coinbase の
USD建てとは水準も微差もある。方向パターンの検証用プロキシとして使う。

使い方:
    python3 data/fetch_crypto.py BTCUSD
    python3 data/fetch_crypto.py ETHUSD BTCUSD
"""
import csv
import gzip
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://api.exchange.coinbase.com"
PRODUCTS = {"BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD"}
T_FROM = datetime(2023, 7, 1, tzinfo=timezone.utc)
HOURS_GMT = (8, 22)  # [8, 22) = JST 17〜翌7時直前（FXと同じ8-21時台）
CA_BUNDLE = os.environ.get("CCR_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")


def _get(url: str, retries: int = 4) -> list:
    ctx = ssl.create_default_context()
    if os.path.exists(CA_BUNDLE):
        try:
            ctx.load_verify_locations(CA_BUNDLE)
        except Exception:
            pass
    req = urllib.request.Request(url, headers={"User-Agent": "binary-research/0.1"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return []


def fetch_pair(name: str) -> int:
    product = PRODUCTS[name]
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    out = os.path.join("data", "m1", f"{name}.csv.gz")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    rows = {}
    day = T_FROM
    req_count = 0
    while day < now:
        # 1日の 8:00-21:59 GMT を 300分×3窓で取る
        for h0, h1 in ((8, 13), (13, 18), (18, 22)):
            start = day.replace(hour=h0)
            end = day.replace(hour=h1) - timedelta(minutes=1)
            if start >= now:
                break
            url = (f"{BASE}/products/{product}/candles?granularity=60"
                   f"&start={start.isoformat()}&end={end.isoformat()}")
            data = _get(url)
            req_count += 1
            for row in data or []:
                # [epoch, low, high, open, close, volume] 新しい順
                try:
                    t = datetime.fromtimestamp(int(row[0]), tz=timezone.utc)
                    lo, hi, op, cl = (float(row[i]) for i in (1, 2, 3, 4))
                    vol = float(row[5])
                except (ValueError, IndexError, TypeError):
                    continue
                if not (HOURS_GMT[0] <= t.hour < HOURS_GMT[1]) or t < T_FROM:
                    continue
                rows[t.isoformat()] = (op, hi, lo, cl, vol)
            time.sleep(0.25)
        day += timedelta(days=1)
        if day.day == 1:
            print(f"  {name} {day.date()} まで / {len(rows):,} 本 "
                  f"({req_count} req)", file=sys.stderr, flush=True)
    with gzip.open(out, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for t in sorted(rows):
            op, hi, lo, cl, vol = rows[t]
            w.writerow([t, f"{op:.2f}", f"{hi:.2f}", f"{lo:.2f}",
                        f"{cl:.2f}", f"{vol:.4f}"])
    print(f"[OUT] {out}: {len(rows):,} 行")
    return len(rows)


def main() -> int:
    names = [a.upper() for a in sys.argv[1:]] or ["BTCUSD", "ETHUSD"]
    ok = 0
    for name in names:
        if name not in PRODUCTS:
            print(f"[skip] 未対応: {name}（対応: {list(PRODUCTS)}）",
                  file=sys.stderr)
            continue
        if fetch_pair(name) > 0:
            ok += 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
