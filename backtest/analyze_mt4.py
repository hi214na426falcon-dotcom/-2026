#!/usr/bin/env python3
"""Mr.2 Gold バックテスト分析ツール.

MT4 のストラテジーテスター・レポート（StrategyTester.htm）、口座履歴の詳細レポート
（Detailed Statement）、または CSV を読み込み、成績指標・2期間比較・ウォークフォワード・
モンテカルロ・推奨ロットを日本語の Markdown レポートで出力する。標準ライブラリのみ（Python 3.10+）。

使い方:
    python backtest/analyze_mt4.py StrategyTester.htm
    python backtest/analyze_mt4.py StrategyTester.htm --capital 140000 --out report.md --csv windows.csv
    python backtest/analyze_mt4.py statement.htm --usdjpy 150 --recent-months 6
    python backtest/analyze_mt4.py trades.csv --deposit 140000   # CSV: close_time, profit 列が必須
"""
from __future__ import annotations

import argparse
import codecs
import csv
import io
import math
import os
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser
from itertools import accumulate
from operator import itemgetter, sub

OPEN_TYPES = {"buy": "buy", "sell": "sell", "買い": "buy", "売り": "sell"}
BASKET_GAP = timedelta(seconds=60)  # この間隔以内に決済された取引は1つのバスケット（ナンピン一括決済）
LOT_STEP = 0.01
CAPITALS = (100_000, 140_000, 200_000, 300_000, 500_000)
MIN_IS_TRADES = 30
DT_RE = re.compile(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?")


@dataclass
class Trade:
    close_time: datetime
    pnl: float  # 手数料・スワップ込みの純損益
    open_time: datetime | None = None
    side: str = ""  # "buy" / "sell" / ""（不明）
    lots: float = 0.0  # 0 = 不明
    ticket: str = ""


@dataclass
class Basket:
    close_time: datetime
    pnl: float
    pnl_001: float  # 0.01ロット換算（バスケット内の最小ロット＝初期ロット基準）
    n: int


@dataclass
class Dataset:
    trades: list[Trade]
    kind: str  # tester / statement / csv
    deposit: float | None = None
    currency: str | None = None
    meta: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 読み込み

def read_text(path: str) -> str:
    """BOM・meta charset・UTF-8/cp932 の順で文字コードを推定して読む."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(codecs.BOM_UTF8):
        return raw[3:].decode("utf-8", "replace")
    if raw[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        return raw.decode("utf-16", "replace")
    if raw[:400].count(b"\x00") > 40:  # BOM なし UTF-16
        return raw.decode("utf-16-le" if raw[1:2] == b"\x00" else "utf-16-be", "replace")
    m = re.search(rb"charset=[\"']?([\w-]+)", raw[:4096], re.I)
    declared = m.group(1).decode("ascii", "ignore").lower() if m else ""
    if declared in ("shift_jis", "shift-jis", "sjis", "x-sjis", "windows-31j"):
        declared = "cp932"
    for enc in [e for e in (declared, "utf-8", "cp932") if e]:
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            pass
    return raw.decode("latin-1")


class _RowParser(HTMLParser):
    """全 <tr> をセル文字列のリストとして集める（表の入れ子や colspan は気にしない）."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._end_row()
            self._row = []
        elif tag in ("td", "th"):
            self._end_cell()
            if self._row is None:
                self._row = []
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._end_cell()
        elif tag in ("tr", "table"):
            self._end_row()

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def _end_cell(self):
        if self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
        self._cell = None

    def _end_row(self):
        self._end_cell()
        if self._row:
            self.rows.append(self._row)
        self._row = None


def html_rows(text: str) -> list[list[str]]:
    p = _RowParser()
    p.feed(text)
    p.close()
    p._end_row()
    return p.rows


def parse_dt(s: str) -> datetime | None:
    m = DT_RE.match(s.strip())
    if not m:
        return None
    y, mo, d, h, mi, sec = m.groups()
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec or 0))
    except ValueError:
        return None


def parse_day(s: str) -> datetime:
    return datetime.strptime(re.sub(r"[./]", "-", s.strip())[:10], "%Y-%m-%d")


