# 非交互式远程/定时运行 ContestTrade（适用于 Cursor Mobile 等场景）
$ErrorActionPreference = "Stop"

$condaEnv = "contesttrade"
$repoDir = "C:\Users\jiangyueheng\Downloads\ContestTrade"

# 激活 conda 环境
& conda activate $condaEnv

Set-Location $repoDir

# 使用当前时间、默认 A 股市场，跳过交互式提示
python -m cli.main run --market CN-Stock --now
