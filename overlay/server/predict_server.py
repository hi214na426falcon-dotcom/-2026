#!/usr/bin/env python3
"""ローカル予測サーバー（Python 標準ライブラリのみ、ポート 8765）。

オーバーレイ拡張へ次を配信する:
- 現在の JST 時間帯の推奨通貨ペア・想定勝率（scout が生成した schedule.json より）
- 連勝数・ボーナスステージ状態（3連勝で逆マーチン。money_mgmt より）
- 予測方向/確率（★ backtest/results/approved_strategy.json が存在し、
  MASTER_PROMPT の合格基準スキーマを満たす時のみ非null。事故防止のため既定はnull）

★ このサーバーもブローカーの発注には一切関与しない（表示専用）。

起動:
    cd overlay/server
    python3 predict_server.py            # http://localhost:8765
    python3 predict_server.py --port 9000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))
for _p in (REPO_ROOT, THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest.money_mgmt import MoneyManager  # noqa: E402
from backtest.inference import infer_direction  # noqa: E402
from backtest.sessions import (  # noqa: E402
    MASTER_SESSIONS_JST, hour_in_windows, parse_hour,
)
from agents.schedule_schema import current_slot as sched_current_slot  # noqa: E402
import live_feed  # noqa: E402  （overlay/server 内の同階層モジュール）

SCHEDULE_PATH = os.path.join(THIS_DIR, "schedule.json")
APPROVED_PATH = os.path.join(REPO_ROOT, "backtest", "results", "approved_strategy.json")
DATA_DIR = os.path.join(REPO_ROOT, "data", "m1")

# 予測方向を出してよい approved_strategy.json の必須キー（README の想定スキーマ）。
_APPROVED_REQUIRED = ("pair", "strategy", "expiry_min", "payout", "oos_passed")

_lock = threading.Lock()
_mm = MoneyManager()
_sched_cache = {"mtime": None, "data": None}


def load_schedule():
    """schedule.json を（更新されていれば）読み直す。"""
    try:
        mtime = os.path.getmtime(SCHEDULE_PATH)
    except OSError:
        return None
    if _sched_cache["mtime"] != mtime:
        try:
            with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
                _sched_cache["data"] = json.load(f)
            _sched_cache["mtime"] = mtime
        except (OSError, json.JSONDecodeError):
            return _sched_cache["data"]
    return _sched_cache["data"]


def load_approved(approved_path: str = None) -> dict:
    """approved_strategy.json を読む（無効なら None）。"""
    path = approved_path or APPROVED_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            approved = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not all(k in approved for k in _APPROVED_REQUIRED) or not approved.get("oos_passed"):
        return None
    return approved


def get_prediction(pair: str, approved_path: str = None, data_dir: str = None) -> dict:
    """方向/確率を返す。合格戦略＋相場データが揃った時のみ非null。

    合格戦略が無ければ必ず null（＝予測は出さない・事故防止）。
    """
    base = {"pair": pair, "direction": None, "confidence": None,
            "status": "検証済み戦略なし — 予測は表示できません"}
    approved = load_approved(approved_path)
    if approved is None:
        if os.path.exists(approved_path or APPROVED_PATH):
            base["status"] = "approved_strategy.json はあるが合格基準スキーマ未充足"
        return base

    # 合格戦略は特定ペア専用。推奨ペアが違う時はそのペアの方向は出さない。
    if pair != approved.get("pair"):
        base["status"] = f"{approved.get('pair')} の合格戦略のみ有効（方向は非表示）"
        return base

    bars = live_feed.recent_bars(approved["pair"], data_dir or DATA_DIR)
    if not bars:
        base["status"] = "相場データなし（data/m1 にCSVを配置、またはライブ接続が必要）"
        return base

    # セッション外なら方向を出さない（合格戦略の対象時間帯だけ）
    sessions = [tuple(s) for s in approved.get("sessions_jst", [])] or list(MASTER_SESSIONS_JST)
    tz = approved.get("tz_offset_hours", 9)
    last_hour = parse_hour(bars.get("last_time"), tz)
    if last_hour is not None and not hour_in_windows(last_hour, sessions):
        base["status"] = "対象時間帯外（夜17-24 / 深夜0-6 JST）"
        return base

    inf = infer_direction(approved, bars["closes"], bars["times"])
    return {"pair": pair, "direction": inf["direction"],
            "confidence": inf["confidence"], "status": inf["status"]}


def build_state() -> dict:
    """オーバーレイ用のまとめ状態。"""
    sched = load_schedule()
    slot = sched_current_slot(sched) if sched else None
    pair = (slot or {}).get("recommended_pair") or "USDJPY"
    pred = get_prediction(pair)
    with _lock:
        money = _mm.snapshot()
    return {
        "feed_status": "オンライン",
        "connected": True,
        "current_slot": slot,
        "schedule_mode": (sched or {}).get("mode"),
        "direction": pred["direction"],
        "confidence": pred["confidence"],
        "status": pred["status"],
        "money": money,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # ノイズ抑制
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/state":
            self._send(200, build_state())
        elif parsed.path == "/schedule":
            self._send(200, load_schedule() or {"error": "schedule.json がありません。run_scout.py を実行してください"})
        elif parsed.path == "/prediction":
            q = parse_qs(parsed.query)
            pair = (q.get("pair", ["USDJPY"])[0]) or "USDJPY"
            self._send(200, get_prediction(pair))
        elif parsed.path in ("/", "/health"):
            self._send(200, {"ok": True, "service": "binary-sign predict server"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}

        if parsed.path == "/result":
            result = body.get("result")
            if result not in ("win", "loss", "tie"):
                self._send(400, {"error": "result は win/loss/tie"})
                return
            with _lock:
                _mm.record(result)
            self._send(200, build_state())
        elif parsed.path == "/reset":
            with _lock:
                _mm.reset()
            self._send(200, build_state())
        else:
            self._send(404, {"error": "not found"})


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ローカル予測サーバー（表示専用）")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args(argv)

    sched = load_schedule()
    if sched:
        print(f"[サーバー] schedule.json 読込 OK（mode={sched.get('mode')}, "
              f"{len(sched.get('slots', []))}時間帯）")
    else:
        print("[サーバー] schedule.json が未生成です。別ターミナルで "
              "`python3 run_scout.py` を実行してください（無くても起動はします）。")
    print(f"[サーバー] http://{args.host}:{args.port}  （Ctrl+C で終了）")
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[サーバー] 終了しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