def num(s: str) -> float | None:
    s = s.replace("\xa0", "").replace(" ", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


META_LABELS = [  # (キー, 正規表現) 英語/日本語ラベルの両方に緩く一致させる
    ("quality", r".*(modell?ing quality|モデリング品質|モデル品質).*"),
    ("deposit", r".*(initial deposit|初期証拠金|初期資金|初期入金).*"),
    ("max_dd", r".*(maximal drawdown|maximum drawdown|最大ドローダウン).*"),
    ("rel_dd", r".*(relative drawdown|相対ドローダウン).*"),
    ("spread", r"spread|スプレッド"),
    ("symbol", r"symbol|通貨ペア|銘柄|シンボル"),
    ("period", r"period|期間"),
    ("model", r"model|モデル"),
]


def parse_dd(v: str) -> tuple[float | None, float | None]:
    """'1234.56 (12.34%)' や '12.34% (1234.56)' → (金額, %)."""
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", v)
    amt = re.search(r"\d[\d ,]*(?:\.\d+)?", re.sub(r"\d+(?:\.\d+)?\s*%", "", v))
    return (num(amt.group()) if amt else None, float(pct.group(1)) if pct else None)


def parse_meta(rows: list[list[str]]) -> dict:
    raw: dict[str, str] = {}
    for r in rows:
        for label, value in zip(r, r[1:]):
            key = label.strip().lower().rstrip(":：").strip()
            for name, pat in META_LABELS:
                if name not in raw and value and re.fullmatch(pat, key):
                    raw[name] = value
                    break
    meta = {k: raw[k] for k in ("symbol", "period", "model", "spread") if k in raw}
    if "quality" in raw and (m := re.search(r"(\d+(?:\.\d+)?)\s*%", raw["quality"])):
        meta["quality"] = float(m.group(1))
    if "deposit" in raw and (v := num(raw["deposit"])) is not None:
        meta["deposit"] = v
    if "max_dd" in raw:
        meta["eq_dd"] = parse_dd(raw["max_dd"])
    if "rel_dd" in raw:
        meta["eq_dd_rel"] = parse_dd(raw["rel_dd"])
    return meta


def parse_tester_rows(rows: list[list[str]]) -> tuple[list[Trade], float | None]:
    """テスターの取引表: # | 時間 | 種別 | 注文番号 | 数量 | 価格 | S/L | T/P | 損益 | 残高."""
    opens: dict[str, tuple[datetime, str, float]] = {}
    trades: list[Trade] = []
    first_balance = None
    for r in rows:
        if len(r) < 9 or not r[0].isdigit() or (t := parse_dt(r[1])) is None:
            continue
        order, side = r[3], OPEN_TYPES.get(r[2].strip().lower())
        if side and order not in opens:
            opens[order] = (t, side, num(r[4]) or 0.0)
        pnl, bal = (num(r[8]), num(r[9])) if len(r) >= 10 else (None, None)
        if pnl is not None and bal is not None:  # 損益と残高がある行＝決済行
            ot, side0, lots0 = opens.get(order, (None, "", 0.0))
            trades.append(Trade(t, pnl, ot, side0, num(r[4]) or lots0, order))
            if first_balance is None:
                first_balance = bal - pnl
    return trades, first_balance


def parse_statement_rows(rows: list[list[str]]) -> tuple[list[Trade], list[tuple[datetime, float]]]:
    """詳細レポートの Closed Transactions: Ticket | Open Time | Type | Size | Item | Price | S/L | T/P |
    Close Time | Price | Commission | Taxes | Swap | Profit."""
    trades, balance_ops = [], []
    for r in rows:
        if len(r) < 4 or (ot := parse_dt(r[1])) is None:
            continue
        typ = r[2].strip().lower()
        if typ == "balance":
            balance_ops.append((ot, num(r[-1]) or 0.0))
        elif len(r) >= 14 and typ in OPEN_TYPES and (ct := parse_dt(r[8])):
            pnl = sum(num(x) or 0.0 for x in r[10:14])
            trades.append(Trade(ct, pnl, ot, OPEN_TYPES[typ], num(r[3]) or 0.0, r[0]))
    return trades, balance_ops


CSV_ALIASES = {
    "close_time": ("closetime", "closedate", "決済時間", "決済日時"),
    "profit": ("profit", "pnl", "netprofit", "損益"),
    "open_time": ("opentime", "opendate", "約定時間", "新規時間"),
    "type": ("type", "side", "direction", "取引種別"),
    "lots": ("lots", "lot", "size", "volume", "数量"),
    "ticket": ("ticket", "order", "注文番号"),
}


def parse_csv(text: str) -> Dataset:
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if r]
    if not rows:
        raise ValueError("CSV が空です")
    head = [re.sub(r"[\s_]", "", h.lower()) for h in rows[0]]
    idx = {k: next((head.index(a) for a in al if a in head), None) for k, al in CSV_ALIASES.items()}
    if idx["close_time"] is None or idx["profit"] is None:
        raise ValueError("CSV のヘッダーに close_time と profit 列が必要です")
    extra = [head.index(c) for c in ("commission", "swap", "taxes") if c in head]

    def cell(r: list[str], key: str) -> str:
        i = idx[key]
        return r[i] if i is not None and i < len(r) else ""

    trades = []
    for r in rows[1:]:
        ct, p = parse_dt(cell(r, "close_time")), num(cell(r, "profit"))
        if ct is None or p is None:
            continue
        p += sum(num(r[i]) or 0.0 for i in extra if i < len(r))
        side = OPEN_TYPES.get(cell(r, "type").strip().lower(), "")
        trades.append(Trade(ct, p, parse_dt(cell(r, "open_time")), side, num(cell(r, "lots")) or 0.0,
                            cell(r, "ticket")))
    if not trades:
        raise ValueError("CSV に有効な取引行がありません")
    return Dataset(trades, "csv")


def load_file(path: str) -> Dataset:
    text = read_text(path)
    if "<tr" not in text.lower():
        ds = parse_csv(text)
    else:
        rows = html_rows(text)
        cur = re.search(r"(?:Currency|通貨)\s*[:：]\s*([A-Z]{3})", " ".join(" ".join(r) for r in rows))
        currency = cur.group(1) if cur else None
        st_trades, ops = parse_statement_rows(rows)
        if st_trades:
            first = min(t.open_time or t.close_time for t in st_trades)
            before = [a for t, a in ops if t <= first]
            ds = Dataset(st_trades, "statement", sum(before) if before else None, currency)
            if len(ops) > len(before):
                ds.warnings.append(f"期間中の入出金 {len(ops) - len(before)} 件は損益に含めていません（DD% はやや不正確）")
        else:
            trades, dep_guess = parse_tester_rows(rows)
            if not trades:
                raise ValueError(f"{path}: 取引行が見つかりません（対応形式: テスターレポート / 詳細レポート / CSV）")
            meta = parse_meta(rows)
            ds = Dataset(trades, "tester", meta.get("deposit") or dep_guess, currency, meta)
    if re.search(r"SYNTHETIC|架空データ", text):
        ds.warnings.append(f"{os.path.basename(path)} は合成（架空）のサンプルデータです。実在EAの成績ではありません")
    return ds


def load_all(paths: list[str]) -> Dataset:
    sets = sorted((load_file(p) for p in paths), key=lambda d: min(t.close_time for t in d.trades))
    seen, trades = set(), []
    for d in sets:
        for t in d.trades:
            key = (t.ticket, t.close_time, round(t.pnl, 2))
            if t.ticket and key in seen:
                continue
            seen.add(key)
            trades.append(t)
    meta: dict = {}
    for d in sets:
        for k, v in d.meta.items():
            meta.setdefault(k, v)
    ds = Dataset(sorted(trades, key=lambda t: t.close_time), "+".join(dict.fromkeys(d.kind for d in sets)),
                 sets[0].deposit, next((d.currency for d in sets if d.currency), None), meta,
                 [w for d in sets for w in d.warnings])
    if len(sets) > 1:
        ds.warnings.append(f"{len(sets)} ファイルを結合しました（初期資金・ヘッダー情報は最も古いファイルを優先）")
    return ds


def convert_currency(ds: Dataset, rate: float) -> None:
    for t in ds.trades:
        t.pnl *= rate
    if ds.deposit:
        ds.deposit *= rate
    for k in ("eq_dd", "eq_dd_rel"):
        if k in ds.meta and ds.meta[k][0] is not None:
            ds.meta[k] = (ds.meta[k][0] * rate, ds.meta[k][1])


# ---------------------------------------------------------------- 指標

def balance_at(trades: list[Trade], deposit: float, when: datetime) -> float:
    return deposit + sum(t.pnl for t in trades if t.close_time < when)


def drawdown(tr: list[Trade], deposit: float, start: datetime | None) -> tuple[float, float, float]:
    """残高曲線の最大DD（金額, 山からの%）と最長DD期間（日）."""
    bal = peak = deposit
    peak_t = start or (tr[0].close_time if tr else None)
    dd = dd_pct = longest = 0.0
    under = False
    for t in tr:
        bal += t.pnl
        if bal >= peak:
            if under:
                longest = max(longest, (t.close_time - peak_t).total_seconds() / 86400)
            peak, peak_t, under = bal, t.close_time, False
        else:
            under = True
            dd = max(dd, peak - bal)
            dd_pct = max(dd_pct, (peak - bal) / peak * 100 if peak > 0 else 100.0)
    if under:
        longest = max(longest, (tr[-1].close_time - peak_t).total_seconds() / 86400)
    return dd, dd_pct, longest


def streaks(pnls: list[float]) -> tuple[int, int]:
    best_w = best_l = cw = cl = 0
    for p in pnls:
        cw, cl = (cw + 1, 0) if p > 0 else (0, cl + 1) if p < 0 else (0, 0)
        best_w, best_l = max(best_w, cw), max(best_l, cl)
    return best_w, best_l


