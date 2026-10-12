<# Read-only dependency plan. Does not execute the listed steps. #>
[CmdletBinding()]
param(
    [string]$LayoutPath = (Join-Path $PSScriptRoot 'native-layout.json'),
    [string]$ProjectRoot,
    [switch]$Json
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Native.Common.ps1')
if (-not $ProjectRoot) { $ProjectRoot = Get-TrdProjectRoot }
$layout = Get-TrdNativeLayout -Path $LayoutPath
$steps = @(
    [pscustomobject]@{ order = 1; action = 'Inspect prerequisites and confirm ports'; command = '.\infra\windows\Test-NativePrerequisites.ps1'; mutates = $false },
    [pscustomobject]@{ order = 2; action = 'Install locked Python and dashboard dependencies'; command = 'uv sync --frozen; pnpm install --frozen-lockfile'; mutates = $true },
    [pscustomobject]@{ order = 3; action = 'Create local development secrets, keep trading disabled'; command = 'uv run python infra/scripts/task.py init-env'; mutates = $true },
    [pscustomobject]@{ order = 4; action = 'Provision local PostgreSQL roles/database'; command = 'uv run python infra/scripts/task.py provision-db'; mutates = $true },
    [pscustomobject]@{ order = 5; action = 'Apply migrations and bootstrap non-live defaults'; command = 'uv run python infra/scripts/task.py migrate; uv run python infra/scripts/task.py bootstrap'; mutates = $true },
    [pscustomobject]@{ order = 6; action = 'Start host development and run checks'; command = 'pnpm dev; uv run python infra/scripts/task.py check'; mutates = $true },
    [pscustomobject]@{ order = 7; action = 'Prepare reviewed Windows service artifacts with isolated env files'; command = 'New-NativeServiceTemplates.ps1 (preview first; explicit -Write after prerequisites)'; mutates = $false },
    [pscustomobject]@{ order = 8; action = 'Later deployment gate: service identities/ACLs, proxy/TLS, Access, MT5 demo, pre-login reboot and restore'; command = 'Phase 10/11 supervised Windows verification required'; mutates = $false }
)
$report = [pscustomobject]@{ project_root = $ProjectRoot; mode = 'native-foundation'; dry_run = $true; bind_host = $layout.bind_host; ports = $layout.ports; steps = $steps; production_ready = $false }
if ($Json) { $report | ConvertTo-Json -Depth 6 } else {
    Write-Output "Read-only native foundation plan for $ProjectRoot"
    $steps | Format-Table order, action, command -Wrap
    Write-Output 'No listed command was executed. PostgreSQL and application health/reboot tests remain separate gates.'
}
