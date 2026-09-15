"""発注アダプタ。

- PaperBroker: 仮想口座で決済まで模擬(実弾なし)。
- BrowserBrokerAdapter: ブラウザ型業者向けの *差込口(スタブ)*。
  実装は利用者が自身の口座・自己責任で行う前提。検知回避等は実装しない。
"""

from .broker import Broker, PaperBroker, Order
from .browser_adapter import BrowserBrokerAdapter

__all__ = ["Broker", "PaperBroker", "Order", "BrowserBrokerAdapter"]