def daily_returns(tr: list[Trade], deposit: float, start: datetime, end: datetime) -> list[float]:
    """日次リターン = 日次損益 ÷ その日の開始残高。取引のない平日も 0 として含める."""
    by_day: dict = defaultdict(float)
    for t in tr:
        by_day[t.close_time.date()] += t.pnl
    d0, d1 = start.date(), end.date()
    days = {d0 + timedelta(i) for i in range((d1 - d0).days + 1)}
    days = sorted({d for d in days if d.weekday() < 5} | set(by_day))
    out, bal = [], deposit
    for d in days:
        p = by_day.get(d, 0.0)
        out.append(p / bal if bal > 0 else 0.0)
        bal += p
    return out


def monthly_returns(tr: list[Trade], deposit: float) -> dict[tuple[int, int], tuple[float, float | None, float]]:
    """{(年, 月): (損益, 月初残高に対する%, 月初残高)}."""
    sums: dict = defaultdict(float)
    for t in tr:
        sums[(t.close_time.year, t.close_time.month)] += t.pnl
    out, bal = {}, deposit
    for k in sorted(sums):
        out[k] = (sums[k], sums[k] / bal * 100 if bal > 0 else None, bal)
        bal += sums[k]
    return out


def compute_metrics(trades: list[Trade], deposit: float,
                    start: datetime | None = None, end: datetime | None = None) -> dict:
    """決済済み取引の残高曲線から成績指標を計算する（start/end はシャープ・CAGR 用の暦期間）."""
    tr = sorted(trades, key=lambda t: t.close_time)
    pnls = [t.pnl for t in tr]
    n = len(pnls)
    wins, losses = [p for p in pnls if p > 0], [-p for p in pnls if p < 0]
    gp, gl = sum(wins), sum(losses)
    net = gp - gl
    start = start or min((t.open_time or t.close_time for t in tr), default=None)
    end = end or (tr[-1].close_time if tr else None)
    dd, dd_pct, dd_days = drawdown(tr, deposit, start)
    years = (end - start).total_seconds() / (365.25 * 86400) if start and end else 0.0
    final = deposit + net
    cagr = None
    if years >= 1 / 52 and deposit > 0:
        cagr = ((final / deposit) ** (1 / years) - 1) * 100 if final > 0 else -100.0
    sharpe = sortino = None
    rets = daily_returns(tr, deposit, start, end) if start and end else []
    if len(rets) > 1:
        mu, sd = statistics.fmean(rets), statistics.stdev(rets)
        down = math.sqrt(statistics.fmean([min(r, 0.0) ** 2 for r in rets]))
        sharpe = mu / sd * math.sqrt(252) if sd > 0 else None
        sortino = mu / down * math.sqrt(252) if down > 0 else None
    avg_w = gp / len(wins) if wins else None
    avg_l = gl / len(losses) if losses else None
    cw, cl = streaks(pnls)
    return {
        "start": start, "end": end, "deposit": deposit, "final": final, "trades": n,
        "net": net, "gross_profit": gp, "gross_loss": gl,
        "pf": gp / gl if gl > 0 else (math.inf if gp > 0 else None),
        "win_rate": len(wins) / n * 100 if n else None,
        "avg_win": avg_w, "avg_loss": avg_l,
        "payoff": avg_w / avg_l if avg_w and avg_l else None,
        "expectancy": net / n if n else None,
        "max_consec_wins": cw, "max_consec_losses": cl,
        "max_dd": dd, "max_dd_pct": dd_pct, "dd_days": dd_days,
        "recovery": net / dd if dd > 0 else None,
        "cagr": cagr, "calmar": cagr / dd_pct if cagr is not None and dd_pct > 0 else None,
        "sharpe": sharpe, "sortino": sortino,
        "monthly": monthly_returns(tr, deposit),
    }


# ---------------------------------------------------------------- バスケット / モンテカルロ / ロット

def group_baskets(trades: list[Trade], gap: timedelta = BASKET_GAP) -> list[Basket]:
    groups: list[list[Trade]] = []
    for t in sorted(trades, key=lambda t: t.close_time):
        if groups and t.close_time - groups[-1][-1].close_time <= gap:
            groups[-1].append(t)
        else:
            groups.append([t])
    out = []
    for g in groups:
        pnl = sum(t.pnl for t in g)
        base = min((t.lots for t in g if t.lots > 0), default=LOT_STEP)
        out.append(Basket(g[-1].close_time, pnl, pnl * LOT_STEP / base, len(g)))
    return out


def path_dd(seq, start: float) -> tuple[float, float]:
    """損益列の最大DD（金額）と最低残高."""
    cum = list(accumulate(seq, initial=start))
    return max(map(sub, accumulate(cum, max), cum)), min(cum)


def pctl(sorted_vals: list[float], q: float) -> float:
    return sorted_vals[min(len(sorted_vals) - 1, max(0, math.ceil(q / 100 * len(sorted_vals)) - 1))]


def monte_carlo(baskets: list[Basket], deposit: float, runs: int = 10000, seed: int | None = None) -> dict | None:
    """バスケット単位のブートストラップ（復元抽出、履歴と同数）で最大DDの分布を推定（固定ロット・複利なし）."""
    n = len(baskets)
    if n < 2 or runs <= 0:
        return None
    act, per = [b.pnl for b in baskets], [b.pnl_001 for b in baskets]
    rng, pop = random.Random(seed), range(n)
    dds, dds001, ruin = [], [], 0
    for _ in range(runs):
        pick = itemgetter(*rng.choices(pop, k=n))
        dd, low = path_dd(pick(act), deposit)
        dds.append(dd)
        dds001.append(path_dd(pick(per), 0.0)[0])
        ruin += low <= deposit * 0.2
    dds.sort()
    dds001.sort()
    return {
        "runs": runs, "baskets": n, "deposit": deposit,
        "dd": {q: pctl(dds, q) for q in (50, 95, 99)},
        "dd001": {q: pctl(dds001, q) for q in (50, 95, 99)},
        "p30": sum(d >= deposit * 0.3 for d in dds) / runs * 100,
        "p50": sum(d >= deposit * 0.5 for d in dds) / runs * 100,
        "ruin": ruin / runs * 100,
    }


def recommend_lot(capital: float, dd99_001: float, max_dd_pct: float, safety: float) -> float:
    """floor(資金 × 許容DD% ÷ (0.01ロットあたりDD99 × 安全係数)) × 0.01."""
    if dd99_001 <= 0:
        return math.inf
    return round(math.floor(capital * max_dd_pct / 100 / (dd99_001 * safety) + 1e-9) * LOT_STEP, 2)


def required_capital(lot: float, dd99_001: float, max_dd_pct: float, safety: float) -> float:
    return lot / LOT_STEP * dd99_001 * safety / (max_dd_pct / 100)


# ---------------------------------------------------------------- ウォークフォワード

def month_floor(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, 1)


