param(
    [Parameter(Mandatory=$true)][string]$Project,
    [string]$Executable='C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe'
)
$ErrorActionPreference='Stop'
# Deliberately fixed loopback endpoint. Never accepts an AWS endpoint or token.
if (Get-Process UnrealEditor -ErrorAction SilentlyContinue) {
    throw 'Close the laptop Unreal game/editor before starting this local test.'
}
if (!(Test-Path -LiteralPath $Executable -PathType Leaf)) { throw 'Unreal executable not found. Pass -Executable.' }
$projectPath=(Resolve-Path -LiteralPath $Project).Path
if ([IO.Path]::GetExtension($projectPath) -ne '.uproject') { throw 'Project must be a .uproject file.' }
$start=[Diagnostics.ProcessStartInfo]::new()
$start.FileName=(Resolve-Path -LiteralPath $Executable).Path
$start.WorkingDirectory=Split-Path $start.FileName -Parent
$start.UseShellExecute=$false
$start.Arguments='"'+$projectPath+'" /Game/Maps/MainMap -game -log -TelemetryMode=LOCAL -TelemetryUrl=ws://127.0.0.1:8000/ws/telemetry?context=SIM_RPM'
$start.EnvironmentVariables.Remove('WW_TELEMETRY_TOKEN')
$null=[Diagnostics.Process]::Start($start)
Write-Host 'Started LOCAL SIM_RPM. Fixed speed is a simulation assumption, not verified PLC state. No AWS token is used.'
