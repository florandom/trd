<# Parser, loopback/config validation and mutation-free preview checks; no Windows services needed. #>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Native.Common.ps1')
$allErrors = @()
Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' | ForEach-Object {
    $tokens = $null
    $parseErrors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$parseErrors)
    $allErrors += $parseErrors
}
if ($allErrors.Count) { throw ($allErrors | Out-String) }
$plan = & (Join-Path $PSScriptRoot 'Get-NativeDeploymentPlan.ps1') -Json | ConvertFrom-Json
if (-not $plan.dry_run -or $plan.production_ready -or $plan.bind_host -ne '127.0.0.1') { throw 'Deployment preview lost its safety contract.' }
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('trd-native-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $layout = Get-TrdNativeLayout
    foreach ($case in @('public-host', 'duplicate-port', 'invalid-port')) {
        $bad = $layout | ConvertTo-Json -Depth 4 | ConvertFrom-Json
        switch ($case) {
            'public-host' { $bad.bind_host = '0.0.0.0' }
            'duplicate-port' { $bad.ports.risk_bridge = $bad.ports.admin_api }
            'invalid-port' { $bad.ports.dashboard = 65536 }
        }
        $layoutPath = Join-Path $temporary "$case.json"
        [IO.File]::WriteAllText($layoutPath, ($bad | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
        $rejected = $false
        try { $null = Get-TrdNativeLayout -Path $layoutPath } catch { $rejected = $true }
        if (-not $rejected) { throw "Unsafe layout was accepted: $case" }
    }
    $previewDirectory = Join-Path $temporary 'preview-output'
    $preview = & (Join-Path $PSScriptRoot 'New-NativeServiceTemplates.ps1') -EnvironmentDirectory $temporary -LogDirectory $temporary -NodePath (Join-Path $temporary 'node.exe') -DashboardServerPath (Join-Path $temporary 'server.js') -OutputDirectory $previewDirectory -Json | ConvertFrom-Json
    if (-not $preview.dry_run -or $preview.artifacts_written -or $preview.installed -or (Test-Path -LiteralPath $previewDirectory)) { throw 'Service preview performed an unauthorized mutation.' }
    if ($preview.services.Count -ne 6 -or @($preview.services.account | Select-Object -Unique).Count -ne 6 -or @($preview.services.env_file | Select-Object -Unique).Count -ne 6) { throw 'Runtime service isolation is missing from the preview.' }
    $blocked = $false
    try { $null = & (Join-Path $PSScriptRoot 'New-NativeServiceTemplates.ps1') -EnvironmentDirectory $temporary -LogDirectory $temporary -NodePath (Join-Path $temporary 'node.exe') -DashboardServerPath (Join-Path $temporary 'server.js') -OutputDirectory $previewDirectory -Write } catch { $blocked = $true }
    if (-not $blocked -or (Test-Path -LiteralPath $previewDirectory)) { throw 'Artifact writing was not blocked without verified WinSW.' }
} finally {
    # Only delete this script's unique disposable test directory.
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
Write-Output 'Windows foundation parser/config/preview checks passed; no services were installed.'