def add_months(dt: datetime, n: int) -> datetime:
    k = dt.year * 12 + dt.month - 1 + n
    return datetime(k // 12, k % 12 + 1, 1)


def wf_windows(first: datetime, last: datetime, is_m: int, oos_m: int) -> list[tuple[datetime, datetime, datetime]]:
    """(IS開始, OOS開始, OOS終了) のリスト。月単位、OOS がデータ範囲に収まるものだけ."""
    s, ceil = month_floor(first), add_months(month_floor(last), 1)
    out = []
    while add_months(s, is_m + oos_m) <= ceil:
        out.append((s, add_months(s, is_m), add_months(s, is_m + oos_m)))
        s = add_months(s, oos_m)
    return out


def block_hours(block: tuple[int, int]) -> set[int]:
    s, n = block
    return {(s + k) % 24 for k in range(n)}


def block_label(block: tuple[int, int]) -> str:
    s, n = block
    return "なし" if n == 0 else f"{s:02d}:00～{(s + n) % 24:02d}:00"


def apply_block(trades: list[Trade], block: tuple[int, int]) -> list[Trade]:
    hrs = block_hours(block)
    return [t for t in trades if (t.open_time or t.close_time).hour not in hrs] if hrs else trades


def block_score(trades: list[Trade]) -> float:
    cum = peak = dd = 0.0
    for t in trades:
        cum += t.pnl
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return cum / (dd + 1)


def best_block(trades: list[Trade], min_trades: int = MIN_IS_TRADES) -> tuple[int, int]:
    """純益 ÷ (最大DD + 1) が最大になる連続 0～4 時間の新規エントリー停止時間帯."""
    best, best_score = (0, 0), block_score(trades)
    if len(trades) < min_trades:
        return best
    for n in range(1, 5):
        for s in range(24):
            sc = block_score(apply_block(trades, (s, n)))
            if sc > best_score + 1e-9:
                best, best_score = (s, n), sc
    return best


def walk_forward(trades: list[Trade], deposit: float, is_m: int, oos_m: int) -> list[dict]:
    tr = sorted(trades, key=lambda t: t.close_time)
    if not tr:
        return []
    out = []
    for i, (a, b, c) in enumerate(wf_windows(tr[0].close_time, tr[-1].close_time, is_m, oos_m), 1):
        is_tr = [t for t in tr if a <= t.close_time < b]
        oos_tr = [t for t in tr if b <= t.close_time < c]
        bal_is, bal_oos = balance_at(tr, deposit, a), balance_at(tr, deposit, b)
        e_is, e_oos = b - timedelta(seconds=1), c - timedelta(seconds=1)
        blk = best_block(is_tr)
        out.append({
            "no": i, "is_start": a, "oos_start": b, "oos_end": c, "block": blk,
            "is": compute_metrics(is_tr, bal_is, a, e_is),
            "is_blk": compute_metrics(apply_block(is_tr, blk), bal_is, a, e_is),
            "oos": compute_metrics(oos_tr, bal_oos, b, e_oos),
            "oos_blk": compute_metrics(apply_block(oos_tr, blk), bal_oos, b, e_oos),
        })
    return out


def wf_summary(windows: list[dict], is_key: str, oos_key: str, is_m: int, oos_m: int) -> dict:
    """判定: OOS黒字率70%以上かつWFE0.5以上→合格 / 黒字率50%以上→要注意 / それ未満→不合格."""
    ins, oos = [w[is_key] for w in windows], [w[oos_key] for w in windows]
    prof = sum(m["net"] > 0 for m in oos) / len(oos) * 100
    pfs = sorted(m["pf"] for m in oos if m["pf"] is not None)

    def ann(m: dict, months: int) -> float:
        return m["net"] / m["deposit"] * 12 / months if m["deposit"] > 0 else 0.0

    is_ann = statistics.fmean(ann(m, is_m) for m in ins)
    oos_ann = statistics.fmean(ann(m, oos_m) for m in oos)
    wfe = oos_ann / is_ann if is_ann > 0 else None
    verdict = "合格" if prof >= 70 and wfe is not None and wfe >= 0.5 else "要注意" if prof >= 50 else "不合格"
    return {"profitable_pct": prof, "pf_median": statistics.median(pfs) if pfs else None,
            "pf_min": pfs[0] if pfs else None, "wfe": wfe, "verdict": verdict,
            "is_ann": is_ann * 100, "oos_ann": oos_ann * 100, "oos_net": sum(m["net"] for m in oos)}


def write_wf_csv(path: str, windows: list[dict]) -> None:
    keys = ("trades", "net", "pf", "win_rate", "max_dd_pct", "sharpe")

    def val(v):
        return "" if v is None else "inf" if isinstance(v, float) and math.isinf(v) else (
            round(v, 4) if isinstance(v, float) else v)

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["window", "is_start", "oos_start", "oos_end", *(f"is_{k}" for k in keys),
                    *(f"oos_{k}" for k in keys), "block", *(f"oos_block_{k}" for k in keys)])
        for x in windows:
            w.writerow([x["no"], f"{x['is_start']:%Y-%m-%d}", f"{x['oos_start']:%Y-%m-%d}", f"{x['oos_end']:%Y-%m-%d}",
                        *(val(x["is"][k]) for k in keys), *(val(x["oos"][k]) for k in keys),
                        block_label(x["block"]), *(val(x["oos_blk"][k]) for k in keys)])


# ---------------------------------------------------------------- レポート

def fm(x: float | None, cur: str, sign: bool = False) -> str:
    if x is None:
        return "-"
    d = 0 if cur == "JPY" else 2
    return f"{x:+,.{d}f}" if sign else f"{x:,.{d}f}"


def fp(x: float | None, d: int = 1, sign: bool = False) -> str:
    return "-" if x is None else (f"{x:+.{d}f}%" if sign else f"{x:.{d}f}%")


def fr(x: float | None, d: int = 2) -> str:
    return "-" if x is None else "∞" if math.isinf(x) else f"{x:.{d}f}"


def rate_pf(pf: float | None) -> str:
    if pf is None:
        return ""
    return "負け" if pf < 1 else "薄い" if pf < 1.3 else "良好" if pf < 2 else "とても良い" if pf <= 2.5 else "過剰最適化を疑う"


def rate_sharpe(s: float | None) -> str:
    if s is None:
        return ""
    return "弱い" if s < 0.5 else "普通" if s < 1 else "良い" if s < 2 else "とても良い" if s <= 3 else "出来すぎ（疑う）"


def rate_dd(p: float | None) -> str:
    return "" if p is None else "目安内" if p <= 20 else "やや高い" if p <= 30 else "危険"


def rated(text: str, rating: str) -> str:
    return f"{text}（{rating}）" if rating else text


