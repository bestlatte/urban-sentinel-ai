# 更新 .env 裡的 AWS 臨時憑證，並記錄到期時間。
#
# 背景
# ----
# 工作坊發的是 STS 臨時憑證（ASIA... + SessionToken），**一定會過期**，沒有辦法
# 讓它不過期。能解決的是另外三件事：
#
#   1. 更新要夠快       → 貼上三行、按 Enter，就好
#   2. 不能被過期偷襲   → 一併記錄 AWS_CREDS_EXPIRE_AT，preflight 會在剩 45 分鐘時警告
#   3. 過期不能炸掉 Demo → USE_BEDROCK 保底路徑照樣跑出黃金值（本來就成立）
#
# 用法
# ----
#     powershell -ExecutionPolicy Bypass -File scripts\refresh_aws_creds.ps1
#
# 然後直接把工作坊入口複製的那一段整個貼上（就是長這樣的三行或四行）：
#
#     export AWS_ACCESS_KEY_ID="ASIA..."
#     export AWS_SECRET_ACCESS_KEY="..."
#     export AWS_SESSION_TOKEN="..."
#
# 貼完按 Enter 再按一次 Enter（空行結束輸入）。

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot '.env'

if (-not (Test-Path $envPath)) {
    Write-Output "找不到 $envPath —— 請先 copy .env.example .env"
    exit 1
}

Write-Output "請貼上工作坊入口的憑證區塊（貼完按 Enter，再按一次 Enter 結束）："
Write-Output ""

$lines = @()
while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    if ($line.Trim() -eq '') {
        if ($lines.Count -gt 0) { break }
        continue
    }
    $lines += $line
}

if ($lines.Count -eq 0) {
    Write-Output "沒有輸入任何內容，中止。"
    exit 1
}

# --- 解析（兩種寫法都收：有沒有 export 前綴、有沒有引號都可以）---
$creds = @{}
foreach ($line in $lines) {
    $t = $line.Trim()
    if ($t -match '^\s*export\s+(.+)$') { $t = $Matches[1] }
    if ($t -match '^\s*(AWS_[A-Z_]+)\s*=\s*(.+?)\s*$') {
        $key = $Matches[1]
        $val = $Matches[2].Trim().Trim('"').Trim("'")
        $creds[$key] = $val
    }
}

$required = @('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN')
$missing = $required | Where-Object { -not $creds.ContainsKey($_) }
if ($missing) {
    Write-Output "缺少這些欄位：$($missing -join ', ')"
    Write-Output "請確認貼上的是完整的憑證區塊。"
    exit 1
}

# --- 先驗證憑證真的有效，再寫檔 ---
# 順序很重要：先寫檔再驗證的話，貼錯內容會把原本還能用的憑證蓋掉。
Write-Output ""
Write-Output "驗證憑證中..."
$env:AWS_ACCESS_KEY_ID = $creds['AWS_ACCESS_KEY_ID']
$env:AWS_SECRET_ACCESS_KEY = $creds['AWS_SECRET_ACCESS_KEY']
$env:AWS_SESSION_TOKEN = $creds['AWS_SESSION_TOKEN']

$identity = & aws sts get-caller-identity --output json
if ($LASTEXITCODE -ne 0) {
    Write-Output "憑證驗證失敗，.env 未變更。"
    exit 1
}
$parsed = $identity | ConvertFrom-Json
Write-Output "有效：$($parsed.Arn)"

# --- 到期時間 ---
Write-Output ""
Write-Output "工作坊入口通常會顯示 session 到期時間。"
Write-Output "輸入還剩幾小時（直接按 Enter 用預設 4 小時）："
$hoursInput = [Console]::In.ReadLine()
$hours = 4.0
if (-not [string]::IsNullOrWhiteSpace($hoursInput)) {
    $parsedHours = 0.0
    if ([double]::TryParse($hoursInput.Trim(), [ref]$parsedHours) -and $parsedHours -gt 0) {
        $hours = $parsedHours
    } else {
        Write-Output "無法解析「$hoursInput」，改用預設 4 小時。"
    }
}
$expireAt = (Get-Date).ToUniversalTime().AddHours($hours).ToString("yyyy-MM-ddTHH:mm:ss+00:00")
$creds['AWS_CREDS_EXPIRE_AT'] = $expireAt

# --- 改寫 .env：只動憑證那幾行，其他設定原樣保留 ---
$managed = @('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_CREDS_EXPIRE_AT')
$kept = @()
foreach ($line in (Get-Content $envPath -Encoding UTF8)) {
    $isManaged = $false
    foreach ($k in $managed) {
        if ($line -match "^\s*(export\s+)?$k\s*=") { $isManaged = $true; break }
    }
    if (-not $isManaged) { $kept += $line }
}

# 尾端多餘空行收乾淨，避免每跑一次就多一行
while ($kept.Count -gt 0 -and $kept[-1].Trim() -eq '') {
    $kept = $kept[0..($kept.Count - 2)]
}

$block = @(
    ''
    '# --- 以下由 scripts\refresh_aws_creds.ps1 自動產生，不要手改 ---'
    "export AWS_ACCESS_KEY_ID=`"$($creds['AWS_ACCESS_KEY_ID'])`""
    "export AWS_SECRET_ACCESS_KEY=`"$($creds['AWS_SECRET_ACCESS_KEY'])`""
    "export AWS_SESSION_TOKEN=`"$($creds['AWS_SESSION_TOKEN'])`""
    "AWS_CREDS_EXPIRE_AT=$expireAt"
)

Set-Content -Path $envPath -Value ($kept + $block) -Encoding UTF8

Write-Output ""
Write-Output ".env 已更新。到期時間記為 $expireAt（約 $hours 小時後）。"
Write-Output "驗證：  python scripts\preflight.py"
