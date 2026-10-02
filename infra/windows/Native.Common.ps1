Set-StrictMode -Version Latest

function Get-TrdNativeLayout {
    param([string]$Path = (Join-Path $PSScriptRoot 'native-layout.json'))
    $layout = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json
    if ($layout.bind_host -ne '127.0.0.1') {
        throw 'Phase 1 native services must bind to 127.0.0.1.'
    }
    $ports = @()
    foreach ($name in @('admin_api', 'risk_bridge', 'dashboard', 'postgres')) {
        $value = $layout.ports.$name
        if ($null -eq $value -or $value -isnot [ValueType] -or [double]$value -ne [int]$value -or $value -lt 1 -or $value -gt 65535) {
            throw "Invalid port for $name. Supply an integer between 1 and 65535."
        }
        $ports += [int]$value
    }
    if (@($ports | Select-Object -Unique).Count -ne $ports.Count) {
        throw 'Native service ports must be distinct.'
    }
    if ($layout.postgres_service -notmatch '^[A-Za-z0-9_-]+$') {
        throw 'postgres_service must be an explicit Windows service name.'
    }
    return $layout
}

function Get-TrdProjectRoot {
    return (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
}

function Assert-TrdPlainPath {
    param([Parameter(Mandatory)][string]$Path)
    if ($Path -match '["%\r\n]') {
        throw 'Paths must not contain quotes, percent expansion, or newlines.'
    }
    if (-not [IO.Path]::IsPathRooted($Path)) {
        throw "An absolute path is required: $Path"
    }
}

function ConvertTo-TrdXmlText {
    param([Parameter(Mandatory)][string]$Value)
    return [Security.SecurityElement]::Escape($Value)
}
