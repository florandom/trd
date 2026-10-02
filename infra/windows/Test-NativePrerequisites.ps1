<# Read-only inventory. Does not install runtimes, alter services, or read secrets. #>
[CmdletBinding()]
param(
    [string]$LayoutPath = (Join-Path $PSScriptRoot 'native-layout.json'),
    [string]$PostgresBin,
    [switch]$Json,
    [switch]$ReportOnly
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Native.Common.ps1')
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Run this preflight on Windows. A macOS/Linux result cannot validate Windows deployment.'
}
$layout = Get-TrdNativeLayout -Path $LayoutPath
$checks = [Collections.Generic.List[object]]::new()
function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $checks.Add([pscustomobject]@{ name = $Name; passed = $Passed; detail = $Detail })
}
Add-Check 'Windows x64 process' ([IntPtr]::Size -eq 8 -and $env:PROCESSOR_ARCHITECTURE -eq 'AMD64') 'The current native PostgreSQL/WinSW target is 64-bit x86 Windows; use a 64-bit shell.'
function Get-VersionOutput {
    param([string]$Executable, [string[]]$Arguments)
    try {
        $output = (& $Executable @Arguments 2>&1 | Out-String).Trim()
        return [pscustomobject]@{ exit_code = $LASTEXITCODE; output = $output }
    } catch {
        return [pscustomobject]@{ exit_code = 1; output = 'Runtime version probe failed. Inspect the installation in an interactive terminal.' }
    }
}

$node = Get-Command node.exe -ErrorAction SilentlyContinue
if ($node) {
    $probe = Get-VersionOutput -Executable $node.Source -Arguments @('--version')
    Add-Check 'Node 24' ($probe.exit_code -eq 0 -and $probe.output -match '^v24\.') $probe.output
} else { Add-Check 'Node 24' $false 'node.exe was not found on PATH.' }

$python = Get-Command py.exe -ErrorAction SilentlyContinue
$pythonArgs = @('-3.13')
if (-not $python) {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    $pythonArgs = @()
}
if ($python) {
    $probe = Get-VersionOutput -Executable $python.Source -Arguments ($pythonArgs + @('--version'))
    Add-Check 'Python 3.13' ($probe.exit_code -eq 0 -and $probe.output -match '^Python 3\.13\.') $probe.output
} else { Add-Check 'Python 3.13' $false 'Neither py.exe nor python.exe was found.' }

foreach ($tool in @('uv.exe', 'pnpm')) {
    $command = if ($tool -eq 'pnpm') { Get-Command pnpm.cmd -ErrorAction SilentlyContinue } else { Get-Command $tool -ErrorAction SilentlyContinue }
    if ($tool -eq 'pnpm' -and -not $command) { $command = Get-Command pnpm.exe -ErrorAction SilentlyContinue }
    if ($command) {
        $probe = Get-VersionOutput -Executable $command.Source -Arguments @('--version')
        Add-Check $tool ($probe.exit_code -eq 0) $probe.output
    } else { Add-Check $tool $false "$tool was not found on PATH." }
}

if ($PostgresBin) {
    $psqlPath = Join-Path $PostgresBin 'psql.exe'
} else {
    $psql = Get-Command psql.exe -ErrorAction SilentlyContinue
    $psqlPath = if ($psql) { $psql.Source } else { Join-Path $env:ProgramFiles 'PostgreSQL\17\bin\psql.exe' }
}
if (Test-Path -LiteralPath $psqlPath -PathType Leaf) {
    $probe = Get-VersionOutput -Executable $psqlPath -Arguments @('--version')
    Add-Check 'PostgreSQL 17 client' ($probe.exit_code -eq 0 -and $probe.output -match 'PostgreSQL\) 17\.') $probe.output
    $pgControl = Join-Path (Split-Path -Parent $psqlPath) 'pg_ctl.exe'
    Add-Check 'PostgreSQL service tools' (Test-Path -LiteralPath $pgControl -PathType Leaf) $pgControl
} else { Add-Check 'PostgreSQL 17 client' $false 'psql.exe not found; specify -PostgresBin for a custom install.' }
$databaseService = Get-Service -Name $layout.postgres_service -ErrorAction SilentlyContinue
Add-Check 'PostgreSQL service registration' ([bool]$databaseService) $(if ($databaseService) { "$($databaseService.Name): $($databaseService.Status)" } else { "No service named $($layout.postgres_service)." })

$listeners = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners())
$portStatus = foreach ($name in @('admin_api', 'risk_bridge', 'dashboard', 'postgres')) {
    $port = [int]$layout.ports.$name
    $bound = @($listeners | Where-Object { $_.Port -eq $port })
    $nonLoopback = @($bound | Where-Object { -not [Net.IPAddress]::IsLoopback($_.Address) })
    [pscustomobject]@{ service = $name; port = $port; listeners = @($bound | ForEach-Object { $_.ToString() }); non_loopback = ($nonLoopback.Count -gt 0) }
}
Add-Check 'Loopback exposure' (@($portStatus | Where-Object non_loopback).Count -eq 0) 'Any non-loopback listener on a configured port must be investigated; this script changes no firewall rules.'
$report = [pscustomobject]@{
    phase = 1
    mode = 'native-foundation'
    checks = $checks.ToArray()
    ports = @($portStatus)
    ready_to_prepare = (@($checks | Where-Object { -not $_.passed }).Count -eq 0)
    production_ready = $false
    notes = @('A client version/service registration does not prove server version, database credentials, migrations, TLS, MT5, or reboot recovery.', 'An occupied port may belong to the expected service or a conflicting process; inspect it before starting services.', 'Redis is optional and is not required for this native path.')
}
if ($Json) { $report | ConvertTo-Json -Depth 6 } else {
    $checks | Format-Table -AutoSize
    $portStatus | Format-Table -AutoSize
    $report.notes | ForEach-Object { Write-Output $_ }
}
if (-not $report.ready_to_prepare -and -not $ReportOnly) { exit 1 }
