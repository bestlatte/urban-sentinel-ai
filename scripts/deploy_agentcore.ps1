# 一個指令完成 AgentCore 部署：前置檢查 → 同步程式 → 部署 → 驗黃金值。
#
# 設計目標：**部署失敗必須在 10 秒內知道原因，而不是跑到一半才炸。**
#
# 實測踩過的兩個坑，這裡都自動處理：
#
#   1. `uv` 不在 PATH → CDK synth 失敗，但 CLI 只說 "Subprocess exited with
#      error 1"，完全沒提 uv。本腳本會自己找到 uv 並補進這個行程的 PATH，
#      所以就算沒跑過 fix_uv_path.ps1 也能部署成功。
#   2. 憑證過期 → deploy 跑到一半才 InvalidClientTokenId。preflight 先擋。
#
# 用法
# ----
#     powershell -ExecutionPolicy Bypass -File scripts\deploy_agentcore.ps1
#     powershell -ExecutionPolicy Bypass -File scripts\deploy_agentcore.ps1 -SkipVerify
#     powershell -ExecutionPolicy Bypass -File scripts\deploy_agentcore.ps1 -VerifyOnly

param(
    [switch]$SkipVerify,   # 部署後不跑 agentcore invoke 驗證（省約 60 秒）
    [switch]$VerifyOnly    # 不部署，只驗證雲端目前的版本
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$agentcoreProject = Join-Path $env:USERPROFILE 'urban-sentinel-agentcore\UrbanSentinelOrch'

function Write-Step($msg) {
    Write-Output ""
    Write-Output "=== $msg ==="
}

# ---------------------------------------------------------------------------
# 0. 把 .env 載進這個 PowerShell 行程
# ---------------------------------------------------------------------------
# 為什麼要在這裡做：agentcore CLI 是獨立行程，它讀的是**環境變數**，不會去讀
# .env（src/env.py 只對 Python 端生效）。少了這步，deploy 會用不到憑證。
Write-Step "載入 .env"
$envPath = Join-Path $repoRoot '.env'
if (-not (Test-Path $envPath)) {
    Write-Output "找不到 $envPath"
    exit 1
}
$loaded = 0
foreach ($line in (Get-Content $envPath -Encoding UTF8)) {
    $t = $line.Trim()
    if ($t -eq '' -or $t.StartsWith('#')) { continue }
    if ($t -match '^\s*export\s+(.+)$') { $t = $Matches[1] }
    if ($t -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
        $k = $Matches[1]
        $v = $Matches[2].Trim().Trim('"').Trim("'")
        Set-Item -Path "env:$k" -Value $v
        $loaded++
    }
}
Write-Output "已載入 $loaded 個變數"

# ---------------------------------------------------------------------------
# 1. uv：自我修復
# ---------------------------------------------------------------------------
Write-Step "檢查 uv"
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCmd) {
    Write-Output "uv 已在 PATH：$($uvCmd.Source)"
} else {
    $uvBin = $null
    try { $uvBin = & python -c "import uv; print(uv.find_uv_bin())" 2>$null } catch { }

    if ([string]::IsNullOrWhiteSpace($uvBin) -or -not (Test-Path $uvBin)) {
        Write-Output "找不到 uv，CDK synth 一定會失敗。"
        Write-Output "請先執行：  pip install uv"
        exit 1
    }
    $uvDir = Split-Path -Parent $uvBin
    $env:PATH = "$uvDir;$env:PATH"
    Write-Output "uv 不在 PATH，已為本次部署補上：$uvDir"
    Write-Output "（想永久解決： powershell -File scripts\fix_uv_path.ps1）"
}