def metric_rows(m: dict, cur: str) -> list[tuple[str, str]]:
    span = f"{m['start']:%Y-%m-%d} ～ {m['end']:%Y-%m-%d}" if m["start"] and m["end"] else "-"
    return [
        ("期間", span),
        ("開始残高", fm(m["deposit"], cur)),
        ("決済取引数", f"{m['trades']:,}"),
        ("純損益", fm(m["net"], cur, True)),
        ("総利益 / 総損失", f"{fm(m['gross_profit'], cur)} / {fm(m['gross_loss'], cur)}"),
        ("プロフィットファクター", rated(fr(m["pf"]), rate_pf(m["pf"]))),
        ("勝率", fp(m["win_rate"])),
        ("平均利益 / 平均損失", f"{fm(m['avg_win'], cur)} / {fm(m['avg_loss'], cur)}"),
        ("ペイオフレシオ（平均利益÷平均損失）", fr(m["payoff"])),
        ("期待値（1取引あたり）", fm(m["expectancy"], cur, True)),
        ("最大連勝 / 最大連敗", f"{m['max_consec_wins']} / {m['max_consec_losses']}"),
        ("最大DD（残高ベース）", f"{fm(m['max_dd'], cur)}（{fp(m['max_dd_pct'])}・{rate_dd(m['max_dd_pct'])}）"),
        ("最長DD期間", f"{m['dd_days']:.0f} 日"),
        ("リカバリーファクター（純益÷最大DD）", fr(m["recovery"])),
        ("CAGR（年率リターン）", fp(m["cagr"])),
        ("カルマーレシオ（CAGR÷最大DD%）", fr(m["calmar"])),
        ("シャープレシオ（年率）", rated(fr(m["sharpe"]), rate_sharpe(m["sharpe"]))),
        ("ソルティノレシオ（年率）", fr(m["sortino"])),
    ]


def table(header: list[str], rows: list[list[str]], align: str = "") -> list[str]:
    align = align or "l" + "r" * (len(header) - 1)
    sep = ["---:" if a == "r" else "---" for a in align]
    return ["| " + " | ".join(header) + " |", "| " + " | ".join(sep) + " |",
            *("| " + " | ".join(r) + " |" for r in rows)]


def monthly_table(monthly: dict) -> list[str]:
    years = sorted({y for y, _ in monthly})
    rows = []
    for y in years:
        cells = [fp(monthly[(y, mo)][1], 1, True) if (y, mo) in monthly else "" for mo in range(1, 13)]
        keys = [k for k in monthly if k[0] == y]
        start_bal = monthly[min(keys)][2]
        total = sum(monthly[k][0] for k in keys)
        rows.append([str(y), *cells, fp(total / start_bal * 100 if start_bal > 0 else None, 1, True)])
    return table(["年", *(f"{m}月" for m in range(1, 13)), "年間"], rows)


def sec_summary(c: dict) -> list[str]:
    a, b, cur = c["A"]["metrics"], c["B"]["metrics"], c["cur"]
    out = ["## まとめ", ""]
    for label, m in ((c["label_a"], a), (c["label_b"], b)):
        out.append(f"- **{label}**: 純損益 {fm(m['net'], cur, True)} {cur} / PF {rated(fr(m['pf']), rate_pf(m['pf']))}"
                   f" / シャープ {rated(fr(m['sharpe']), rate_sharpe(m['sharpe']))}"
                   f" / 最大DD {fp(m['max_dd_pct'])}（残高ベース・{rate_dd(m['max_dd_pct'])}）")
    if c["wf"]:
        s0, s1 = c["wf_sum"]
        out.append(f"- **ウォークフォワード判定**: EAそのまま = **{s0['verdict']}**、時間帯ブロック最適化 = **{s1['verdict']}**")
    if c["dd99"] is not None:
        out.append(f"- **モンテカルロ**: 0.01ロットあたり最大DD（99%タイル）= {fm(c['dd99'], cur)} {cur}")
        out.append(f"- **推奨ロット**（資金 {c['capital']:,.0f} 円・許容DD {c['max_dd_pct']:g}%）: {c['lot_text']}")
    return out + [""]


def sec_data(c: dict) -> list[str]:
    ds, meta, cur, tr = c["ds"], c["ds"].meta, c["cur"], c["trades"]
    kinds = {"tester": "ストラテジーテスター・レポート", "statement": "口座履歴（詳細レポート）", "csv": "CSV"}
    first, last = min(t.open_time or t.close_time for t in tr), tr[-1].close_time
    rows = [["入力ファイル", ", ".join(os.path.basename(p) for p in c["files"])],
            ["形式", " + ".join(kinds.get(k, k) for k in ds.kind.split("+"))]]
    for key, label in (("symbol", "通貨ペア"), ("period", "テスト期間（ヘッダー）"), ("model", "モデル"), ("spread", "スプレッド")):
        if key in meta:
            rows.append([label, meta[key]])
    if "quality" in meta:
        rows.append(["モデリング品質", f"{meta['quality']:.2f}%"])
    rows += [["取引データ期間", f"{first:%Y-%m-%d} ～ {last:%Y-%m-%d}（約 {(last - first).days / 365.25:.1f} 年）"],
             ["決済取引数 / バスケット数", f"{len(tr):,} / {len(c['A']['baskets']):,}"],
             ["初期資金", f"{fm(c['deposit'], cur)} {cur}"],
             ["通貨", cur + (f"（USD→JPY 換算レート {c['usdjpy']:g}）" if c["usdjpy"] else "")]]
    if c["filter_text"]:
        rows.append(["分析対象の絞り込み", c["filter_text"]])
    out = ["## 1. データ概要", "", *table(["項目", "内容"], [[a, b.replace("|", "/")] for a, b in rows], "ll"), ""]
    if c["warnings"]:
        out += ["### 注意事項", "", *(f"- {w}" for w in c["warnings"]), ""]
    return out


def sec_metrics(c: dict) -> list[str]:
    a, b, cur, meta = c["A"]["metrics"], c["B"]["metrics"], c["cur"], c["ds"].meta
    rows = [[la, va, vb] for (la, va), (_, vb) in zip(metric_rows(a, cur), metric_rows(b, cur))]
    out = [f"## 2. 成績指標（{c['label_a']} と {c['label_b']} の比較）", "", f"金額の単位: {cur}", "",
           *table(["指標", c["label_a"], c["label_b"]], rows), "",
           "※ 最大DDは決済済み取引の残高曲線（初期資金込み、山から谷）で計算しています。"
           "ナンピン（逆行時に買い増し・売り増し）型EAでは含み損が決済まで表に出ないため、"
           "**有効証拠金（含み損込み）ベースのDDはこれより大きくなります**。"]
    eq = meta.get("eq_dd")
    if c["ds"].kind == "tester" and eq and eq[0]:
        ratio = f"、残高ベースの約 {eq[0] / c['bal_dd_all']:.1f} 倍" if c["bal_dd_all"] > 0 else ""
        rel = meta.get("eq_dd_rel")
        rel_text = f"、相対ドローダウン {fp(rel[1], 2)}" if rel and rel[1] is not None else ""
        out.append(f"テスターが記録した最大ドローダウン（含み損込み・テスト全期間）: **{fm(eq[0], cur)} {cur}"
                   f"（{fp(eq[1], 2)}）**{rel_text}{ratio}。")
    else:
        out.append("含み損込みのDDはこのデータからは分かりません（ストラテジーテスターのレポートなら取得できます）。")
    out += ["", f"### 月別リターン（{c['label_a']}、月初残高に対する%）", "", *monthly_table(a["monthly"]), ""]
    return out


