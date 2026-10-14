"""run_backtests.py のユニットテスト（ネットワーク・MT4 なしで動く）.

実行: python3 -I -m unittest discover -s automation/tests -v
"""
from __future__ import annotations

import contextlib
import email.parser
import email.policy
import http.client
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from datetime import date, datetime
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backtest"))

import make_sample as ms  # noqa: E402
import run_backtests as rb  # noqa: E402

WEBHOOK = "https://discord.com/api/webhooks/123456/abc-DEF_ghi"


def make_cfg(**over) -> dict:
    return rb.normalize_config({"mt4_dir": r"C:\MT4 Backtest", **over})


class DateTests(unittest.TestCase):
    def test_last_sunday_and_dst(self):
        self.assertEqual(rb.last_sunday(2026, 3), date(2026, 3, 29))
        self.assertEqual(rb.last_sunday(2026, 10), date(2026, 10, 25))
        self.assertEqual(rb.last_sunday(2025, 3), date(2025, 3, 30))
        sn = rb.server_now
        self.assertEqual(sn(datetime(2026, 3, 29, 0, 59)), datetime(2026, 3, 29, 2, 59))  # GMT+2
        self.assertEqual(sn(datetime(2026, 3, 29, 1, 0)), datetime(2026, 3, 29, 4, 0))    # GMT+3
        self.assertEqual(sn(datetime(2026, 10, 25, 0, 59)), datetime(2026, 10, 25, 3, 59))
        self.assertEqual(sn(datetime(2026, 10, 25, 1, 0)), datetime(2026, 10, 25, 3, 0))
        # 土曜 09:07 JST = 00:07 UTC → サーバーは土曜（前日の金曜までが完了日）
        self.assertEqual(sn(datetime(2026, 10, 17, 0, 7)).date(), date(2026, 10, 17))

    def test_shift_months_clamps_day(self):
        self.assertEqual(rb.shift_months(date(2024, 2, 29), -12), date(2023, 2, 28))
        self.assertEqual(rb.shift_months(date(2026, 3, 31), -1), date(2026, 2, 28))
        self.assertEqual(rb.shift_months(date(2026, 1, 15), -60), date(2021, 1, 15))

    def test_default_runs(self):
        plans = {p.name: p for p in rb.plan_runs(make_cfg(), date(2026, 10, 17))}
        self.assertEqual(list(plans), ["5y", "recent12m", "since_v2", "5y_stress"])
        p = plans["5y"]
        self.assertEqual((p.start, p.end, p.test_to, p.spread, p.wfa), (date(2021, 10, 16), date(2026, 10, 16),
                                                                        date(2026, 10, 17), 34, True))
        self.assertEqual(plans["recent12m"].start, date(2025, 10, 16))
        self.assertFalse(plans["recent12m"].wfa)
        self.assertEqual(plans["since_v2"].start, date(2026, 4, 6))
        self.assertEqual((plans["5y_stress"].spread, plans["5y_stress"].stress), (60, True))

    def test_only_and_errors(self):
        cfg = make_cfg()
        self.assertEqual([p.name for p in rb.plan_runs(cfg, date(2026, 10, 17), ["recent12m"])], ["recent12m"])
        with self.assertRaises(rb.RunError):
            rb.plan_runs(cfg, date(2026, 10, 17), ["nope"])
        with self.assertRaises(rb.RunError):  # v2 リリース前の日付では開始日 > 終了日
            rb.plan_runs(cfg, date(2026, 4, 1), ["since_v2"])
        with self.assertRaises(rb.RunError):
            make_cfg(runs=[{"name": "bad name", "years": 1}])
        with self.assertRaises(rb.RunError):
            make_cfg(runs=[{"name": "x", "years": 1, "months": 3}])

    def test_config_comments_and_defaults(self):
        with open(os.path.join(HERE, "config.example.json"), encoding="utf-8") as f:
            raw = rb.strip_comments(json.load(f))
        self.assertFalse([k for k in raw if k.startswith("_")])
        cfg = rb.normalize_config(raw)
        self.assertEqual(cfg["terminal_exe"], os.path.join(r"C:\MT4_Backtest", "terminal.exe"))
        self.assertEqual(cfg["reports_dir"], os.path.join(os.path.dirname(HERE), "reports"))
        self.assertAlmostEqual(rb.analysis_deposit(cfg), 140000 / 158.4)
        self.assertEqual([r["name"] for r in cfg["runs"]], [r["name"] for r in rb.DEFAULT_RUNS])
        self.assertEqual(rb.analysis_deposit(make_cfg(account_currency="JPY")), 140000)


