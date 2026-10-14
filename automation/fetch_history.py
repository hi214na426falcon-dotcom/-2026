#!/usr/bin/env python3
"""XAUUSD 1分足ヒストリー取得ツール（Dukascopy 無料データ -> MT4 .hst）.

Dukascopy の公開データから XAUUSD の1分足（BID）を1日ずつダウンロードし、HFM の
サーバー時間（GMT+2、欧州夏時間中は GMT+3）に変換して、バックテスト用 MT4 の
history/<サーバー名>/XAUUSD1.hst に書き込む。ストラテジーテスターで5年分の M1 テストをするための準備。
取得元は2つ: jetta（Dukascopy の JSON API）と bi5（従来のデータフィード）。既定（auto）は jetta を使い、
つながらない日は bi5 で取り直す。どちらも続けて失敗したら早めに中止する（.hst は書き換えない）。
ダウンロードした日別ファイルはキャッシュするので、2回目以降は新しい日だけ取得する。標準ライブラリのみ（Python 3.10+）。

使い方:
    python automation/fetch_history.py --mt4-dir "C:/Users/me/AppData/Roaming/MetaQuotes/Terminal/XXXX"
        --server "HFMarketsSV-Demo Server 2" --symbol XAUUSD --from 2021-10-01
    python automation/fetch_history.py ... --offline        # 通信せずキャッシュだけで作り直す
    python automation/fetch_history.py ... --csv xau.csv    # ヒストリーセンター取込用 CSV も保存

書き込み中は MT4 を終了しておくこと。成功すると最後の行に書き込んだ .hst のパスを表示する。
既存の .hst（ブローカーのデータ）と重なる時間帯は価格・時刻を照合し、桁や時差がおかしければ書き換えずに中止する。
"""
from __future__ import annotations

import argparse
import bisect
import calendar
import contextlib
import glob
import http.client
import json
import lzma
import math
import os
import random
import re
import shutil
import statistics
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from array import array
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import BinaryIO, Callable, Iterator, NamedTuple

