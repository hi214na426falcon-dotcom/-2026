#!/usr/bin/env python3
"""Mr.2 Gold 運用ナビ.

毎朝 ForexFactory の経済指標カレンダー（と金価格のボラティリティ）を取得し、
XAUUSD 1分足EAの稼働判断（通常稼働 / 時間帯停止 / 終日停止）を Discord Webhook に通知する。
標準ライブラリだけで動くので GitHub Actions でそのまま実行できる。

使い方:
    DISCORD_WEBHOOK_URL=... python notifier/daily_brief.py
    python notifier/daily_brief.py --dry-run                      # 送信せず内容を表示
    python notifier/daily_brief.py --dry-run --fixture events.json --now 2026-10-16T05:45+09:00
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
NY = ZoneInfo("America/New_York")
SERVER_TZ = ZoneInfo("Europe/Athens")  # HFM MT4: GMT+2、欧州夏時間中は GMT+3
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "config.json")
USER_AGENT = "Mozilla/5.0 (compatible; gold-ea-brief/1.0)"

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
DEFAULT_SCHEDULE = os.path.join(HERE, "key_events.json")
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=6mo&interval=1d"

GREEN, YELLOW, RED = 0, 1, 2
LEVEL_META = {
    GREEN: ("🟢", "通常稼働OK", 0x2ECC71),
    YELLOW: ("🟡", "指標前後だけ停止して稼働", 0xF1C40F),
    RED: ("🔴", "停止推奨の時間帯あり", 0xE74C3C),
}
TIER_ICON = {"red": "🔴", "yellow": "🟡", "info": "⚪", "holiday": "🏦", "other": "🌐"}
WEEKDAYS_JA = "月火水木金土日"

# ForexFactory の英語タイトル → 日本語（m/m, y/y, q/q は別途付与）
TITLE_JA = {
    "Non-Farm Employment Change": "米雇用統計（非農業部門雇用者数）",
    "ADP Non-Farm Employment Change": "ADP雇用統計",
    "Unemployment Rate": "失業率",
    "Average Hourly Earnings": "平均時給",
    "Unemployment Claims": "新規失業保険申請件数",
    "JOLTS Job Openings": "JOLTS求人件数",
    "CPI": "消費者物価指数（CPI）",
    "Core CPI": "コアCPI",
    "PPI": "生産者物価指数（PPI）",
    "Core PPI": "コアPPI",
    "Retail Sales": "小売売上高",
    "Core Retail Sales": "コア小売売上高",
    "Federal Funds Rate": "FOMC政策金利",
    "FOMC Statement": "FOMC声明",
    "FOMC Press Conference": "FOMC記者会見",
    "FOMC Economic Projections": "FOMC経済見通し（ドットチャート）",
    "FOMC Meeting Minutes": "FOMC議事要旨",
    "Advance GDP": "GDP速報値",
    "Prelim GDP": "GDP改定値",
    "Final GDP": "GDP確定値",
    "Core PCE Price Index": "コアPCEデフレーター",
    "ISM Manufacturing PMI": "ISM製造業景況指数",
    "ISM Services PMI": "ISM非製造業景況指数",
    "Prelim UoM Consumer Sentiment": "ミシガン大消費者信頼感（速報）",
    "Revised UoM Consumer Sentiment": "ミシガン大消費者信頼感（確報）",
    "Prelim UoM Inflation Expectations": "ミシガン大期待インフレ率（速報）",
    "CB Consumer Confidence": "消費者信頼感指数（CB）",
    "Empire State Manufacturing Index": "NY連銀製造業景況指数",
    "Philly Fed Manufacturing Index": "フィラデルフィア連銀景況指数",
    "Durable Goods Orders": "耐久財受注",
    "Core Durable Goods Orders": "コア耐久財受注",
    "Employment Cost Index": "雇用コスト指数",
    "Bank Holiday": "祝日（銀行休業）",
}
SUFFIX_JA = {"m/m": "前月比", "y/y": "前年比", "q/q": "前期比"}
COUNTRY_JA = {"USD": "米", "EUR": "欧", "GBP": "英", "JPY": "日", "CNY": "中",
              "AUD": "豪", "CAD": "加", "CHF": "スイス", "NZD": "NZ"}


@dataclass
class Event:
    title: str
    country: str
    impact: str
    time: datetime
    forecast: str = ""
    previous: str = ""
    tier: str | None = None


@dataclass
class Window:
    start: datetime
    end: datetime
    level: int
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 時刻ユーティリティ

def to_server(dt: datetime) -> datetime:
    """HFM MT4 サーバー時間（GMT+2、3月最終日曜〜10月最終日曜は GMT+3）."""
    return dt.astimezone(SERVER_TZ)


def hm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def md_w(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS_JA[d.weekday()]})"


def span_text(w: Window) -> str:
    sj, ej = w.start.astimezone(JST), w.end.astimezone(JST)
    ss, es = to_server(w.start), to_server(w.end)
    nxt = "翌" if ej.date() != sj.date() else ""
    nxt_s = "翌" if es.date() != ss.date() else ""
    return f"JST {hm(sj)}〜{nxt}{hm(ej)}（サーバー {hm(ss)}〜{nxt_s}{hm(es)}）"


def trading_day_bounds(d: date) -> tuple[datetime, datetime]:
    """JST 06:00 から翌 06:00 までを 1 営業日として扱う."""
    start = datetime(d.year, d.month, d.day, 6, 0, tzinfo=JST)
    return start, start + timedelta(days=1)


# ---------------------------------------------------------------- データ取得

def http_get(url: str, timeout: int = 20, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                break
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def parse_ff(records: list[dict]) -> list[Event]:
    events = []
    for r in records:
        try:
            t = datetime.fromisoformat(r["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=NY)
        events.append(Event(
            title=(r.get("title") or "").strip(),
            country=(r.get("country") or "").strip().upper(),
            impact=(r.get("impact") or "").strip(),
            time=t,
            forecast=(r.get("forecast") or "").strip(),
            previous=(r.get("previous") or "").strip(),
        ))
    return events


def fetch_ff() -> list[Event]:
    """ForexFactory は 1IP あたり 5分2回まで。制限時は HTML が返るので中身を検証し、1回だけ待って再試行する."""
    for attempt in range(2):
        body = http_get(FF_URL).strip()
        if body.startswith(b"["):
            return parse_ff(json.loads(body))
        if attempt == 0:
            time.sleep(150)
    raise RuntimeError("ForexFactory がJSON以外を返しました（アクセス制限の可能性）")


def load_static_schedule(path: str) -> list[Event]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return parse_ff(json.load(f).get("events", []))


def merge_with_static(live: list[Event] | None, static: list[Event]) -> list[Event]:
    """ライブデータが無い日だけ静的スケジュール（FOMC/CPI/雇用統計）で補う."""
    if not live:
        return sorted(static, key=lambda e: e.time)
    covered = {e.time.astimezone(NY).date() for e in live}
    last = max(e.time for e in live)
    extra = [e for e in static if e.time > last and e.time.astimezone(NY).date() not in covered]
    return sorted(live + extra, key=lambda e: e.time)


def load_events(fixture: str | None) -> list[Event]:
    if fixture:
        with open(fixture, encoding="utf-8") as f:
            return parse_ff(json.load(f))
    return fetch_ff()


def load_bars(symbol: str, fixture: str | None = None) -> list[tuple[date, float, float, float, float]]:
    if fixture:
        with open(fixture, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.loads(http_get(YAHOO_URL.format(symbol=urllib.request.quote(symbol))))
    res = data["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = []
    for ts, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"]):
        if None in (o, h, l, c):
            continue
        bars.append((datetime.fromtimestamp(ts, NY).date(), o, h, l, c))
    return bars


def volatility_stats(bars) -> dict | None:
    if len(bars) < 30:
        return None
    trs = []
    for prev, cur in zip(bars, bars[1:]):
        _, _, h, l, _ = cur
        pc = prev[4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atrs = [sum(trs[i - 14:i]) / 14 for i in range(14, len(trs) + 1)]
    atr14 = atrs[-1]
    base = statistics.median(atrs[-120:])
    last, prev = bars[-1], bars[-2]
    rng = last[2] - last[3]
    return {
        "date": last[0],
        "close": last[4],
        "change": last[4] - prev[4],
        "change_pct": (last[4] / prev[4] - 1) * 100,
        "range": rng,
        "atr14": atr14,
        "atr_base": base,
        "atr_ratio": atr14 / base if base else 1.0,
        "range_ratio": rng / atr14 if atr14 else 1.0,
    }


# ---------------------------------------------------------------- 判定ロジック

def classify(ev: Event, cfg: dict) -> str | None:
    t = ev.title.lower()
    watch = ev.country in cfg["watch_currencies"]
    if ev.impact == "Holiday":
        return "holiday" if watch else None
    if not watch:
        return "other" if ev.impact == "High" else None
    red = any(k.lower() in t for k in cfg["red_keywords"])
    if red and not any(x.lower() in t for x in cfg.get("red_exclude_keywords", [])):
        return "red"
    if ev.impact in cfg["yellow_impacts"] or any(k.lower() in t for k in cfg.get("yellow_keywords", [])):
        return "yellow"
    if ev.impact in cfg.get("info_impacts", []):
        return "info"
    return None


def title_ja(ev: Event) -> str:
    title = ev.title
    suffix = ""
    for en, ja in SUFFIX_JA.items():
        if title.endswith(" " + en):
            title, suffix = title[: -len(en) - 1], ja
            break
    if title in TITLE_JA:
        name = TITLE_JA[title]
    elif title.endswith(" Speaks"):
        who = title[: -len(" Speaks")].replace("Fed Chair", "FRB議長").replace("FOMC Member", "FOMC委員")
        name = who + " 発言"
    else:
        name = ev.title
        suffix = ""
    prefix = COUNTRY_JA.get(ev.country, ev.country)
    return f"{prefix} {name}{' ' + suffix if suffix else ''}"


def build_windows(events: list[Event], cfg: dict) -> list[Window]:
    raw = []
    for ev in events:
        if ev.tier not in ("red", "yellow"):
            continue
        w = cfg[f"{ev.tier}_window"]
        raw.append(Window(
            start=ev.time - timedelta(minutes=w["before_min"]),
            end=ev.time + timedelta(minutes=w["after_min"]),
            level=RED if ev.tier == "red" else YELLOW,
            reasons=[f"{hm(ev.time.astimezone(JST))} {title_ja(ev)}"],
        ))
    raw.sort(key=lambda w: w.start)
    merged: list[Window] = []
    for w in raw:
        if merged and w.start <= merged[-1].end:
            m = merged[-1]
            m.end = max(m.end, w.end)
            m.level = max(m.level, w.level)
            m.reasons += [r for r in w.reasons if r not in m.reasons]
        else:
            merged.append(w)
    return merged


def seasonal_reason(d: date, cfg: dict) -> str | None:
    key = (d.month, d.day)
    for p in cfg.get("seasonal_stop_periods", []):
        f = tuple(int(x) for x in p["from"].split("-"))
        t = tuple(int(x) for x in p["to"].split("-"))
        inside = f <= key <= t if f <= t else (key >= f or key <= t)
        if inside:
            return p["reason"]
    return None


@dataclass
class DayPlan:
    day: date
    events: list[Event]
    windows: list[Window]
    stop_all_day: list[str]
    level: int


def plan_day(d: date, events: list[Event], cfg: dict, vol_level: int = GREEN) -> DayPlan:
    start, end = trading_day_bounds(d)
    todays = [e for e in events if start <= e.time < end]
    for e in todays:
        e.tier = classify(e, cfg)
    windows = build_windows(todays, cfg)
    stop = []
    if d.isoformat() in cfg.get("stop_dates", {}):
        stop.append(cfg["stop_dates"][d.isoformat()])
    season = seasonal_reason(d, cfg)
    if season:
        stop.append(season)
    holiday = any(e.tier == "holiday" for e in todays)
    level = max([w.level for w in windows] + [vol_level, RED if stop else GREEN, YELLOW if holiday else GREEN])
    return DayPlan(d, todays, windows, stop, level)


def vol_assessment(vol: dict | None, cfg: dict) -> tuple[int, str | None]:
    if not vol:
        return GREEN, None
    v = cfg["volatility"]
    if vol["atr_ratio"] >= v["atr_ratio_danger"] or vol["range_ratio"] >= v["range_ratio_danger"]:
        return RED, "ボラティリティ急拡大：ロットを半分にするか、本日は停止を推奨"
    if vol["atr_ratio"] >= v["atr_ratio_caution"] or vol["range_ratio"] >= v["range_ratio_caution"]:
        return YELLOW, "ボラティリティ高め：指標前後の停止を徹底し、ロットを上げないこと"
    return GREEN, None


# ---------------------------------------------------------------- メッセージ生成

def clip(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[: limit - 2] + "…"


def event_line(e: Event, day: date | None = None) -> str:
    t = e.time.astimezone(JST)
    extra = []
    if e.forecast:
        extra.append(f"予想 {e.forecast}")
    if e.previous:
        extra.append(f"前回 {e.previous}")
    tail = f"（{' / '.join(extra)}）" if extra else ""
    clock = "終日" if e.tier == "holiday" else ("翌" if day and t.date() > day else "") + hm(t)
    return f"{TIER_ICON.get(e.tier, '・')} {clock} {title_ja(e)}{tail}"


def headline(plan: DayPlan) -> str:
    if plan.stop_all_day:
        return "🔴 本日は終日停止を推奨"
    if plan.level == RED and any(w.level == RED for w in plan.windows):
        return "🔴 重要指標あり：下記の時間帯は必ず停止"
    if plan.level == RED:
        return "🔴 本日は停止またはロット半分を推奨"
    if plan.level == YELLOW and not plan.windows and any(e.tier == "holiday" for e in plan.events):
        return "🟡 米国の祝日：薄商いに注意して稼働（不安ならロットを下げる）"
    if plan.level == YELLOW:
        return "🟡 指標前後だけ停止して稼働"
    return "🟢 通常稼働OK（米国の重要指標なし）"


def ea_setting_text(plan: DayPlan) -> str:
    if plan.stop_all_day:
        return "MT4 の「自動売買」ボタンをOFF（終日）。保有ポジションの有無も確認。"
    if not plan.windows:
        return "変更不要（新規エントリー不可時間帯は通常どおり）。"
    lines = [f"・{span_text(w)}" for w in plan.windows]
    if len(plan.windows) > 1:
        whole = Window(plan.windows[0].start, plan.windows[-1].end, RED)
        if whole.end - whole.start <= timedelta(hours=10):
            lines.append(f"EAの不可時間帯は1つなので、まとめて {span_text(whole)} に設定するのが簡単です。")
        else:
            lines.append("時間帯が離れているので、2つ目以降は「自動売買」ボタンで手動停止してください。")
    lines.append("※停止開始時点で保有中のポジションはEAが管理を続けます（停止されるのは新規エントリーのみ）。")
    return "\n".join(lines)


def risk_text(vol: dict | None, usdjpy: float | None, cfg: dict) -> str | None:
    if not vol or not usdjpy:
        return None
    lot, cap = cfg["lot"], cfg["capital_jpy"]
    per_lot_jpy = vol["atr14"] * 100 * lot * usdjpy  # 1lot = 100oz
    pct = per_lot_jpy / cap * 100
    return (f"ATR14 ${vol['atr14']:.1f} を {lot}lot（1ポジション）で丸々逆行されると 約 -¥{per_lot_jpy:,.0f}"
            f"（資金 ¥{cap:,} の {pct:.1f}%）。ナンピンで複数ポジションになると、その分だけ倍増します。")


def build_daily_payload(now: datetime, events: list[Event] | None, cfg: dict,
                        vol: dict | None, usdjpy: float | None, calendar_error: str | None) -> dict:
    today = now.astimezone(JST).date()
    vol_level, vol_note = vol_assessment(vol, cfg)

    if events is None:
        desc = ("⚠️ 経済指標カレンダーの取得に失敗しました。\n"
                "本日は ForexFactory などで米国の重要指標（雇用統計・CPI・FOMC）を手動で確認し、"
                "該当する時間帯はEAを停止してください。")
        return {"username": "Gold EA 運用ナビ", "embeds": [{
            "title": f"{md_w(today)} Mr.2 Gold 稼働判断",
            "description": desc + (f"\n```{clip(calendar_error or '', 300)}```" if calendar_error else ""),
            "color": LEVEL_META[RED][2],
        }]}

    plan = plan_day(today, events, cfg, vol_level)
    fields = []
    if calendar_error:
        fields.append({"name": "⚠️ カレンダー取得失敗",
                       "value": "ForexFactory に接続できなかったため、予備スケジュール（FOMC・CPI・雇用統計のみ）で判定しています。"
                                "その他の指標は手動で確認してください。"})

    shown = [e for e in plan.events if e.tier in ("red", "yellow", "holiday", "info")]
    fields.append({
        "name": "📅 本日の米国指標（JST）",
        "value": clip("\n".join(event_line(e, today) for e in shown) or "米国の主要指標はありません。"),
    })
    others = [e for e in plan.events if e.tier == "other"]
    if others:
        fields.append({"name": "🌐 その他の主要国（参考）",
                       "value": clip("\n".join(event_line(e, today) for e in others))})

    fields.append({"name": "⚙️ EAの操作", "value": clip(ea_setting_text(plan))})
    if plan.stop_all_day:
        fields.append({"name": "⛔ 終日停止の理由", "value": clip("\n".join(plan.stop_all_day))})

    if vol:
        vtxt = (f"金先物 終値 ${vol['close']:,.1f}（{vol['change']:+.1f} / {vol['change_pct']:+.2f}%）\n"
                f"直近の値幅 ${vol['range']:.1f} ／ ATR14 ${vol['atr14']:.1f}"
                f"（平常時の {vol['atr_ratio']:.2f} 倍）")
        if usdjpy:
            vtxt += f"\nUSDJPY {usdjpy:.2f}"
        if vol_note:
            vtxt += f"\n**{vol_note}**"
        fields.append({"name": "📈 ボラティリティ", "value": clip(vtxt)})
        rt = risk_text(vol, usdjpy, cfg)
        if rt:
            fields.append({"name": "💴 本日の想定リスク", "value": clip(rt)})
    else:
        fields.append({"name": "📈 ボラティリティ", "value": "価格データを取得できませんでした（指標のみで判定）。"})

    upcoming = []
    for i in range(1, 7):
        d = today + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        p = plan_day(d, events, cfg)
        reds = [e for e in p.events if e.tier == "red"]
        if reds or p.stop_all_day:
            names = "、".join(dict.fromkeys(title_ja(e) for e in reds)) or "、".join(p.stop_all_day)
            upcoming.append(f"🔴 {md_w(d)} {names}")
    if upcoming:
        fields.append({"name": "🗓️ 今後の要注意日", "value": clip("\n".join(upcoming))})

    notes = []
    if today.weekday() == 0:
        notes.append("月曜オープン直後はスプレッドが広がりやすいので、JST 8:00頃まではEAの新規エントリーに注意。")
    if today.weekday() == 4:
        notes.append("金曜：週末の窓開けリスク。クローズ前に保有ポジションを確認。")
    if notes:
        fields.append({"name": "📝 メモ", "value": clip("\n".join(notes))})

    emoji, _, color = LEVEL_META[plan.level]
    payload = {
        "username": "Gold EA 運用ナビ",
        "embeds": [{
            "title": f"{md_w(today)} Mr.2 Gold 稼働判断",
            "description": f"**{headline(plan)}**",
            "color": color,
            "fields": fields[:25],
            "footer": {"text": "データ: ForexFactory / Yahoo Finance（金先物で代用）・最終判断はご自身で"},
            "timestamp": now.astimezone(timezone.utc).isoformat(),
        }],
    }
    if plan.level == RED and cfg.get("mention_on_red"):
        payload["content"] = cfg["mention_on_red"]
        payload["allowed_mentions"] = {"parse": ["everyone", "roles", "users"]}
    return payload


def payload_to_text(payload: dict) -> str:
    out = []
    if payload.get("content"):
        out.append(payload["content"])
    for emb in payload.get("embeds", []):
        out.append(f"■ {emb.get('title', '')}")
        out.append(emb.get("description", ""))
        for f in emb.get("fields", []):
            out.append(f"\n[{f['name']}]\n{f['value']}")
    return "\n".join(out)


# ---------------------------------------------------------------- Discord 送信

def post_discord(url: str, payload: dict, retries: int = 3) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=20):
                return
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = float(json.loads(e.read()).get("retry_after", 2))
                except Exception:
                    wait = 2.0
                time.sleep(min(wait, 30))
                continue
            raise RuntimeError(f"Discord returned HTTP {e.code}: {e.read()[:300]!r}") from e
        except urllib.error.URLError:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("Discord webhook post failed after retries")


# ---------------------------------------------------------------- エントリーポイント

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--fixture", help="ForexFactory 形式の JSON（テスト用）")
    ap.add_argument("--gold-fixture", help="Yahoo chart 形式の JSON（テスト用）")
    ap.add_argument("--usdjpy-fixture", help="Yahoo chart 形式の JSON（テスト用）")
    ap.add_argument("--no-price", action="store_true", help="価格データを取得しない")
    ap.add_argument("--now", help="現在時刻を上書き（例: 2026-10-16T05:45+09:00）")
    ap.add_argument("--dry-run", action="store_true", help="送信せず内容を表示")
    ap.add_argument("--force", action="store_true", help="土日でも送信する")
    ap.add_argument("--schedule", default=DEFAULT_SCHEDULE, help="予備の重要指標スケジュール")
    ap.add_argument("--wait-until", help="JSTでこの時刻（HH:MM）まで待ってから送信（Actions の遅延対策）")
    args = ap.parse_args(argv)

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    if now.astimezone(JST).weekday() >= 5 and not args.force:
        print("土日のため送信しません（--force で強制送信）")
        return 0

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    if os.environ.get("EA_CAPITAL_JPY"):
        cfg["capital_jpy"] = int(os.environ["EA_CAPITAL_JPY"])
    if os.environ.get("EA_LOT"):
        cfg["lot"] = float(os.environ["EA_LOT"])

    if args.wait_until and not args.now:
        hh, mm = (int(x) for x in args.wait_until.split(":"))
        target = now.astimezone(JST).replace(hour=hh, minute=mm, second=0, microsecond=0)
        wait = (target - datetime.now(JST)).total_seconds()
        if 0 < wait <= 2 * 3600:
            print(f"{args.wait_until} JST まで {wait / 60:.0f} 分待機します")
            time.sleep(wait)
            now = datetime.now(JST)

    events, cal_err = None, None
    try:
        events = load_events(args.fixture)
    except Exception as e:
        cal_err = str(e)
        print(f"[warn] calendar: {e}", file=sys.stderr)
    static = load_static_schedule(args.schedule)
    if events is not None or static:
        events = merge_with_static(events, static)

    vol, usdjpy = None, None
    if not args.no_price:
        try:
            vol = volatility_stats(load_bars("GC=F", args.gold_fixture))
        except Exception as e:
            print(f"[warn] gold price: {e}", file=sys.stderr)
        try:
            usdjpy = load_bars("USDJPY=X", args.usdjpy_fixture)[-1][4]
        except Exception as e:
            print(f"[warn] usdjpy: {e}", file=sys.stderr)

    payload = build_daily_payload(now, events, cfg, vol, usdjpy, cal_err)

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if args.dry_run or not webhook:
        if not args.dry_run:
            print("DISCORD_WEBHOOK_URL が未設定のため表示のみ行います。", file=sys.stderr)
        print(payload_to_text(payload))
        return 0 if args.dry_run else 2

    post_discord(webhook, payload)
    print("Discord に送信しました。")
    return 1 if cal_err else 0


if __name__ == "__main__":
    sys.exit(main())
