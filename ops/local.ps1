# 내 PC(로컬 개발) 명령 모음 — Windows PowerShell용. 사용법: .\ops\local.ps1 help
# macOS·Linux·Git Bash는 ops/local.sh. make 없이 Makefile과 같은 명령을 직접 부른다.
# 실행이 막히면(스크립트 실행 정책) 한 번만: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# Makefile이 자동으로 거는 환경값과 같다.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = Join-Path $Root 'src'

function Show-Usage {
    @'
사용법: .\ops\local.ps1 <명령>

설치·점검
  setup                  Python 의존성(uv.lock)과 프론트·HMI npm 패키지 설치
  check                  PR 전 전체 검사 (= make check: ruff·format·pytest·스킬 동기화)
  env-check              내 .env를 .env.example과 비교 (값은 출력 안 함)

보조 서비스 (Docker Desktop)
  db                     PostgreSQL 기동 후 스키마 최신화
  qdrant                 Qdrant 서버 기동 (.env에 QDRANT_URL=http://localhost:6333일 때만 필요)
  ps                     로컬 컨테이너 상태
  logs [서비스]           로컬 컨테이너 로그 따라가기 (postgres|qdrant, 기본 postgres)
  volumes                로컬 볼륨 이름·크기
  down                   보조 서비스 정지 (데이터 볼륨은 유지)

실행 (각각 PowerShell 창 하나씩 켜 둔다)
  api                    백엔드 FastAPI  http://localhost:8000/docs
  front                  프론트(Next.js) http://localhost:3100
  hmi                    HMI(Vite)       http://localhost:5173
  seed                   시연용 계정 만들기
  seed-docs [--replace]  팀 문서 미리 등록·임베딩, 같은 파일은 건너뜀
  reindex-reports        승인 보고서를 지금 컬렉션에 전부 다시 등록
  urls                   로컬 주소 모음

처음 한 번 순서: setup → Copy-Item .env.example .env(값 채우기) → db → seed → seed-docs → api / front / hmi
'@ | Write-Output
}

# 실패하면 그 자리에서 멈춘다(PowerShell 5.1은 &&가 없다).
function Run([string]$Exe, [string[]]$ArgList) {
    & $Exe @ArgList
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Need([string]$Exe) {
    if (-not (Get-Command $Exe -ErrorAction SilentlyContinue)) {
        Write-Error "$Exe 이(가) 필요하다 (docs/LOCAL_SETUP.md)"
    }
}

# make와 같이 .env가 있을 때만 --env-file로 넘긴다.
function Uv-Run([string[]]$ArgList) {
    $envFile = if (Test-Path '.env') { @('--env-file', '.env') } else { @() }
    Run 'uv' (@('run', '--no-sync') + $envFile + $ArgList)
}

function Npm-Dev([string]$Dir) {
    Need 'npm'
    Push-Location $Dir
    try {
        if (-not (Test-Path 'node_modules')) { Run 'npm' @('ci') }
        Run 'npm' @('run', 'dev')
    } finally { Pop-Location }
}

$cmd = if ($args.Count -gt 0) { [string]$args[0] } else { 'help' }
$arg1 = if ($args.Count -gt 1) { [string]$args[1] } else { '' }

switch ($cmd) {
    'setup' {
        Need 'uv'; Need 'npm'
        Run 'uv' @('sync', '--locked', '--no-install-project')
        Push-Location 'frontend'; try { Run 'npm' @('ci') } finally { Pop-Location }
        Push-Location 'hmi/web'; try { Run 'npm' @('ci') } finally { Pop-Location }
    }
    'check' {
        Run 'uv' @('run', '--no-sync', 'ruff', 'check', '.')
        Run 'uv' @('run', '--no-sync', 'ruff', 'format', '--check', '.')
        Run 'uv' @('run', '--no-sync', 'pytest')
        Run 'uv' @('run', '--no-sync', 'python', 'scripts/sync_skills.py', '--check')
    }
    'env-check' { Run 'uv' @('run', '--no-sync', 'python', 'scripts/check_env.py') }
    'db' {
        Need 'docker'
        Run 'docker' @('compose', 'up', '-d', 'postgres')
        Uv-Run @('alembic', 'upgrade', 'head')
    }
    'qdrant' { Need 'docker'; Run 'docker' @('compose', '--profile', 'qdrant', 'up', '-d', 'qdrant') }
    'ps' { Run 'docker' @('compose', '--profile', 'qdrant', 'ps') }
    'logs' {
        $svc = if ($arg1) { $arg1 } else { 'postgres' }
        Run 'docker' @('compose', '--profile', 'qdrant', 'logs', '-f', '--tail', '100', $svc)
    }
    'volumes' {
        $prefix = (Split-Path -Leaf $Root) + '_'
        Write-Output '[볼륨] Docker Desktop은 경로가 VM 안이라 탐색기에서 보이지 않는다'
        docker system df -v | Where-Object { $_ -match '^VOLUME NAME' -or $_.StartsWith($prefix) }
    }
    'down' { Run 'docker' @('compose', '--profile', 'qdrant', 'down') }
    'api' {
        Uv-Run @('uvicorn', '--app-dir', 'src', 'weeing_weeing.api.app:app', '--reload')
    }
    'front' { Npm-Dev 'frontend' }
    'hmi' { Npm-Dev 'hmi/web' }
    'seed' { Uv-Run @('python', 'scripts/seed_users.py') }
    'seed-docs' {
        $extra = if ($arg1 -eq '--replace') { @('--replace') } elseif ($arg1) { Write-Error 'seed-docs 인자는 --replace만 받는다' } else { @() }
        Uv-Run (@('python', 'scripts/seed_documents.py') + $extra)
    }
    'reindex-reports' { Uv-Run @('python', 'scripts/index_reports.py', '--all') }
    'urls' {
        @'
API 문서    http://localhost:8000/docs   (헬스: http://localhost:8000/health)
프론트      http://localhost:3100
HMI        http://localhost:5173
PostgreSQL localhost:5432
Qdrant     http://localhost:6333/dashboard (qdrant 기동 시)
'@ | Write-Output
    }
    { $_ -in 'help', '-h', '--help' } { Show-Usage }
    default { Write-Output "모르는 명령: $cmd"; Show-Usage; exit 2 }
}