class IniTests(unittest.TestCase):
    def setUp(self):
        self.plan = rb.RunPlan("5y", date(2021, 10, 16), date(2026, 10, 16), 34, True)

    def ini(self, **over) -> dict[str, str]:
        text = rb.ini_text(make_cfg(**over), self.plan)
        self.assertFalse([ln for ln in text.splitlines() if ln.startswith("[")])  # セクションなし
        return dict(ln.split("=", 1) for ln in text.splitlines() if ln and not ln.startswith(";"))

    def test_keys(self):
        kv = self.ini()
        self.assertEqual(kv["TestExpert"], "Mr2_gold_v2.0(HFMonly)")
        self.assertEqual(kv["TestSymbol"], "XAUUSD")
        self.assertEqual((kv["TestPeriod"], kv["TestModel"], kv["TestSpread"]), ("M1", "0", "34"))
        self.assertEqual((kv["TestFromDate"], kv["TestToDate"]), ("2021.10.16", "2026.10.17"))
        self.assertEqual(kv["TestReport"], "auto_reports\\mr2_5y")
        for k in ("ExpertsEnable", "ExpertsDllImport", "ExpertsExpImport", "ExpertsTrades", "TestDateEnable",
                  "TestReplaceReport", "TestShutdownTerminal"):
            self.assertEqual(kv[k], "true", k)
        for k in ("TestOptimization", "TestVisualEnable"):
            self.assertEqual(kv[k], "false", k)
        self.assertNotIn("TestExpertParameters", kv)
        self.assertNotIn("Login", kv)

    def test_parameters_and_secrets(self):
        kv = self.ini(parameters_file=r"C:\MT4 Backtest\tester\mr2.set", login=12345, password="s3cret!",
                      server="HFMarketsSV-Demo Server 2")
        self.assertEqual(kv["TestExpertParameters"], "mr2.set")
        self.assertEqual((kv["Login"], kv["Password"], kv["Server"]), ("12345", "s3cret!", "HFMarketsSV-Demo Server 2"))
        masked = rb.mask_secrets(rb.ini_text(make_cfg(login=12345, password="s3cret!"), self.plan))
        self.assertNotIn("s3cret", masked)
        self.assertNotIn("12345", masked)
        self.assertIn("Password=********", masked)

    def test_written_file_crlf_no_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "auto dir", "5y.ini")
            rb.write_ini(path, rb.ini_text(make_cfg(), self.plan))
            with open(path, "rb") as f:
                raw = f.read()
        self.assertTrue(raw.startswith(b"; Mr.2"))
        self.assertIn(b"TestSymbol=XAUUSD\r\n", raw)
        self.assertNotIn(b"\r\r", raw)


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mt4 = os.path.join(self.tmp.name, "MT4 Backtest (HFM)")
        os.makedirs(self.mt4)
        self.cfg = rb.normalize_config({"mt4_dir": self.mt4, "timeout_minutes": 1})
        self.plan = rb.RunPlan("5y", date(2021, 10, 16), date(2026, 10, 16), 34, True)
        self.report = os.path.join(self.mt4, "auto_reports", "mr2_5y.htm")
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake_run(self, write: bool):
        def run(cmd, **kw):
            self.calls.append((cmd, kw))
            with open(cmd[2], encoding="cp932") as f:
                self.ini = f.read()
            if write:
                with open(self.report, "w") as f:
                    f.write("<html></html>")
            return subprocess.CompletedProcess(cmd, 0)
        return run

    def test_report_created(self):
        with mock.patch.object(rb.subprocess, "run", side_effect=self.fake_run(True)), \
                contextlib.redirect_stdout(io.StringIO()):
            path = rb.run_tester(self.cfg, self.plan, dry_run=False)
        self.assertEqual(path, self.report)
        cmd, kw = self.calls[0]
        ini_path = os.path.join(self.mt4, "auto", "5y.ini")
        self.assertEqual(cmd, [os.path.join(self.mt4, "terminal.exe"), "/portable", ini_path])  # スペース込みで1要素
        self.assertEqual(kw["cwd"], self.mt4)
        self.assertEqual(kw["timeout"], 60)
        self.assertIn("TestReport=auto_reports\\mr2_5y", self.ini)
        self.assertTrue(os.path.isfile(ini_path))  # パスワードなしなら ini を残す

    def test_stale_report_is_rejected(self):
        os.makedirs(os.path.dirname(self.report))
        with open(self.report, "w") as f:
            f.write("old")
        old = time.time() - 3600
        os.utime(self.report, (old, old))
        self.assertIsNone(rb.find_report(self.cfg, "5y", since=time.time()))
        self.assertEqual(rb.find_report(self.cfg, "5y"), self.report)
        with mock.patch.object(rb.subprocess, "run", side_effect=self.fake_run(False)), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(rb.RunError) as cm:
                rb.run_tester(self.cfg, self.plan, dry_run=False)
        self.assertIn("すでに起動", str(cm.exception))
        self.assertFalse(os.path.exists(self.report))  # 古いレポートは起動前に削除

    def test_old_mtime_after_launch_is_rejected(self):
        def run(cmd, **kw):  # MT4 が古い日時のファイルを残した（今回の実行で更新されていない）
            os.makedirs(os.path.dirname(self.report), exist_ok=True)
            with open(self.report, "w") as f:
                f.write("x")
            os.utime(self.report, (time.time() - 600, time.time() - 600))
            return subprocess.CompletedProcess(cmd, 0)
        with mock.patch.object(rb.subprocess, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(rb.RunError):
                rb.run_tester(self.cfg, self.plan, dry_run=False)

    def test_timeout_and_password_ini_removed(self):
        cfg = {**self.cfg, "password": "pw"}
        with mock.patch.object(rb.subprocess, "run", side_effect=subprocess.TimeoutExpired("terminal", 60)), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(rb.RunError) as cm:
                rb.run_tester(cfg, self.plan, dry_run=False)
        self.assertIn("強制終了", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.mt4, "auto", "5y.ini")))

    def test_dry_run_ini_has_no_password(self):
        os.makedirs(os.path.dirname(self.report))
        open(self.report, "w").close()
        cfg = {**self.cfg, "login": "12345", "password": "S3cret!"}
        with mock.patch.object(rb.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(rb.run_tester(cfg, self.plan, dry_run=True), self.report)
        run.assert_not_called()
        with open(os.path.join(self.mt4, "auto", "5y.ini"), encoding="cp932") as f:
            ini = f.read()
        self.assertIn("Password=********", ini)
        self.assertNotIn("S3cret", ini + out.getvalue())

    def test_setup_problems(self):
        probs = rb.setup_problems({**self.cfg, "parameters_file": "mr2.set"})
        self.assertEqual(len(probs), 3)  # terminal.exe / EA / .set
        for rel in ("terminal.exe", os.path.join("MQL4", "Experts", "Mr2_gold_v2.0(HFMonly).ex4"),
                    os.path.join("tester", "mr2.set")):
            os.makedirs(os.path.dirname(os.path.join(self.mt4, rel)), exist_ok=True)
            open(os.path.join(self.mt4, rel), "w").close()
        self.assertEqual(rb.setup_problems({**self.cfg, "parameters_file": "mr2.set"}), [])


def result(name: str, pf: float | None = 1.6, dd: float = 10.0, eq: float | None = None, lot: float | None = 0.02,
           wfa: bool = False, verdict: str | None = None, stress: bool = False, prev: dict | None = None) -> rb.RunResult:
    plan = rb.RunPlan(name, date(2025, 10, 16), date(2026, 10, 16), 60 if stress else 34, wfa, stress)
    summary = {"currency": "JPY", "all": {"trades": 500, "net": 50000.0, "pf": pf, "max_dd_pct": dd, "sharpe": 1.5},
               "eq_dd_pct": eq, "wf_verdict": verdict, "lot": lot, "dd99_001": 20000.0, "quality": 25.0}
    r = rb.RunResult(plan, summary, prev=prev)
    r.entry = rb.history_entry(date(2026, 10, 17), plan, summary)
    r.entry["delta"] = rb.deltas(r.entry, prev)
    return r


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()

    def level(self, *results) -> str:
        return rb.evaluate(list(results), self.cfg)[0]

    def test_levels(self):
        self.assertEqual(self.level(result("5y", wfa=True, verdict="合格"), result("recent12m")), "green")
        self.assertEqual(self.level(result("recent12m", pf=1.2)), "yellow")
        self.assertEqual(self.level(result("recent12m", dd=22)), "yellow")
        self.assertEqual(self.level(result("recent12m", pf=1.05)), "red")
        self.assertEqual(self.level(result("recent12m", dd=26)), "red")
        self.assertEqual(self.level(result("recent12m", dd=10, eq=30)), "red")  # 含み損込みDDも見る
        self.assertEqual(self.level(result("5y", wfa=True, verdict="要注意"), result("recent12m")), "yellow")
        self.assertEqual(self.level(result("recent12m", lot=0.0)), "yellow")  # 資金不足
        self.assertEqual(self.level(result("recent12m"), result("5y_stress", lot=0.0, stress=True)), "green")
        self.assertEqual(self.level(result("recent12m"), result("5y_stress", pf=0.9, stress=True)), "yellow")
        self.assertEqual(self.level(result("recent12m", prev={"date": "2026-10-10", "pf": 1.9})), "yellow")

    def test_failures_are_gray_not_red(self):
        failed = rb.RunResult(result("recent12m").plan, error="MT4 already running")
        level, reasons = rb.evaluate([failed, rb.RunResult(result("5y").plan, error="x")], self.cfg)
        self.assertEqual(level, "gray")  # ツールの失敗で「稼働停止を検討」にしない
        self.assertIn("EA の成績が悪いという意味ではありません", reasons[0])
        # 判定基準の直近ランだけ失敗 → 他が良くても「このまま稼働」にしない
        level, reasons = rb.evaluate([result("5y", wfa=True, verdict="合格"), failed], self.cfg)
        self.assertEqual(level, "gray")
        self.assertIn("直近（recent12m）のテストが失敗したため", reasons[0])
        # 成績の黄が別にあれば黄。失敗も理由に残る
        level, reasons = rb.evaluate([result("5y", wfa=True, verdict="要注意"), failed], self.cfg)
        self.assertEqual(level, "yellow")
        self.assertTrue(any("失敗" in x for x in reasons))
        level, reasons = rb.evaluate([result("recent12m"), rb.RunResult(result("since_v2").plan, error="x")], self.cfg)
        self.assertEqual(level, "gray")
        self.assertIn("since_v2 のテストが失敗しました", reasons[0])

    def test_deposit_mismatch(self):
        cfg = make_cfg()  # USD 口座・140000円 ÷ 158.4 = 883.84 USD
        self.assertIsNone(rb.deposit_mismatch(cfg, {"tester_deposit": 885.0}))
        self.assertIsNone(rb.deposit_mismatch(cfg, {"tester_deposit": None}))
        self.assertEqual(rb.deposit_mismatch(cfg, {"tester_deposit": 140000.0}), 140000.0)
        r = result("recent12m", dd=10, eq=None)
        r.summary["deposit_mismatch"] = 140000.0  # analyze_report が含み損DD% を消した後の状態
        level, reasons = rb.evaluate([r], cfg)
        self.assertEqual(level, "yellow")
        self.assertIn("テスターの初期証拠金 140,000.00 USD が設定の資金 883.84 USD と違います", reasons[0])
        self.assertIn("含み損込み: テスターの初期証拠金が違うため不明", rb.run_value(r))

    def test_reasons_text(self):
        level, reasons = rb.evaluate([result("recent12m", pf=1.05, dd=30)], self.cfg)
        self.assertEqual(level, "red")
        self.assertEqual(len(reasons), 2)
        self.assertIn("PF 1.05", reasons[0])


class HistoryTests(unittest.TestCase):
    def test_append_and_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "reports", "history.jsonl")
            self.assertEqual(rb.load_history(path), [])
            e1 = result("5y", pf=1.5, dd=12.0, lot=0.02).entry
            e1["date"] = "2026-10-10"
            rb.append_history(path, [e1, {**result("recent12m").entry, "date": "2026-10-10"}])
            with open(path, "a", encoding="utf-8") as f:
                f.write("{壊れた行\n")
            e_same_day = {**e1, "date": "2026-10-17", "pf": 9.9}
            rb.append_history(path, [e_same_day])
            hist = rb.load_history(path)
            self.assertEqual(len(hist), 3)
            prev = rb.previous_entry(hist, "5y", date(2026, 10, 17))
            self.assertEqual(prev["date"], "2026-10-10")  # 同じ日の再実行とは比べない
            self.assertIsNone(rb.previous_entry(hist, "since_v2", date(2026, 10, 17)))
            now = result("5y", pf=1.7, dd=11.0, lot=0.03).entry
            d = rb.deltas(now, prev)
            self.assertAlmostEqual(d["pf"], 0.2)
            self.assertAlmostEqual(d["max_dd_pct"], -1.0)
            self.assertAlmostEqual(d["lot"], 0.01)
            self.assertNotIn("eq_dd_pct", d)  # 不明（None）の項目は比較しない
            self.assertEqual(rb.deltas(now, None), {})

    def test_entry_handles_inf(self):
        e = result("5y", pf=float("inf"), lot=float("inf")).entry
        self.assertIsNone(e["pf"])
        self.assertIsNone(e["lot"])
        json.dumps(e, allow_nan=False)


