#!/bin/bash
# ContestTrade 远程运行脚本
# 用法：从 Cursor 手机端或定时任务直接执行
#   bash scripts/run_remote.sh [CN-Stock|US-Stock]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MARKET="${1:-CN-Stock}"

cd "$REPO_DIR"

# 激活 conda 环境
source /Users/jiangyueheng/miniconda3/etc/profile.d/conda.sh
conda activate contesttrade

echo "🚀 启动 ContestTrade 远程分析 | 市场: $MARKET | 时间: $(date '+%Y-%m-%d %H:%M:%S')"

# 非交互式运行，使用当前时间
python -m cli.main run --market "$MARKET" --now

echo "✅ 分析完成"
echo "📄 报告位置: $REPO_DIR/contest_trade/agents_workspace/results/"
