"""ブラウザ型業者向けの発注アダプタ(差込口/スタブ)。

【重要・お読みください】
- ブラウザ型業者の多くは、自動売買/ボットによる操作を利用規約(ToS)で禁止しています。
  実弾で自動発注すると、アカウント凍結・出金拒否・法的リスクが生じ得ます。
- 本ファイルは「あなたが自分の口座・自己責任で実装するための空の差込口」です。
  Claude 側では、検知回避・不正アクセス・規約回避のための実装は行いません。
- まずは backtest と PaperBroker で手法の妥当性を確認することを強く推奨します。

有効化の手順(利用者が自分で行う):
  1) 対象業者の規約を確認し、自動化が許可されているか(またはデモ口座か)を確認する。
  2) 可能なら業者の *公式 API* を使う(最も安全)。
  3) 公式 API が無くブラウザ操作が必要な場合のみ、Playwright 等で
     `_do_place` を実装する。セレクタ等は各自の環境に合わせる。
"""

from __future__ import annotations

from typing import Optional

from ..core.models import Trade
from .broker import Broker, Order


class BrowserBrokerAdapter(Broker):
    """ブラウザ操作(または公式API)で実弾発注するためのアダプタ雛形。

    既定では *無効* で、place() は明示的な有効化なしに NotImplementedError を送出する。
    """

    def __init__(self, enabled: bool = False, dry_run: bool = True):
        self.enabled = enabled
        # dry_run=True の間は、実際のクリック/送信は行わずログのみ。
        self.dry_run = dry_run

    def place(self, order: Order) -> Trade:
        if not self.enabled:
            raise NotImplementedError(
                "BrowserBrokerAdapter は未実装/無効です。実弾接続は利用者が"
                "規約と自己責任を確認のうえ _do_place() を実装し、enabled=True に"
                "してください。まずは PaperBroker での検証を推奨します。"
            )
        return self._do_place(order)

    def settle(self, trade: Trade, exit_price: float, settle_time: int) -> Trade:
        # バイナリーは満期で自動決済されるのが通常。結果取得の実装も利用者側。
        trade.settle(exit_price, settle_time)
        return trade

    # ---- 利用者が実装する部分 --------------------------------------
    def _do_place(self, order: Order) -> Trade:  # pragma: no cover - 雛形
        """ここに Playwright 等での発注処理を実装する(利用者責任)。

        例(擬似コード):
            page.goto(BROKER_URL)
            page.fill(AMOUNT_SELECTOR, str(order.stake))
            if order.direction == Direction.CALL:
                page.click(CALL_BUTTON)
            else:
                page.click(PUT_BUTTON)
        """
        raise NotImplementedError("_do_place を実装してください(利用者責任)。")
