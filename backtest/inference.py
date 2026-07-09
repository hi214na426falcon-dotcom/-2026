"""合格戦略から「今まさにシグナルが出ているか」を推論する。

predict_server はこのモジュールを使い、``approved_strategy.json`` の戦略を
直近の 1 分足に適用して、現在バーに方向シグナルが立っているかを判定する。

原則（先読み防止）:
- 判定は「直近バーまでの終値」だけで行う（戦略・指標はそもそも未来を見ない）。
- 現在バーにシグナルが無ければ ``direction=None``（＝「シグナル待機中」）。
  無理に方向を出さない。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .data import Bar, Series
from .strategies import STRATEGIES


def infer_direction(
    approved: Dict,
    closes: Sequence[float],
    times: Optional[Sequence[Optional[str]]] = None,
) -> Dict[str, object]:
    """合格戦略を直近終値列に適用し、現在バーの方向を返す。

    戻り値: {"direction": "UP"|"DOWN"|None, "confidence": float|None, "status": str}
    """
    strat = approved.get("strategy")
    if strat not in STRATEGIES:
        return {"direction": None, "confidence": None,
                "status": f"未知の戦略: {strat}"}
    if not closes or len(closes) < 30:
        return {"direction": None, "confidence": None,
                "status": "バー不足（推論には直近30本以上が必要）"}

    params = dict(approved.get("params") or {})
    bars: List[Bar] = []
    for i, c in enumerate(closes):
        t = times[i] if times is not None and i < len(times) else None
        bars.append(Bar(time=t, open=c, high=c, low=c, close=float(c)))
    series = Series(bars, name=approved.get("pair", "live"))

    fn = STRATEGIES[strat]
    try:
        signals = fn(series, seed=0) if strat == "random" else fn(series, **params)
    except TypeError:
        # params が戦略シグネチャに合わない場合は既定引数で
        signals = fn(series)

    last = signals[-1] if signals else None
    if last is None:
        return {"direction": None, "confidence": None, "status": "シグナル待機中"}

    # 信頼度 = 合格時の OOS 勝率（＝この型が過去に勝った割合。創作しない）
    oos = approved.get("oos") or {}
    conf = oos.get("win_rate")
    return {
        "direction": last,
        "confidence": float(conf) if isinstance(conf, (int, float)) else None,
        "status": "シグナル発生",
    }
