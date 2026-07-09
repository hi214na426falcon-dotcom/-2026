"""資金管理（マネーマネジメント）ロジック。

このプロジェクトの方針を守るための「賭け金の決め方」を、検証可能な形で実装する。

方針:
- 基本は 1 回 ``base_stake``（既定 1,000 円）の固定額（フラットベット）。
- **3 連勝すると「ボーナスステージ」に入り、逆マーチンゲール**（アンチマーチンゲール
  ＝勝った直後だけ次を増やす）で、勝ち分（ハウスマネー）を伸ばしにいく。
- **負けたら即座に ``base_stake`` に戻り、ボーナスステージを抜ける。**

【絶対に守る制約（MASTER_PROMPT より）】
- 通常のマーチンゲール（負けたら倍賭け）は **禁止**。このモジュールは増額を
  「勝った直後」だけに限定するため、負けを取り返すために賭け金を上げることは
  構造的に起こらない。
- ボーナスステージの増額は上限（``bonus_ladder`` の最後の値）で頭打ちになる。
  1 回の負けで失う額は「その時点の賭け金」だけで、青天井にはならない。

UI 表示について:
- ひなの要望どおり「賭け金の具体額」は前面に出さなくてよい設計にしてある。
  オーバーレイ側は ``bonus_active`` / ``bonus_level`` だけを見れば
  「ボーナスステージ演出」を出せる（金額は非表示にできる）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

WIN = "win"
LOSS = "loss"
TIE = "tie"  # 引き分け（返金）は連勝を途切れさせない中立イベントとして扱う


@dataclass
class MoneyManager:
    """連勝に応じてボーナスステージ／逆マーチンを管理する状態機械。

    使い方:
        mm = MoneyManager()
        mm.next_stake          # これから張る額（既定 1000）
        mm.record("win")       # 結果を記録
        mm.bonus_active        # ボーナスステージ中か（3連勝以上）
        mm.bonus_level         # ボーナス内のレベル（0=通常, 1..=段階）
    """

    base_stake: float = 1000.0
    bonus_threshold: int = 3  # 何連勝でボーナスステージに入るか
    # ボーナスステージ中の賭け金倍率（base_stake に対する倍率）。
    # index = bonus_level - 1。最後の値で頭打ち（青天井防止）。
    # 逆マーチン＝勝つほど少しずつ増やす。負けたら即リセット。
    bonus_ladder: List[float] = field(default_factory=lambda: [1.5, 2.0, 3.0])
    # ボーナスの最高段で勝ったら利益を確定して通常に戻る（利食い）か。
    cash_out_at_top: bool = True

    streak: int = 0  # 現在の連勝数
    _bonus_level: int = 0  # 0=通常, 1..=ボーナス段
    history: List[str] = field(default_factory=list)

    # --- 状態の参照 -------------------------------------------------------
    @property
    def bonus_active(self) -> bool:
        """ボーナスステージ中か（= bonus_threshold 連勝以上を達成中）。"""
        return self._bonus_level > 0

    @property
    def bonus_level(self) -> int:
        """ボーナス段（0=通常, 1..=逆マーチンの段）。"""
        return self._bonus_level

    @property
    def next_stake(self) -> float:
        """これから張るべき賭け金。通常は base_stake、ボーナス中は逆マーチン。"""
        if self._bonus_level <= 0:
            return self.base_stake
        idx = min(self._bonus_level, len(self.bonus_ladder)) - 1
        return self.base_stake * self.bonus_ladder[idx]

    @property
    def at_bonus_top(self) -> bool:
        """逆マーチンが最高段に達しているか。"""
        return self._bonus_level >= len(self.bonus_ladder)

    # --- 状態の更新 -------------------------------------------------------
    def record(self, result: str) -> None:
        """1 回のトレード結果を記録して状態を更新する。

        result: "win" / "loss" / "tie"
        """
        if result not in (WIN, LOSS, TIE):
            raise ValueError(f"result は win/loss/tie のいずれか: {result!r}")
        self.history.append(result)

        if result == TIE:
            # 引き分け（返金）は連勝を伸ばしも切りもしない中立扱い。
            return

        if result == LOSS:
            # 負けたら即リセット（逆マーチンなので賭け金は上げない）。
            self.streak = 0
            self._bonus_level = 0
            return

        # result == WIN
        self.streak += 1
        if self.streak >= self.bonus_threshold:
            if self.bonus_active and self.at_bonus_top and self.cash_out_at_top:
                # 最高段で勝った → 利食いして通常に戻る（連勝カウントは継続）。
                self._bonus_level = 0
            else:
                # ボーナス段を 1 つ進める（未突入なら 1 段目へ）。
                self._bonus_level = min(self._bonus_level + 1, len(self.bonus_ladder))

    def reset(self) -> None:
        """連勝・ボーナス状態を初期化（履歴は保持）。"""
        self.streak = 0
        self._bonus_level = 0

    def snapshot(self) -> Dict[str, object]:
        """オーバーレイ配信用の状態スナップショット。"""
        return {
            "streak": self.streak,
            "bonus_active": self.bonus_active,
            "bonus_level": self.bonus_level,
            "bonus_threshold": self.bonus_threshold,
            "at_bonus_top": self.at_bonus_top,
            # 金額は既定で表示しない運用のため補助情報として同梱（UI 側で任意表示）。
            "base_stake": self.base_stake,
            "next_stake": self.next_stake,
            "trades": len(self.history),
        }


@dataclass
class MMResult:
    """資金管理シミュレーションの結果。"""

    end_balance: float
    total_pnl: float
    max_drawdown: float
    max_drawdown_pct: float
    max_streak: int
    bonus_entries: int
    balances: List[float]


def simulate_money_management(
    results: List[str],
    payout: float = 1.90,
    start_balance: float = 100000.0,
    mm: Optional[MoneyManager] = None,
) -> MMResult:
    """勝敗列に対して、この資金管理ルールで資金曲線を再現する。

    results: "win"/"loss"/"tie" の列（バックテストや実トレード記録から）。
    payout : 総払い戻し倍率（例 1.90 = 90% ペイアウト → 純利益 0.90 倍）。

    【正直な注意】これは資金管理の効果を可視化するための道具であり、
    勝率そのものを上げるものではない。逆マーチンは「勝っている時に伸ばす」
    ための工夫で、負け越す戦略に使えば資金は減る（勝率が損益分岐を上回って
    いることが大前提）。
    """
    if mm is None:
        mm = MoneyManager()
    balance = start_balance
    balances = [balance]
    peak = balance
    max_dd = 0.0
    max_dd_pct = 0.0
    max_streak = 0
    bonus_entries = 0
    was_bonus = False

    for r in results:
        stake = mm.next_stake
        if r == WIN:
            balance += stake * (payout - 1.0)
        elif r == LOSS:
            balance -= stake
        # tie は損益 0

        mm.record(r)
        max_streak = max(max_streak, mm.streak)
        if mm.bonus_active and not was_bonus:
            bonus_entries += 1
        was_bonus = mm.bonus_active

        balances.append(balance)
        if balance > peak:
            peak = balance
        dd = peak - balance
        if dd > max_dd:
            max_dd = dd
        if peak > 0 and dd / peak > max_dd_pct:
            max_dd_pct = dd / peak

    return MMResult(
        end_balance=balance,
        total_pnl=balance - start_balance,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        max_streak=max_streak,
        bonus_entries=bonus_entries,
        balances=balances,
    )
