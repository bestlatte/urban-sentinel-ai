# 把 uv.exe 所在目錄永久加進 Windows 的 user PATH。
#
# 為什麼需要這個
# --------------
# `pip install uv` 會把 uv.exe 放進 %APPDATA%\Python\Python3xx\Scripts，
# 而那個目錄**預設不在** Windows 的 user PATH 上。結果是 `python -m uv` 可以跑、
# `uv --version` 卻是 command not found。
#
# AgentCore 的 CDK synth 是用 `uv` 這個名字去 spawn 子行程的，所以它會失敗，
# 而且 CLI 只吐這一行：
#
#     CDK synth failed: node dist/bin/cdk.js: Subprocess exited with error 1
#
# 完全沒提到 uv。要跑 `node dist/bin/cdk.js` 才看得到真正的訊息
# 「uv is required. Install uv from ... and ensure it is on your PATH.」
#
# 用法
# ----
#     powershell -ExecutionPolicy Bypass -File scripts\fix_uv_path.ps1
#
# 執行後**新開一個終端機**才會生效（PATH 是行程啟動時讀的）。
# 本腳本同時也會設定當前 session 的 PATH，所以當下這個視窗可以直接繼續用。

$ErrorActionPreference = 'Stop'

# --- 找出 uv.exe ---
$uvBin = $null
$onPath = Get-Command uv -ErrorAction SilentlyContinue
if ($onPath) {
    Write-Output "uv 已經在 PATH 上：$($onPath.Source)"
    Write-Output "不需要做任何事。"
    exit 0
}

try {
    $uvBin = & python -c "import uv; print(uv.find_uv_bin())" 2>$null
} catch {
    $uvBin = $null
}

if ([string]::IsNullOrWhiteSpace($uvBin) -or -not (Test-Path $uvBin)) {
    Write-Output "找不到 uv.exe。"
    Write-Output "請先安裝：  pip install uv"
    Write-Output "或用官方安裝器（會自動處理 PATH）："
    Write-Output '  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"'
    exit 1
}

$uvDir = Split-Path -Parent $uvBin
Write-Output "找到 uv：$uvBin"
Write-Output "目錄    ：$uvDir"

# --- 加進 user PATH（不是 machine PATH，不需要系統管理員權限）---
$userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
if ($null -eq $userPath) { $userPath = '' }

$already = ($userPath -split ';' | Where-Object { $_.TrimEnd('\') -ieq $uvDir.TrimEnd('\') })
if ($already) {
    Write-Output "user PATH 裡已經有這個目錄了，只更新當前 session。"
} else {
    $newPath = if ($userPath.TrimEnd(';') -eq '') { $uvDir } else { $userPath.TrimEnd(';') + ';' + $uvDir }

    # 刻意用 .NET API 而不是 setx：setx 有 1024 字元上限，超過會**靜默截斷 PATH**，
    # 那是會弄壞整台機器環境的那種失敗。SetEnvironmentVariable 沒有這個限制。
    [Environment]::SetEnvironmentVariable('PATH', $newPath, 'User')
    Write-Output "已加入 user PATH（原長度 $($userPath.Length) → 新長度 $($newPath.Length)）。"
}

# 當前 session 也補上，這個視窗不用重開
$env:PATH = "$uvDir;$env:PATH"

Write-Output ""
& uv --version
Write-Output ""
Write-Output "完成。其他已開著的終端機需要重開才會看到這個 PATH。"
