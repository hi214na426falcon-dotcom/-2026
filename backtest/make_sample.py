#!/usr/bin/env python3
"""テスト用の合成（架空）MT4 ストラテジーテスター・レポートを生成する.

乱数で作った *架空の* 取引履歴（XAUUSD M1 風、ナンピン風バスケットを含む）で、実在EAの成績ではない。
analyze_mt4.py の動作確認・ユニットテスト専用。英語ラベル版（ASCII のみ）と日本語ラベル版（Shift_JIS）を出力する。

使い方:
    python backtest/make_sample.py --out-dir /tmp/samples
    python backtest/make_sample.py --out-dir . --years 2 --seed 7
"""
from __future__ import annotations

import argparse
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

USDJPY = 150.0
OZ_PER_LOT = 100
DEPOSIT = 1_000_000.0
START = datetime(2021, 1, 4)
BAD_HOURS = (15, 16, 17)  # 架空の「荒れやすい時間帯」（時間帯ブロックの検証用）


@dataclass
class SampleTrade:
    order: int
    side: str
    lots: float
    open_time: datetime
    open_price: float
    close_time: datetime
    close_price: float
    close_type: str
    pnl: float = 0.0


def _single(rng: random.Random, t0: datetime, price: float) -> list[SampleTrade]:
    side = rng.choice(("buy", "sell"))
    sign = 1 if side == "buy" else -1
    win = rng.random() < (0.55 if t0.hour in BAD_HOURS else 0.80)
    move = rng.uniform(1.5, 3.5) if win else -rng.uniform(4.0, 8.0)
    op = price + rng.uniform(-5, 5)
    t1 = t0 + timedelta(minutes=rng.randint(1, 120))
    lots = rng.choice((0.01, 0.01, 0.01, 0.02))
    return [SampleTrade(0, side, lots, t0, round(op, 2), t1, round(op + sign * move, 2), "t/p" if win else "s/l")]


def _basket(rng: random.Random, t0: datetime, price: float) -> list[SampleTrade]:
    """逆行するたびにロットを増やして追加エントリーし、全ポジションを同時に決済する（ナンピン風）."""
    side = rng.choice(("buy", "sell"))
    sign = 1 if side == "buy" else -1
    lots = (0.01, 0.02, 0.03, 0.05, 0.08)[:rng.randint(2, 5)]
    step, p0, t = rng.uniform(2.5, 4.0), price + rng.uniform(-5, 5), t0
    opens = []
    for i in range(len(lots)):
        opens.append((t, round(p0 - sign * step * i, 2)))
        t += timedelta(minutes=rng.randint(3, 40))
    avg = sum(lot * p for lot, (_, p) in zip(lots, opens)) / sum(lots)
    win = rng.random() < 0.88
    close_p = avg + sign * rng.uniform(1.0, 2.5) if win else opens[-1][1] - sign * rng.uniform(4.0, 8.0)
    t_close = t + timedelta(minutes=rng.randint(1, 60))
    return [SampleTrade(0, side, lot, ot, op, t_close, round(close_p, 2), "close") for lot, (ot, op) in zip(lots, opens)]


def generate_trades(seed: int = 42, years: float = 5.0) -> list[SampleTrade]:
    rng = random.Random(seed)
    trades: list[SampleTrade] = []
    price, day, end = 1850.0, START, START + timedelta(days=round(365.25 * years))
    while day < end:
        price = max(1200.0, price + rng.gauss(0.15, 18))  # 日次のランダムウォーク
        if day.weekday() < 5:
            for _ in range(rng.choice((1, 1, 2, 2, 3))):
                t0 = day + timedelta(hours=rng.randint(1, 22), minutes=rng.randint(0, 59))
                trades += (_basket if rng.random() < 0.12 else _single)(rng, t0, price)
        day += timedelta(days=1)
    trades.sort(key=lambda t: t.open_time)
    for i, t in enumerate(trades, 1):
        sign = 1 if t.side == "buy" else -1
        t.order = i
        t.pnl = round((t.close_price - t.open_price) * sign * t.lots * OZ_PER_LOT * USDJPY)
    return trades