class DiscordTests(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()
        prev = {"date": "2026-10-10", "pf": 1.5, "net_jpy": 40000, "max_dd_pct": 9.0, "lot": 0.02}
        self.results = [result("5y", wfa=True, verdict="合格", eq=18.0, prev=prev), result("recent12m"),
                        rb.RunResult(rb.RunPlan("since_v2", date(2026, 4, 6), date(2026, 10, 16), 34), error="レポートなし")]

    def test_payload(self):
        level, reasons = rb.evaluate(self.results, self.cfg)
        p = rb.build_payload(self.results, level, reasons, [], self.cfg, date(2026, 10, 17))
        emb = p["embeds"][0]
        self.assertEqual(len(emb["fields"]), 3)
        self.assertEqual(level, "gray")  # 失敗があれば「このまま稼働」にはしない
        self.assertEqual(emb["color"], rb.LEVELS["gray"][0])
        self.assertTrue(emb["description"].startswith("⚪ **判定: 保留"))
        self.assertIn("since_v2 のテストが失敗しました", emb["description"])
        self.assertNotIn("問題なし", emb["description"])
        level, reasons = rb.evaluate(self.results[:2], self.cfg)
        ok = rb.build_payload(self.results[:2], level, reasons, [], self.cfg, date(2026, 10, 17))["embeds"][0]
        self.assertEqual((level, ok["color"]), ("green", rb.LEVELS["green"][0]))
        self.assertIn("・直近成績・ウォークフォワード・PF・推奨ロットに問題なし", ok["description"])
        only5y = rb.build_payload(self.results[:1], "green", [], [], self.cfg, date(2026, 10, 17))["embeds"][0]
        self.assertIn("直近 recent12m は今回実行していません", only5y["description"])
        self.assertNotIn("直近成績", only5y["description"])
        v = emb["fields"][0]["value"]
        for s in ("PF 1.60", "純損益 +50,000円", "DD 10.0%（含み損込み 18.0%）", "シャープ 1.50", "WF 合格",
                  "推奨ロット 0.02", "前週比（2026-10-10）: PF +0.10", "DD +1.0pt"):
            self.assertIn(s, v)
        self.assertNotIn("WF", emb["fields"][1]["value"])
        self.assertIn("記録なし", emb["fields"][1]["value"])
        self.assertIn("失敗", emb["fields"][2]["value"])
        red = rb.build_payload(self.results, "red", ["x"], [], self.cfg, date(2026, 10, 17))["embeds"][0]
        self.assertEqual(red["color"], rb.LEVELS["red"][0])
        self.assertIn("稼働停止を検討", red["description"])
        noted = rb.build_payload(self.results[:2], "green", [], ["ヒストリー失敗"], self.cfg, date(2026, 10, 17))
        self.assertEqual(noted["embeds"][0]["color"], rb.LEVELS["green"][0])  # 色とアイコン・文面を一致させる
        self.assertIn("⚠️ ヒストリー失敗", noted["embeds"][0]["description"])
        fail = rb.failure_payload("設定エラー", date(2026, 10, 17))["embeds"][0]
        self.assertEqual(fail["color"], rb.LEVELS["gray"][0])
        self.assertNotIn("稼働停止", fail["description"])
        self.assertIn("判定", rb.payload_text(p))

    def test_multipart(self):
        payload = {"embeds": [{"title": "テスト 🟢"}]}
        files = [("mr2_5y_2026-10-17.md", "# レポート\n".encode("utf-8")), ("b.md", b"two")]
        body, ctype = rb.multipart_body(payload, files, boundary="BOUND")
        self.assertEqual(ctype, "multipart/form-data; boundary=BOUND")
        self.assertTrue(body.endswith(b"--BOUND--\r\n"))
        msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            f"Content-Type: {ctype}\r\n\r\n".encode() + body)
        parts = list(msg.iter_parts())
        self.assertEqual([pt.get_param("name", header="content-disposition") for pt in parts],
                         ["payload_json", "files[0]", "files[1]"])
        pj = json.loads(parts[0].get_payload(decode=True).decode("utf-8"))
        self.assertEqual(pj["embeds"][0]["title"], "テスト 🟢")
        self.assertEqual(pj["attachments"], [{"id": 0, "filename": "mr2_5y_2026-10-17.md"}, {"id": 1, "filename": "b.md"}])
        self.assertEqual(parts[1].get_filename(), "mr2_5y_2026-10-17.md")
        self.assertEqual(parts[1].get_payload(decode=True), "# レポート\n".encode("utf-8"))

    def test_post_retries_429(self):
        calls, sleeps = [], []

        def opener(req, timeout):
            calls.append(req)
            if len(calls) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(b'{"retry_after": 1.5}'))
            return contextlib.nullcontext()

        rb.post_discord(WEBHOOK, {"content": "x"}, [("a.md", b"a")], opener=opener, sleep=sleeps.append)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [1.5])
        self.assertTrue(calls[1].get_header("Content-type").startswith("multipart/form-data"))

    def test_post_errors_hide_url(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"message": "Invalid"}'))

        with self.assertRaises(rb.RunError) as cm:
            rb.post_discord(WEBHOOK, {"content": "x"}, opener=opener, sleep=lambda s: None)
        self.assertIn("401", str(cm.exception))
        self.assertNotIn("abc-DEF", str(cm.exception))
        with self.assertRaises(rb.RunError) as cm:
            rb.post_discord("https://example.com/secret-hook", {"content": "x"}, opener=opener)
        self.assertNotIn("secret-hook", str(cm.exception))

    def test_webhook_format(self):
        ok = (WEBHOOK, WEBHOOK + "?wait=true", "https://canary.discord.com/api/webhooks/1/x",
              "https://discordapp.com/api/webhooks/1/x?thread_id=123")
        bad = (WEBHOOK + " abc", WEBHOOK + "\n", WEBHOOK + " " + WEBHOOK, WEBHOOK + "日本", "http://discord.com/api/webhooks/1/x")
        self.assertTrue(all(rb.WEBHOOK_RE.fullmatch(u) for u in ok))
        self.assertFalse(any(rb.WEBHOOK_RE.fullmatch(u) for u in bad))
        for u in bad:
            with self.assertRaises(rb.RunError) as cm:
                rb.post_discord(u, {"content": "x"}, opener=lambda *a, **k: self.fail("送信してはいけない"))
            self.assertNotIn("abc-DEF", str(cm.exception))

    def test_invalid_url_error_hides_token(self):
        def opener(req, timeout):
            raise http.client.InvalidURL(f"URL can't contain control characters. {req.selector!r}")

        with self.assertRaises(rb.RunError) as cm:
            rb.post_discord(WEBHOOK, {"content": "x"}, opener=opener, sleep=lambda s: None)
        self.assertNotIn("abc-DEF", str(cm.exception))
        with mock.patch.object(rb, "post_discord", side_effect=ValueError(WEBHOOK)), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            rb.notify_failure(WEBHOOK, "x", date(2026, 10, 17))  # 例外を外に出さない
        self.assertNotIn("abc-DEF", out.getvalue())
        self.assertEqual(rb.redact(f"boom {WEBHOOK} '/api/webhooks/123456/abc-DEF_ghi x'", WEBHOOK).count("abc-DEF"), 0)
        self.assertNotIn("TOKEN", rb.redact("'/api/webhooks/99/TOKEN abc'"))


