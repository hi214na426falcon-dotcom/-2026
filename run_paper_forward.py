#!/usr/bin/env python3
"""ペーパー・フォワードテスト（Actions ランナー用・執行なしの正直な前向き採点）。

事前登録済みの forward_test.json のピック（このスクリプトより前にコミット済み＝
後出し不可）を、Coinbase から到着する新しい1分足に適用して紙上取引を記録する。

原則:
- start_from（初回実行時刻）より前のバーでは取引しない（ピック確定前のデータで
  成績を作らない）
- 完成したバーのみ使用（形成中の現在分は除外）
- エントリー = シグナルバーの終値 / 判定 = expiry_min 分後のバーの終値
- 同値=負け・1,000円固定・ペイアウト1.90想定・建玉中は新規なし（no_overlap）

状態は results/paper/ に保存し、ワークフローがブランチへコミットする。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))

from backtest.data import Bar, Series
from backtest.strategies import DOWN, UP, STRATEGIES
from backtest.walkforward import slot_index_jst
from fetch_crypto import _get, BASE, PRODUCTS

STATE_PATH = os.path.join("results", "paper", "paper_state.json")
LOG_PATH = os.path.join("results", "paper", "paper_log.jsonl")
FWD_PATH = os.path.join("overlay", "server", "forward_test.json")
PAYOUT = 1.90
STAKE = 1000.0
HISTORY_KEEP = 600
# 新規エントリーを止める時刻（UTC）。既定は当面の継続運用のため先の日付。
# 環境変数 PAPER_TRADE_UNTIL（ISO8601）で上書き可。以降は決済のみ・新規なし。
TRADE_UNTIL = datetime.fromisoformat(
    os.environ.get("PAPER_TRADE_UNTIL", "2026-07-21T22:00:00+00:00"))


def in_slot(iso: str, slot) -> bool:
    if slot == "all":
        return slot_index_jst(iso) is not None
    h = (datetime.fromisoformat(iso).hour + 9) % 24
    return slot[0] <= h < slot[1]


def fetch_recent(product: str, start: datetime, end: datetime):
    """[start, end] の完成1分足を (iso, close) 昇順で返す。"""
    out = {}
    cur = start
    while cur < end:
        chunk_end = min(cur + timedelta(minutes=299), end)
        url = (f"{BASE}/products/{product}/candles?granularity=60"
               f"&start={cur.isoformat()}&end={chunk_end.isoformat()}")
        for row in _get(url) or []:
            try:
                t = datetime.fromtimestamp(int(row[0]), tz=timezone.utc)
                out[t.isoformat()] = float(row[4])
            except (ValueError, IndexError, TypeError):
                continue
        cur = chunk_end + timedelta(minutes=1)
    return sorted(out.items())


def signal_at_last(pick, closes, times):
    sbars = [Bar(time=times[i], open=c, high=c, low=c, close=c)
             for i, c in enumerate(closes)]
    fn = STRATEGIES[pick["strategy"]]
    sig = fn(Series(sbars, name=pick["pair"]), **(pick.get("params") or {}))
    last = sig[-1] if sig else None
    if pick.get("invert") and last is not None:
        last = UP if last == DOWN else DOWN
    return last


TODAY_PATH = os.path.join("results", "paper", "today_pairs.json")


def _todays_pairs():
    """当日の対象ペア（run_daily_cycle.py が選抜）。無ければ None＝全推奨。"""
    if not os.path.exists(TODAY_PATH):
        return None
    try:
        with open(TODAY_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return set(d.get("pairs") or [])
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    now = datetime.now(timezone.utc)
    todays = _todays_pairs()
    with open(FWD_PATH, encoding="utf-8") as f:
        picks = [p for p in json.load(f).get("picks", [])
                 if p["pair"] in PRODUCTS and p.get("recommended")
                 and (todays is None or p["pair"] in todays)]
    if not picks:
        print("本日の対象ペアなし（today_pairs.json の選抜で0件）")
        return 0

    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state = {}
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)

    closed_total = []
    for pick in picks:
        pair = pick["pair"]
        st = state.setdefault(pair, {
            "start_from": now.isoformat(),
            "history": [], "pending": None,
            "n": 0, "w": 0, "l": 0, "pnl": 0.0,
        })
        start_from = datetime.fromisoformat(st["start_from"])
        last_hist = (datetime.fromisoformat(st["history"][-1][0])
                     if st["history"] else now - timedelta(hours=10))
        # 完成バーのみ（90秒マージン）
        bars = fetch_recent(PRODUCTS[pair], last_hist + timedelta(minutes=1),
                            now - timedelta(seconds=90))
        hist = st["history"] + [[t, c] for t, c in bars]
        hist = hist[-HISTORY_KEEP:]
        st["history"] = hist
        times = [h[0] for h in hist]
        closes = [h[1] for h in hist]
        close_by_time = dict(zip(times, closes))

        for i, (t, c) in enumerate(zip(times, closes)):
            if datetime.fromisoformat(t) <= last_hist:
                continue  # 既処理
            # 1) 建玉の決済判定
            p = st["pending"]
            if p:
                exp_t = (datetime.fromisoformat(p["entry_time"])
                         + timedelta(minutes=pick["expiry_min"])).isoformat()
                if t >= exp_t:
                    # 判定分のバーが欠損していたら、それ以降の最初のバーで決済
                    exit_px = close_by_time.get(exp_t, c)
                    move = exit_px - p["entry"]
                    if p["direction"] == "DOWN":
                        move = -move
                    win = move > 0
                    st["n"] += 1
                    st["w" if win else "l"] += 1
                    pnl = STAKE * (PAYOUT - 1) if win else -STAKE
                    st["pnl"] += pnl
                    # JST日付タグ（日次評価用）＝エントリー時刻+9h の日付
                    jday = (datetime.fromisoformat(p["entry_time"])
                            + timedelta(hours=9)).date().isoformat()
                    rec = {"pair": pair, "day": jday,
                           "entry_time": p["entry_time"],
                           "direction": p["direction"], "entry": p["entry"],
                           "exit_time": exp_t, "exit": exit_px,
                           "result": "win" if win else "loss", "pnl": pnl}
                    closed_total.append(rec)
                    with open(LOG_PATH, "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    st["pending"] = None
            # 2) 新規シグナル（テスト期限内・スロット内・建玉なし・開始時刻以降）
            bar_dt = datetime.fromisoformat(t)
            if (st["pending"] is None and bar_dt >= start_from
                    and bar_dt <= TRADE_UNTIL and in_slot(t, pick["slot_jst"])
                    and i >= 40):
                d = signal_at_last(pick, closes[:i + 1], times[:i + 1])
                if d is not None:
                    st["pending"] = {"entry_time": t, "entry": c,
                                     "direction": d}

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)

    print(f"=== ペーパー・フォワードテスト {now.isoformat()} ===")
    for pair, st in state.items():
        n, w = st["n"], st["w"]
        wr = f"{w/n*100:.1f}%" if n else "―"
        pend = st["pending"]
        print(f"{pair}: {n}戦 {w}勝{st['l']}敗 勝率 {wr} 損益 {st['pnl']:+,.0f}円"
              f"  建玉 {pend['direction']+'@'+pend['entry_time'] if pend else 'なし'}")
    if closed_total:
        print(f"今回の決済 {len(closed_total)} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
