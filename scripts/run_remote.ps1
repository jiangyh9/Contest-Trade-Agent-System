# ContestTrade 远程运行脚本 (PowerShell / Windows)
# 用法：.\scripts\run_remote.ps1 [CN-Stock|US-Stock]

$Market = if ($args[0]) { $args[0] } else { "CN-Stock" }
$RepoDir = Split-Path -Parent $PSScriptRoot

Set-Location $RepoDir

conda activate contesttrade

Write-Host "🚀 启动 ContestTrade 远程分析 | 市场: $Market | 时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

python -m cli.main run --market $Market --now

Write-Host "✅ 分析完成"
Write-Host "📄 报告位置: $RepoDir\contest_trade\agents_workspace\results\"
