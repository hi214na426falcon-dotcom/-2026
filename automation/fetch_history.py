#!/usr/bin/env python3
"""XAUUSD 1分足ヒストリー取得ツール（Dukascopy 無料データ -> MT4 .hst）.

Dukascopy の公開データフィードから XAUUSD の1分足（BID）を1日ずつダウンロードし、HFM の
サーバー時間（GMT+2、欧州夏時間中は GMT+3）に変換して、バックテスト用 MT4 の
history/<サーバー名>/XAUUSD1.hst に書き込む。ストラテジーテスターで5年分の M1 テストをするための準備。
ダウンロードした日別ファイルはキャッシュするので、2回目以降は新しい日だけ取得する。標準ライブラリのみ（Python 3.10+）。

使い方:
    python automation/fetch_history.py --mt4-dir "C:/Users/me/AppData/Roaming/MetaQuotes/Terminal/XXXX"
        --server "HFMarketsSV-Demo Server 2" --symbol XAUUSD --from 2021-10-01
    python automation/fetch_history.py ... --offline        # 通信せずキャッシュだけで作り直す
    python automation/fetch_history.py ... --csv xau.csv    # ヒストリーセンター取込用 CSV も保存

書き込み中は MT4 を終了しておくこと。成功すると最後の行に書き込んだ .hst のパスを表示する。
"""
from __future__ import annotations

import argparse
import bisect
import calendar
import contextlib
import glob
import http.client
import lzma
import math
import os
import random
import re
import shutil
import statistics
import struct
import sys
import time
import urllib.error
import urllib.request
from array import array
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import BinaryIO, Iterator, NamedTuple

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
RETRIES = 5
TIMEOUT = 30
REFRESH_DAYS = 2  # 今日と直近この日数はキャッシュがあっても取り直す（未確定データ対策）
DIVISORS = (1000, 100, 100000, 10)  # 価格の割り算値の候補（優先順。XAUUSD は通常 1000）
GOLD_RANGE = (200.0, 20000.0)  # 金価格としてありえる範囲（割り算値の自動判定用）
BI5_REC = struct.Struct(">Iiiiif")  # 秒, 始値, 終値, 安値, 高値, 出来高（Dukascopy の並び順）
HST_HEADER = struct.Struct("<i64s12siiii52x")  # 148 バイト
HST_REC = struct.Struct("<qddddqiq")  # 401: 時刻, 始, 高, 安, 終, ティック出来高, スプレッド, 実出来高（60 バイト）
HST400_REC = struct.Struct("<iddddd")  # 400（旧形式）: 時刻, 始, 安, 高, 終, 出来高
HST_VERSION = 401
COPYRIGHT = b"(C)opyright 2003, MetaQuotes Software Corp."
KEEP_BACKUPS = 2  # 最初のバックアップ（元のブローカーデータ）＋直近この数を残す


class Bar(NamedTuple):
    ctm: int  # サーバー時間を UTC とみなしたエポック秒（MT4 の datetime と同じ）
    open: float
    high: float
    low: float
    close: float
    volume: int


class FetchError(Exception):
    """利用者に日本語でそのまま伝えるエラー."""


# ---------------------------------------------------------------- 日付・サーバー時間

