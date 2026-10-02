<# Preview by default. -Write creates reviewed artifacts only; never installs/starts services. #>
[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$EnvironmentDirectory,
    [string]$LogDirectory = 'C:\ProgramData\Trd\logs',
    [string]$NodePath,
    [string]$DashboardServerPath,
    [string]$LayoutPath = (Join-Path $PSScriptRoot 'native-layout.json'),
    [string]$OutputDirectory,
    [string]$WinSWPath,
    [string]$ExpectedSha256,
    [switch]$Write,
    [switch]$Json
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Native.Common.ps1')
if (-not $ProjectRoot) { $ProjectRoot = Get-TrdProjectRoot }
if (-not $EnvironmentDirectory) { $EnvironmentDirectory = 'C:\ProgramData\Trd\env' }
if (-not $DashboardServerPath) { $DashboardServerPath = Join-Path $ProjectRoot 'apps\dashboard\.next\standalone\apps\dashboard\server.js' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot 'generated' }
if (-not $NodePath) {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    $NodePath = if ($node) { $node.Source } else { 'C:\Program Files\nodejs\node.exe' }
}
foreach ($path in @($ProjectRoot, $EnvironmentDirectory, $LogDirectory, $NodePath, $DashboardServerPath, $OutputDirectory)) { Assert-TrdPlainPath $path }
$layout = Get-TrdNativeLayout -Path $LayoutPath
$pythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$definitions = @(
    @{ id = 'trdapi'; role = 'api'; args = "-m uvicorn apps.api.main:app --host 127.0.0.1 --port $($layout.ports.admin_api) --loop asyncio" },
    @{ id = 'trdbridge'; role = 'bridge'; args = "-m uvicorn apps.worker.bridge:app --host 127.0.0.1 --port $($layout.ports.risk_bridge) --loop asyncio" },
    @{ id = 'trdai'; role = 'ai'; args = '-m apps.worker.main --service ai' },
    @{ id = 'trdcollector'; role = 'telegram'; args = '-m apps.telegram.main' },
    @{ id = 'trdmaintenance'; role = 'maintenance'; args = '-m apps.worker.main --service maintenance' },
    @{ id = 'trddashboard'; role = 'dashboard'; args = "--env-file=`"$(Join-Path $EnvironmentDirectory '.env.dashboard')`" `"$DashboardServerPath`"" }
)
$services = foreach ($definition in $definitions) {
    [pscustomobject]@{
        id = $definition.id
        role = $definition.role
        account = "NT SERVICE\$($definition.id)"
        env_file = Join-Path $EnvironmentDirectory ".env.$($definition.role)"
        executable = if ($definition.role -eq 'dashboard') { $NodePath } else { $pythonPath }
        arguments = $definition.args
        depends_on = if ($definition.role -eq 'dashboard') { 'trdapi' } else { $layout.postgres_service }
        log_path = Join-Path $LogDirectory $definition.id
    }
}

if ($Write) {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Artifact writing requires Windows; use preview for planning.' }
    if (-not $WinSWPath -or -not $ExpectedSha256) { throw '-Write requires WinSWPath and a trusted independently approved ExpectedSha256 for stable WinSW 2.12.0.' }
    $verified = & (Join-Path $PSScriptRoot 'Test-WinSWArtifact.ps1') -Path $WinSWPath -ExpectedSha256 $ExpectedSha256
    foreach ($path in @($pythonPath, $NodePath, $DashboardServerPath) + @($services.env_file)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required artifact/env file is missing: $path" }
    }
    if (Test-Path -LiteralPath $OutputDirectory) { throw 'OutputDirectory already exists. Choose a new review directory; existing files are never overwritten.' }
    # Review the complete plan and provision restrictive ACLs before later service installation.
    New-Item -ItemType Directory -Path $OutputDirectory -ErrorAction Stop | Out-Null
    foreach ($service in $services) {
        $directory = Join-Path $OutputDirectory $service.id
        New-Item -ItemType Directory -Path $directory -ErrorAction Stop | Out-Null
        $exe = ConvertTo-TrdXmlText $service.executable
        $arguments = ConvertTo-TrdXmlText $service.arguments
        $envFile = ConvertTo-TrdXmlText $service.env_file
        $workingDirectory = ConvertTo-TrdXmlText $ProjectRoot
        $logPath = ConvertTo-TrdXmlText $service.log_path
        $dependency = ConvertTo-TrdXmlText $service.depends_on
        $extraEnv = if ($service.role -eq 'dashboard') {
            "  <env name=`"HOSTNAME`" value=`"127.0.0.1`" />`n  <env name=`"PORT`" value=`"$($layout.ports.dashboard)`" />`n  <env name=`"NODE_ENV`" value=`"production`" />"
        } else { '' }
        $xml = @"
<?xml version="1.0" encoding="utf-8"?>
<service>
  <id>$($service.id)</id>
  <name>TRD $($service.role) (Phase 1 foundation)</name>
  <description>Trading disabled. Review identities, ACLs and recovery before deployment.</description>
  <executable>$exe</executable>
  <arguments>$arguments</arguments>
  <workingdirectory>$workingDirectory</workingdirectory>
  <env name="ENV_FILE" value="$envFile" />
  <env name="TRADING_MODE" value="paper" />
  <env name="ENABLE_AUTOMATION" value="false" />
  <env name="ENABLE_LIVE_TRADING" value="false" />
$extraEnv
  <serviceaccount><domain>NT SERVICE</domain><user>$($service.id)</user></serviceaccount>
  <startmode>Automatic</startmode>
  <delayedAutoStart />
  <depend>$dependency</depend>
  <stoptimeout>30 sec</stoptimeout>
  <stopparentprocessfirst>true</stopparentprocessfirst>
  <onfailure action="restart" delay="10 sec" />
  <onfailure action="restart" delay="30 sec" />
  <onfailure action="restart" delay="60 sec" />
  <resetfailure>1 hour</resetfailure>
  <logpath>$logPath</logpath>
  <log mode="roll-by-size"><sizeThreshold>1024</sizeThreshold><keepFiles>7</keepFiles></log>
</service>
"@
        # XML syntax is checked before an artifact is written. No secret file is read.
        $null = [xml]$xml
        $xmlPath = Join-Path $directory "$($service.id).xml"
        [IO.File]::WriteAllText($xmlPath, $xml, [Text.UTF8Encoding]::new($false))
        Copy-Item -LiteralPath $verified.path -Destination (Join-Path $directory "$($service.id).exe") -ErrorAction Stop
    }
}
$result = [pscustomobject]@{
    phase = 1
    dry_run = (-not $Write)
    artifacts_written = [bool]$Write
    output_directory = $OutputDirectory
    pinned_winsw = '2.12.0 (x64; trusted SHA256 required for -Write)'
    services = @($services)
    installed = $false
    production_ready = $false
    notes = @('Virtual-service-account creation, effective ACL isolation, graceful shutdown and pre-login reboot are not yet tested.', 'Preview and artifact generation do not install services, create accounts, change firewall/RDP, configure Autologon, or read env-file contents.', 'The local native database must already be provisioned/migrated. Service dependencies do not prove schema readiness.')
}
if ($Json) { $result | ConvertTo-Json -Depth 6 } else { $services | Format-Table id, account, env_file, executable, arguments -Wrap; $result.notes | ForEach-Object { Write-Output $_ } }
