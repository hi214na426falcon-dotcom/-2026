"""バイナリーオプション（High/Low・固定時間 Up/Down）バックテスト用パッケージ。

依存: Python 標準ライブラリのみ（numpy / pandas 不要）。

主要モジュール:
- data       : 価格データの生成・CSV 読み込み
- indicators : テクニカル指標（SMA / EMA / RSI / MACD / Bollinger）
- strategies : シグナル生成戦略
- engine     : バックテスト本体と成績指標
- optimize   : 学習/検証分割による「過剰最適化」の実証
"""

from .data import Bar, Series, load_csv, generate_synthetic
from .engine import Trade, BacktestResult, run_backtest, format_report
from .strategies import STRATEGIES

__all__ = [
    "Bar",
    "Series",
    "load_csv",
    "generate_synthetic",
    "Trade",
    "BacktestResult",
    "run_backtest",
    "format_report",
    "STRATEGIES",
]
