<#
.SYNOPSIS
  TEST ONLY. Opens a browser for the test stack on another machine, without admin rights.

.DESCRIPTION
  The test stack's hostnames (itop/sso/chat/mcp.example.com) must reach the Docker host on port 443.
  Instead of the hosts file (needs admin rights), this script starts a browser with its own profile
  that resolves those names to the Docker host:

  - Firefox: a separate profile with network.dns.forceResolve, so EVERY hostname goes to the
    Docker host in that profile. Use it only for the test stack, not for normal browsing.
  - Edge or Chrome: a separate profile with --host-resolver-rules for the four hostnames only.

  With -CaFile it also trusts the test CA for the current Windows user (Cert:\CurrentUser\Root,
  no admin rights; Windows asks once for confirmation). Edge and Chrome use that store; the Firefox
  profile reads it through security.enterprise_roots.enabled.

  Profiles are kept in %USERPROFILE%\.itop-mcp-test\. -Shortcut adds a desktop shortcut.

.EXAMPLE
  .\open-browser.ps1 -HostIp 192.168.178.25 -CaFile ..\certs\ca.crt -Shortcut
.EXAMPLE
  .\open-browser.ps1 -HostIp 192.168.178.25 -Browser edge
#>
param(
    [Parameter(Mandatory = $true)] [string] $HostIp,
    [ValidateSet('firefox', 'edge', 'chrome')] [string] $Browser = 'firefox',
    [string] $CaFile,
    [switch] $Shortcut
)
$ErrorActionPreference = 'Stop'
$hosts = 'itop.example.com', 'sso.example.com', 'chat.example.com', 'mcp.example.com'
$urls = 'https://chat.example.com https://itop.example.com'
$base = Join-Path $env:USERPROFILE '.itop-mcp-test'
New-Item -ItemType Directory -Force $base | Out-Null

if ($CaFile) {
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 (Resolve-Path $CaFile).Path
    if (Get-ChildItem Cert:\CurrentUser\Root | Where-Object Thumbprint -eq $cert.Thumbprint) {
        Write-Host "Test CA already trusted: $($cert.Subject)"
    } else {
        Write-Host "Trusting the test CA for this Windows user; confirm the Windows security warning with Yes."
        # In its own window: the confirmation dialog needs an interactive session.
        $cmd = "Import-Certificate -FilePath '$((Resolve-Path $CaFile).Path)' -CertStoreLocation Cert:\CurrentUser\Root"
        Start-Process powershell -Wait -ArgumentList '-NoProfile', '-Command', $cmd
        if (-not (Get-ChildItem Cert:\CurrentUser\Root | Where-Object Thumbprint -eq $cert.Thumbprint)) {
            throw 'The test CA was not imported.'
        }
    }
}

function Find-Exe([string[]] $candidates) {
    $found = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $found) { throw "Browser not found: $($candidates -join ', ')" }
    return $found
}

if ($Browser -eq 'firefox') {
    $exe = Find-Exe @("$env:ProgramFiles\Mozilla Firefox\firefox.exe", "${env:ProgramFiles(x86)}\Mozilla Firefox\firefox.exe",
                      "$env:LOCALAPPDATA\Mozilla Firefox\firefox.exe")
    $profileDir = Join-Path $base 'firefox-profile'
    New-Item -ItemType Directory -Force $profileDir | Out-Null
    @"
// TEST ONLY: Firefox profile for the itop-mcp test stack. Every hostname resolves to $HostIp.
user_pref("network.dns.forceResolve", "$HostIp");
// No DNS over HTTPS, so forceResolve applies.
user_pref("network.trr.mode", 5);
// Trust the test CA from the Windows certificate store.
user_pref("security.enterprise_roots.enabled", true);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
"@ | Set-Content -Path (Join-Path $profileDir 'user.js') -Encoding ascii
    $arguments = "-no-remote -profile `"$profileDir`" $urls"
} else {
    if ($Browser -eq 'edge') {
        $exe = Find-Exe @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")
    } else {
        $exe = Find-Exe @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")
    }
    $profileDir = Join-Path $base "$Browser-profile"
    $rules = ($hosts | ForEach-Object { "MAP $_ $HostIp" }) -join ', '
    $arguments = "--user-data-dir=`"$profileDir`" --host-resolver-rules=`"$rules`" --no-first-run $urls"
}

if ($Shortcut) {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) "iTop test stack ($Browser).lnk"))
    $lnk.TargetPath = $exe
    $lnk.Arguments = $arguments
    $lnk.WorkingDirectory = $base
    $lnk.Description = "TEST ONLY: $Browser with *.example.com -> $HostIp"
    $lnk.Save()
    Write-Host "Desktop shortcut: $($lnk.FullName)"
}

Start-Process $exe -ArgumentList $arguments
Write-Host "Started $Browser with its own profile in $profileDir"