LABELS = {
    "en": dict(
        title="Strategy Tester Report", symbol="Symbol", period="Period", model="Model", params="Parameters",
        bars="Bars in test", ticks="Ticks modelled", quality="Modelling quality", mismatch="Mismatched charts errors",
        deposit="Initial deposit", spread="Spread", net="Total net profit", gp="Gross profit", gl="Gross loss",
        pf="Profit factor", ep="Expected payoff", absdd="Absolute drawdown", maxdd="Maximal drawdown",
        reldd="Relative drawdown", total="Total trades",
        cols=("#", "Time", "Type", "Order", "Size", "Price", "S / L", "T / P", "Profit", "Balance"),
        period_v="1 Minute (M1)", spread_v="Current (35)",
        model_v="Every tick (the most precise method based on all available least timeframes to generate each tick)",
        note="SYNTHETIC SAMPLE - FAKE DATA FOR TESTING ONLY (not real EA results)", charset="windows-1252"),
    "ja": dict(
        title="ストラテジーテスター・レポート", symbol="通貨ペア", period="期間", model="モデル", params="パラメーター",
        bars="テストバー数", ticks="モデルティック数", quality="モデリング品質", mismatch="不整合チャートエラー",
        deposit="初期証拠金", spread="スプレッド", net="純益", gp="総利益", gl="総損失",
        pf="プロフィットファクター", ep="期待利得", absdd="絶対ドローダウン", maxdd="最大ドローダウン",
        reldd="相対ドローダウン", total="総取引数",
        cols=("#", "時間", "取引種別", "注文番号", "数量", "価格", "決済逆指値（S/L）", "決済指値（T/P）", "損益", "残高"),
        period_v="1分足 (M1)", spread_v="現在値 (35)",
        model_v="全ティック（利用可能な最小時間枠を使った最も正確な方法）",
        note="合成サンプル：テスト専用の架空データ（実在EAの成績ではありません）", charset="shift_jis"),
}


def _fmt_time(t: datetime) -> str:
    return t.strftime("%Y.%m.%d %H:%M")


def _trade_rows(trades: list[SampleTrade], rng: random.Random) -> list[str]:
    events = []  # (時刻, 種類 0=新規 1=変更 2=決済, 注文番号, 種別, 取引)
    for t in trades:
        events.append((t.open_time, 0, t.order, t.side, t))
        events.append((t.close_time, 2, t.order, t.close_type, t))
        if t.close_type != "close" and rng.random() < 0.2:
            events.append((t.open_time + timedelta(minutes=1), 1, t.order, "modify", t))
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    rows, bal = [], DEPOSIT
    for i, (when, kind, order, typ, t) in enumerate(events, 1):
        price = t.close_price if kind == 2 else t.open_price
        cells = f"<td>{i}</td><td class=msdate>{_fmt_time(when)}</td><td>{typ}</td><td>{order}</td>" \
                f"<td class=mspt>{t.lots:.2f}</td><td>{price:.2f}</td><td>0.00</td><td>0.00</td>"
        if kind == 2:
            bal += t.pnl
            cells += f"<td class=mspt>{t.pnl:.2f}</td><td class=mspt>{bal:.2f}</td>"
        else:
            cells += "<td colspan=2></td>"
        bg = ' bgcolor="#E0E0E0"' if i % 2 == 0 else ""
        rows.append(f"<tr{bg} align=right>{cells}</tr>")
    return rows