def sec_wf(c: dict) -> list[str]:
    wf, cur, is_m, oos_m = c["wf"], c["cur"], c["is_m"], c["oos_m"]
    out = [f"## 3. ウォークフォワード分析（IS {is_m}ヶ月 → OOS {oos_m}ヶ月、{oos_m}ヶ月ずつずらす）", ""]
    if not wf:
        return out + [f"データ期間が IS+OOS（{is_m + oos_m}ヶ月）に満たないため省略しました。", ""]
    out += ["IS（インサンプル＝評価・調整に使う期間）の直後の OOS（アウトオブサンプル＝未知の期間）で成績が再現するかを、"
            "期間をずらしながら繰り返し確認します。EA内部のパラメータは固定なので、"
            "(1) EAそのままでの時期による安定性 と、(2) ユーザーが変更できる唯一の設定「新規エントリー停止時間帯」を"
            " IS で最適化して OOS に適用した場合 の2通りを検証します。", ""]

    def span(a: datetime, b: datetime) -> str:
        return f"{a:%Y-%m}～{b - timedelta(days=1):%Y-%m}"

    rows = []
    for w in wf:
        i, o = w["is"], w["oos"]
        rows.append([str(w["no"]), span(w["is_start"], w["oos_start"]), span(w["oos_start"], w["oos_end"]),
                     fr(i["pf"]), fm(i["net"], cur, True), fp(i["win_rate"]), fp(i["max_dd_pct"]), fr(i["sharpe"]),
                     str(i["trades"]), fr(o["pf"]), fm(o["net"], cur, True), fp(o["win_rate"]),
                     fp(o["max_dd_pct"]), fr(o["sharpe"]), str(o["trades"])])
    out += ["### (1) EAそのまま", "",
            *table(["#", "IS期間", "OOS期間", "IS PF", "IS 純益", "IS 勝率", "IS DD%", "IS SR", "IS 取引",
                    "OOS PF", "OOS 純益", "OOS 勝率", "OOS DD%", "OOS SR", "OOS 取引"], rows, "lll" + "r" * 12), ""]
    rows = [[str(w["no"]), block_label(w["block"]), fm(w["is_blk"]["net"], cur, True),
             f"{fm(w['oos']['net'], cur, True)} → {fm(w['oos_blk']['net'], cur, True)}",
             f"{fr(w['oos']['pf'])} → {fr(w['oos_blk']['pf'])}",
             f"{w['oos']['trades']} → {w['oos_blk']['trades']}"] for w in wf]
    out += ["### (2) 新規エントリー停止時間帯の最適化", "",
            f"各 IS で「純益 ÷ (最大DD + 1)」が最大になる連続 0～4 時間の停止時間帯（新規約定時刻、MT4サーバー時間）を選び、"
            f"続く OOS に適用します（IS の取引が {MIN_IS_TRADES} 回未満なら停止なし）。"
            "**停止時間帯に建てられた取引を単純に除外する近似**で、ナンピンの連鎖やポジション経路の変化は無視しています。", "",
            *table(["#", "ISで選ばれた停止時間帯", "IS 純益（停止後）", "OOS 純益 なし→あり", "OOS PF なし→あり",
                    "OOS 取引 なし→あり"], rows, "llrrrr"), ""]
    s0, s1 = c["wf_sum"]
    rows = [["OOS 黒字ウィンドウ率", fp(s0["profitable_pct"], 0), fp(s1["profitable_pct"], 0)],
            ["OOS PF 中央値 / 最小", f"{fr(s0['pf_median'])} / {fr(s0['pf_min'])}", f"{fr(s1['pf_median'])} / {fr(s1['pf_min'])}"],
            ["年率リターン 平均 IS / OOS", f"{fp(s0['is_ann'])} / {fp(s0['oos_ann'])}", f"{fp(s1['is_ann'])} / {fp(s1['oos_ann'])}"],
            ["WFE（OOS年率 ÷ IS年率）", fr(s0["wfe"]), fr(s1["wfe"])],
            ["OOS 合計純益", fm(s0["oos_net"], cur, True), fm(s1["oos_net"], cur, True)],
            ["**判定**", f"**{s0['verdict']}**", f"**{s1['verdict']}**"]]
    out += ["### 安定性の判定", "", *table(["評価項目", "EAそのまま", "時間帯ブロック適用"], rows), "",
            "判定基準: OOS 黒字ウィンドウ率 70% 以上 かつ WFE 0.5 以上 → **合格** / 黒字率 50% 以上 → **要注意** / それ未満 → **不合格**"]
    diff = s1["oos_net"] - s0["oos_net"]
    blocks = Counter(w["block"] for w in wf if w["block"][1] > 0)
    effect = ("改善。停止時間帯の設定を検討する価値はありますが、選ばれる時間帯が安定しているかも確認してください" if diff > 0
              else "改善せず。このデータでは停止時間帯の最適化に効果は見られません")
    out.append(f"時間帯ブロックによる OOS 合計純益の変化: {fm(diff, cur, True)} {cur}（{effect}）。")
    if blocks:
        (blk, k), = blocks.most_common(1)
        out.append(f"最も多く選ばれた停止時間帯: {block_label(blk)}（{len(wf)} 回中 {k} 回）。"
                   "毎回違う時間帯が選ばれる場合は、偶然のノイズを拾っている可能性が高いです。")
    return out + [""]


def sec_mc(c: dict) -> list[str]:
    cur = c["cur"]
    mcs = [(c["label_a"], c["A"]["mc"]), (c["label_b"], c["B"]["mc"])]
    out = ["## 4. モンテカルロ・シミュレーション", "",
           "決済が 60 秒以内に続いた取引を1つの「バスケット」（ナンピンの一括決済）とみなし、バスケット単位で復元抽出"
           "（ブートストラップ、履歴と同じ数）して取引順序を入れ替えた損益曲線を多数作り、最大DDの分布を推定します"
           "（固定ロット・複利なし）。DD% は開始残高に対する割合です。", ""]
    if not any(m for _, m in mcs):
        return out + ["バスケット数が少ないため省略しました。", ""]

    def cell(m: dict | None, f) -> str:
        return f(m) if m else "-"

    def dd(q: int):
        return lambda m: f"{fm(m['dd'][q], cur)}（{fp(m['dd'][q] / m['deposit'] * 100)}）"

    rows = [["試行回数 / バスケット数", *(cell(m, lambda m: f"{m['runs']:,} / {m['baskets']:,}") for _, m in mcs)],
            ["最大DD 50%タイル（中央値）", *(cell(m, dd(50)) for _, m in mcs)],
            ["最大DD 95%タイル", *(cell(m, dd(95)) for _, m in mcs)],
            ["最大DD 99%タイル", *(cell(m, dd(99)) for _, m in mcs)],
            ["DD 30%以上 になる確率", *(cell(m, lambda m: fp(m["p30"])) for _, m in mcs)],
            ["DD 50%以上 になる確率", *(cell(m, lambda m: fp(m["p50"])) for _, m in mcs)],
            ["破産確率（残高が開始残高の20%以下）", *(cell(m, lambda m: fp(m["ruin"], 2)) for _, m in mcs)],
            ["0.01ロット換算 最大DD 50/95/99%",
             *(cell(m, lambda m: " / ".join(fm(m["dd001"][q], cur) for q in (50, 95, 99))) for _, m in mcs)]]
    return out + [*table(["項目", *(lab for lab, _ in mcs)], rows), "",
                  f"金額の単位: {cur}。0.01ロット換算は各バスケットの最小ロット（＝初期ロット）を 0.01 に揃えて計算しています。",
                  "※ 取引順序の入れ替えでは含み損の深さ（決済前の評価損）は再現できません。", ""]