class EndToEndTests(unittest.TestCase):
    """make_sample.py の架空レポートを「MT4 が作ったレポート」として使う."""

    @classmethod
    def setUpClass(cls):
        cls.samples = tempfile.TemporaryDirectory()
        cls.sample = ms.write_samples(cls.samples.name, seed=7, years=2.0)["en"]

    @classmethod
    def tearDownClass(cls):
        cls.samples.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mt4 = os.path.join(self.tmp.name, "MT4 Backtest")
        self.reports = os.path.join(self.tmp.name, "my reports")
        os.makedirs(os.path.join(self.mt4, "auto_reports"))
        self.cfg_path = os.path.join(self.tmp.name, "config.json")
        cfg = {"_comment": "テスト", "mt4_dir": self.mt4, "reports_dir": self.reports, "account_currency": "JPY",
               "capital_jpy": 1000000, "mc_runs": 100, "discord_webhook_url": WEBHOOK,
               "runs": [{"name": "5y", "years": 5, "wfa": True}, {"name": "recent12m", "months": 12}]}
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *extra: str, env: dict | None = None) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            if not env:
                os.environ.pop("DISCORD_WEBHOOK_URL", None)
            rc = rb.main(["--config", self.cfg_path, *extra])
        return rc, out.getvalue()

    def test_dry_run(self):
        shutil.copy(self.sample, os.path.join(self.mt4, "auto_reports", "mr2_5y.htm"))
        with mock.patch.object(rb.subprocess, "run") as run, mock.patch.object(rb, "post_discord") as post:
            rc, out = self.run_main("--dry-run", "--today", "2023-01-07")
        self.assertEqual(rc, 1)  # recent12m のレポートがない
        run.assert_not_called()
        post.assert_not_called()
        self.assertIn("TestExpert=Mr2_gold_v2.0(HFMonly)", out)
        self.assertIn("TestFromDate=2018.01.06", out)
        self.assertIn("判定:", out)
        self.assertIn("mr2_5y_2023-01-07.md", out)
        self.assertIn("失敗", out)
        self.assertNotIn(WEBHOOK, out)
        day = os.path.join(self.reports, "2023-01-07")
        self.assertTrue(os.path.isfile(os.path.join(day, "mr2_5y.md")))
        self.assertTrue(os.path.isfile(os.path.join(day, "mr2_5y.htm")))
        self.assertTrue(os.path.isfile(os.path.join(self.mt4, "auto", "5y.ini")))
        self.assertFalse(os.path.exists(os.path.join(self.reports, "history.jsonl")))
        with open(os.path.join(day, "mr2_5y.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("ウォークフォワード", md)
        rc, out = self.run_main("--dry-run", "--today", "2023-01-07", "--only", "5y")
        self.assertEqual(rc, 0)

    def test_full_run_with_mocked_mt4_and_discord(self):
        for rel in ("terminal.exe", os.path.join("MQL4", "Experts", "Mr2_gold_v2.0(HFMonly).ex4")):
            os.makedirs(os.path.dirname(os.path.join(self.mt4, rel)), exist_ok=True)
            open(os.path.join(self.mt4, rel), "w").close()
        launched, posted = [], []

        def fake_run(cmd, **kw):
            launched.append(cmd)
            if cmd[0] == sys.executable:  # fetch_history.py
                return subprocess.CompletedProcess(cmd, 0)
            name = os.path.splitext(os.path.basename(cmd[2]))[0]
            shutil.copy(self.sample, os.path.join(self.mt4, "auto_reports", f"mr2_{name}.htm"))
            return subprocess.CompletedProcess(cmd, 0)

        def fake_post(url, payload, files=None, **kw):
            posted.append((url, payload, files))

        fake_dir = os.path.join(self.tmp.name, "automation")  # fetch_history.py の代わり（中身は実行しない）
        os.makedirs(fake_dir)
        script = os.path.join(fake_dir, "fetch_history.py")
        open(script, "w").close()
        with mock.patch.object(rb.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(rb, "post_discord", side_effect=fake_post), mock.patch.object(rb, "HERE", fake_dir):
            rc1, _ = self.run_main("--today", "2023-01-07")
            rc2, out2 = self.run_main("--today", "2023-01-14", "--skip-history")
        self.assertEqual((rc1, rc2), (0, 0))
        fetch = launched[0]
        self.assertEqual(fetch[1:], [script, "--mt4-dir", self.mt4, "--server", "HFMarketsSV-Demo Server 2",
                                     "--symbol", "XAUUSD", "--from", "2018-01-06"])
        self.assertEqual(sum(c[0] == sys.executable for c in launched), 1)  # 2回目は --skip-history
        self.assertEqual(len(posted), 2)
        url, payload, files = posted[1]
        self.assertEqual(url, WEBHOOK)
        self.assertEqual([n for n, _ in files], ["mr2_5y_2023-01-14.md", "mr2_recent12m_2023-01-14.md"])
        self.assertIn("前週比（2023-01-07）", payload["embeds"][0]["fields"][0]["value"])
        hist = rb.load_history(os.path.join(self.reports, "history.jsonl"))
        self.assertEqual([(h["date"], h["run"]) for h in hist],
                         [("2023-01-07", "5y"), ("2023-01-07", "recent12m"),
                          ("2023-01-14", "5y"), ("2023-01-14", "recent12m")])
        self.assertIn(hist[0]["wf_verdict"], ("合格", "要注意", "不合格"))
        self.assertIsNone(hist[1]["wf_verdict"])
        self.assertEqual(hist[2]["delta"]["pf"], 0)  # 同じレポートなので差は 0
        self.assertNotIn(WEBHOOK, out2)

    def test_tester_deposit_mismatch(self):
        cfg = rb.normalize_config({"mt4_dir": self.mt4, "reports_dir": self.reports, "mc_runs": 50})  # USD・883.84
        plan = rb.RunPlan("recent12m", date(2022, 1, 7), date(2023, 1, 6), 34)
        with contextlib.redirect_stdout(io.StringIO()):
            md, s = rb.analyze_report(cfg, plan, self.sample, os.path.join(self.reports, "d"))
        self.assertEqual(s["tester_deposit"], ms.DEPOSIT)  # 換算前のレポート記載値
        self.assertEqual(s["deposit_mismatch"], ms.DEPOSIT)
        self.assertIsNone(s["eq_dd_pct"])  # 別の証拠金で計算された含み損DD% は判定に使わない
        with open(md, encoding="utf-8") as f:
            self.assertIn("テスターの初期証拠金 1,000,000.00 USD", f.read())
        self.assertEqual(rb.history_entry(date(2023, 1, 7), plan, s)["tester_deposit"], ms.DEPOSIT)

    def test_unexpected_error_and_bad_webhook_hide_token(self):
        posted = []
        with mock.patch.object(rb, "run_all", side_effect=ValueError(f"boom '/api/webhooks/123456/abc-DEF_ghi'")), \
                mock.patch.object(rb, "post_discord", side_effect=lambda url, p, *a, **k: posted.append(p)):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                os.environ.pop("DISCORD_WEBHOOK_URL", None)
                rc = rb.main(["--config", self.cfg_path, "--today", "2023-01-07"])
        self.assertEqual(rc, 1)
        self.assertIn("ValueError", err.getvalue())
        self.assertNotIn("abc-DEF", err.getvalue() + json.dumps(posted, ensure_ascii=False))
        with open(self.cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["discord_webhook_url"] = WEBHOOK + " abc"  # 余計な空白（貼り付けミス）
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc, out = self.run_main("--today", "2023-01-07", "--skip-history")
        self.assertEqual(rc, 1)  # 落ちずに終了する
        self.assertIn("形式が正しくありません", out)
        self.assertNotIn("abc-DEF", out + err.getvalue())

    def test_failure_notice(self):
        posted = []
        with mock.patch.object(rb, "post_discord", side_effect=lambda url, p, *a, **k: posted.append(p)), \
                mock.patch.object(rb.subprocess, "run") as run:
            rc, out = self.run_main("--today", "2023-01-07", "--skip-history")
        self.assertEqual(rc, 1)
        run.assert_not_called()  # terminal.exe も EA もないので起動前に失敗
        self.assertEqual(len(posted), 1)
        self.assertIn("失敗", posted[0]["embeds"][0]["title"])
        self.assertIn("terminal.exe", posted[0]["embeds"][0]["description"])

    def test_bad_config(self):
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write('{"mt4_dir": "C:\\MT4"}')  # \M は JSON として不正
        with mock.patch.object(rb, "post_discord") as post:
            rc, out = self.run_main("--today", "2023-01-07", env={"DISCORD_WEBHOOK_URL": WEBHOOK})
        self.assertEqual(rc, 1)
        self.assertIn("JSON", out)
        post.assert_called_once()
        self.assertEqual(post.call_args[0][0], WEBHOOK)


if __name__ == "__main__":
    unittest.main()
