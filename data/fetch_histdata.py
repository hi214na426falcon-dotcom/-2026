#!/usr/bin/env python3
"""HistData.com の M1 アーカイブから data/m1/<PAIR>.csv を作る。

Dukascopy の時間別ティック取得（fetch_dukascopy.py）は 1 リクエスト約 21 秒の
スロットリングを受け、GitHub Actions の 6 時間制限内に 3 年分を完走できないことが
実測で判明した（2026-07-10 プローブ: 42 ファイル 902 秒、データ自体は正常）。
本スクリプトは同じ実データ源として月次/年次の一括 zip（HistData.com、
philipperemy/FX-1-Minute-Data と同じ経路 = `pip install histdata`）を使う。

- HistData の時刻は EST (UTC-5, DST なし年間固定)。UTC に変換して ISO8601 で出力。
- GMT 8-21 時（= JST 17 時〜翌 6 時）にフィルタ。
- 期間は [2023-07-01, 2026-07-01) にフィルタ（MASTER_PROMPT の指定範囲）。

使い方（Actions ランナーまたは通常ネットの PC で）:
    pip install histdata
    python3 data/fetch_histdata.py EURJPY
"""
import csv
import glob
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone

from histdata.api import download_hist_data

PAIR = (sys.argv[1] if len(sys.argv) > 1 else "EURJPY").upper()
T_FROM = datetime(2023, 7, 1, tzinfo=timezone.utc)
T_TO = datetime(2026, 7, 1, tzinfo=timezone.utc)
OUT = os.path.join("data", "m1", f"{PAIR}.csv")
HOURS_GMT = set(range(8, 22))
EST = timezone(timedelta(hours=-5))  # HistData は年間固定 GMT-5

os.makedirs("dl", exist_ok=True)
got = 0
for year in range(T_FROM.year, T_TO.year + 1):
    try:
        p = download_hist_data(year=year, pair=PAIR.lower(),
                               output_directory="dl", verbose=False)
        print(f"[DL] {year} 通年 -> {p}", flush=True)
        got += 1
        continue
    except AssertionError:
        pass  # 通年 zip なし（当年）→ 月別へ
    except Exception as e:
        print(f"[skip] {year} 通年: {e}", file=sys.stderr, flush=True)
    for month in range(1, 13):
        try:
            p = download_hist_data(year=str(year), month=str(month),
                                   pair=PAIR.lower(),
                                   output_directory="dl", verbose=False)
            print(f"[DL] {year}-{month:02d} -> {p}", flush=True)
            got += 1
        except Exception as e:
            print(f"[skip] {year}-{month:02d}: {e}", file=sys.stderr, flush=True)

if got == 0:
    print("何もダウンロードできませんでした（HistData も遮断の可能性）", file=sys.stderr)
    sys.exit(1)

rows = {}
for z in sorted(glob.glob("dl/*.zip")):
    try:
        zf = zipfile.ZipFile(z)
    except zipfile.BadZipFile:
        print(f"[skip] 壊れた zip: {z}", file=sys.stderr)
        continue
    with zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            with zf.open(name) as f:
                for line in f.read().decode("ascii", "replace").splitlines():
                    parts = line.strip().split(";")
                    if len(parts) < 5:
                        continue
                    try:
                        t = datetime.strptime(parts[0], "%Y%m%d %H%M%S")
                        o, h, l, c = (float(x) for x in parts[1:5])
                    except ValueError:
                        continue
                    t = t.replace(tzinfo=EST).astimezone(timezone.utc)
                    if t.hour not in HOURS_GMT or not (T_FROM <= t < T_TO):
                        continue
                    v = float(parts[5]) if len(parts) > 5 else 0.0
                    rows[t.isoformat()] = (o, h, l, c, v)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["time", "open", "high", "low", "close", "volume"])
    for t in sorted(rows):
        o, h, l, c, v = rows[t]
        w.writerow([t, f"{o:.5f}", f"{h:.5f}", f"{l:.5f}", f"{c:.5f}", f"{v:.0f}"])
print(f"[OUT] {OUT}: {len(rows)} 行")
sys.exit(0 if rows else 1)
