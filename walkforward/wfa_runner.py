#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MT4 ウォークフォワードテスト自動化ランナー

wfa_config.json の設定に従い、期間をローリングしながら
  IS(学習期間)で最適化 → 最良パラメータを選抜 → OOS(検証期間)でテスト
を全ウィンドウぶん自動実行し、wfa_summary.csv に集計する。

実行環境: Windows (MT4がインストールされたPC)。Python標準ライブラリのみ使用。

使い方:
    python wfa_runner.py --config wfa_config.json --dry-run   # 設定確認のみ
    python wfa_runner.py --config wfa_config.json             # 本実行

事前準備:
  - EA(DaypitaAlphaScalper)とデイピタアルファをコンパイル済みにしておく
  - MT4のヒストリーセンター(F2)で対象通貨ペアの過去データを取得しておく
  - 実行中は同じMT4を手動で開かない(テスターを占有するため)
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
GENERATED = HERE / "generated"   # .ini / .set の生成先
REPORTS = HERE / "reports"       # テスターレポートの出力先


# ----------------------------------------------------------------------
# 期間ウィンドウの生成
# ----------------------------------------------------------------------
def add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1) if d.day == 1 else date(y, m, min(d.day, 28))


def build_windows(cfg: dict) -> list:
    w = cfg["windows"]
    start = date.fromisoformat(w["start"])
    windows = []
    for i in range(w["count"]):
        is_from = add_months(start, i * w["oos_months"])
        is_to = add_months(is_from, w["is_months"])
        oos_from = is_to
        oos_to = add_months(oos_from, w["oos_months"])
        windows.append({
            "index": i + 1,
            "is_from": is_from, "is_to": is_to,
            "oos_from": oos_from, "oos_to": oos_to,
        })
    return windows


# ----------------------------------------------------------------------
# MT4 用の .set / .ini 生成
# ----------------------------------------------------------------------
def fmt_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def set_file_text(fixed: dict, optimized: dict, optimize: bool,
                  selected: dict = None) -> str:
    """MT4 テスター用 .set ファイルを生成する。
    optimize=True のとき optimized_params に最適化フラグ(,F=1)と範囲を付ける。
    selected を渡すと、そのパラメータ値で固定する(OOSテスト用)。
    """
    lines = []
    for k, v in fixed.items():
        lines.append(f"{k}={fmt_value(v)}")
    for k, rng in optimized.items():
        start, step, stop = rng
        value = selected[k] if (selected and k in selected) else start
        lines.append(f"{k}={value}")
        lines.append(f"{k},F={'1' if optimize else '0'}")
        lines.append(f"{k},1={start}")
        lines.append(f"{k},2={step}")
        lines.append(f"{k},3={stop}")
    return "\n".join(lines) + "\n"


def ini_text(cfg: dict, set_name: str, d_from: date, d_to: date,
             report_path: Path, optimize: bool) -> str:
    return "\n".join([
        f"TestExpert={cfg['expert']}",
        f"TestExpertParameters={set_name}",
        f"TestSymbol={cfg['symbol']}",
        f"TestPeriod={cfg['period']}",
        f"TestModel={cfg.get('model', 0)}",
        f"TestSpread={cfg.get('spread', 0)}",
        f"TestOptimization={'true' if optimize else 'false'}",
        "TestDateEnable=true",
        f"TestFromDate={d_from.strftime('%Y.%m.%d')}",
        f"TestToDate={d_to.strftime('%Y.%m.%d')}",
        f"TestReport={report_path}",
        "TestReplaceReport=true",
        "TestShutdownTerminal=true",
        "TestVisualEnable=false",
    ]) + "\n"


