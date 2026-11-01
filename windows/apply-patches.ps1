# Apply the official Heavy Gear patches, then apply this project's Windows fixes.
[CmdletBinding()]
param(
    [string]$GamePath = (Join-Path $env:USERPROFILE 'Games\HeavyGear'),
    [string]$Disc1Path,
    [ValidateSet('all', '1.1', '1.2')]
    [string]$Version = 'all',
    [string]$Patch11Path,
    [string]$Patch12Path,
    [switch]$FixesOnly,
    [string]$HgfixPath,
    [switch]$InstallRenderer,
    [string]$RendererPath,
    [double]$MenuFps = 30,
    [double]$SimFps = 30,
    [string[]]$Fix = @(),
    [string[]]$Skip = @()
)

$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$game = [IO.Path]::GetFullPath($GamePath)
$disc1 = if ($Disc1Path) { [IO.Path]::GetFullPath($Disc1Path) } else { Join-Path $project 'HG-DISC-1' }
$patch11 = if ($Patch11Path) { [IO.Path]::GetFullPath($Patch11Path) } else { Join-Path $project 'patches\hgp187d\hgp187d.exe' }
$patch12 = if ($Patch12Path) { [IO.Path]::GetFullPath($Patch12Path) } else { Join-Path $project 'patches\hgpatc12\HGPATC12.EXE' }
$discData = Join-Path $disc1 'INSTALL\DATA'

if (($InstallRenderer -or $RendererPath) -and
    ($FixesOnly -or $Version -notin @('all', '1.2'))) {
    throw 'Direct3D 9 renderer requires the official 1.2 update. Apply version 1.2 (or all official updates) before installing the renderer.'
}

function Get-GameFile {
    param([Parameter(Mandatory = $true)][string]$Name)

    $file = Get-ChildItem -LiteralPath $game -File |
        Where-Object { $_.Name -ieq $Name } |
        Select-Object -First 1
    if (-not $file) {
        throw "Required game file '$Name' was not found in '$game'. Run setup-heavygear.ps1 first."
    }
    return $file.FullName
}

function Get-Hash {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Get-HgfixArguments {
    $arguments = @(
        $game,
        '--menu-fps', $MenuFps.ToString([Globalization.CultureInfo]::InvariantCulture),
        '--sim-fps', $SimFps.ToString([Globalization.CultureInfo]::InvariantCulture)
    )
    foreach ($name in $Fix) {
        $arguments += @('--fix', $name)
    }
    foreach ($name in $Skip) {
        $arguments += @('--skip', $name)
    }
    return $arguments
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-OfficialPatchRegistryDiagnostics {
    $lines = @()
    $registry = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::LocalMachine,
        [Microsoft.Win32.RegistryView]::Registry32
    )
    try {
        $activision = $registry.OpenSubKey('Software\Activision\Heavy Gear')
        if ($activision) {
            try {
                $versionKeys = @($activision.GetSubKeyNames() | Sort-Object)
                $lines += "HKLM 32-bit\Software\Activision\Heavy Gear: EXE='$($activision.GetValue('EXE', '<missing>'))'; FTP='$($activision.GetValue('FTP', '<missing>'))'; version subkeys=[$($versionKeys -join ', ')]"
            } finally {
                $activision.Dispose()
            }
        } else {
            $lines += 'HKLM 32-bit\Software\Activision\Heavy Gear: missing'
        }

        $appPaths = $registry.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\App Paths\HG.EXE')
        if ($appPaths) {
            try {
                $lines += "HKLM 32-bit\App Paths\HG.EXE: default='$($appPaths.GetValue('', '<missing>'))'; Path='$($appPaths.GetValue('Path', '<missing>'))'"
            } finally {
                $appPaths.Dispose()
            }
        } else {
            $lines += 'HKLM 32-bit\App Paths\HG.EXE: missing'
        }
    } finally {
        $registry.Dispose()
    }
    return $lines -join [Environment]::NewLine
}

function Set-OfficialPatchRegistryEntries {
    $registry = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::LocalMachine,
        [Microsoft.Win32.RegistryView]::Registry32
    )
    try {
        $activision = $registry.CreateSubKey('Software\Activision\Heavy Gear')
        try {
            $activision.SetValue('EXE', 'HG.EXE', [Microsoft.Win32.RegistryValueKind]::String)
            $activision.SetValue('FTP', 'HGEARW95', [Microsoft.Win32.RegistryValueKind]::String)
            if (@($activision.GetSubKeyNames()).Count -eq 0) {
                $versionKey = $activision.CreateSubKey('1.00')
                $versionKey.Dispose()
            }
        } finally {
            $activision.Dispose()
        }

        $appPaths = $registry.CreateSubKey(
            'Software\Microsoft\Windows\CurrentVersion\App Paths\HG.EXE'
        )
        try {
            $appPaths.SetValue('', $exe, [Microsoft.Win32.RegistryValueKind]::String)
            $appPaths.SetValue('Path', $game, [Microsoft.Win32.RegistryValueKind]::String)
        } finally {
            $appPaths.Dispose()
        }
    } finally {
        $registry.Dispose()
    }
}

