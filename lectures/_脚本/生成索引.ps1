# 生成讲座总索引（包装器）
# 真正的实现在同目录的 生成索引.py —— 本脚本只负责找到 python 并调用它。
# 用法：powershell -File "…\大学\lectures\_脚本\生成索引.ps1"

$ErrorActionPreference = 'Stop'

$py = Join-Path $PSScriptRoot '生成索引.py'
if (-not (Test-Path -LiteralPath $py)) {
    throw "找不到 生成索引.py：$py"
}

$python = $null
foreach ($cand in @('python', 'python3', 'py')) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source; break }
}

if (-not $python) {
    throw "未找到 python。请安装 Python 或把它加入 PATH；也可以手动运行：python `"$py`""
}

& $python $py
exit $LASTEXITCODE
