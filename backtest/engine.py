"""バイナリーオプション（High/Low・固定時間 Up/Down）のバックテストエンジン。

価格モデル:
- バー i でシグナルが出たら close[i] をストライク（エントリー価格）として建玉。
- ``expiry_bars`` 本後の close[i + expiry_bars] を「判定レート」とする。
- UP  : 判定レート > エントリー で勝ち。
- DOWN: 判定レート < エントリー で勝ち。
- 同値（タイ）の扱いは ``tie_policy`` で指定:
    "loss"   … 負け（保守的・既定）
    "refund" … 投資額返却（多くの実ブローカーの挙動に近い）
    "win"    … 勝ち
- 損益: 勝ち = stake * (payout - 1) / 負け = -stake / 返却 = 0

ペイアウトの定義:
``payout`` は「勝った時に戻る総額の倍率」。例: payout=1.85 なら 1000 円投資で
1850 円が戻り、純利益は 850 円。負ければ 1000 円すべて失う。
→ 損益分岐勝率は 1 / payout。

【正直な前提】
- このエンジンはスプレッド/約定遅延を 0 と仮定する。実際の固定時間取引では
  判定が不利に働くこともあるため、本エンジンの結果は実運用よりやや楽観的になりうる。
- 「判定レート > / <」は厳密不等号。実ブローカーの丸めや同値判定で差が出る。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .data import Series
from .strategies import DOWN, UP, Signals


@dataclass
class Trade:
    index: int
    direction: str
    entry: float
    expiry_index: int
    exit: float
    result: str  # "win" | "loss" | "tie"
    pnl: float
    balance: float
    time: Optional[str] = None


@dataclass
class BacktestResult:
    trades: List[Trade] = field(default_factory=list)
    payout: float = 1.85
    stake: float = 1000.0
    start_balance: float = 100000.0
    tie_policy: str = "loss"
    name: str = ""

    def metrics(self) -> Dict[str, float]:
        t = self.trades
        n = len(t)
        wins = sum(1 for x in t if x.result == "win")
        losses = sum(1 for x in t if x.result == "loss")
        ties = sum(1 for x in t if x.result == "tie")
        decided = wins + losses
        win_rate = wins / decided if decided else 0.0
        breakeven = 1.0 / self.payout
        total_pnl = sum(x.pnl for x in t)
        end_balance = self.start_balance + total_pnl
        roi = total_pnl / self.start_balance if self.start_balance else 0.0

        # 勝率の 95% 信頼区間（正規近似）と、損益分岐との統計的な区別可否。
        # breakeven が CI の内側にある＝「優位はノイズと区別できない（有意でない）」。
        if decided > 0:
            se = (win_rate * (1.0 - win_rate) / decided) ** 0.5
            ci_low = win_rate - 1.96 * se
            ci_high = win_rate + 1.96 * se
        else:
            ci_low = ci_high = 0.0
        significant = breakeven < ci_low or breakeven > ci_high
        gross_win = sum(x.pnl for x in t if x.pnl > 0)
        gross_loss = -sum(x.pnl for x in t if x.pnl < 0)
        if gross_loss > 0:
            profit_factor = gross_win / gross_loss
        else:
            profit_factor = float("inf") if gross_win > 0 else 0.0
        expectancy = total_pnl / n if n else 0.0

        # 最大ドローダウン（残高曲線のピークからの最大下落）
        curve = [self.start_balance] + [x.balance for x in t]
        peak = curve[0]
        max_dd = 0.0
        max_dd_pct = 0.0
        for b in curve:
            if b > peak:
                peak = b
            dd = peak - b
            if dd > max_dd:
                max_dd = dd
            if peak > 0 and dd / peak > max_dd_pct:
                max_dd_pct = dd / peak

        return {
            "trades": float(n),
            "wins": float(wins),
            "losses": float(losses),
            "ties": float(ties),
            "win_rate": win_rate,
            "breakeven_win_rate": breakeven,
            "edge": win_rate - breakeven,
            "total_pnl": total_pnl,
            "end_balance": end_balance,
            "roi": roi,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "max_drawdown": max_dd,
            "max_drawdown_pct": max_dd_pct,
            "win_rate_ci_low": ci_low,
            "win_rate_ci_high": ci_high,
            "significant": 1.0 if significant else 0.0,
        }


def run_backtest(
    series: Series,
    signals: Signals,
    payout: float = 1.85,
    expiry_bars: int = 1,
    stake: float = 1000.0,
    start_balance: float = 100000.0,
    tie_policy: str = "loss",
    no_overlap: bool = True,
    name: str = "",
) -> BacktestResult:
    """シグナル列に対してバックテストを実行する。

    no_overlap=True の場合、建玉中（エントリー〜判定）は新規シグナルを無視する
    （単一ポジションのトレーダーを想定。残高曲線が逐次的になり解釈が明確）。
    """
    if len(signals) != len(series):
        raise ValueError("signals と series の長さが一致しません。")
    if payout <= 0:
        raise ValueError("payout は正の値で指定してください。")

    closes = series.closes
    n = len(series)
    balance = start_balance
    trades: List[Trade] = []
    open_until = -1

    for i in range(n):
        sig = signals[i]
        if sig is None:
            continue
        j = i + expiry_bars
        if j >= n:
            break
        if no_overlap and i <= open_until:
            continue

        entry = closes[i]
        exit_price = closes[j]

        if exit_price == entry:
            if tie_policy == "win":
                result = "win"
            elif tie_policy == "refund":
                result = "tie"
            else:
                result = "loss"
        else:
            up_won = exit_price > entry
            won = (sig == UP and up_won) or (sig == DOWN and not up_won)
            result = "win" if won else "loss"

        if result == "win":
            pnl = stake * (payout - 1.0)
        elif result == "loss":
            pnl = -stake
        else:
            pnl = 0.0

        balance += pnl
        trades.append(
            Trade(
                index=i,
                direction=sig,
                entry=entry,
                expiry_index=j,
                exit=exit_price,
                result=result,
                pnl=pnl,
                balance=balance,
                time=series.bars[i].time,
            )
        )
        open_until = j

    return BacktestResult(
        trades=trades,
        payout=payout,
        stake=stake,
        start_balance=start_balance,
        tie_policy=tie_policy,
        name=name or series.name,
    )


def format_report(result: BacktestResult) -> str:
    """成績指標を読みやすい文字列に整形する。"""
    m = result.metrics()
    edge = m["edge"]
    significant = m["significant"] >= 1.0
    if m["total_pnl"] > 0:
        verdict = (
            "プラス（統計的に有意な優位の可能性）"
            if significant
            else "プラスだが誤差範囲（有意でない＝偶然の可能性大）"
        )
    else:
        verdict = (
            "負け越し（統計的に有意）" if significant else "負け越し（誤差範囲）"
        )
    pf = m["profit_factor"]
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
    lines = [
        f"=== {result.name} ===",
        f"  ペイアウト率        : {result.payout:.2f} 倍   "
        f"(損益分岐勝率 = {m['breakeven_win_rate']*100:.1f}%)",
        f"  取引回数            : {int(m['trades'])} 回 "
        f"(勝 {int(m['wins'])} / 負 {int(m['losses'])} / 引分 {int(m['ties'])})",
        f"  勝率                : {m['win_rate']*100:.1f}%  "
        f"(95%信頼区間 {m['win_rate_ci_low']*100:.1f}〜{m['win_rate_ci_high']*100:.1f}%)",
        f"  損益分岐との差(edge): {edge*100:+.1f} ポイント",
        f"  総損益              : {m['total_pnl']:+,.0f} 円  (ROI {m['roi']*100:+.1f}%)",
        f"  期待値/取引         : {m['expectancy']:+,.1f} 円",
        f"  プロフィットファクタ: {pf_str}",
        f"  最大ドローダウン    : {m['max_drawdown']:,.0f} 円 "
        f"({m['max_drawdown_pct']*100:.1f}%)",
        f"  判定                : {verdict}",
    ]
    return "\n".join(lines)