JETTA_URL = "https://jetta.dukascopy.com/v1"
BI5_URL = "https://datafeed.dukascopy.com/datafeed"
HEADERS = {  # Referer とブラウザ風の User-Agent が無いと jetta は 202（ボット判定・空の応答）を返す
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.dukascopy.com/", "Accept": "*/*"}
RETRIES = 3
TIMEOUT = 30
MAX_WAIT = 60  # 再試行前に待つ最長秒数（Retry-After もここで頭打ち）
RETRY_CODES = frozenset({202, 408, 429, 500, 502, 503, 504})  # 時間をおけば直るかもしれない応答
BREAKER_LIMIT = 8  # 取得元がこの日数続けて失敗したら、その取得元は以後使わない
MAX_FAILED = 30  # 取得できない日がこの数に達したら中止する
REFRESH_DAYS = 2  # 今日と直近この日数はキャッシュがあっても取り直す（未確定データ対策）
DEFAULT_DIVISOR = 1000  # bi5 の価格の割り算値（Dukascopy の XAUUSD は小数3桁）
GOLD_RANGE = (200.0, 20000.0)  # 金価格としてありえる範囲（桁違いの検出用）
MAX_DAY_JUMP = 0.3  # 前の日の終値からこの割合以上離れたら桁違いとみなす
CHECK_BARS = 30000  # 既存ヒストリーとの照合に使う直近の重なり本数（約3週間）
MIN_CHECK_BARS = 300  # これより重なりが少なければ照合しない
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


# ---------------------------------------------------------------- 取得元（URL と読み方）

class DayData(NamedTuple):
    recs: list[tuple]  # (UTC の日初からの秒, 始, 終, 安, 高, 出来高)。価格は整数（divisor で割ると価格）
    divisor: float = 0.0  # 価格の割り算値（0 = 取得元が示さない → --divisor か既定値）


class Provider(NamedTuple):
    name: str
    ext: str  # キャッシュファイルの拡張子
    url: Callable[[str, date], str]
    decode: Callable[[bytes, date], DayData]  # 壊れたデータは ValueError


def day_url(instrument: str, day: date) -> str:
    """bi5: 1日分の1分足 URL。月は 0 始まり（1月 = 00）."""
    return f"{BI5_URL}/{instrument}/{day.year}/{day.month - 1:02d}/{day.day:02d}/BID_candles_min_1.bi5"


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


def parse_bi5(raw: bytes) -> list[tuple[int, int, int, int, int, float]]:
    """展開済み bi5 を (秒, 始値, 終値, 安値, 高値, 出来高) の整数価格のまま読む."""
    return list(BI5_REC.iter_unpack(raw))


def decode_bi5(data: bytes, day: date) -> DayData:
    return DayData(parse_bi5(decompress_bi5(data)))


def jetta_url(instrument: str, day: date) -> str:
    """jetta: 1日分の1分足 URL。銘柄は XAU-USD 形式、月は 1 始まりで 0 埋めなし."""
    code = f"{instrument[:3]}-{instrument[3:]}" if len(instrument) == 6 and instrument.isalpha() else instrument
    return f"{JETTA_URL}/candles/minute/{code}/BID/{day.year}/{day.month}/{day.day}"


def decode_jetta(data: bytes, day: date) -> DayData:
    """jetta の JSON を読む。最初の足（open/high/low/close）に差分を足していく形式.

    時刻は timestamp（ミリ秒）に times[i] × shift ミリ秒ずつ足す。価格は multiplier 単位の整数の差分。
    データなしの日は times が空。
    """
    if not data:
        return DayData([])
    try:
        d = json.loads(data)
        times = d["times"]
        if not times:
            return DayData([])
        mult, shift, t = float(d["multiplier"]), int(d["shift"]), int(d["timestamp"])
        cols = [d[k] for k in ("opens", "closes", "lows", "highs", "volumes")]
        if mult <= 0 or shift <= 0 or min(times) < 0 or any(len(c) != len(times) for c in cols):
            raise ValueError("列の長さ・multiplier・shift・times が不正です")
        units = [round(float(d[k]) / mult) for k in ("open", "close", "low", "high")]
        base, recs = utc_epoch(day) * 1000, []
        for i, dt in enumerate(times):
            t += int(dt) * shift
            units = [u + int(c[i]) for u, c in zip(units, cols)]  # 始・終・安・高（出来高の列は使わない）
            recs.append(((t - base) // 1000, *units, float(cols[4][i])))
    except (ValueError, KeyError, TypeError, IndexError) as e:
        raise ValueError(f"JSON の形式が想定と違います: {e}") from None
    return DayData(recs, 1 / mult)


PROVIDERS = {"jetta": Provider("jetta", ".json", jetta_url, decode_jetta),
             "bi5": Provider("bi5", ".bi5", day_url, decode_bi5)}
PROVIDER_ORDER = {"auto": ("jetta", "bi5"), "jetta": ("jetta",), "bi5": ("bi5",)}


# ---------------------------------------------------------------- ダウンロード・キャッシュ

class HttpStatus(Exception):
    def __init__(self, code: int, retry_after: float | None = None) -> None:
        super().__init__(f"HTTP {code}")
        self.code, self.retry_after = code, retry_after


def retry_after(headers) -> float | None:
    """Retry-After（秒数）を読む。無い・日付形式なら None."""
    try:
        return max(0.0, float(headers.get("Retry-After")))
    except (AttributeError, TypeError, ValueError):
        return None


def http_get(url: str, timeout: float = TIMEOUT) -> bytes:
    """1回だけ GET する。404（データなし）は空バイト列、200 以外は HttpStatus."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                raise HttpStatus(r.status, retry_after(r.headers))
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return b""
        raise HttpStatus(e.code, retry_after(e.headers)) from None


def fetch_day(p: Provider, instrument: str, day: date, on_429: Callable[[], None] | None = None,
              retries: int = RETRIES) -> tuple[bytes, DayData]:
    """1日分をダウンロードして読む。一時的なエラー（202/429/5xx・通信エラー・壊れたデータ）は間隔をあけて再試行."""
    url, err = p.url(instrument, day), ""
    for attempt in range(1, retries + 1):
        wait: float | None = None
        try:
            data = http_get(url)
            return data, p.decode(data, day)
        except HttpStatus as e:
            if e.code not in RETRY_CODES:
                raise FetchError(f"HTTP {e.code}（{url}）") from None
            if e.code == 429 and on_429:
                on_429()
            err, wait = str(e), e.retry_after
        except (OSError, http.client.HTTPException, ValueError) as e:
            err = str(e) or type(e).__name__
        if attempt < retries:
            time.sleep(min(MAX_WAIT, 2.0 ** attempt if wait is None else wait) + random.random())
    raise FetchError(f"{err}（{retries} 回試行: {url}）")


def cache_path(cache_dir: str, instrument: str, day: date, ext: str = ".bi5") -> str:
    return os.path.join(cache_dir, instrument, str(day.year), f"{day:%Y-%m-%d}_BID_m1{ext}")


class DayResult(NamedTuple):
    status: str  # cached / downloaded / stale（再取得できず前回分を使用）/ missing（オフラインで未取得）/ failed
    data: DayData | None = None
    note: str = ""  # downloaded は取得元の名前、stale・failed は理由


class Fetcher:
    """取得元（優先順）とキャッシュから1日分ずつ取得する。続けて失敗した取得元は以後使わない（サーバーに負担をかけない）."""

    def __init__(self, providers: list[Provider], cache_dir: str, instrument: str, offline: bool = False,
                 limit: int = BREAKER_LIMIT) -> None:
        self.providers, self.cache_dir, self.instrument = providers, cache_dir, instrument
        self.offline, self.limit = offline, limit
        self.fails = {p.name: 0 for p in providers}
        self.errors: dict[str, str] = {}
        self.rate_limited = threading.Event()  # 429 を受けたら以後は1本ずつ取得する
        self._lock, self._serial = threading.Lock(), threading.Lock()

    def alive(self) -> list[Provider]:
        with self._lock:
            return [p for p in self.providers if self.fails[p.name] < self.limit]

    def record(self, name: str, error: str = "") -> None:
        with self._lock:
            if self.fails[name] < self.limit:  # 一度止めた取得元はそのまま
                self.fails[name] = self.fails[name] + 1 if error else 0
            if error:
                self.errors[name] = error

    def read_cache(self, day: date) -> DayData | None:
        """キャッシュ済みの日を読む（どの取得元のファイルでもよく、データありを優先）。壊れたファイルは消す."""
        found = None
        for p in PROVIDERS.values():
            path = cache_path(self.cache_dir, self.instrument, day, p.ext)
            try:
                with open(path, "rb") as f:
                    data = p.decode(f.read(), day)
            except FileNotFoundError:
                continue
            except ValueError:
                with contextlib.suppress(OSError):
                    os.remove(path)  # 壊れたキャッシュは捨てて取り直す
                continue
            if found is None or (data.recs and not found.recs):
                found = data
        return found

    def write_cache(self, day: date, p: Provider, data: bytes) -> None:
        """取得したファイルを保存する（データなしの日は空ファイル）。同じ日の別の取得元のファイルは消す."""
        path = cache_path(self.cache_dir, self.instrument, day, p.ext)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
        for other in PROVIDERS.values():
            if other.ext != p.ext:
                with contextlib.suppress(FileNotFoundError):
                    os.remove(cache_path(self.cache_dir, self.instrument, day, other.ext))

    def get_day(self, day: date, recent: bool = False) -> DayResult:
        """1日分を返す。recent（直近の日）はキャッシュがあっても取り直し、取れなければ前回分を使う."""
        cached = self.read_cache(day)
        if cached is not None and (self.offline or not recent):
            return DayResult("cached", cached)
        if self.offline:
            return DayResult("missing")
        err = "接続できない状態が続いたため取得を止めました"
        for p in self.alive():
            try:
                with self._serial if self.rate_limited.is_set() else contextlib.nullcontext():
                    raw, data = fetch_day(p, self.instrument, day, self.rate_limited.set)
            except FetchError as e:
                self.record(p.name, str(e))
                err = f"{p.name}: {e}"
                continue
            self.record(p.name)
            if data.recs or not recent:  # 直近の「データなし」は未確定かもしれないので保存しない（次回また取得）
                self.write_cache(day, p, raw)
            if not data.recs and cached and cached.recs:
                return DayResult("stale", cached, f"{p.name} がデータなしと返したため前回の取得分を使いました")
            return DayResult("downloaded", data, p.name)
        if cached is not None:
            return DayResult("stale", cached, f"再取得できなかったため前回の取得分を使いました（{err}）")
        return DayResult("failed", None, err)


# ---------------------------------------------------------------- 足への変換

def day_bars(day: date, recs: list[tuple], divisor: float, digits: int = 2, min_volume: int = 4) -> list[Bar]:
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


def check_scale(bars: list[Bar], divisor: float, prev_close: float = 0.0) -> None:
    """価格の桁が正しそうか確かめる（金価格の範囲内か・前の日から急に飛んでいないか）。おかしければ ValueError."""
    med = statistics.median(b.open for b in bars)
    if not GOLD_RANGE[0] <= med <= GOLD_RANGE[1]:
        raise ValueError(f"価格の桁が想定と違います（始値の中央値 {med:g}、割り算値 {divisor:g}）。"
                         "bi5 なら --divisor で指定してください")
    if prev_close and abs(med / prev_close - 1) > MAX_DAY_JUMP:
        raise ValueError(f"前の日の終値 {prev_close:g} から価格が飛んでいます（始値の中央値 {med:g}）。"
                         "取得元や日によって価格の桁が違う可能性があります")


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

    def close_at(self, ctm: int) -> float | None:
        i = bisect.bisect_left(self.ctm, ctm)
        return HST_REC.unpack_from(self.buf, i * HST_REC.size)[4] if i < len(self.ctm) and self.ctm[i] == ctm else None


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


def scan_hst(path: str, first: int, last: int) -> tuple[list[Bar], list[Bar]]:
    """既存 .hst から (first～last と重なる直近 CHECK_BARS 本, last より新しい足) を読む."""
    with open(path, "rb") as f:
        header = _read_header(f)
        if header["period"] != 1:
            raise ValueError(f"既存ファイルが M1 ではありません（period={header['period']}）")
        overlap: deque[Bar] = deque(maxlen=CHECK_BARS)
        newer: dict[int, Bar] = {}
        for b in _iter_records(f, header["version"]):
            if b.ctm > last:
                newer[b.ctm] = b
            elif b.ctm >= first:
                overlap.append(b)
    return list(overlap), [newer[k] for k in sorted(newer)]


def close_pairs(store: BarStore, ref: list[Bar], shift: int = 0) -> list[tuple[int, float, float]]:
    """ref の各足と、shift 秒ずらした時刻のダウンロード分の足の終値の組 (時刻, ダウンロード分, ref)."""
    out = []
    for b in ref:
        if b.close > 0 and (c := store.close_at(b.ctm + shift)) is not None:
            out.append((b.ctm, c, b.close))
    return out


def check_against_existing(store: BarStore, ref: list[Bar]) -> str:
    """既存ヒストリー（初回はブローカーのデータ）と重なる足で、価格の桁と時差を照合する.

    明らかに合わなければ FetchError（.hst は書き換えない）。結果の説明文を返す。
    """
    pairs = {s: close_pairs(store, ref, s) for s in (0, -3600, 3600)}
    same = pairs[0]
    if len(same) < MIN_CHECK_BARS:
        return f"既存ヒストリーと重なる足が少ない（{len(same)} 本）ため、価格・時刻の照合はしていません"
    hint = "既存の .hst が正しくない場合は削除するか、--no-check を付けて実行してください"
    ratio = statistics.median(d / r for _, d, r in same)
    if not 0.98 <= ratio <= 1.02:
        raise FetchError(f"Dukascopy の価格が既存ヒストリーの約 {ratio:.3g} 倍です（桁違いの可能性）。"
                         f".hst は書き換えていません。{hint}")
    gap = {s: statistics.median(abs(d - r) for _, d, r in p) for s, p in pairs.items() if len(p) >= MIN_CHECK_BARS}
    best = min(gap, key=gap.__getitem__)
    if best and gap[best] < gap[0] * 0.5:
        raise FetchError(f"Dukascopy の時刻が既存ヒストリーと {abs(best) // 3600} 時間ずれているようです（終値の差の"
                         f"中央値: そのまま {gap[0]:.2f} / {best // 3600:+d} 時間ずらすと {gap[best]:.2f}）。"
                         f"サーバー時間（GMT+2/+3）の変換を確認してください。.hst は書き換えていません。{hint}")
    note = (f"既存ヒストリーと照合しました（{len(same):,} 本、価格の比 {ratio:.4f}、"
            f"終値の差の中央値 {gap[0]:.2f}）")
    if odd := shifted_days(pairs):
        note += (f"\n注意: 次の日は既存ヒストリーと1時間ずれているようです（夏時間の切り替え時期の違いの可能性）: "
                 + ", ".join(odd[:10]))
    return note


def shifted_days(pairs: dict[int, list[tuple[int, float, float]]], min_bars: int = 60) -> list[str]:
    """1時間ずらした方が既存ヒストリーとよく合う日（サーバー時間の日付）を返す."""
    by_day: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for s, p in pairs.items():
        for ctm, d, r in p:
            by_day[ctm // 86400][s].append(abs(d - r))
    out = []
    for day, g in sorted(by_day.items()):
        others = [statistics.median(v) for s, v in g.items() if s and len(v) >= min_bars]
        if len(g[0]) >= min_bars and others and min(others) < statistics.median(g[0]) * 0.5:
            out.append(time.strftime("%Y-%m-%d", time.gmtime(day * 86400)))
    return out


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


def failed_message(failed: list[str], stopped: bool = False) -> str:
    shown = "\n  ".join(failed[:10]) + (f"\n  ...ほか {len(failed) - 10} 日" if len(failed) > 10 else "")
    head = "取得できない日が多いため途中で中止しました。" if stopped else ""
    return (f"{head}{len(failed)} 日分を取得できませんでした（.hst は書き換えていません）。"
            f"時間をおいて再実行すると、取得済みの日はキャッシュから読みます。\n  {shown}")


def down_message(fetcher: Fetcher) -> str:
    detail = "\n  ".join(f"{n}: {e}" for n, e in fetcher.errors.items())
    return ("Dukascopy に接続できません（続けて失敗したため取得を中止しました。.hst は書き換えていません）。"
            "時間をおいて再実行してください。取得済みの日はキャッシュに残っています。\n  " + detail)


def add_day(args: argparse.Namespace, store: BarStore, info: dict, day: date, res: DayResult,
            prev_close: float) -> float:
    """1日分の結果を集計し、足に変換して store に足す。最後の終値を返す（翌日の桁チェック用）."""
    info["stats"][res.status] += 1
    if res.status == "failed":
        info["failed"].append(f"{day}: {res.note}")
        return prev_close
    if res.status == "stale":
        info["stale"].append(f"{day}: {res.note}")
    elif res.status == "downloaded":
        info["sources"][res.note] += 1
    data = res.data or DayData([])
    div = data.divisor or args.divisor or DEFAULT_DIVISOR
    bars = day_bars(day, data.recs, div, args.digits, args.min_volume) if data.recs else []
    if not bars:
        if res.status != "missing":
            info["stats"]["empty"] += 1
            if day.weekday() < 5:
                info["empty_weekdays"].append(day)
        return prev_close
    try:
        check_scale(bars, div, prev_close)
    except ValueError as e:
        raise FetchError(f"{day}: {e}（.hst は書き換えていません）") from None
    info["divisors"][div] += 1
    store.add(bars)
    return bars[-1].close


def fetch_all(args: argparse.Namespace, days: list[date], fetcher: Fetcher) -> tuple[BarStore, dict]:
    """全日を並列で取得し、日付順に足へ変換してため込む。取得元が全部止まったら途中で中止する."""
    recent_from = datetime.now(timezone.utc).date() - timedelta(days=REFRESH_DAYS)
    store = BarStore()
    info: dict = {"stats": Counter(), "divisors": Counter(), "sources": Counter(), "failed": [], "stale": [],
                  "empty_weekdays": []}

    def job(day: date) -> DayResult:
        try:
            return fetcher.get_day(day, day >= recent_from)
        except OSError as e:
            return DayResult("failed", None, str(e))

    pending: deque = deque()
    todo, window, prev_close, done = iter(days), args.workers * 2, 0.0, 0
    step = max(1, len(days) // 10)
    ex = ThreadPoolExecutor(max_workers=args.workers)
    try:
        while True:
            while len(pending) < window and (day := next(todo, None)) is not None:
                pending.append((day, ex.submit(job, day)))
            if not pending:
                break
            day, fut = pending.popleft()
            prev_close = add_day(args, store, info, day, fut.result(), prev_close)
            done += 1
            if fetcher.rate_limited.is_set() and window > 1:
                window = 1
                print("注意: アクセスが多すぎると言われた（HTTP 429）ため、1本ずつ取得します", file=sys.stderr, flush=True)
            if not args.offline and not fetcher.alive():
                raise FetchError(down_message(fetcher))
            if len(info["failed"]) >= MAX_FAILED:
                raise FetchError(failed_message(info["failed"], stopped=True))
            if done % step == 0 or done == len(days):
                s = info["stats"]
                print(f"  {done}/{len(days)} 日 処理済み（ダウンロード {s['downloaded']} / キャッシュ {s['cached']} / "
                      f"失敗 {s['failed']}）", file=sys.stderr, flush=True)
    finally:
        for _, fut in pending:
            fut.cancel()
        ex.shutdown(wait=True, cancel_futures=True)
    return store, info


def merge_existing(args: argparse.Namespace, store: BarStore, path: str) -> list[str]:
    """既存 .hst と照合してバックアップし、ダウンロード分より新しい足（ブローカーの最新データ）を引き継ぐ."""
    if not os.path.exists(path):
        return []
    last, notes = store.ctm[-1], []
    try:
        overlap, newer = scan_hst(path, store.ctm[0], last)
    except (OSError, ValueError, struct.error) as e:
        overlap, newer = [], None
        notes.append(f"注意: 既存ファイルを読めなかったため照合・引き継ぎはしません（{e}）")
    if not args.no_check and newer is not None:
        notes.append(check_against_existing(store, overlap))
    try:
        notes.append(f"既存ファイルのバックアップ: {backup_file(path)}")
    except OSError as e:
        raise FetchError(f"既存の .hst をバックアップできないため中止しました（.hst は書き換えていません）: {e}") from None
    if newer is not None:
        store.add(newer)
        notes.append(f"既存ヒストリーから {fmt_time(last)} より新しい足 {len(newer):,} 本を引き継ぎました")
    return notes


def run(args: argparse.Namespace) -> str:
    """ヒストリーを作って .hst のパスを返す。経過と注意は stdout に表示する."""
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    end = min(args.end or yesterday, yesterday)
    if args.start > end:
        raise FetchError(f"開始日 {args.start} が終了日 {end} より後です（終了日は昨日（UTC）まで）")
    if not re.fullmatch(r"[\x21-\x7e]{1,11}", args.symbol):
        raise FetchError(f"銘柄名は半角11文字以内で指定してください: {args.symbol}")
    if not 1 <= args.workers <= 16:
        raise FetchError("--workers は 1～16 で指定してください")
    if not 0 <= args.digits <= 8 or args.min_volume < 1:
        raise FetchError("--digits は 0～8、--min-volume は 1 以上で指定してください")
    hst_path = os.path.join(hst_dir_for(args.mt4_dir, args.server), f"{args.symbol}1.hst")
    days = trading_days(args.start, end)
    fetcher = Fetcher([PROVIDERS[n] for n in PROVIDER_ORDER[args.provider]], args.cache_dir, args.source,
                      args.offline)
    mode = "キャッシュのみ" if args.offline else f"取得元 {' → '.join(PROVIDER_ORDER[args.provider])}、同時 {args.workers} 本"
    print(f"Dukascopy {args.source} 1分足: {args.start} ～ {end}（UTC、土曜を除く {len(days)} 日、{mode}）",
          file=sys.stderr, flush=True)
    if args.end and args.end > end:
        print(f"注意: 今日以降のデータはまだ確定していないため {end} までにしました", file=sys.stderr, flush=True)

    store, info = fetch_all(args, days, fetcher)
    if info["failed"]:
        raise FetchError(failed_message(info["failed"]))
    if not store:
        raise FetchError("指定期間に1分足がありません" + ("（キャッシュが空です。--offline を外してください）" if args.offline else ""))

    first_dl, last_dl = store.ctm[0], store.ctm[-1]
    notes = merge_existing(args, store, hst_path)
    try:
        write_hst(hst_path, args.symbol, args.digits, store)
    except PermissionError as e:
        raise FetchError(f".hst を書き込めません（MT4 が開いている可能性があります。MT4 を終了して再実行してください）: {e}") from None
    except OSError as e:
        raise FetchError(f".hst を書き込めません: {e}") from None
    if args.csv:
        try:
            write_csv(args.csv, store, args.digits)
            notes.append(f"CSV を保存しました: {args.csv}")
        except OSError as e:
            notes.append(f"注意: CSV を保存できませんでした（.hst は書き込み済み）: {e}")

    print_summary(args, store, info, first_dl, last_dl, notes)
    return hst_path


def print_summary(args: argparse.Namespace, store: BarStore, info: dict, first_dl: int, last_dl: int,
                  notes: list[str]) -> None:
    stats, divs, empty, stale = info["stats"], info["divisors"], info["empty_weekdays"], info["stale"]
    sources = "、".join(f"{n} {c} 日" for n, c in info["sources"].items())
    lines = ["", f"=== {args.symbol} M1 ヒストリーを作成しました ===",
             f"日数: ダウンロード {stats['downloaded']}" + (f"（{sources}）" if sources else "")
             + f" / キャッシュ {stats['cached']} / うちデータなし {stats['empty']}"
             + (f" / 前回分で代用 {stats['stale']}" if stats["stale"] else "")
             + (f" / 未取得 {stats['missing']}" if stats["missing"] else ""),
             f"足の本数: {len(store):,} 本（サーバー時間 {fmt_time(store.ctm[0])} ～ {fmt_time(store.ctm[-1])}）",
             f"Dukascopy 分: {fmt_time(first_dl)} ～ {fmt_time(last_dl)}、価格の割り算値: "
             + ", ".join(f"{d:g}（{n} 日）" for d, n in sorted(divs.items()))
             + ("（--divisor 指定）" if args.divisor else ""), *notes]
    warns = []
    if len(divs) > 1:
        warns.append("日によって価格の割り算値が違います。価格が正しいかチャートで確認してください")
    if stale:
        warns.append(f"直近 {len(stale)} 日は再取得できず前回の取得分を使いました: "
                     + ", ".join(s.split(":", 1)[0] for s in stale))
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
    g.add_argument("--to", dest="end", type=parse_date, metavar="YYYY-MM-DD", help="終了日（UTC、この日を含む。既定・上限: 昨日）")
    g.add_argument("--provider", choices=tuple(PROVIDER_ORDER), default="auto",
                   help="取得元（既定 auto: jetta を使い、取れない日は bi5 で取り直す）")
    g.add_argument("--source", default="XAUUSD", metavar="銘柄", help="Dukascopy 側の銘柄名（既定 XAUUSD）")
    g.add_argument("--cache-dir", default=cache, metavar="フォルダ",
                   help=f"日別ファイルの保存先（既定: {cache}）".replace("%", "%%"))
    g.add_argument("--workers", type=int, default=4, metavar="数", help="同時ダウンロード数（既定 4）")
    g.add_argument("--offline", action="store_true", help="通信せずキャッシュだけで作る")
    g = ap.add_argument_group("変換・確認")
    g.add_argument("--divisor", type=int, choices=(10, 100, 1000, 100000),
                   help=f"bi5 の価格の割り算値（既定 {DEFAULT_DIVISOR}。jetta はデータ内の値を使う）")
    g.add_argument("--min-volume", type=int, default=4, metavar="数",
                   help="ティック出来高の最小値（既定 4。テスターが各足の始値・高値・安値・終値を必ず通るように）")
    g.add_argument("--no-check", action="store_true", help="既存の .hst（ブローカーのデータ）との価格・時刻の照合をしない")
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
