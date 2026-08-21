#!/usr/bin/env bash
# 中断→再開ヘルパー。トークン制限やコンテナ再生成のあと、これ1発で続きから。
#   bash resume.sh [composite|atr|baseline ...]   (省略時は composite atr)
# やること: 最新をpull → 依存を確保 → 各runを起動(state から自動で続きから)。
set -uo pipefail
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"

RUNS=("$@"); [ ${#RUNS[@]} -eq 0 ] && RUNS=(composite atr)

echo "[resume] pull 最新 state..."
git -C "$ROOT" pull --rebase --autostash origin HEAD 2>&1 | tail -2 || true
python3 -c "import pandas,numpy" 2>/dev/null || pip3 install -q pandas numpy

for run in "${RUNS[@]}"; do
  echo "[resume] === $run ==="
  python3 -u runner.py "$run"
done
echo "[resume] 全 run 完了。results/survivors_*.json を確認。"
