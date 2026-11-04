# 운영 서버(AWS EC2) 명령 모음 — Windows PowerShell용. 사용법: .\ops\aws.ps1 help
# macOS·Linux·Git Bash는 ops/aws.sh. 서버 안에서는 ops/server.sh를 직접 쓴다.
#
# 접속·터널은 여기서 처리하고, 나머지 명령은 ops/server.sh를 SSH로 보내 서버에서 실행한다.
# Windows 10 이상에 들어 있는 OpenSSH(ssh.exe)를 쓴다. 서버 별칭은 기본 ww-team(docs/AWS_ACCESS.md 2절).
# 별칭 바꾸기: $env:WW_HOST = '별칭'
# 실행이 막히면(스크립트 실행 정책) 한 번만: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$HostAlias = if ($env:WW_HOST) { $env:WW_HOST } else { 'ww-team' }
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerScript = Join-Path $Here 'server.sh'

function Show-Usage {
    @'
사용법: .\ops\aws.ps1 <명령> [인자]        (서버 별칭 바꾸기: $env:WW_HOST = '별칭')

내 PC에서
  ssh                    서버 셸 접속
  tunnel                 DB·Qdrant SSH 터널 (localhost:15432 → 5432, localhost:16333 → 6333). Ctrl+C로 종료
  urls                   웹·HMI·API 문서·Langfuse 주소
  deploys                최근 배포 워크플로 실행 기록 (gh 필요)

서버 명령 (서버에서 실행)
  ps | health | logs [서비스] [줄수] | logs-all [줄수] | images
  volumes | disk | rag | db | env-keys
  seed-docs [--replace] | reindex-reports | retry-reports
  restart <서비스> | up | pull-up | langfuse-ps | langfuse-logs [줄수]
  자세한 설명: .\ops\aws.ps1 server-help
'@ | Write-Output
}

# server.sh를 base64로 보내 서버 임시 파일로 실행한다. 인자는 영문·숫자·-·_만 받는다.
function Invoke-Server([string[]]$ServerArgs) {
    foreach ($a in $ServerArgs) {
        if ($a -notmatch '^[A-Za-z0-9_-]+$') { Write-Error "잘못된 인자: $a" }
    }
    # Windows 체크아웃의 CRLF가 섞여도 서버 bash가 읽을 수 있게 LF로 맞춘다.
    $text = [System.IO.File]::ReadAllText($ServerScript) -replace "`r", ''
    $b64 = [Convert]::ToBase64String([System.Text.UTF8Encoding]::new($false).GetBytes($text))
    $joined = $ServerArgs -join ' '
    $remote = 'f=$(mktemp) && echo ' + $b64 + ' | base64 -d > $f && bash $f ' + $joined + '; rc=$?; rm -f $f; exit $rc'
    & ssh -t $HostAlias $remote
    exit $LASTEXITCODE
}

$cmd = if ($args.Count -gt 0) { [string]$args[0] } else { 'help' }

switch ($cmd) {
    'ssh' { & ssh $HostAlias; exit $LASTEXITCODE }
    'tunnel' {
        Write-Output '터널 열림: PostgreSQL localhost:15432, Qdrant http://localhost:16333/dashboard (Ctrl+C로 종료)'
        & ssh -N -L 15432:localhost:5432 -L 16333:localhost:6333 $HostAlias
        exit $LASTEXITCODE
    }
    'urls' {
        @'
웹(프론트)  https://<EC2_IP>/
HMI        https://<EC2_IP>/hmi/
API 문서    https://<EC2_IP>/api/docs
Langfuse   https://langfuse.<EC2_IP>.sslip.io
DB·Qdrant  .\ops\aws.ps1 tunnel 후 localhost:15432 / http://localhost:16333/dashboard
'@ | Write-Output
    }
    'deploys' { & gh run list --workflow deploy.yml --limit 10; exit $LASTEXITCODE }
    'server-help' { Invoke-Server @('help') }
    { $_ -in 'help', '-h', '--help' } { Show-Usage }
    default { Invoke-Server ([string[]]$args) }
}
