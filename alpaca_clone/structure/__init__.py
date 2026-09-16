"""相場構造の検出(プライスアクション)。

アルパカ式の中核= 価格構造。ここでは OHLC から因果的に(未来足を見ずに)
トレンド/スイング/サポレジ/トレンドライン/ベースライン/MTF/ノイズを検出する。
"""

from .detectors import StructureView, StructureSnapshot, resample_htf

__all__ = ["StructureView", "StructureSnapshot", "resample_htf"]
