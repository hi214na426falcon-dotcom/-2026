"""binbot — バイナリーオプション バックテスト & ペーパートレード基盤.

正直さに関する注意 (READ ME):
  * 本パッケージは「確実に勝てる」自動売買を提供しません。そのようなものは
    原理的に存在しません。提供するのは、戦略を *正直に* 検証するための道具です。
  * バックテストの勝率は過去データ上の数字であり、将来を保証しません。
  * 実ブローカーへの発注はデフォルトで無効です (binbot.broker.LiveBroker は
    意図的に未実装)。デモ/ペーパートレードのみ動作します。

詳細は README.md を参照してください。
"""

__version__ = "0.1.0"

from . import data, indicators, strategy, metrics, backtest  # noqa: F401

__all__ = ["data", "indicators", "strategy", "metrics", "backtest"]