function Invoke-Hgfix {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $candidates = @()
    if ($HgfixPath) {
        $candidates += $HgfixPath
    } else {
        $candidates += @(
            (Join-Path $project 'dist\hgfix.exe'),
            (Join-Path $project 'windows\hgfix.exe')
        )
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            & $candidate @Arguments
            if ($LASTEXITCODE -ne 0) {
                throw "hgfix failed with exit code $LASTEXITCODE."
            }
            return
        }
    }
    if ($HgfixPath) {
        throw "Could not find the specified hgfix executable: '$HgfixPath'."
    }

    $script = Join-Path $project 'patcher\hgfix.py'
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3 $script @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "hgfix failed with exit code $LASTEXITCODE."
        }
        return
    }

    $python = Get-Command python -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch '\\WindowsApps\\' } |
        Select-Object -First 1
    if ($python) {
        & $python.Source $script @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "hgfix failed with exit code $LASTEXITCODE."
        }
        return
    }

    throw "Could not find hgfix.exe or a Python 3 interpreter (the Microsoft Store app-execution alias is not an interpreter). Install Python 3 and rerun, or build dist\hgfix.exe with windows\build-exe.ps1 -Target tools."
}

function Test-HgfixOptions {
    $probeArguments = @($game, '--platform', 'windows', '--list')
    foreach ($name in $Fix) {
        $probeArguments += @('--fix', $name)
    }
    foreach ($name in $Skip) {
        $probeArguments += @('--skip', $name)
    }

    $command = $null
    $prefix = @()
    if ($HgfixPath) {
        if (-not (Test-Path -LiteralPath $HgfixPath -PathType Leaf)) {
            throw "Could not find the specified hgfix executable: '$HgfixPath'."
        }
        $command = $HgfixPath
    } else {
        $candidate = @(
            (Join-Path $project 'dist\hgfix.exe'),
            (Join-Path $project 'windows\hgfix.exe')
        ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
        if ($candidate) {
            $command = $candidate
        } else {
            $script = Join-Path $project 'patcher\hgfix.py'
            $py = Get-Command py -ErrorAction SilentlyContinue
            if ($py) {
                $command = $py.Source
                $prefix = @('-3', $script)
            } else {
                $python = Get-Command python -ErrorAction SilentlyContinue |
                    Where-Object { $_.Source -notmatch '\\WindowsApps\\' } |
                    Select-Object -First 1
                if (-not $python) {
                    throw "Could not find hgfix.exe or Python 3 to validate the selected fixes. Download hgfix.exe into dist\hgfix.exe or install Python 3."
                }
                $command = $python.Source
                $prefix = @($script)
            }
        }
    }

    $output = @()
    $exitCode = 0
    try {
        $output = & $command @prefix @probeArguments 2>&1
        $exitCode = $LASTEXITCODE
    } catch {
        $exitCode = if ($LASTEXITCODE) { $LASTEXITCODE } else { 1 }
        $output += $_.Exception.Message
    }
    if ($exitCode -ne 0) {
        $diagnostic = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
        if ($diagnostic -match 'unknown fix') {
            throw "The selected hgfix tool is outdated and does not support one or more selected fixes.`r`n$diagnostic`r`nUpdate dist\hgfix.exe from the latest project release or rebuild it with windows\build-exe.ps1 before applying patches. If official 1.2 has already completed, rerun apply-patches.ps1 with -FixesOnly after updating hgfix.exe."
        }
        throw "Could not validate the selected fixes with hgfix (exit code $exitCode).`r`n$diagnostic"
    }
}

if (-not (Test-Path -LiteralPath $game -PathType Container)) {
    throw "Game folder '$game' does not exist. Run windows\setup-heavygear.ps1 first."
}
Test-HgfixOptions
if (-not $FixesOnly -and -not (Test-IsAdministrator)) {
    throw 'The official patchers require a 32-bit HKLM registry entry. Re-run this script from an elevated PowerShell session.'
}
if (Get-Process -Name HG -ErrorAction SilentlyContinue) {
    throw 'Heavy Gear is running. Exit the game before applying patches.'
}

$installPatchers = @()
if (-not $FixesOnly -and $Version -in @('all', '1.1')) {
    if (-not (Test-Path -LiteralPath $patch11 -PathType Leaf)) {
        throw "Official 1.1 patch not found: '$patch11'. Place hgp187d.exe there."
    }
    $installPatchers += [PSCustomObject]@{ Version = '1.1'; Path = $patch11 }
}
if (-not $FixesOnly -and $Version -in @('all', '1.2')) {
    if (-not (Test-Path -LiteralPath $patch12 -PathType Leaf)) {
        throw "Official 1.2 patch not found: '$patch12'. Place HGPATC12.EXE there."
    }
    $installPatchers += [PSCustomObject]@{ Version = '1.2'; Path = $patch12 }
}

$shell = Get-GameFile 'HGSHELL.DLL'
$sim = Get-GameFile 'HGSIM.DLL'
$exe = Get-GameFile 'HG.EXE'

if ($FixesOnly) {
    Write-Host 'Applying this project''s Windows fixes only'
    Invoke-Hgfix -Arguments (Get-HgfixArguments)
    if ($InstallRenderer -or $RendererPath) {
        $rendererInstaller = Join-Path $PSScriptRoot 'install-renderer.ps1'
        & $rendererInstaller -GamePath $game -RendererPath $RendererPath
    }
    Write-Host 'Community fixes applied.'
    Write-Host "Start the game normally: $exe"
    return
}

$backupRoot = Join-Path $project 'backups'
$backupRootFull = [IO.Path]::GetFullPath($backupRoot).TrimEnd('\') + '\'
$gameRootFull = $game.TrimEnd('\') + '\'
if ($backupRootFull.StartsWith($gameRootFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The game folder '$game' contains the repository backup folder; choose a different -GamePath to avoid copying a backup into itself."
}
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$backup = Join-Path $backupRoot ("HeavyGear-before-official-{0}" -f (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
Write-Host "Backing up the current game folder to $backup"
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Get-ChildItem -LiteralPath $game -Force | Copy-Item -Destination $backup -Recurse

$originals = @($shell, $sim, $exe) | Where-Object { Test-Path -LiteralPath "$_.orig" }
if ($originals.Count -gt 0) {
    Write-Host 'Restoring this project''s previous fix backups before applying delta patches'
    Invoke-Hgfix -Arguments @($game, '--restore')
}

if ($Version -ne '1.2') {
    foreach ($name in @('HG.EXE', 'HGSHELL.DLL', 'HGSIM.DLL')) {
        $installed = Get-GameFile $name
        $discFile = Join-Path $discData $name
        if (-not (Test-Path -LiteralPath $discFile -PathType Leaf)) {
            throw "Disc 1 original not found: '$discFile'."
        }
        if ((Get-Hash $installed) -ne (Get-Hash $discFile)) {
            throw "$name is not the unmodified 1.0 file from disc 1. For 1.1/1.2 patching, restore a clean game install first."
        }
    }
}

foreach ($patch in $installPatchers) {
    Set-OfficialPatchRegistryEntries
    $before = @{}
    foreach ($name in @('HG.EXE', 'HGSHELL.DLL', 'HGSIM.DLL')) {
        $before[$name] = Get-Hash (Get-GameFile $name)
    }
    Write-Host ''
    Write-Host "Starting official Heavy Gear $($patch.Version) patch. Click Proceed in its window; close the game if it starts."
    # The patchers are RTPatch Professional apps whose GUI windows render all-black when launched
    # detached (double-clicked or via Start-Process, which gives them no console handle). Run via
    # cmd.exe /c from this console so the patcher inherits a console handle and its Proceed/Quit
    # window renders; the user clicks Proceed. -NOCONFIRM/-NOMESSAGE keep it in that mode.
    Push-Location (Split-Path -Parent $patch.Path)
    try {
        cmd.exe /c "`"$($patch.Path)`" -NOCONFIRM -NOMESSAGE"
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    $changed = @()
    foreach ($name in @('HG.EXE', 'HGSHELL.DLL', 'HGSIM.DLL')) {
        if ((Get-Hash (Get-GameFile $name)) -ne $before[$name]) {
            $changed += $name
        }
    }
    if ($changed.Count -eq 0) {
        $registryDiagnostics = Get-OfficialPatchRegistryDiagnostics
        throw "The official $($patch.Version) patch did not change HG.EXE, HGSHELL.DLL, or HGSIM.DLL (cancelled or failed; installer exit code $($exitCode)).`r`nChanged files: none.`r`nExpected game folder: $game`r`n32-bit registry state:`r`n$registryDiagnostics`r`nThe Activision EXE/FTP values should be exactly 'HG.EXE' and 'HGEARW95'; for patch 1.2 after 1.1, the version subkey should include 1.87. App Paths should point to this game folder. Check the patcher's own message.`r`nBackup: $backup"
    }
    Write-Host "Official patch $($patch.Version) changed: $($changed -join ', ')."
    if (Get-Process -Name HG -ErrorAction SilentlyContinue) {
        throw "Heavy Gear is still running after the $($patch.Version) patcher closed. Exit the game and run the remaining patch steps again. Backup: $backup"
    }
}

Write-Host ''
Write-Host 'Applying this project''s Windows fixes'
Invoke-Hgfix -Arguments (Get-HgfixArguments)
if ($InstallRenderer -or $RendererPath) {
    $rendererInstaller = Join-Path $PSScriptRoot 'install-renderer.ps1'
    & $rendererInstaller -GamePath $game -RendererPath $RendererPath
}

Write-Host ''
Write-Host "Patches are applied. Backup: $backup"
Write-Host "Start the game normally (do not run it as Administrator): $exe"
