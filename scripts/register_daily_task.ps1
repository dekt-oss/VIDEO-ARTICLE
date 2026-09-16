# daily_local.ps1 을 Windows 작업 스케줄러에 등록한다. **한 번만** 실행하면 된다.
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1
#
# 등록하면 매일 09:10 에 수집·채점이 자동으로 돈다. 관리자 권한은 필요 없다
# (현재 사용자 계정의 작업으로 등록한다).
#
# ★ PC 가 꺼져 있으면 그 시각에는 못 돈다. 그래서 StartWhenAvailable 을 켠다 —
#   놓친 작업은 PC 를 켠 뒤 최대한 빨리 한 번 실행된다.
# ★ 배터리로 돌아가는 노트북에서도 실행되게 DontStopIfGoingOnBatteries 를 켠다.
#
# 해제:  Unregister-ScheduledTask -TaskName "video-article-daily" -Confirm:$false
# 확인:  Get-ScheduledTask -TaskName "video-article-daily"
# 즉시 한 번 실행: Start-ScheduledTask -TaskName "video-article-daily"

$ErrorActionPreference = "Stop"

$TaskName = "video-article-daily"
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "scripts\daily_local.ps1"

if (-not (Test-Path $Script)) { throw "daily_local.ps1 을 찾을 수 없습니다: $Script" }

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $Script) `
    -WorkingDirectory $Root

# 09:10 — 정각을 피한다(다른 예약과 겹치지 않게).
$trigger = New-ScheduledTaskTrigger -Daily -At "09:10"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Output "기존 작업을 덮어씁니다: $TaskName"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "video-article 논문 수집·5축 채점 (GitHub Actions 한도 소진 대비 로컬 실행)" | Out-Null

Write-Output ""
Write-Output "등록 완료: $TaskName"
Write-Output "  실행 시각 : 매일 09:10 (PC 가 꺼져 있었으면 켠 뒤 곧 한 번 실행)"
Write-Output "  스크립트  : $Script"
Write-Output "  로그      : $Root\logs\daily_YYYY-MM-DD.log"
Write-Output ""
Write-Output "지금 바로 한 번 돌려보려면:"
Write-Output "  Start-ScheduledTask -TaskName $TaskName"
