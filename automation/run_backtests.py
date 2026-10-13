#!/usr/bin/env python3
"""Mr.2 Gold 週次バックテスト自動実行ツール.

バックテスト専用のポータブル版 MT4 でストラテジーテスターを起動し、レポートを backtest/analyze_mt4.py で
分析して Discord に投稿する（Windows のタスクスケジューラから週1回実行する想定）。標準ライブラリのみ（Python 3.10+）。

使い方:
    python automation/run_backtests.py --config automation/config.json
    python automation/run_backtests.py --config automation/config.json --dry-run
    python automation/run_backtests.py --config automation/config.json --only 5y recent12m --skip-history
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import ntpath
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
USER_AGENT = "Mozilla/5.0 (compatible; mr2-weekly-backtest/1.0)"
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
WEBHOOK_RE = re.compile(r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+")
SECRET_KEYS = ("Login", "Password", "Server")
LEVELS = {  # 色, アイコン, 推奨アクション
    "green": (0x2ECC71, "🟢", "このまま稼働"),
    "yellow": (0xF1C40F, "🟡", "ロットを下げる"),
    "red": (0xE74C3C, "🔴", "稼働停止を検討"),
}
DEFAULT_RUNS = [
    {"name": "5y", "years": 5, "wfa": True},
    {"name": "recent12m", "months": 12},
    {"name": "since_v2", "from": "2026-04-06"},
    {"name": "5y_stress", "years": 5, "spread": "stress"},
]
DEFAULT_ALERTS = {
    "recent_run": "recent12m",   # 「直近成績」として判定に使うラン
    "red_pf_below": 1.1,         # 直近 PF がこれ未満 → 赤（稼働停止を検討）
    "red_dd_pct_above": 25,      # 直近 最大DD% がこれ超 → 赤
    "yellow_pf_below": 1.3,      # 直近 PF がこれ未満 → 黄（ロットを下げる）
    "yellow_dd_pct_above": 20,   # 直近 最大DD% がこれ超 → 黄
    "yellow_pf_drop": 0.2,       # 直近 PF が前週からこれ以上低下 → 黄
}
DEFAULTS = {
    "mt4_dir": r"C:\MT4_Backtest", "terminal_exe": "", "expert": "Mr2_gold_v2.0(HFMonly)", "symbol": "XAUUSD",
    "server_dir": "HFMarketsSV-Demo Server 2", "parameters_file": "", "spread": 34, "stress_spread": 60,
    "account_currency": "USD", "usdjpy": 158.4, "capital_jpy": 140000, "analysis_deposit": None,
    "current_lot": 0.01, "mc_runs": 10000, "runs": DEFAULT_RUNS, "history_years": 5, "timeout_minutes": 240,
    "reports_dir": "", "discord_webhook_url": "", "alerts": {}, "login": "", "password": "", "server": "",
}


class RunError(Exception):
    """利用者向けの日本語メッセージを持つ失敗."""


@dataclass
class RunPlan:
    name: str
    start: date
    end: date  # 最後の完了日（この日を含む）
    spread: int
    wfa: bool = False
    stress: bool = False
    is_months: int = 12
    oos_months: int = 3

    @property
    def test_to(self) -> date:
        """MT4 の TestToDate。終了日当日を確実に含めるため翌日を指定する."""
        return self.end + timedelta(days=1)

    @property
    def label(self) -> str:
        return f"{self.name}｜{self.start}〜{self.end}｜スプレッド{self.spread}"


@dataclass
class RunResult:
    plan: RunPlan
    summary: dict | None = None  # analyze_mt4.summarize() の結果
    entry: dict | None = None    # history.jsonl の1行
    prev: dict | None = None     # 同じランの前回の行
    md_path: str | None = None
    error: str | None = None


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- 日付・サーバー時間

def last_sunday(year: int, month: int) -> date:
    d = date(year, month, calendar.monthrange(year, month)[1])
    return d - timedelta(days=(d.weekday() + 1) % 7)


def is_eu_dst(utc: datetime) -> bool:
    """欧州夏時間: 3月最終日曜 01:00 UTC ～ 10月最終日曜 01:00 UTC."""
    s, e = last_sunday(utc.year, 3), last_sunday(utc.year, 10)
    return datetime(s.year, s.month, s.day, 1) <= utc < datetime(e.year, e.month, e.day, 1)


def server_now(utc: datetime | None = None) -> datetime:
    """HFM MT4 サーバー時間（GMT+2、欧州夏時間中は GMT+3）."""
    utc = utc or datetime.now(timezone.utc).replace(tzinfo=None)
    return utc + timedelta(hours=3 if is_eu_dst(utc) else 2)


def shift_months(d: date, n: int) -> date:
    k = d.year * 12 + d.month - 1 + n
    y, m = divmod(k, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def parse_date(s: str, what: str) -> date:
    try:
        return datetime.strptime(str(s).strip().replace("/", "-").replace(".", "-"), "%Y-%m-%d").date()
    except ValueError:
        raise RunError(f"{what} の日付「{s}」は YYYY-MM-DD 形式で書いてください") from None


def plan_runs(cfg: dict, today: date, only: list[str] | None = None) -> list[RunPlan]:
    end = today - timedelta(days=1)
    names = [r["name"] for r in cfg["runs"]]
    if only and (unknown := sorted(set(only) - set(names))):
        raise RunError(f"--only の {', '.join(unknown)} は設定の runs にありません（{', '.join(names)}）")
    plans = []
    for r in cfg["runs"]:
        if only and r["name"] not in only:
            continue
        if "from" in r:
            start = parse_date(r["from"], f"runs の {r['name']}")
        elif "years" in r:
            start = shift_months(end, -12 * int(r["years"]))
        else:
            start = shift_months(end, -int(r["months"]))
        if start > end:
            raise RunError(f"{r['name']}: 開始日 {start} が終了日 {end} より後です")
        stress = r.get("spread") == "stress"
        spread = int(cfg["stress_spread"] if stress else r.get("spread", cfg["spread"]))
        plans.append(RunPlan(r["name"], start, end, spread, bool(r.get("wfa")), stress,
                             int(r.get("is_months", 12)), int(r.get("oos_months", 3))))
    return plans


# ---------------------------------------------------------------- 設定

def strip_comments(obj):
    """「_」で始まるキー（説明用）を再帰的に取り除く."""
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [strip_comments(v) for v in obj]
    return obj


def read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8-sig") as f:
            raw = json.load(f)
    except FileNotFoundError:
        raise RunError(f"設定ファイル {path} がありません。automation\\config.example.json を config.json "
                       "という名前でコピーして編集してください") from None
    except json.JSONDecodeError as e:
        raise RunError(f"設定ファイル {path} の {e.lineno} 行目 {e.colno} 文字目が JSON として正しくありません"
                       "（パスの \\ は \\\\ と2つ重ねるか / を使う、行末のカンマ忘れ・付けすぎに注意）") from None
    if not isinstance(raw, dict):
        raise RunError(f"設定ファイル {path} の中身は {{ }} で囲んでください")
    return strip_comments(raw)


def normalize_config(raw: dict) -> dict:
    cfg = {**DEFAULTS, **raw}
    cfg["alerts"] = {**DEFAULT_ALERTS, **(raw.get("alerts") or {})}
    cfg["mt4_dir"] = str(cfg["mt4_dir"]).strip()
    if not cfg["mt4_dir"]:
        raise RunError("mt4_dir（バックテスト用 MT4 のフォルダ）を設定してください")
    cfg["terminal_exe"] = str(cfg["terminal_exe"] or "").strip() or os.path.join(cfg["mt4_dir"], "terminal.exe")
    rd = str(cfg["reports_dir"] or "").strip() or "reports"
    cfg["reports_dir"] = rd if os.path.isabs(rd) else os.path.join(REPO, rd)
    cfg["account_currency"] = str(cfg["account_currency"]).upper()
    if cfg["account_currency"] not in ("USD", "JPY"):
        raise RunError("account_currency は USD か JPY を指定してください")
    for key in ("usdjpy", "capital_jpy", "spread", "stress_spread", "history_years", "timeout_minutes", "mc_runs"):
        try:
            if float(cfg[key]) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise RunError(f"{key} には正の数値を指定してください") from None
    if not isinstance(cfg["runs"], list) or not cfg["runs"]:
        raise RunError("runs（実行するテストの一覧）が空です")
    seen = set()
    for r in cfg["runs"]:
        name = str(r.get("name", "")) if isinstance(r, dict) else ""
        if not NAME_RE.match(name) or name in seen:
            raise RunError(f"runs の name「{name}」は英数字・_・- のみで、重複しない名前にしてください")
        seen.add(name)
        if sum(k in r for k in ("years", "months", "from")) != 1:
            raise RunError(f"runs の {name} には years / months / from のどれか1つだけを指定してください")
    return cfg


def analysis_deposit(cfg: dict) -> float:
    if cfg["analysis_deposit"]:
        return float(cfg["analysis_deposit"])
    usd = cfg["account_currency"] == "USD"
    return float(cfg["capital_jpy"]) / float(cfg["usdjpy"]) if usd else float(cfg["capital_jpy"])


# ---------------------------------------------------------------- MT4

def ini_text(cfg: dict, plan: RunPlan) -> str:
    """MT4 の起動設定ファイル（[セクション] なしの key=value 形式）."""
    kv = [(k, str(cfg.get(k.lower()) or "").strip()) for k in SECRET_KEYS]
    kv = [(k, v) for k, v in kv if v]
    kv += [("ExpertsEnable", "true"), ("ExpertsDllImport", "true"), ("ExpertsExpImport", "true"),
           ("ExpertsTrades", "true"), ("TestExpert", cfg["expert"])]
    if cfg["parameters_file"]:
        kv.append(("TestExpertParameters", ntpath.basename(str(cfg["parameters_file"]))))
    kv += [("TestSymbol", cfg["symbol"]), ("TestPeriod", "M1"), ("TestModel", "0"), ("TestSpread", str(plan.spread)),
           ("TestOptimization", "false"), ("TestDateEnable", "true"),
           ("TestFromDate", f"{plan.start:%Y.%m.%d}"), ("TestToDate", f"{plan.test_to:%Y.%m.%d}"),
           ("TestReport", f"auto_reports\\mr2_{plan.name}"), ("TestReplaceReport", "true"),
           ("TestShutdownTerminal", "true"), ("TestVisualEnable", "false")]
    return "; Mr.2 Gold auto backtest - generated by run_backtests.py\n" + "".join(f"{k}={v}\n" for k, v in kv)


def mask_secrets(text: str) -> str:
    return re.sub(rf"^({'|'.join(SECRET_KEYS)})=.*$", r"\1=********", text, flags=re.M)


def write_ini(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="cp932", newline="\r\n") as f:
            f.write(text)
    except UnicodeEncodeError:
        raise RunError("expert / parameters_file などに Shift_JIS で書けない文字があります") from None


def report_candidates(cfg: dict, name: str) -> list[str]:
    base = os.path.join(cfg["mt4_dir"], "auto_reports", f"mr2_{name}")
    return [base + ".htm", base + ".html", base]


def find_report(cfg: dict, name: str, since: float | None = None) -> str | None:
    """既存のレポートを探す。since を渡すとそれ以降に更新されたものだけを返す."""
    for p in report_candidates(cfg, name):
        if os.path.isfile(p) and (since is None or os.path.getmtime(p) >= since - 2):
            return p
    return None


def setup_problems(cfg: dict) -> list[str]:
    mt4, out = cfg["mt4_dir"], []
    if not os.path.isdir(mt4):
        return [f"バックテスト用 MT4 のフォルダ {mt4} がありません"]
    if not os.path.isfile(cfg["terminal_exe"]):
        out.append(f"MT4 本体 {cfg['terminal_exe']} がありません")
    ex = os.path.join(mt4, "MQL4", "Experts", cfg["expert"])
    stems = [ex] if ex.lower().endswith((".ex4", ".mq4")) else [ex + ".ex4", ex + ".mq4"]
    if not any(os.path.isfile(p) for p in stems):
        out.append(f"EA {cfg['expert']}.ex4 が {os.path.join(mt4, 'MQL4', 'Experts')} にありません")
    if cfg["parameters_file"]:
        setf = os.path.join(mt4, "tester", ntpath.basename(str(cfg["parameters_file"])))
        if not os.path.isfile(setf):
            out.append(f"パラメーターファイル {setf} がありません（テスターの「エキスパート設定」→「保存」で tester フォルダに保存）")
    return out


def missing_report_message(cfg: dict, name: str, elapsed: float) -> str:
    mt4 = cfg["mt4_dir"]
    quick = (f"MT4 が {elapsed:.0f} 秒で終了しました。同じフォルダの MT4 がすでに起動していた可能性が高いです。"
             if elapsed < 30 else "")
    return (f"レポート {report_candidates(cfg, name)[0]} が作成されませんでした。{quick}"
            f"主な原因: (1) {mt4} の MT4 がすでに起動していた（起動中の画面が前に出るだけでテストは始まりません。閉じてから再実行）"
            f" (2) EA「{cfg['expert']}」が MQL4\\Experts にない (3) {cfg['symbol']} 1分足のヒストリーがない"
            f" (4) デモ口座にログインできない。{mt4}\\tester\\logs と {mt4}\\logs のログを確認してください")


def launch_mt4(cfg: dict, ini_path: str) -> float:
    """MT4 をポータブルモードで起動し、終了まで待つ。所要秒数を返す."""
    t0 = time.monotonic()
    try:
        subprocess.run([cfg["terminal_exe"], "/portable", ini_path], cwd=cfg["mt4_dir"],
                       timeout=float(cfg["timeout_minutes"]) * 60, check=False)
    except subprocess.TimeoutExpired:
        raise RunError(f"MT4 が {cfg['timeout_minutes']} 分以内に終了しなかったため強制終了しました"
                       "（timeout_minutes を増やすか、ヒストリー・EA の状態を確認）") from None
    except OSError as e:
        raise RunError(f"MT4（{cfg['terminal_exe']}）を起動できませんでした: {e}") from None
    return time.monotonic() - t0


def run_tester(cfg: dict, plan: RunPlan, dry_run: bool) -> str:
    """ini を書いて MT4 を起動し、今回作成されたレポートのパスを返す."""
    text = ini_text(cfg, plan)
    ini_path = os.path.join(cfg["mt4_dir"], "auto", f"{plan.name}.ini")
    log(f"[{plan.name}] {plan.start}〜{plan.end}（スプレッド {plan.spread}）")
    if dry_run:
        print(f"----- {ini_path} -----\n{mask_secrets(text)}", flush=True)
        if os.path.isdir(cfg["mt4_dir"]):
            write_ini(ini_path, text)
        if not (htm := find_report(cfg, plan.name)):
            raise RunError(f"既存のレポート {report_candidates(cfg, plan.name)[0]} がありません（ドライランのため MT4 は起動していません）")
        log(f"[{plan.name}] ドライラン: MT4 は起動せず既存のレポートを分析します")
        return htm
    write_ini(ini_path, text)
    os.makedirs(os.path.join(cfg["mt4_dir"], "auto_reports"), exist_ok=True)
    for p in report_candidates(cfg, plan.name) + [report_candidates(cfg, plan.name)[2] + ".gif"]:
        try:
            os.remove(p)
        except OSError:
            pass
    started = time.time()
    log(f"[{plan.name}] MT4 を起動してテストを実行中...")
    try:
        elapsed = launch_mt4(cfg, ini_path)
    finally:
        if cfg.get("password"):
            try:
                os.remove(ini_path)  # パスワード入りの ini を残さない
            except OSError:
                pass
    if not (htm := find_report(cfg, plan.name, since=started)):
        raise RunError(missing_report_message(cfg, plan.name, elapsed))
    log(f"[{plan.name}] テスト完了（{elapsed / 60:.1f} 分）")
    return htm


def fetch_history(cfg: dict, start: date, dry_run: bool) -> str | None:
    """fetch_history.py を別プロセスで実行する。問題があれば警告文を返す（処理は続行）."""
    script = os.path.join(HERE, "fetch_history.py")
    cmd = [sys.executable, script, "--mt4-dir", cfg["mt4_dir"], "--server", cfg["server_dir"],
           "--symbol", cfg["symbol"], "--from", start.isoformat()]
    if dry_run:
        log(f"ドライラン: ヒストリー取得は実行しません（{start} 以降を取得する予定）")
        return None
    if not os.path.isfile(script):
        return "fetch_history.py が見つからないため、ヒストリーの更新をスキップしました（既存のデータでテスト）"
    log(f"ヒストリーを更新中（{start} 以降）...")
    try:
        rc = subprocess.run(cmd, cwd=REPO, timeout=float(cfg["timeout_minutes"]) * 60, check=False).returncode
    except subprocess.TimeoutExpired:
        return "ヒストリーの更新が時間切れになりました（既存のデータでテスト）"
    except OSError as e:
        return f"ヒストリーの更新を実行できませんでした: {e}（既存のデータでテスト）"
    return None if rc == 0 else f"ヒストリーの更新に失敗しました（終了コード {rc}）。既存のデータでテストしました"


# ---------------------------------------------------------------- 分析・履歴

def load_analyzer():
    path = os.path.join(REPO, "backtest")
    if path not in sys.path:
        sys.path.insert(0, path)
    import analyze_mt4
    return analyze_mt4


def analyze_report(cfg: dict, plan: RunPlan, htm: str, day_dir: str) -> tuple[str, dict]:
    """レポートを日付フォルダにコピーして分析し、(Markdown のパス, 要約) を返す."""
    os.makedirs(day_dir, exist_ok=True)
    copy = os.path.join(day_dir, f"mr2_{plan.name}.htm")
    shutil.copy2(htm, copy)
    gif = os.path.splitext(htm)[0] + ".gif"
    if os.path.isfile(gif):
        shutil.copy2(gif, os.path.join(day_dir, f"mr2_{plan.name}.gif"))
    argv = [copy, "--capital", f"{float(cfg['capital_jpy']):g}", "--deposit", f"{analysis_deposit(cfg):.2f}",
            "--mc-runs", str(int(cfg["mc_runs"]))]
    if cfg["account_currency"] == "USD":
        argv += ["--usdjpy", f"{float(cfg['usdjpy']):g}"]
    argv += ["--is-months", str(plan.is_months), "--oos-months", str(plan.oos_months)] if plan.wfa else ["--no-wf"]
    log(f"[{plan.name}] 分析中（モンテカルロは少し時間がかかります）...")
    try:
        report, summary = load_analyzer().analyze(argv)
    except (OSError, ValueError, SystemExit) as e:
        raise RunError(f"レポートの分析に失敗しました: {e}") from None
    md = os.path.join(day_dir, f"mr2_{plan.name}.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write(f"> 自動バックテスト「{plan.name}」: {plan.start} 〜 {plan.end}（スプレッド {plan.spread}、"
                f"{datetime.now():%Y-%m-%d %H:%M} 実行）\n\n{report}")
    return md, summary


def finite(x, digits: int = 2):
    return round(x, digits) if isinstance(x, (int, float)) and math.isfinite(x) else None


def history_entry(today: date, plan: RunPlan, s: dict) -> dict:
    m = s["all"]
    return {"date": today.isoformat(), "run": plan.name, "from": plan.start.isoformat(), "to": plan.end.isoformat(),
            "spread": plan.spread, "trades": m["trades"], "net_jpy": finite(m["net"], 0), "pf": finite(m["pf"], 3),
            "max_dd_pct": finite(m["max_dd_pct"]), "eq_dd_pct": finite(s["eq_dd_pct"]), "sharpe": finite(m["sharpe"]),
            "wf_verdict": s["wf_verdict"] if plan.wfa else None, "dd99_001_jpy": finite(s["dd99_001"], 0),
            "lot": finite(s["lot"]), "quality": finite(s["quality"])}


def load_history(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict):
                out.append(d)
    return out


def previous_entry(history: list[dict], run: str, today: date) -> dict | None:
    prev = [h for h in history if h.get("run") == run and str(h.get("date", "")) < today.isoformat()]
    return sorted(prev, key=lambda h: str(h["date"]))[-1] if prev else None


DELTA_KEYS = ("pf", "net_jpy", "max_dd_pct", "eq_dd_pct", "sharpe", "lot")


def deltas(entry: dict, prev: dict | None) -> dict:
    if not prev:
        return {}
    num = (int, float)
    return {k: round(entry[k] - prev[k], 3) for k in DELTA_KEYS
            if isinstance(entry.get(k), num) and isinstance(prev.get(k), num)}


def append_history(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 判定

def evaluate(results: list[RunResult], cfg: dict) -> tuple[str, list[str]]:
    """(green / yellow / red, 理由のリスト)."""
    a, red, yellow = cfg["alerts"], [], []
    ok = [r for r in results if r.summary]
    if not ok:
        return "red", ["すべてのテストが失敗したため成績を確認できません"]
    if rec := next((r for r in ok if r.plan.name == a["recent_run"]), None):
        m, eq = rec.summary["all"], rec.summary["eq_dd_pct"]
        pf, dd = m["pf"], max(m["max_dd_pct"] or 0.0, eq or 0.0)
        tag = f"直近（{rec.plan.name}）"
        if pf is not None and pf < a["red_pf_below"]:
            red.append(f"{tag}の PF {pf:.2f} が {a['red_pf_below']} 未満")
        elif pf is not None and pf < a["yellow_pf_below"]:
            yellow.append(f"{tag}の PF {pf:.2f} が {a['yellow_pf_below']} 未満")
        if dd > a["red_dd_pct_above"]:
            red.append(f"{tag}の最大DD {dd:.1f}% が {a['red_dd_pct_above']}% 超")
        elif dd > a["yellow_dd_pct_above"]:
            yellow.append(f"{tag}の最大DD {dd:.1f}% が {a['yellow_dd_pct_above']}% 超")
        prev_pf = (rec.prev or {}).get("pf")
        if pf is not None and math.isfinite(pf) and isinstance(prev_pf, (int, float)) and prev_pf - pf >= a["yellow_pf_drop"]:
            yellow.append(f"{tag}の PF が前週 {prev_pf:.2f} → {pf:.2f} に低下")
    for r in ok:
        s, n = r.summary, r.plan.name
        if r.plan.wfa and s["wf_verdict"] and s["wf_verdict"] != "合格":
            yellow.append(f"{n} のウォークフォワード判定が「{s['wf_verdict']}」")
        if s["all"]["pf"] is not None and s["all"]["pf"] < 1.0:
            yellow.append(f"{n} の PF {s['all']['pf']:.2f} が 1.0 未満（負け）")
        lot = s["lot"]
        if not r.plan.stress and lot is not None and math.isfinite(lot) and lot < float(cfg["current_lot"]):
            yellow.append(f"{n} の推奨ロット {fmt_lot(lot)} が運用ロット {float(cfg['current_lot']):.2f} を下回る")
    return ("red" if red else "yellow" if yellow else "green"), red + yellow


# ---------------------------------------------------------------- Discord

def fmt_lot(lot: float | None) -> str:
    if lot is None:
        return "-"
    return "制限なし" if math.isinf(lot) else "資金不足" if lot < 0.01 else f"{lot:.2f}"


def fmt_num(x: float | None, d: int = 2) -> str:
    return "-" if x is None else "∞" if math.isinf(x) else f"{x:.{d}f}"


def fmt_money(x: float | None, cur: str) -> str:
    if x is None:
        return "-"
    return f"{x:+,.0f}円" if cur == "JPY" else f"{x:+,.2f} {cur}"


def delta_text(r: RunResult) -> str:
    if not r.prev:
        return "前週比: 記録なし（初回）"
    d = r.entry.get("delta", {}) if r.entry else {}
    parts = [f"PF {d['pf']:+.2f}" if "pf" in d else "",
             f"純損益 {fmt_money(d['net_jpy'], 'JPY')}" if "net_jpy" in d else "",
             f"DD {d['max_dd_pct']:+.1f}pt" if "max_dd_pct" in d else "",
             f"推奨ロット {d['lot']:+.2f}" if "lot" in d else ""]
    return f"前週比（{r.prev.get('date')}）: " + (" / ".join(p for p in parts if p) or "比較できる項目なし")


def run_value(r: RunResult) -> str:
    if r.error:
        return f"❌ 失敗: {r.error}"[:1024]
    s, m = r.summary, r.summary["all"]
    dd = f"DD {fmt_num(m['max_dd_pct'], 1)}%"
    if s["eq_dd_pct"] is not None:
        dd += f"（含み損込み {s['eq_dd_pct']:.1f}%）"
    parts = [f"PF {fmt_num(m['pf'])}", f"純損益 {fmt_money(m['net'], s['currency'])}", dd,
             f"シャープ {fmt_num(m['sharpe'])}"]
    if r.plan.wfa:
        parts.append(f"WF {s['wf_verdict'] or '期間不足'}")
    parts.append(f"推奨ロット {fmt_lot(s['lot'])}")
    return f"{' / '.join(parts)}\n取引 {m['trades']:,} 回　{delta_text(r)}"[:1024]


def build_payload(results: list[RunResult], level: str, reasons: list[str], notes: list[str],
                  cfg: dict, today: date) -> dict:
    color, icon, action = LEVELS[level]
    if any(r.error for r in results):
        notes = [*notes, "一部のテストが失敗しました（下の ❌ を確認）"]
    if notes and level == "green":
        color = LEVELS["yellow"][0]
    desc = [f"{icon} **判定: {action}**", *(f"・{x}" for x in reasons or ["直近成績・ウォークフォワード・推奨ロットに問題なし"])]
    desc += [f"⚠️ {n}" for n in notes]
    lots = [r.summary["lot"] for r in results if r.summary and not r.plan.stress and r.summary["lot"] is not None]
    if lots:
        desc.append(f"推奨ロット（ストレス以外で最も慎重な値）: **{fmt_lot(min(lots))}**"
                    f"（資金 {float(cfg['capital_jpy']):,.0f}円・運用ロット {float(cfg['current_lot']):.2f}）")
    q = next((r.summary["quality"] for r in results if r.summary and r.summary["quality"] is not None), None)
    foot = "MT4 テスター（M1・生成ティック）による参考値です。詳細は添付のレポートを確認してください。"
    if q is not None:
        foot = f"モデリング品質 {q:.0f}%。" + foot
    embed = {"title": f"Mr.2 Gold 週次バックテスト（{today}）", "description": "\n".join(desc)[:4000],
             "color": color, "fields": [{"name": r.plan.label[:256], "value": run_value(r), "inline": False}
                                        for r in results][:25],
             "footer": {"text": foot}, "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return {"username": "Mr.2 Gold バックテスト", "embeds": [embed], "allowed_mentions": {"parse": []}}


def failure_payload(message: str, today: date) -> dict:
    return {"username": "Mr.2 Gold バックテスト", "allowed_mentions": {"parse": []}, "embeds": [{
        "title": f"Mr.2 Gold 週次バックテスト失敗（{today}）", "color": LEVELS["red"][0],
        "description": f"🔴 自動バックテストが失敗しました。\n{message[:3500]}\n\n詳細は reports\\last_run.log を確認してください。"}]}


def payload_text(payload: dict) -> str:
    out = []
    for e in payload.get("embeds", []):
        out += [f"■ {e.get('title', '')}", e.get("description", "")]
        out += [f"\n[{f['name']}]\n{f['value']}" for f in e.get("fields", [])]
        if "footer" in e:
            out.append(f"\n{e['footer']['text']}")
    return "\n".join(out)


def multipart_body(payload: dict, files: list[tuple[str, bytes]], boundary: str | None = None) -> tuple[bytes, str]:
    """payload_json + files[n] の multipart/form-data を組み立てる."""
    boundary = boundary or f"mr2-{uuid.uuid4().hex}"
    payload = {**payload, "attachments": [{"id": i, "filename": n} for i, (n, _) in enumerate(files)]}
    body = bytearray()

    def part(disposition: str, ctype: str, data: bytes) -> None:
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; {disposition}\r\n"
                    f"Content-Type: {ctype}\r\n\r\n".encode("utf-8"))
        body.extend(data + b"\r\n")

    part('name="payload_json"', "application/json", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    for i, (name, data) in enumerate(files):
        part(f'name="files[{i}]"; filename="{name}"', "text/markdown; charset=utf-8", data)
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def post_discord(url: str, payload: dict, files: list[tuple[str, bytes]] | None = None, retries: int = 4,
                 opener=urllib.request.urlopen, sleep=time.sleep) -> None:
    """Webhook に送信する（429 は retry_after だけ待って再送）。エラー文に URL は含めない."""
    if not WEBHOOK_RE.match(url):
        raise RunError("Discord の Webhook URL の形式が正しくありません（https://discord.com/api/webhooks/... ）")
    if files:
        data, ctype = multipart_body(payload, files[:10])
    else:
        data, ctype = json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json"
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": ctype, "User-Agent": USER_AGENT})
        try:
            with opener(req, timeout=60):
                return
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = float(json.loads(e.read()).get("retry_after", 2))
                except Exception:
                    wait = 2.0
                sleep(min(max(wait, 0.5), 60))
                continue
            if e.code >= 500:
                sleep(2 * (attempt + 1))
                continue
            detail = e.read()[:200].decode("utf-8", "replace")
            raise RunError(f"Discord への送信に失敗しました（HTTP {e.code}）: {detail}") from None
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            log(f"Discord への接続に失敗（{type(reason).__name__}）。再試行します")
            sleep(2 * (attempt + 1))
    raise RunError("Discord への送信に失敗しました（再試行の上限）")


def notify_failure(webhook: str, message: str, today: date) -> None:
    if not webhook:
        return
    try:
        post_discord(webhook, failure_payload(message, today))
        log("Discord に失敗通知を送信しました")
    except RunError as e:
        log(f"Discord への失敗通知も送れませんでした: {e}")


# ---------------------------------------------------------------- メイン

def run_all(cfg: dict, args: argparse.Namespace, today: date, webhook: str) -> int:
    plans = plan_runs(cfg, today, args.only)
    day_dir = os.path.join(cfg["reports_dir"], today.isoformat())
    hist_path = os.path.join(cfg["reports_dir"], "history.jsonl")
    notes: list[str] = []
    if not args.skip_history:
        hist_from = min([shift_months(today - timedelta(days=1), -12 * int(cfg["history_years"]))]
                        + [p.start for p in plans])
        if warn := fetch_history(cfg, hist_from, args.dry_run):
            log(f"警告: {warn}")
            notes.append(warn)
    if problems := setup_problems(cfg):
        if not args.dry_run:
            raise RunError("準備ができていません: " + " / ".join(problems))
        for p in problems:
            log(f"警告（ドライランのため続行）: {p}")

    history = load_history(hist_path)
    results = []
    for plan in plans:
        res = RunResult(plan)
        try:
            htm = run_tester(cfg, plan, args.dry_run)
            res.md_path, res.summary = analyze_report(cfg, plan, htm, day_dir)
            res.entry = history_entry(today, plan, res.summary)
            res.prev = previous_entry(history, plan.name, today)
            res.entry["delta"] = deltas(res.entry, res.prev)
            log(f"[{plan.name}] 完了: PF {fmt_num(res.summary['all']['pf'])} / 推奨ロット {fmt_lot(res.summary['lot'])}")
        except RunError as e:
            res.error = str(e)
            log(f"[{plan.name}] 失敗: {e}")
        results.append(res)

    entries = [r.entry for r in results if r.entry]
    if args.dry_run:
        log(f"ドライラン: {hist_path} には追記しません")
    elif entries:
        append_history(hist_path, entries)
    level, reasons = evaluate(results, cfg)
    payload = build_payload(results, level, reasons, notes, cfg, today)
    files = []
    for r in results:
        if r.md_path:
            with open(r.md_path, "rb") as f:
                files.append((f"mr2_{r.plan.name}_{today}.md", f.read()))
    if args.dry_run:
        print("----- Discord に送る内容（ドライラン） -----", flush=True)
        print(payload_text(payload))
        print("添付: " + (", ".join(f"{n}（{len(b) // 1024 + 1} KB）" for n, b in files) or "なし"), flush=True)
    elif webhook:
        post_discord(webhook, payload, files)
        log("Discord に送信しました")
    else:
        log("Discord の Webhook URL が未設定のため送信しませんでした")
    log(f"判定: {LEVELS[level][2]}（レポート: {day_dir}）")
    return 1 if notes or any(r.error for r in results) else 0


class JaHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, prefix or "使い方: ")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="run_backtests.py", description=__doc__, add_help=False,
                                 formatter_class=JaHelpFormatter)
    ap._optionals.title = "オプション"
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"),
                    help="設定ファイル（既定: automation/config.json）")
    ap.add_argument("--skip-history", action="store_true", help="ヒストリーの更新（fetch_history.py）をしない")
    ap.add_argument("--only", nargs="+", metavar="NAME", help="指定した名前のテストだけ実行（例: --only 5y recent12m）")
    ap.add_argument("--dry-run", action="store_true",
                    help="MT4 を起動せず Discord にも送らない。ini と送信内容を表示し、既存のレポートがあれば分析する")
    ap.add_argument("--today", help="今日の日付を上書き（YYYY-MM-DD。既定は HFM サーバー時間の今日）")
    ap.add_argument("-h", "--help", action="help", help="このヘルプを表示して終了")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    try:
        today = parse_date(args.today, "--today") if args.today else server_now().date()
    except RunError as e:
        log(f"エラー: {e}")
        return 2
    try:
        raw = read_json(args.config)
        webhook = webhook or str(raw.get("discord_webhook_url") or "").strip()
        cfg = normalize_config(raw)
        return run_all(cfg, args, today, webhook)
    except Exception as e:  # 想定外の例外も含め、失敗は必ず通知する
        if isinstance(e, RunError):
            msg = str(e)
            log(f"エラー: {msg}")
        else:
            traceback.print_exc()
            msg = f"想定外のエラー: {type(e).__name__}: {e}"
        if not args.dry_run:
            notify_failure(webhook, msg, today)
        return 1


if __name__ == "__main__":
    sys.exit(main())