def parse_date(s: str) -> date:
    try:
        return datetime.strptime(re.sub(r"[./]", "-", s.strip()), "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"日付は YYYY-MM-DD 形式で指定してください: {s}") from None


def utc_epoch(day: date) -> int:
    return calendar.timegm(day.timetuple())


def fmt_time(ctm: int) -> str:
    return time.strftime("%Y.%m.%d %H:%M", time.gmtime(ctm))


def trading_days(start: date, end: date) -> list[date]:
    """start～end（両端含む）の日付。土曜は Dukascopy に1分足が無いので除く."""
    days = (start + timedelta(days=n) for n in range((end - start).days + 1))
    return [d for d in days if d.weekday() != 5]


def last_sunday(year: int, month: int) -> date:
    d = date(year, month, calendar.monthrange(year, month)[1])
    return d - timedelta(days=(d.weekday() + 1) % 7)


@lru_cache(maxsize=None)
def eu_dst_utc(year: int) -> tuple[int, int]:
    """欧州夏時間の開始・終了（UTC エポック秒）＝3月・10月の最終日曜 01:00 UTC."""
    return utc_epoch(last_sunday(year, 3)) + 3600, utc_epoch(last_sunday(year, 10)) + 3600


def server_offset(utc_ts: int) -> int:
    """HFM サーバーの UTC との差（秒）: 欧州夏時間中は GMT+3、それ以外は GMT+2."""
    start, end = eu_dst_utc(time.gmtime(utc_ts).tm_year)
    return 3 * 3600 if start <= utc_ts < end else 2 * 3600


def to_server_time(utc_ts: int) -> int:
    return utc_ts + server_offset(utc_ts)


# ---------------------------------------------------------------- ダウンロード・キャッシュ

def day_url(instrument: str, day: date) -> str:
    """1日分の1分足 URL。月は 0 始まり（1月 = 00）."""
    return f"{BASE_URL}/{instrument}/{day.year}/{day.month - 1:02d}/{day.day:02d}/BID_candles_min_1.bi5"


def cache_path(cache_dir: str, instrument: str, day: date) -> str:
    return os.path.join(cache_dir, instrument, str(day.year), f"{day:%Y-%m-%d}_BID_m1.bi5")


def http_get(url: str, timeout: float = TIMEOUT) -> bytes:
    """1回だけ GET する。404（データなし）は空バイト列を返す."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return b""
        raise


def decompress_bi5(data: bytes) -> bytes:
    """bi5（LZMA 圧縮）を展開する。空ならデータなし。壊れていれば ValueError."""
    if not data:
        return b""
    try:
        raw = lzma.decompress(data)
    except lzma.LZMAError as e:
        raise ValueError(f"bi5 を展開できません: {e}") from e
    if len(raw) % BI5_REC.size:
        raise ValueError(f"bi5 のサイズが不正です（{len(raw)} バイト）")
    return raw


def download_bi5(url: str, retries: int = RETRIES) -> tuple[bytes, bytes]:
    """(圧縮データ, 展開データ) を返す。失敗時は間隔を広げながら再試行する."""
    err: Exception | None = None
    for attempt in range(retries):
        if attempt:
            time.sleep(min(60, 2 ** attempt) + random.random())
        try:
            data = http_get(url)
            return data, decompress_bi5(data)
        except (OSError, http.client.HTTPException, ValueError) as e:
            err = e
    raise FetchError(f"ダウンロード失敗（{retries} 回試行）: {url}（{err}）")


def get_day(instrument: str, day: date, cache_dir: str, offline: bool = False,
            refresh: bool = False) -> tuple[str, bytes]:
    """1日分の展開済み bi5 を返す。状態は cached / downloaded / missing（オフラインで未取得）."""
    path = cache_path(cache_dir, instrument, day)
    if os.path.exists(path) and (offline or not refresh):
        with open(path, "rb") as f:
            data = f.read()
        try:
            return "cached", decompress_bi5(data)
        except ValueError:
            os.remove(path)  # 壊れたキャッシュは捨てて取り直す
    if offline:
        return "missing", b""
    data, raw = download_bi5(day_url(instrument, day))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "wb") as f:  # データなしの日も空ファイルで記録する
        f.write(data)
    os.replace(path + ".tmp", path)
    return "downloaded", raw


# ---------------------------------------------------------------- bi5 -> 足

def parse_bi5(raw: bytes) -> list[tuple[int, int, int, int, int, float]]:
    """展開済み bi5 を (秒, 始値, 終値, 安値, 高値, 出来高) の整数価格のまま読む."""
    return list(BI5_REC.iter_unpack(raw))


def detect_divisor(opens: list[int]) -> int:
    """始値の中央値が金価格の範囲に入る割り算値を DIVISORS の優先順で選ぶ."""
    med = statistics.median(opens)
    for d in DIVISORS:
        if GOLD_RANGE[0] <= med / d <= GOLD_RANGE[1]:
            return d
    raise ValueError(f"価格の桁を判定できません（始値の中央値 {med}）。--divisor で指定してください")


def day_bars(day: date, recs: list[tuple], divisor: int, digits: int = 2, min_volume: int = 4) -> list[Bar]:
    """1日分のレコードをサーバー時間の足（昇順・重複なし、同時刻は後勝ち）にする."""
    base, out = utc_epoch(day), {}
    for sec, o, c, lo, hi, vol in recs:
        if min(o, c, lo, hi) <= 0:
            continue
        has_vol = vol > 0 and math.isfinite(vol)
        if not has_vol and o == c == lo == hi:
            continue  # 休場中の埋め草（出来高0・値動きなし）
        ctm = to_server_time(base + sec - sec % 60)
        p = [round(x / divisor, digits) for x in (o, hi, lo, c)]
        out[ctm] = Bar(ctm, p[0], max(p), min(p), p[3], max(min_volume, round(vol) if has_vol else 0))
    return [out[k] for k in sorted(out)]


# ---------------------------------------------------------------- .hst

class BarStore:
    """サーバー時間昇順・重複なしの足を .hst のレコード形式（1本60バイト）でため込む."""

    def __init__(self) -> None:
        self.ctm = array("q")
        self.buf = bytearray()

    def __len__(self) -> int:
        return len(self.ctm)

    def add(self, bars: list[Bar]) -> None:
        """昇順・重複なしの bars を末尾に足す。時刻が重なる部分は並べ直し、同時刻は後から来た足を優先."""
        if bars and self.ctm and bars[0].ctm <= self.ctm[-1]:
            i = bisect.bisect_left(self.ctm, bars[0].ctm)
            merged = {b.ctm: b for b in self.bars(i)}
            merged.update((b.ctm, b) for b in bars)
            del self.ctm[i:], self.buf[i * HST_REC.size:]
            bars = [merged[k] for k in sorted(merged)]
        for b in bars:
            self.ctm.append(b.ctm)
            self.buf += HST_REC.pack(*b, 0, 0)

    def bars(self, start: int = 0) -> Iterator[Bar]:
        data = self.buf if start == 0 else bytes(self.buf[start * HST_REC.size:])
        for r in HST_REC.iter_unpack(data):
            yield Bar(*r[:6])


def write_hst(path: str, symbol: str, digits: int, store: BarStore) -> None:
    """MT4 .hst（バージョン401）を一時ファイル経由で書き込む（途中で失敗しても元のファイルは壊れない）."""
    header = HST_HEADER.pack(HST_VERSION, COPYRIGHT, symbol.encode("ascii"), 1, digits, 0, 0)
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(header)
            f.write(store.buf)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("ascii", "replace")


def _read_header(f: BinaryIO) -> dict:
    raw = f.read(HST_HEADER.size)
    if len(raw) < HST_HEADER.size:
        raise ValueError("ヘッダーが短すぎます")
    ver, cr, sym, period, digits, _timesign, _sync = HST_HEADER.unpack(raw)
    if ver not in (400, 401):
        raise ValueError(f"未対応の .hst バージョンです（{ver}）")
    return {"version": ver, "copyright": _cstr(cr), "symbol": _cstr(sym), "period": period, "digits": digits}


def _iter_records(f: BinaryIO, version: int) -> Iterator[Bar]:
    rec = HST_REC if version == 401 else HST400_REC
    while chunk := f.read(rec.size * 8192):
        for r in rec.iter_unpack(chunk[:len(chunk) - len(chunk) % rec.size]):
            yield Bar(*r[:6]) if version == 401 else Bar(r[0], r[1], r[3], r[2], r[4], int(r[5]))


def read_hst(path: str) -> tuple[dict, list[Bar]]:
    """.hst を (ヘッダー情報, 足のリスト) として読む（バージョン 400/401 対応）."""
    with open(path, "rb") as f:
        header = _read_header(f)
        return header, list(_iter_records(f, header["version"]))


def merge_existing(store: BarStore, path: str) -> int:
    """既存 .hst のうちダウンロード分の最後より新しい足（ブローカーの最新データ）を末尾に足す."""
    last = store.ctm[-1]
    with open(path, "rb") as f:
        header = _read_header(f)
        if header["period"] != 1:
            raise ValueError(f"既存ファイルが M1 ではありません（period={header['period']}）")
        newer = {b.ctm: b for b in _iter_records(f, header["version"]) if b.ctm > last}
    store.add([newer[k] for k in sorted(newer)])
    return len(newer)


def backup_file(path: str, keep: int = KEEP_BACKUPS) -> str:
    """path を <path>.<日時>.bak にコピーする。最初のバックアップと直近 keep 個以外は削除する."""
    dst = f"{path}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
    shutil.copy2(path, dst)
    for old in sorted(glob.glob(glob.escape(path) + ".*.bak"))[1:-keep]:
        os.remove(old)
    return dst


def write_csv(path: str, store: BarStore, digits: int) -> None:
    """MT4 ヒストリーセンター取込用 CSV（YYYY.MM.DD,HH:MM,始,高,安,終,出来高）."""
    with open(path, "w", encoding="ascii", newline="") as f:
        for b in store.bars():
            prices = ",".join(f"{x:.{digits}f}" for x in (b.open, b.high, b.low, b.close))
            f.write(f"{time.strftime('%Y.%m.%d,%H:%M', time.gmtime(b.ctm))},{prices},{b.volume}\r\n")


# ---------------------------------------------------------------- 取得処理

def hst_dir_for(mt4_dir: str, server: str) -> str:
    history = os.path.join(mt4_dir, "history")
    if not os.path.isdir(history):
        raise FetchError(f"MT4 のデータフォルダではありません（history フォルダがありません）: {mt4_dir}\n"
                         "  MT4 の「ファイル > データフォルダを開く」で開く場所を --mt4-dir に指定してください")
    path = os.path.join(history, server)
    if not os.path.isdir(path):
        found = ", ".join(sorted(n for n in os.listdir(history) if os.path.isdir(os.path.join(history, n))))
        raise FetchError(f"サーバーのフォルダがありません: {path}\n"
                         f"  先にこの MT4 でサーバー「{server}」にログインしてください（既存のフォルダ: {found or 'なし'}）")
    return path


def fetch_all(args: argparse.Namespace, days: list[date]) -> tuple[BarStore, dict]:
    """全日を並列で取得し、日付順に足へ変換してため込む."""
    today = datetime.now(timezone.utc).date()
    store, stats, divisors = BarStore(), Counter(), Counter()
    failed: list[str] = []
    empty_weekdays: list[date] = []

    def job(day: date) -> tuple[date, str, bytes, str]:
        try:
            refresh = day >= today - timedelta(days=REFRESH_DAYS)
            return (day, *get_day(args.source, day, args.cache_dir, args.offline, refresh), "")
        except (FetchError, OSError) as e:
            return day, "failed", b"", str(e)

    step = max(1, len(days) // 10)
    ex = ThreadPoolExecutor(max_workers=args.workers)
    try:
        for i, (day, status, raw, err) in enumerate(ex.map(job, days), 1):
            stats[status] += 1
            if err:
                failed.append(f"{day}: {err}")
            recs = parse_bi5(raw)
            opens = [r[1] for r in recs if r[1] > 0]
            try:
                div = args.divisor or (detect_divisor(opens) if opens else 0)
            except ValueError as e:
                raise FetchError(f"{day}: {e}") from None
            bars = day_bars(day, recs, div, args.digits, args.min_volume) if opens else []
            if bars:
                divisors[div] += 1
                store.add(bars)
            elif status in ("cached", "downloaded"):
                stats["empty"] += 1
                if day.weekday() < 5:
                    empty_weekdays.append(day)
            if i % step == 0 or i == len(days):
                print(f"  {i}/{len(days)} 日 処理済み（ダウンロード {stats['downloaded']} / "
                      f"キャッシュ {stats['cached']} / 失敗 {stats['failed']}）", file=sys.stderr, flush=True)
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
    return store, {"stats": stats, "divisors": divisors, "failed": failed, "empty_weekdays": empty_weekdays}


def run(args: argparse.Namespace) -> str:
    """ヒストリーを作って .hst のパスを返す。経過と注意は stdout に表示する."""
    end = args.end or datetime.now(timezone.utc).date() - timedelta(days=1)
    if args.start > end:
        raise FetchError(f"開始日 {args.start} が終了日 {end} より後です")
    if not re.fullmatch(r"[\x21-\x7e]{1,11}", args.symbol):
        raise FetchError(f"銘柄名は半角11文字以内で指定してください: {args.symbol}")
    if not 1 <= args.workers <= 16:
        raise FetchError("--workers は 1～16 で指定してください")
    if not 0 <= args.digits <= 8 or args.min_volume < 1:
        raise FetchError("--digits は 0～8、--min-volume は 1 以上で指定してください")
    hst_dir = hst_dir_for(args.mt4_dir, args.server)
    hst_path = os.path.join(hst_dir, f"{args.symbol}1.hst")
    days = trading_days(args.start, end)
    mode = "キャッシュのみ" if args.offline else f"同時 {args.workers} 本で取得"
    print(f"Dukascopy {args.source} 1分足: {args.start} ～ {end}（UTC、土曜を除く {len(days)} 日、{mode}）",
          file=sys.stderr, flush=True)

    store, info = fetch_all(args, days)
    stats, failed = info["stats"], info["failed"]
    if failed:
        shown = "\n  ".join(failed[:10]) + (f"\n  ...ほか {len(failed) - 10} 日" if len(failed) > 10 else "")
        raise FetchError(f"{len(failed)} 日分を取得できませんでした（.hst は書き換えていません）。"
                         f"もう一度実行すると取得済みの日はキャッシュから読みます。\n  {shown}")
    if not store:
        raise FetchError("指定期間に1分足がありません" + ("（キャッシュが空です。--offline を外してください）" if args.offline else ""))

    first_dl, last_dl = store.ctm[0], store.ctm[-1]
    notes: list[str] = []
    if os.path.exists(hst_path):
        notes.append(f"既存ファイルのバックアップ: {backup_file(hst_path)}")
        try:
            added = merge_existing(store, hst_path)
            notes.append(f"既存ヒストリーから {fmt_time(last_dl)} より新しい足 {added:,} 本を引き継ぎました")
        except (OSError, ValueError, struct.error) as e:
            notes.append(f"注意: 既存ファイルを読めなかったため引き継ぎません（{e}）")
    try:
        write_hst(hst_path, args.symbol, args.digits, store)
    except PermissionError as e:
        raise FetchError(f".hst を書き込めません（MT4 が開いている可能性があります。MT4 を終了して再実行してください）: {e}") from None
    except OSError as e:
        raise FetchError(f".hst を書き込めません: {e}") from None
    if args.csv:
        write_csv(args.csv, store, args.digits)
        notes.append(f"CSV を保存しました: {args.csv}")

    print_summary(args, store, info, first_dl, last_dl, notes)
    return hst_path


def print_summary(args: argparse.Namespace, store: BarStore, info: dict, first_dl: int, last_dl: int,
                  notes: list[str]) -> None:
    stats, divs, empty = info["stats"], info["divisors"], info["empty_weekdays"]
    lines = ["", f"=== {args.symbol} M1 ヒストリーを作成しました ===",
             f"日数: ダウンロード {stats['downloaded']} / キャッシュ {stats['cached']} / "
             f"うちデータなし {stats['empty']}" + (f" / 未取得 {stats['missing']}" if stats["missing"] else ""),
             f"足の本数: {len(store):,} 本（サーバー時間 {fmt_time(store.ctm[0])} ～ {fmt_time(store.ctm[-1])}）",
             f"Dukascopy 分: {fmt_time(first_dl)} ～ {fmt_time(last_dl)}、価格の割り算値: "
             + ", ".join(f"{d}（{n} 日）" for d, n in sorted(divs.items()))
             + ("（指定）" if args.divisor else "（自動判定）"), *notes]
    warns = []
    if len(divs) > 1:
        warns.append("日によって価格の割り算値が違います。価格が正しいかチャートで確認してください（--divisor で固定できます）")
    if stats["missing"]:
        warns.append(f"キャッシュに無い {stats['missing']} 日は含まれていません（--offline を外すと取得します）")
    if empty:
        shown = ", ".join(f"{d:%Y-%m-%d}" for d in empty[:10]) + (" ほか" if len(empty) > 10 else "")
        warns.append(f"データなしの平日 {len(empty)} 日（祝日なら正常）: {shown}")
    fxt = glob.glob(os.path.join(glob.escape(args.mt4_dir), "tester", "history", f"{glob.escape(args.symbol)}1_*.fxt"))
    if fxt:
        warns.append(f"古いテスト用ファイル（{', '.join(os.path.basename(p) for p in fxt)}）があります。"
                     "tester/history から削除してからテストすると新しいヒストリーで作り直されます")
    warns += ["書き換え中は MT4 を終了（少なくとも XAUUSD のチャートを閉じて）おいてください。"
              "起動中だと置き換えに失敗したり、MT4 が古いデータで上書きしたりします",
              "MT4 の「ツール > オプション > チャート」で「ヒストリー内の最大バー数」と「チャートの最大バー数」を"
              "十分大きく（例: 99999999）してください。小さいままだと古い足が切り捨てられます",
              "Dukascopy の価格は HFM の実際の価格・スプレッドと少し違います（テスターのスプレッドは別途指定）"]
    print("\n".join(lines + [f"注意: {w}" for w in warns]))


# ---------------------------------------------------------------- CLI

class JaHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, prefix or "使い方: ")


def build_parser() -> argparse.ArgumentParser:
    cache = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "dukascopy"))
    ap = argparse.ArgumentParser(prog="fetch_history.py", description=__doc__, add_help=False,
                                 usage="%(prog)s --mt4-dir フォルダ --server サーバー名 --from 開始日 [オプション]",
                                 formatter_class=JaHelpFormatter)
    g = ap.add_argument_group("書き込み先（バックテスト用 MT4）")
    g.add_argument("--mt4-dir", required=True, metavar="フォルダ",
                   help="MT4 のデータフォルダ（「ファイル > データフォルダを開く」の場所。history フォルダがある所）")
    g.add_argument("--server", required=True, metavar="名前", help='サーバー名＝history 内のフォルダ名（例: "HFMarketsSV-Demo Server 2"）')
    g.add_argument("--symbol", default="XAUUSD", metavar="銘柄", help="MT4 の銘柄名（既定 XAUUSD。<銘柄名>1.hst に書き込む）")
    g.add_argument("--digits", type=int, default=2, metavar="桁", help="価格の小数桁数（既定 2＝HFM の XAUUSD）")
    g = ap.add_argument_group("期間・取得元")
    g.add_argument("--from", dest="start", type=parse_date, required=True, metavar="YYYY-MM-DD", help="開始日（UTC、例: 2021-10-01）")
    g.add_argument("--to", dest="end", type=parse_date, metavar="YYYY-MM-DD", help="終了日（UTC、この日を含む。既定: 昨日）")
    g.add_argument("--source", default="XAUUSD", metavar="銘柄", help="Dukascopy 側の銘柄名（既定 XAUUSD）")
    g.add_argument("--cache-dir", default=cache, metavar="フォルダ",
                   help=f"日別ファイルの保存先（既定: {cache}）".replace("%", "%%"))
    g.add_argument("--workers", type=int, default=4, metavar="数", help="同時ダウンロード数（既定 4）")
    g.add_argument("--offline", action="store_true", help="通信せずキャッシュだけで作る")
    g = ap.add_argument_group("変換")
    g.add_argument("--divisor", type=int, choices=DIVISORS, help="価格の割り算値（既定: 日ごとに自動判定）")
    g.add_argument("--min-volume", type=int, default=4, metavar="数",
                   help="ティック出来高の最小値（既定 4。テスターが各足の始値・高値・安値・終値を必ず通るように）")
    g = ap.add_argument_group("出力")
    g.add_argument("--csv", metavar="パス", help="ヒストリーセンター取込用 CSV も保存する")
    g.add_argument("-h", "--help", action="help", help="このヘルプを表示して終了")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        path = run(args)
    except FetchError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("中断しました（取得済みの日はキャッシュに残っています）", file=sys.stderr)
        return 130
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
