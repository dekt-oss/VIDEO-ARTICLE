# 매일 수집·채점을 로컬에서 돌린다 (Actions 분 0).
#
# ★ 왜: GitHub Actions 무료 한도가 계정 공유라 매달 초에 소진되고, 그 뒤로는 engine.yml
#   크론이 3초 만에 죽는다(2026-08 에 11일, 2026-09 에 9/6 부터 정지). 그동안 논문 수집·
#   채점이 통째로 멈춰 배치가 빈 날이 된다. 이 스크립트가 그 자리를 메운다.
#
# 쓰는 법
#   수동:   powershell -ExecutionPolicy Bypass -File scripts\daily_local.ps1
#   자동:   scripts\register_daily_task.ps1 을 한 번 실행하면 매일 09:10 에 돈다.
#
# 로그는 logs\daily_YYYY-MM-DD.log 에 쌓인다(.gitignore 의 *.log 라 커밋되지 않는다).

$ErrorActionPreference = "Stop"

# 이 스크립트 위치 기준으로 프로젝트 루트를 잡는다(작업 스케줄러가 어디서 부르든 동작하게).
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$LogDir = Join-Path $Root "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("daily_{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Output $line
    Add-Content -Path $LogFile -Value $line -Encoding utf8
}

Write-Log "=== 시작 (로컬 수집·채점) ==="

# 엔진이 .env 를 읽는다(python-dotenv). 없으면 여기서 멈추는 게 낫다 —
# 빈 키로 돌면 "수집 0건"이 성공처럼 보인다.
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Log "!! .env 가 없습니다. 중단합니다."
    exit 1
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
$env:SCORE_LIMIT = "150"
$env:PEER_REVIEWED_ONLY = "true"
$env:MODEL_SCORING = "gemini-2.5-flash"

$failed = $false

foreach ($step in @(
    @{ Name = "collect"; Args = @("-m", "engine.collect") },
    @{ Name = "score";   Args = @("-m", "engine.score") }
)) {
    Write-Log ("--- {0} 시작" -f $step.Name)
    # 2>&1 로 합쳐 로그에 전부 남긴다. 네이티브 exe 라 $LASTEXITCODE 로 판단한다.
    & python $step.Args 2>&1 | ForEach-Object { Add-Content -Path $LogFile -Value $_ -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) {
        Write-Log ("!! {0} 실패 (exit {1}) — 로그: {2}" -f $step.Name, $LASTEXITCODE, $LogFile)
        $failed = $true
        break   # collect 가 실패하면 score 를 돌릴 이유가 없다
    }
    Write-Log ("--- {0} 완료" -f $step.Name)
}

if ($failed) {
    Write-Log "=== 실패로 종료 ==="
    exit 1
}

Write-Log "=== 완료 — 대시보드에서 오늘 배치를 확인하세요 ==="
exit 0
