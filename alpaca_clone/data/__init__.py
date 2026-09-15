"""データフィード: 過去データ(CSV)と検証用の合成データ。"""

from .feed import CandleFeed, CSVFeed, SyntheticFeed, load_candles_csv

__all__ = ["CandleFeed", "CSVFeed", "SyntheticFeed", "load_candles_csv"]
