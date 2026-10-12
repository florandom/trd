<# Verifies an operator-supplied stable WinSW artifact; downloads/executes nothing. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedSha256
)
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Verify WinSW on Windows.' }
$artifact = Get-Item -LiteralPath $Path -ErrorAction Stop
if ($artifact.PSIsContainer -or $artifact.Extension -ne '.exe') { throw 'Supply the WinSW x64 executable.' }
$actual = (Get-FileHash -LiteralPath $artifact.FullName -Algorithm SHA256).Hash
if ($actual -ne $ExpectedSha256) { throw 'WinSW checksum mismatch. No templates were written and no service was installed.' }
$metadata = @($artifact.VersionInfo.ProductVersion, $artifact.VersionInfo.FileVersion) -join ' '
if ($metadata -notmatch '(^|\s)2\.12\.0(\.0)?(\s|$)') { throw "Expected stable WinSW 2.12.0, found metadata: $metadata" }
[pscustomobject]@{ path = $artifact.FullName; pinned_release = '2.12.0'; sha256 = $actual; checksum_verified = $true; service_installed = $false }
