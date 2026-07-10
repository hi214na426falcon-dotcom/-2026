#!/usr/bin/env python3
"""HistData.com の M1 アーカイブから data/m1/<PAIR>.csv.gz を作る（複数ペア対応）。

Dukascopy の時間別ティック取得（fetch_dukascopy.py）は 1 リクエスト約 21 秒の
スロットリングを受け、GitHub Actions の 6 時間制限内に 3 年分を完走できないことが
実測で判明した（2026-07-10 プローブ: 42 ファイル 902 秒、データ自体は正常）。
本スクリプトは同じ実データ源として月次/年次の一括 zip（HistData.com、
philipperemy/FX-1-Minute-Data と同じ経路 = `pip install histdata`）を使う。

- HistData の時刻は EST (UTC-5, DST なし年間固定)。UTC に変換して ISO8601 で出力。
- GMT 8-21 時（= JST 17 時〜翌 6 時）にフィルタ。
- 期間は [2023-07-01, 2026-07-01) にフィルタ（MASTER_PROMPT の指定範囲）。
- 出力は gzip 圧縮 CSV（リポジトリ肥大防止）。backtest.data.load_csv は .gz 対応。

使い方（Actions ランナーまたは通常ネットの PC で）:
    pip install histdata
    python3 data/fetch_histdata.py EURJPY USDJPY GBPJPY ...
"""
import csv
import glob
import gzip
import io
import os
import shutil
import sys
import zipfile
from datetime import datetime, timedelta, timezone

from histdata.api import download_hist_data

PAIRS = [a.upper() for a in sys.argv[1:]] or ["EURJPY"]
T_FROM = datetime(2023, 7, 1, tzinfo=timezone.utc)
T_TO = datetime(2026, 7, 1, tzinfo=timezone.utc)
HOURS_GMT = set(range(8, 22))
EST = timezone(timedelta(hours=-5))  # HistData は年間固定 GMT-5


def download_pair(pair: str, dl_dir: str) -> int:
    got = 0
    for year in range(T_FROM.year, T_TO.year + 1):
        try:
            p = download_hist_data(year=year, pair=pair.lower(),
                                   output_directory=dl_dir, verbose=False)
            print(f"[DL] {pair} {year} 通年 -> {p}", flush=True)
            got += 1
            continue
        except AssertionError:
            pass  # 通年 zip なし（当年）→ 月別へ
        except Exception as e:
            print(f"[skip] {pair} {year} 通年: {e}", file=sys.stderr, flush=True)
        for month in range(1, 13):
            try:
                p = download_hist_data(year=str(year), month=str(month),
                                       pair=pair.lower(),
                                       output_directory=dl_dir, verbose=False)
                print(f"[DL] {pair} {year}-{month:02d} -> {p}", flush=True)
                got += 1
            except Exception as e:
                print(f"[skip] {pair} {year}-{month:02d}: {e}",
                      file=sys.stderr, flush=True)
    return got


def build_csv(pair: str, dl_dir: str) -> int:
    rows = {}
    for z in sorted(glob.glob(os.path.join(dl_dir, "*.zip"))):
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
                    for line in io.TextIOWrapper(f, encoding="ascii",
                                                 errors="replace"):
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
    out = os.path.join("data", "m1", f"{pair}.csv.gz")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for t in sorted(rows):
            o, h, l, c, v = rows[t]
            w.writerow([t, f"{o:.5f}", f"{h:.5f}", f"{l:.5f}", f"{c:.5f}",
                        f"{v:.0f}"])
    print(f"[OUT] {out}: {len(rows)} 行", flush=True)
    return len(rows)


def main() -> int:
    ok = 0
    for pair in PAIRS:
        dl_dir = os.path.join("dl", pair.lower())
        os.makedirs(dl_dir, exist_ok=True)
        if download_pair(pair, dl_dir) == 0:
            print(f"[NG] {pair}: 何もダウンロードできませんでした",
                  file=sys.stderr, flush=True)
            continue
        if build_csv(pair, dl_dir) > 0:
            ok += 1
        shutil.rmtree(dl_dir, ignore_errors=True)  # ランナーのディスク節約
    print(f"[DONE] {ok}/{len(PAIRS)} ペア成功")
    return 0 if ok == len(PAIRS) else (0 if ok > 0 else 1)


if __name__ == "__main__":
    raise SystemExit(main())