def render_html(trades: list[SampleTrade], lang: str = "en", seed: int = 42) -> str:
    L = LABELS[lang]
    pnls = [t.pnl for t in sorted(trades, key=lambda t: t.close_time)]
    gp, gl = sum(p for p in pnls if p > 0), -sum(p for p in pnls if p < 0)
    bal = peak = low = DEPOSIT
    dd = dd_pct = 0.0
    for p in pnls:
        bal += p
        peak, low = max(peak, bal), min(low, bal)
        dd, dd_pct = max(dd, peak - bal), max(dd_pct, (peak - bal) / peak * 100)
    eq_dd, eq_pct = dd * 1.8, dd_pct * 1.8  # 架空の「含み損込みDD」（残高DDの1.8倍）
    first, last = trades[0].open_time, max(t.close_time for t in trades)

    def row(label: str, value: str) -> str:
        return f"<tr align=left><td colspan=2>{label}</td><td colspan=4>{value}</td></tr>"

    head = [
        row(L["symbol"], "XAUUSD (Gold vs US Dollar)"),
        row(L["period"], f"{L['period_v']} {_fmt_time(first)} - {_fmt_time(last)} ({first:%Y.%m.%d} - {last:%Y.%m.%d})"),
        row(L["model"], L["model_v"]),
        row(L["params"], "Lots=0.01; StopHourStart=0; StopHourEnd=0; (synthetic)"),
        f"<tr align=left><td>{L['bars']}</td><td align=right>1854321</td><td>{L['ticks']}</td>"
        f"<td align=right>98765432</td><td>{L['quality']}</td><td align=right>90.00%</td></tr>",
        f"<tr align=left><td>{L['mismatch']}</td><td align=right>0</td></tr>",
        f"<tr align=left><td>{L['deposit']}</td><td align=right>{DEPOSIT:.2f}</td><td></td><td></td>"
        f"<td>{L['spread']}</td><td align=right>{L['spread_v']}</td></tr>",
        f"<tr align=left><td>{L['net']}</td><td align=right>{gp - gl:.2f}</td><td>{L['gp']}</td>"
        f"<td align=right>{gp:.2f}</td><td>{L['gl']}</td><td align=right>{-gl:.2f}</td></tr>",
        f"<tr align=left><td>{L['pf']}</td><td align=right>{gp / gl:.2f}</td><td>{L['ep']}</td>"
        f"<td align=right>{(gp - gl) / len(pnls):.2f}</td><td></td><td></td></tr>",
        f"<tr align=left><td>{L['absdd']}</td><td align=right>{DEPOSIT - low:.2f}</td><td>{L['maxdd']}</td>"
        f"<td align=right>{eq_dd:.2f} ({eq_pct:.2f}%)</td><td>{L['reldd']}</td>"
        f"<td align=right>{eq_pct:.2f}% ({eq_dd:.2f})</td></tr>",
        f"<tr align=left><td>{L['total']}</td><td align=right>{len(pnls)}</td></tr>",
    ]
    cols = "".join(f"<td>{c}</td>" for c in L["cols"])
    body = _trade_rows(trades, random.Random(seed + 1))
    return "\n".join([
        "<html><head>",
        f"<title>Strategy Tester: Mr.2 Gold [{L['note']}]</title>",
        f'<meta http-equiv="Content-Type" content="text/html; charset={L["charset"]}">',
        "</head><body><div align=center>",
        f'<div style="font: 20pt Times New Roman"><b>{L["title"]}</b></div>',
        f'<div style="font: 14pt Times New Roman; color: red"><b>{L["note"]}</b></div>',
        '<div style="font: 16pt Times New Roman"><b>Mr.2 Gold</b></div><br>',
        "<table width=820 cellspacing=1 cellpadding=3 border=0>", *head, "</table><br>",
        "<table width=820 cellspacing=1 cellpadding=3 border=0>",
        f'<tr bgcolor="#C0C0C0" align=right>{cols}</tr>', *body, "</table>",
        "</div></body></html>", ""])


def write_samples(out_dir: str, seed: int = 42, years: float = 5.0) -> dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    trades = generate_trades(seed, years)
    paths = {}
    for lang in ("en", "ja"):
        path = os.path.join(out_dir, f"sample_tester_{lang}.htm")
        with open(path, "w", encoding="cp932", newline="\r\n") as f:
            f.write(render_html(trades, lang, seed))
        paths[lang] = path
    return paths


class JaHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, prefix or "使い方: ")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, add_help=False, usage="%(prog)s [オプション]",
                                 formatter_class=JaHelpFormatter)
    ap._optionals.title = "オプション"
    ap.add_argument("-h", "--help", action="help", help="このヘルプを表示して終了")
    ap.add_argument("--out-dir", default=".", help="出力先フォルダ（既定: カレント）")
    ap.add_argument("--seed", type=int, default=42, help="乱数シード（既定 42）")
    ap.add_argument("--years", type=float, default=5.0, help="生成する期間（年、既定 5）")
    args = ap.parse_args(argv)
    for lang, path in write_samples(args.out_dir, args.seed, args.years).items():
        print(f"[架空データ] {lang}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