def sec_lot(c: dict) -> list[str]:
    out = ["## 5. 推奨ロット", ""]
    if c["dd99"] is None:
        return out + ["モンテカルロの結果がないため計算できません。", ""]
    dd99, safety, pct = c["dd99"], c["safety"], c["max_dd_pct"]
    out += ["推奨ロット = floor( 資金 × 許容DD% ÷ ( 0.01ロットあたり最大DD(99%タイル) × 安全係数 ) ) × 0.01", "",
            f"- 0.01ロットあたり最大DD(99%) = **{fm(dd99, 'JPY')} 円**（{c['label_a']} と {c['label_b']} の大きい方）",
            f"- 安全係数 = **{safety:.2f}**（{c['safety_reason']}）",
            f"- 許容DD = 資金の **{pct:g}%**",
            f"- 資金 {c['capital']:,.0f} 円 → {c['lot_text']}", ""]
    caps = sorted(set(CAPITALS) | {int(c["capital"])})
    rows = []
    for cap in caps:
        lot = recommend_lot(cap, dd99, pct, safety)
        if math.isinf(lot):
            rows.append([f"{cap:,}", "制限なし", "-", "-"])
            continue
        worst = lot / LOT_STEP * dd99 * safety
        rows.append([f"{cap:,}", f"{lot:.2f}" if lot >= LOT_STEP else "資金不足",
                     fm(worst, "JPY") if lot >= LOT_STEP else "-", fp(worst / cap * 100) if lot >= LOT_STEP else "-"])
    return out + [*table(["資金（円）", "推奨ロット", "想定最悪DD（円）", "資金比"], rows), "",
                  "※ 0.01ロット単位の損益が初期ロットに比例すると仮定しています（ナンピンのロット倍率も初期ロットに比例）。"
                  "証拠金維持率・ロスカット水準・スリッページ・スプレッド拡大は考慮していません。"
                  "ナンピン段数が増えると必要証拠金も増えるため、実際の口座では余裕を持たせてください。", ""]


GUIDE = """## 6. 指標の読み方

- **最大ドローダウン（最大DD）**: 資産の山（それまでの最高値）から谷までの最大の落ち込み。「最悪どれだけ減ったか」を表します。
  目安: 資金の **20% 以内** なら許容範囲、20～30% は注意、**30% 超は危険**（精神的にも運用を続けにくい）。
  ナンピン型は含み損が決済まで残高に出ないため、残高ベースのDDは実態より小さく見えます。テスターの「最大ドローダウン」（含み損込み）も必ず確認してください。
- **シャープレシオ（年率）**: リターン ÷ リターンのブレ（標準偏差）。毎日安定して増えているほど高くなります。
  目安: 0.5 未満 弱い / 0.5～1 普通 / 1～2 良い / 2～3 とても良い / **3 超は出来すぎ**（過剰最適化やテスト条件の甘さを疑う）。
  ナンピン型は損失を先送りするため、シャープが実態より高く出やすい点に注意。
- **プロフィットファクター（PF）**: 総利益 ÷ 総損失。1.0 を下回ると負け。
  目安: 1.0 未満 負け / 1.0～1.3 薄い（スプレッドやスリッページが増えると負けに転じやすい） / 1.3～2.0 良好 / 2.0～2.5 とても良い / **2.5 超は過剰最適化を疑う**。
- **WFE（ウォークフォワード効率）**: 未知期間（OOS）の年率リターン ÷ 評価期間（IS）の年率リターン。0.5 以上なら IS の成績が未知の期間でもある程度再現しています。
- **モンテカルロ 99%タイル**: 取引順序を入れ替えた多数のシナリオのうち「100回に1回の悪いケース」の最大DD。推奨ロットはこれに安全係数を掛けて計算しています。
- **モデリング品質**: 1分足EAは値動きの再現精度に敏感です。90% は標準ヒストリーの上限、実ティック（Tick Data Suite 等）なら 99.9%。90% 未満や実ティックなしの結果は楽観的になりやすいです。
"""


def build_report(c: dict) -> str:
    lines = ["# Mr.2 Gold バックテスト分析レポート", "",
             f"作成日時: {datetime.now():%Y-%m-%d %H:%M}　/　分析ツール: analyze_mt4.py", ""]
    for sec in (sec_summary, sec_data, sec_metrics, sec_wf, sec_mc, sec_lot):
        lines += sec(c)
    return "\n".join(lines) + "\n" + GUIDE


# ---------------------------------------------------------------- CLI

class JaHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, prefix or "使い方: ")


