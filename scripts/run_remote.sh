#!/usr/bin/env bash
# 非交互式远程/定时运行 ContestTrade（适用于 Cursor Mobile 等场景）
set -e

CONDA_ENV="contesttrade"
REPO_DIR="/Users/jiangyueheng/Downloads/ContestTrade"

# 激活 conda 环境
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV"

cd "$REPO_DIR"

# 使用当前时间、默认 A 股市场，跳过交互式提示
python -m cli.main run --market CN-Stock --now
