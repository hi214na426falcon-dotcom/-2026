#!/usr/bin/env python3
"""通貨ペア・スカウトを実行して schedule.json を生成する CLI。

Fable5(オーケストレーター)→Opus4.8(ワーカー) のマルチエージェントで
「どの時間帯にどの通貨ペアを狙うか」を調べ、オーバーレイが読む
``overlay/server/schedule.json`` に書き出す。API 鍵が無ければ自動でオフライン計算。

使用例:
    # 既定(合成データ・全ペア)でスケジュール生成（オフラインでも動く）
    python3 run_scout.py

    # LLM を使わず決定論のみ
    python3 run_scout.py --no-llm

    # 実データ(data/m1)＋逆張り系＋満期3分＋ペイアウト90%
    python3 run_scout.py --strategy bollinger --expiry 3 --payout 1.90 --data-dir data/m1

    # デモ用に平均回帰の合成データ（弱いエッジが出る。実弾の根拠にはしない）
    python3 run_scout.py --process meanrevert
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from agents.pair_stats import DEFAULT_PAIRS
from agents.schedule_schema import current_slot, validate_schedule
from agents.scout import run_scout


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="通貨ペア・スカウト（Fable5→Opus4.8）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--pairs", nargs="*", default=DEFAULT_PAIRS, help="調査する通貨ペア")
    p.add_argument("--strategy", default="bollinger", help="戦略名（既定 bollinger）")
    p.add_argument("--expiry", type=int, default=3, help="満期(分)。1分足N本先で判定（既定3）")
    p.add_argument("--payout", type=float, default=1.90, help="ペイアウト総倍率（既定1.90=90%）")
    p.add_argument("--data-dir", default="data/m1", help="実データCSV置き場（無ければ合成）")
    p.add_argument(
        "--process",
        choices=["randomwalk", "meanrevert", "trend"],
        default="randomwalk",
        help="合成データの生成過程（実データがある場合は無視）",
    )
    p.add_argument("--no-llm", action="store_true", help="LLMを使わず決定論のみで生成")
    p.add_argument(
        "--out",
        default=os.path.join("overlay", "server", "schedule.json"),
        help="出力先（既定 overlay/server/schedule.json）",
    )
    args = p.parse_args(argv)

    print(f"[スカウト] pairs={args.pairs} strategy={args.strategy} "
          f"expiry={args.expiry}分 payout={args.payout} llm={'off' if args.no_llm else 'on'}")
    sched = run_scout(
        pairs=args.pairs,
        strategy=args.strategy,
        expiry_min=args.expiry,
        payout=args.payout,
        data_dir=args.data_dir,
        process=args.process,
        use_llm=not args.no_llm,
    )

    problems = validate_schedule(sched)
    if problems:
        print("[警告] スケジュール検証で問題:", file=sys.stderr)
        for pr in problems:
            print("  -", pr, file=sys.stderr)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(sched, f, ensure_ascii=False, indent=2)

    print(f"[スカウト] mode={sched['mode']}（{sched['orchestrator_model']}→{sched['worker_model']}）")
    print(f"[スカウト] 書き出し: {args.out}")
    print("\n=== 時間帯別 推奨ペア（JST）===")
    for slot in sched["slots"]:
        wr = slot.get("expected_win_rate")
        wr_s = f"{wr*100:.1f}%" if wr is not None else "―"
        print(f"  {slot['window']:>12}  → {slot.get('recommended_pair') or '―':<8} "
              f"想定勝率 {wr_s:<7} 信頼度 {slot.get('confidence','')}"
              f"  GO={'○' if slot.get('go') else '×'}")
    cur = current_slot(sched)
    if cur:
        print(f"\n[今の時間帯] {cur['window']} → {cur.get('recommended_pair') or '―'}")
    print("\n" + sched["disclaimer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