# ---------------------------------------------------------------------------
# 2. 前置檢查
# ---------------------------------------------------------------------------
Write-Step "前置檢查"
Push-Location $repoRoot
try {
    & python scripts\preflight.py --deploy --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Output ""
        Write-Output "前置檢查未通過，中止部署。"
        exit 1
    }
    Write-Output "全部通過"
} finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# 3. 同步程式碼進 codeLocation
# ---------------------------------------------------------------------------
if (-not $VerifyOnly) {
    Write-Step "同步 src/ data/ prompts/ 進部署包"
    Push-Location $repoRoot
    try {
        & python scripts\build_agentcore_package.py
        if ($LASTEXITCODE -ne 0) { Write-Output "打包失敗，中止。"; exit 1 }
    } finally {
        Pop-Location
    }

    # -----------------------------------------------------------------------
    # 4. 部署
    # -----------------------------------------------------------------------
    Write-Step "agentcore deploy"
    Push-Location $agentcoreProject
    try {
        # -y 是必要的：沒有它 CLI 會要求互動式終端機，在腳本裡直接失敗
        # （"Error: This command requires an interactive terminal."）
        & agentcore deploy -y
        if ($LASTEXITCODE -ne 0) { Write-Output "部署失敗。"; exit 1 }
    } finally {
        Pop-Location
    }
}

# ---------------------------------------------------------------------------
# 5. 驗證雲端黃金值
# ---------------------------------------------------------------------------
if ($SkipVerify) {
    Write-Output ""
    Write-Output "已略過雲端驗證（-SkipVerify）。"
    exit 0
}

Write-Step "驗證雲端黃金值（agentcore invoke，約 45 秒）"
Push-Location $agentcoreProject
try {
    # 刻意**不寫** `2>&1`。Windows PowerShell 5.1 把 native 指令的 stderr 每一行
    # 包成 ErrorRecord，在 $ErrorActionPreference='Stop' 之下會直接拋
    # NativeCommandError 中止腳本——即使 agentcore 本身回傳 0 也一樣。
    # agentcore 的進度動畫走 stderr、JSON 結果走 stdout，所以只收 stdout 就對了。
    $raw = (& agentcore invoke 'TPE_2026_ACC_001') | Out-String
} finally {
    Pop-Location
}

$start = $raw.IndexOf('{')
$end = $raw.LastIndexOf('}')
if ($start -lt 0 -or $end -le $start) {
    Write-Output "無法從回應中找到 JSON，原始輸出："
    Write-Output $raw
    exit 1
}

$result = $raw.Substring($start, $end - $start + 1) | ConvertFrom-Json
$d = $result.decision_result

$checks = @(
    @{ Name = '主要路線'; Expected = 'RD_TPE_004';        Actual = $d.routes.primary.segment_id }
    @{ Name = '次要路線'; Expected = 'RD_TPE_005';        Actual = $d.routes.secondary.segment_id }
    @{ Name = 'ETE';      Expected = 90;                  Actual = $d.ete.minutes }
    @{ Name = '恢復時間'; Expected = '2026-05-20 23:40';  Actual = $d.ete.recovery_at }
)

Write-Output ""
$failed = $false
foreach ($c in $checks) {
    if ("$($c.Actual)" -eq "$($c.Expected)") {
        Write-Output ("  [ok]   {0,-8} {1}" -f $c.Name, $c.Actual)
    } else {
        Write-Output ("  [FAIL] {0,-8} 期望 {1}，實得 {2}" -f $c.Name, $c.Expected, $c.Actual)
        $failed = $true
    }
}

$langs = @()
foreach ($k in 'zh', 'en', 'ja', 'ko') {
    if ($d.notifications.$k) { $langs += $k }
}
Write-Output ("  [info] 簡訊語言 {0}" -f ($langs -join '/'))
Write-Output ("  [info] degraded {0}" -f $(if ($d.degraded.Count -eq 0) { '(無)' } else { $d.degraded -join ', ' }))
Write-Output ("  [info] 耗時     {0} ms" -f $d.duration_ms)

Write-Output ""
if ($failed) {
    Write-Output "雲端黃金值驗證失敗。"
    exit 1
}
Write-Output "雲端黃金值全數通過，部署完成。"