def collect_warnings(ds: Dataset, trades: list[Trade], cur: str, usdjpy: float | None) -> list[str]:
    w, meta = list(ds.warnings), ds.meta
    if ds.kind == "tester":
        q = meta.get("quality")
        if q is None:
            w.append("モデリング品質が不明です（n/a）。結果の信頼性を確認できません")
        elif q < 90:
            w.append(f"モデリング品質 {q:.2f}% は 90% 未満です：**結果は楽観的になりやすい**（信頼性が低い）")
        elif q < 99:
            w.append(f"M1（1分足）EA を実ティックデータなし（モデリング品質 {q:.2f}%）でテストしています："
                     "**結果は楽観的になりやすい**。Tick Data Suite 等の実ティック（99.9%）での再テストを推奨")
        if "model" in meta and not re.search(r"every tick|全ティック", meta["model"], re.I):
            w.append("モデルが「全ティック」ではありません：1分足EAの結果としては信頼できません")
        if re.search(r"current|現在", meta.get("spread", ""), re.I):
            w.append("スプレッドが「現在値」で固定されています：指標時などのスプレッド拡大は反映されていません")
    else:
        w.append("口座履歴/CSV のため、含み損（有効証拠金）ベースのDDは分かりません")
    if (k := sum(t.lots <= 0 for t in trades)):
        w.append(f"ロット不明の取引 {k} 件は 0.01 ロットとみなしました")
    if (k := sum(t.open_time is None for t in trades)):
        w.append(f"新規約定時刻が不明な取引 {k} 件は決済時刻で時間帯を判定しました")
    if cur != "JPY" and not usdjpy:
        w.append(f"損益通貨が {cur} です。推奨ロット表は円建てを前提とするため --usdjpy の指定を推奨します")
    return w


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="analyze_mt4.py", description=__doc__, add_help=False,
                                 usage="%(prog)s ファイル [ファイル ...] [オプション]",
                                 formatter_class=JaHelpFormatter)
    g = ap.add_argument_group("入力")
    g.add_argument("files", nargs="+", help="StrategyTester.htm / 詳細レポート .htm / CSV（複数可）")
    g.add_argument("--deposit", type=float, help="初期資金を上書き（元データの通貨で指定。不明なら --capital を使用）")
    g.add_argument("--currency", help="通貨ラベル（既定: データから取得、無ければ JPY）")
    g.add_argument("--usdjpy", type=float, help="損益が USD のとき円に換算するレート（例: 150）")
    g = ap.add_argument_group("期間")
    g.add_argument("--start", help="分析開始日（例: 2021-01-01、決済日時で絞り込み）")
    g.add_argument("--end", help="分析終了日（この日を含む）")
    g.add_argument("--recent-months", type=int, default=12, help="比較する直近期間の月数（既定 12）")
    g.add_argument("--recent-start", help="直近期間の開始日（指定すると --recent-months より優先）")
    g = ap.add_argument_group("ウォークフォワード")
    g.add_argument("--is-months", type=int, default=12, help="IS（評価期間）の月数（既定 12）")
    g.add_argument("--oos-months", type=int, default=3, help="OOS（検証期間）の月数＝ずらし幅（既定 3）")
    g = ap.add_argument_group("モンテカルロ・推奨ロット")
    g.add_argument("--mc-runs", type=int, default=10000, help="モンテカルロ試行回数（既定 10000）")
    g.add_argument("--seed", type=int, default=42, help="乱数シード（既定 42、同じ値なら同じ結果）")
    g.add_argument("--capital", type=float, default=140000, help="推奨ロット計算に使う運用資金（円、既定 140000）")
    g.add_argument("--max-dd-pct", type=float, default=30, help="許容する最大DD（資金に対する%%、既定 30）")
    g.add_argument("--safety", type=float, default=1.5,
                   help="安全係数（既定 1.5。テスターの含み損DD÷残高DD の方が大きければそちらを使用）")
    g = ap.add_argument_group("出力")
    g.add_argument("--out", help="Markdown レポートの保存先（画面にも表示します）")
    g.add_argument("--csv", help="ウォークフォワード各ウィンドウの指標を CSV で保存")
    g.add_argument("-h", "--help", action="help", help="このヘルプを表示して終了")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    try:
        ds = load_all(args.files)
    except (OSError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    if args.deposit:
        ds.deposit = args.deposit
    if args.usdjpy:
        convert_currency(ds, args.usdjpy)
    cur = args.currency or ("JPY" if args.usdjpy else ds.currency) or "JPY"
    deposit = ds.deposit
    if not deposit:
        ds.warnings.append(f"初期資金が不明なため --capital の {args.capital:,.0f} を初期資金とみなしました（--deposit で指定可）")
        deposit = args.capital
    all_tr = ds.trades
    bal_dd_all = drawdown(all_tr, deposit, None)[0]

    start = parse_day(args.start) if args.start else None
    end = parse_day(args.end) + timedelta(days=1) if args.end else None
    tr = [t for t in all_tr if (not start or t.close_time >= start) and (not end or t.close_time < end)]
    if not tr:
        print("エラー: 指定期間に取引がありません", file=sys.stderr)
        return 1
    dep0 = balance_at(all_tr, deposit, start) if start else deposit
    filter_text = " ".join(x for x in (f"{args.start} から" if args.start else "", f"{args.end} まで" if args.end else "") if x)

    last = tr[-1].close_time
    if args.recent_start:
        r_start, label_b = parse_day(args.recent_start), f"{args.recent_start} 以降"
    else:
        r_start, label_b = add_months(month_floor(last), 1 - args.recent_months), f"直近{args.recent_months}ヶ月"
    rec = [t for t in tr if t.close_time >= r_start]
    span_start = max(r_start, start) if start else r_start

    print("分析中（モンテカルロは少し時間がかかります）...", file=sys.stderr)
    periods = {}
    for key, trades, dep, s in (("A", tr, dep0, start), ("B", rec, balance_at(tr, dep0, r_start), span_start)):
        baskets = group_baskets(trades)
        periods[key] = {"metrics": compute_metrics(trades, dep, s, end - timedelta(seconds=1) if end else None),
                        "baskets": baskets, "mc": monte_carlo(baskets, dep, args.mc_runs, args.seed)}
    wf = walk_forward(tr, dep0, args.is_months, args.oos_months)
    wf_sum = (wf_summary(wf, "is", "oos", args.is_months, args.oos_months),
              wf_summary(wf, "is_blk", "oos_blk", args.is_months, args.oos_months)) if wf else None

    mcs = [p["mc"] for p in periods.values() if p["mc"]]
    dd99 = max(m["dd001"][99] for m in mcs) if mcs else None
    safety, safety_reason = args.safety, "既定値"
    eq = ds.meta.get("eq_dd")
    if ds.kind == "tester" and eq and eq[0] and bal_dd_all > 0:
        ratio = eq[0] / bal_dd_all
        safety = max(args.safety, ratio)
        safety_reason = f"テスターの含み損DD ÷ 残高DD = {ratio:.2f} と {args.safety:g} の大きい方"
    lot_text = "-"
    if dd99 is not None:
        lot = recommend_lot(args.capital, dd99, args.max_dd_pct, safety)
        if math.isinf(lot):
            lot_text = "DDが記録されていないため計算できません"
        elif lot >= LOT_STEP:
            lot_text = f"**{lot:.2f} ロット**"
        else:
            need = [required_capital(x, dd99, args.max_dd_pct, safety) for x in (0.01, 0.02)]
            lot_text = (f"**資金不足**（0.01ロットに必要な資金 {need[0]:,.0f} 円、0.02ロットなら {need[1]:,.0f} 円）")

    ctx = {"ds": ds, "files": args.files, "trades": tr, "cur": cur, "deposit": deposit, "usdjpy": args.usdjpy,
           "filter_text": filter_text, "A": periods["A"], "B": periods["B"],
           "label_a": "全期間" if not filter_text else "指定期間", "label_b": label_b,
           "wf": wf, "wf_sum": wf_sum, "is_m": args.is_months, "oos_m": args.oos_months,
           "dd99": dd99, "safety": safety, "safety_reason": safety_reason, "capital": args.capital,
           "max_dd_pct": args.max_dd_pct, "lot_text": lot_text, "bal_dd_all": bal_dd_all,
           "warnings": collect_warnings(ds, tr, cur, args.usdjpy)}
    report = build_report(ctx)
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"レポートを保存しました: {args.out}", file=sys.stderr)
    if args.csv and wf:
        write_wf_csv(args.csv, wf)
        print(f"ウィンドウ別CSVを保存しました: {args.csv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