def run_terminal(cfg: dict, ini_path: Path):
    cmd = [cfg["terminal_path"], str(ini_path)]
    print(f"    起動: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, timeout=cfg.get("timeout_sec", 7200))
    except subprocess.TimeoutExpired:
        print("    !! タイムアウト。timeout_sec を増やすか期間/範囲を狭めてください")


# ----------------------------------------------------------------------
# レポート解析
# ----------------------------------------------------------------------
def read_report(path: Path) -> str:
    for enc in ("utf-16", "utf-8", "cp932", "cp1252"):
        try:
            text = path.read_text(encoding=enc)
            if "<" in text:
                return text
        except (UnicodeError, UnicodeDecodeError):
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def to_float(s: str) -> float:
    s = re.sub(r"[^\d.\-]", "", s.replace("&nbsp;", "").strip())
    try:
        return float(s) if s not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def parse_optimization_report(path: Path) -> list:
    """最適化レポートの各パス(行)を辞書のリストにして返す。
    行の title 属性にパラメータ一覧が入っている。
    列: Pass, Profit, Total trades, Profit factor, Expected payoff, DD$, DD%
    """
    html = read_report(path)
    rows = []
    for m in re.finditer(r'<tr[^>]*title="([^"]+)"[^>]*>(.*?)</tr>',
                         html, re.S | re.I):
        params_str, body = m.group(1), m.group(2)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", body, re.S | re.I)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if len(cells) < 7:
            continue
        params = {}
        for kv in params_str.split(";"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k.strip()] = v.strip()
        rows.append({
            "pass": cells[0],
            "profit": to_float(cells[1]),
            "trades": int(to_float(cells[2])),
            "profit_factor": to_float(cells[3]),
            "expected_payoff": to_float(cells[4]),
            "dd_money": to_float(cells[5]),
            "dd_pct": to_float(cells[6]),
            "params": params,
        })
    return rows


def select_best(rows: list, sel: dict):
    """利益プラスかつ最低取引数を満たす中から、指定基準で最良パスを選ぶ"""
    crit = sel.get("criterion", "profit_factor")
    min_trades = sel.get("min_trades", 30)
    cands = [r for r in rows if r["trades"] >= min_trades and r["profit"] > 0]
    if not cands:
        return None
    cands.sort(key=lambda r: (r.get(crit, 0.0), -r["dd_pct"]), reverse=True)
    return cands[0]


def parse_single_report(path: Path) -> dict:
    """単発バックテストレポートのサマリー値を抜き出す"""
    html = read_report(path)

    def grab(label):
        m = re.search(label + r"\s*</td>\s*<td[^>]*>([^<]*)", html, re.I)
        return to_float(m.group(1)) if m else 0.0

    return {
        "profit": grab("Total net profit"),
        "profit_factor": grab("Profit factor"),
        "expected_payoff": grab("Expected payoff"),
        "trades": int(grab("Total trades")),
        "dd_pct": grab(r"Maximal drawdown"),  # "1234.56 (2.34%)" → 先頭の金額を取得
    }


# ----------------------------------------------------------------------
# メイン処理
# ----------------------------------------------------------------------
def run_window(cfg: dict, win: dict, dry_run: bool):
    idx = win["index"]
    tester_dir = Path(cfg["data_path"]) / "tester"
    tag = f"wfa_w{idx:02d}"
    print(f"\n=== ウィンドウ {idx}: IS {win['is_from']}~{win['is_to']} / "
          f"OOS {win['oos_from']}~{win['oos_to']} ===")

    # --- 1) IS 最適化 ---
    # MT4はTestReport名に自動で .htm を付けるため、iniには拡張子なしで渡す
    is_set = f"{tag}_is.set"
    is_report_base = REPORTS / f"{tag}_is"
    is_report = is_report_base.with_suffix(".htm")
    is_ini = GENERATED / f"{tag}_is.ini"
    (GENERATED / is_set).write_text(
        set_file_text(cfg["fixed_params"], cfg["optimized_params"], True),
        encoding="ascii")
    is_ini.write_text(
        ini_text(cfg, is_set, win["is_from"], win["is_to"], is_report_base,
                 True),
        encoding="ascii")

    if dry_run:
        print(f"    [dry-run] 生成: {is_ini.name}, {is_set}")
    else:
        copy_set_to_tester(GENERATED / is_set, tester_dir)
        run_terminal(cfg, is_ini)
        if not is_report.exists():
            print(f"    !! ISレポートが見つかりません: {is_report}")
            print("       (レポートがMT4インストールフォルダ側に出ていないか確認)")
            return None

    best = None
    if not dry_run:
        rows = parse_optimization_report(is_report)
        print(f"    IS最適化パス数: {len(rows)}")
        best = select_best(rows, cfg["selection"])
        if best is None:
            print("    !! 選抜基準(利益>0かつ最低取引数)を満たすパスなし → このウィンドウは不合格")
            return {"window": win, "is": None, "oos": None, "params": None}
        print(f"    選抜: PF={best['profit_factor']:.2f} "
              f"利益={best['profit']:.0f} 取引数={best['trades']} "
              f"params={best['params']}")

    # --- 2) OOS テスト ---
    oos_set = f"{tag}_oos.set"
    oos_report_base = REPORTS / f"{tag}_oos"
    oos_report = oos_report_base.with_suffix(".htm")
    oos_ini = GENERATED / f"{tag}_oos.ini"
    selected = best["params"] if best else None
    (GENERATED / oos_set).write_text(
        set_file_text(cfg["fixed_params"], cfg["optimized_params"], False,
                      selected),
        encoding="ascii")
    oos_ini.write_text(
        ini_text(cfg, oos_set, win["oos_from"], win["oos_to"],
                 oos_report_base, False),
        encoding="ascii")

    if dry_run:
        print(f"    [dry-run] 生成: {oos_ini.name}, {oos_set}")
        return None

    copy_set_to_tester(GENERATED / oos_set, tester_dir)
    run_terminal(cfg, oos_ini)
    if not oos_report.exists():
        print(f"    !! OOSレポートが見つかりません: {oos_report}")
        return None

    oos = parse_single_report(oos_report)
    print(f"    OOS結果: 利益={oos['profit']:.0f} PF={oos['profit_factor']:.2f} "
          f"取引数={oos['trades']}")
    return {"window": win, "is": best, "oos": oos, "params": selected}


def copy_set_to_tester(src: Path, tester_dir: Path):
    tester_dir.mkdir(parents=True, exist_ok=True)
    (tester_dir / src.name).write_bytes(src.read_bytes())


def write_summary(cfg: dict, results: list):
    out = HERE / "wfa_summary.csv"
    is_months = cfg["windows"]["is_months"]
    oos_months = cfg["windows"]["oos_months"]
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["window", "is_from", "is_to", "oos_from", "oos_to",
                    "selected_params", "is_profit", "is_pf", "is_trades",
                    "oos_profit", "oos_pf", "oos_trades", "wfe"])
        for r in results:
            if r is None:
                continue
            win = r["window"]
            if r["is"] is None or r["oos"] is None:
                w.writerow([win["index"], win["is_from"], win["is_to"],
                            win["oos_from"], win["oos_to"],
                            "NO_QUALIFYING_PASS", "", "", "", "", "", "", ""])
                continue
            # WFE = OOSの月次利益 / ISの月次利益 (1.0でIS並みの成績を維持)
            wfe = ""
            if r["is"]["profit"] > 0:
                wfe = round((r["oos"]["profit"] / oos_months) /
                            (r["is"]["profit"] / is_months), 3)
            w.writerow([win["index"], win["is_from"], win["is_to"],
                        win["oos_from"], win["oos_to"],
                        json.dumps(r["params"], ensure_ascii=False),
                        r["is"]["profit"], r["is"]["profit_factor"],
                        r["is"]["trades"],
                        r["oos"]["profit"], r["oos"]["profit_factor"],
                        r["oos"]["trades"], wfe])
    print(f"\n集計を書き出しました: {out}")

    done = [r for r in results if r and r["oos"]]
    if done:
        wins = sum(1 for r in done if r["oos"]["profit"] > 0)
        total = sum(r["oos"]["profit"] for r in done)
        print(f"OOS勝ちウィンドウ: {wins}/{len(done)} "
              f"({100 * wins / len(done):.0f}%) / OOS合計損益: {total:.0f}")
        print("合格の目安: 勝ちウィンドウ60%以上・OOS合計がプラス・平均WFE 0.5以上")
        print("→ wfa_summary.csv を prompts/フォワードテスト運用プロンプト.md の"
              "テンプレでClaudeに貼って分析してください")


def main():
    ap = argparse.ArgumentParser(description="MT4ウォークフォワードテスト自動化")
    ap.add_argument("--config", default=str(HERE / "wfa_config.json"))
    ap.add_argument("--dry-run", action="store_true",
                    help="MT4を起動せず、生成される設定と期間だけ確認する")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    GENERATED.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)

    if not args.dry_run:
        term = Path(cfg["terminal_path"])
        data = Path(cfg["data_path"])
        if not term.exists():
            sys.exit(f"terminal_path が見つかりません: {term}")
        if not data.exists():
            sys.exit(f"data_path が見つかりません: {data}")

    windows = build_windows(cfg)
    print(f"ウィンドウ数: {len(windows)} "
          f"(IS {cfg['windows']['is_months']}ヶ月 / OOS {cfg['windows']['oos_months']}ヶ月)")

    results = [run_window(cfg, w, args.dry_run) for w in windows]

    if not args.dry_run:
        write_summary(cfg, results)
    else:
        print("\n[dry-run] 完了。generated/ 内のファイルを確認し、"
              "問題なければ --dry-run を外して実行してください")


if __name__ == "__main__":
    main()
