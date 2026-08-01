# 測試事件注入 + 解除流程

$headers = @{ "Content-Type" = "application/json" }

# 1. 注入事件
Write-Host "=== Step 1: 注入事件 TPE_2026_ACC_001 ===" -ForegroundColor Cyan
$body = '{"event_id": "TPE_2026_ACC_001"}'
$r = Invoke-RestMethod -Uri "http://localhost:8000/api/incidents/evaluate" -Method POST -Headers $headers -Body $body
Write-Host "status: $($r.status)"
Write-Host "event_id: $($r.payload.incident.event_id)"
Write-Host "level: $($r.payload.level)"
Write-Host "primary_route: $($r.payload.routes.primary.name)"
Write-Host ""

# 2. 檢查 active_incidents
Write-Host "=== Step 2: 檢查活躍事件 ===" -ForegroundColor Cyan
$r2 = Invoke-RestMethod -Uri "http://localhost:8000/api/incidents/history" -Method GET
Write-Host "活躍事件數: $($r2.incidents.Count)"
foreach ($inc in $r2.incidents) {
    Write-Host "  - $($inc.event_id): $($inc.incident.status)"
}
Write-Host ""

# 3. 解除事件
Write-Host "=== Step 3: 解除事件 ===" -ForegroundColor Cyan
$body3 = '{"status": "Resolved"}'
$r3 = Invoke-RestMethod -Uri "http://localhost:8000/api/incidents/TPE_2026_ACC_001/resolve" -Method POST -Headers $headers -Body $body3
Write-Host "status: $($r3.status)"
Write-Host "message: $($r3.message)"
Write-Host "freed_segment: $($r3.freed_segment)"
Write-Host "affected_incidents: $($r3.affected_incidents -join ', ')"
Write-Host ""

# 4. 再次檢查 active_incidents
Write-Host "=== Step 4: 解除後檢查活躍事件 ===" -ForegroundColor Cyan
$r4 = Invoke-RestMethod -Uri "http://localhost:8000/api/incidents/history" -Method GET
Write-Host "活躍事件數: $($r4.incidents.Count)"
foreach ($inc in $r4.incidents) {
    Write-Host "  - $($inc.event_id): $($inc.incident.status)"
}

Write-Host ""
Write-Host "=== 測試完成 ===" -ForegroundColor Green
