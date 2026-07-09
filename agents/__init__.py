"""通貨ペア・スカウト（マルチエージェント）パッケージ。

役割:
- 「どの時間帯にどの通貨ペアが有利か」を、バックテスト統計に基づいて調べ、
  オーバーレイに配信する ``schedule.json`` を生成する。
- 上位オーケストレーター（Claude Fable 5）が調査計画・指示を出し、
  各時間帯の精査を下位ワーカー（Claude Opus 4.8）に委譲する
  マルチエージェント構成。API 鍵が無い環境では決定論的な統計計算に自動フォールバックする。

依存:
- ``pair_stats`` / ``schedule_schema`` は Python 標準ライブラリ + backtest パッケージのみ。
- ``scout`` の LLM 経路のみ ``anthropic`` SDK を遅延 import する（未導入でも動く）。
"""

from .schedule_schema import build_schedule, current_slot, validate_schedule

__all__ = ["build_schedule", "current_slot", "validate_schedule"]
