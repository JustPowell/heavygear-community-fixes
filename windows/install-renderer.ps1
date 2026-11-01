# Install the community renderer DLL into the game's plugin directory.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$GamePath,
    [string]$RendererPath
)

$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$game = [IO.Path]::GetFullPath($GamePath)

if (-not (Test-Path -LiteralPath $game -PathType Container)) {
    throw "Game folder '$game' does not exist."
}

if ($RendererPath) {
    $renderer = (Resolve-Path -LiteralPath $RendererPath).Path
} else {
    $candidates = @(
        (Join-Path $project 'dist\3dfx_hgd3d9.dll'),
        (Join-Path $project 'renderer\hgd3d9\3dfx_hgd3d9.dll'),
        (Join-Path $project 'renderer\hgd3d9\hgd3d9.dll')
    )
    $renderer = $candidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if (-not $renderer) {
        throw "Could not find the renderer DLL. Download the heavygear-renderer-windows artifact from GitHub Actions or the release, then pass its path with -RendererPath."
    }
}

$bytes = [IO.File]::ReadAllBytes($renderer)
if ($bytes.Length -lt 64 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) {
    throw "'$renderer' is not a valid Windows PE file."
}
$peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
if ($peOffset -lt 0 -or $peOffset + 24 -gt $bytes.Length -or
    $bytes[$peOffset] -ne 0x50 -or $bytes[$peOffset + 1] -ne 0x45 -or
    $bytes[$peOffset + 2] -ne 0 -or $bytes[$peOffset + 3] -ne 0) {
    throw "'$renderer' has an invalid PE header."
}
$machine = [BitConverter]::ToUInt16($bytes, $peOffset + 4)
$characteristics = [BitConverter]::ToUInt16($bytes, $peOffset + 22)
if ($machine -ne 0x014c -or ($characteristics -band 0x2000) -eq 0) {
    throw "'$renderer' must be a 32-bit (x86) Windows DLL."
}

$pluginDir = Join-Path $game 'PLUGIN'
if (-not (Test-Path -LiteralPath $pluginDir -PathType Container)) {
    throw "Renderer plugin directory '$pluginDir' does not exist. Is this a complete Heavy Gear install?"
}
$destination = Join-Path $pluginDir '3dfx_hgd3d9.dll'
# Check for any old renderer files that should be moved out of the plugin list
$oldNames = @('hgrender.dll', '3dfx_hgrender.dll')
$asideDir = Join-Path $game 'hgd3d9-runs'

foreach ($oldName in $oldNames) {
    $oldPath = Join-Path $pluginDir $oldName
    if (Test-Path -LiteralPath $oldPath -PathType Leaf) {
        New-Item -ItemType Directory -Path $asideDir -Force | Out-Null
        $aside = Join-Path $asideDir ("{0}.old-name-{1}" -f $oldName, (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
        Move-Item -LiteralPath $oldPath -Destination $aside
        Write-Host "Moved old plugin name out of the game's plugin list: $aside"
    }
}

$sourceHash = (Get-FileHash -LiteralPath $renderer -Algorithm SHA256).Hash
if (Test-Path -LiteralPath $destination -PathType Leaf) {
    $destinationHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
    if ($sourceHash -eq $destinationHash) {
        Write-Host "Renderer already installed: $destination"
    } else {
        New-Item -ItemType Directory -Path $asideDir -Force | Out-Null
        $aside = Join-Path $asideDir ("3dfx_hgd3d9.dll-{0}.bak" -f (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
        Move-Item -LiteralPath $destination -Destination $aside
        Copy-Item -LiteralPath $renderer -Destination $destination
        Write-Host "Updated renderer; previous DLL saved to $aside"
    }
} else {
    Copy-Item -LiteralPath $renderer -Destination $destination
    Write-Host "Installed renderer: $destination"
}

# Keep the resolution set under the old name.
$oldRes = Join-Path $game 'hgrender.res'
$newRes = Join-Path $game 'hgd3d9.res'
if ((Test-Path -LiteralPath $oldRes -PathType Leaf) -and -not (Test-Path -LiteralPath $newRes)) {
    Move-Item -LiteralPath $oldRes -Destination $newRes
}

# Select it, unless the game already selects some other renderer (the Direct3D plugin DX5DRAW.DLL and this
# renderer's old names do not count). Same rule as installer_core.select_default_renderer.
$setting = Join-Path $game 'DLLFILE.INI'
$current = ''
if (Test-Path -LiteralPath $setting -PathType Leaf) {
    $current = ([IO.File]::ReadAllText($setting)).Trim().Trim('"')
}
if ($current -and $current -notin (@('DX5DRAW.DLL') + $oldNames)) {
    Write-Host "Left the selected renderer ($current) as it is. To use the Direct3D 9 renderer, select it in Heavy Gear under Options > Renderer."
} else {
    $backup = "$setting.hglauncher.bak"
    if ((Test-Path -LiteralPath $setting -PathType Leaf) -and -not (Test-Path -LiteralPath $backup)) {
        Copy-Item -LiteralPath $setting -Destination $backup
    }
    [IO.File]::WriteAllText($setting, "3dfx_hgd3d9.dll`r`n", [Text.Encoding]::ASCII)
    Write-Host 'Selected the Direct3D 9 renderer as the game''s renderer.'
}
