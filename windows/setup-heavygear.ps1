# Install the pre-copied game files from disc 1 without overwriting existing files.
# Optional system components (Indeo 5 and fonts) require an elevated PowerShell session.
[CmdletBinding()]
param(
    [string]$Disc1Path = (Join-Path $PSScriptRoot '..\HG-DISC-1'),
    [string]$GamePath = (Join-Path $env:USERPROFILE 'Games\HeavyGear'),
    [switch]$ExistingInstall,
    [ValidateSet('action', 'sim', 'wasd')]
    [string]$Controls = 'action',
    [switch]$InstallSystemComponents,
    [string]$CodecPath,
    [string]$UnshieldPath,
    [switch]$InstallRenderer,
    [string]$RendererPath
)

$ErrorActionPreference = 'Stop'

if ($InstallRenderer -or $RendererPath) {
    throw 'Direct3D 9 renderer requires the official 1.2 update. Install it after patching with windows\apply-patches.ps1.'
}

function ConvertTo-ProcessArgument {
    param([string]$Value)
    '"' + $Value.Replace('"', '\"') + '"'
}

function Copy-MissingFiles {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $Source -Force -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($Source.Length).TrimStart('\')
        $target = Join-Path $Destination $relative
        if (Test-Path -LiteralPath $target) {
            if (Test-Path -LiteralPath $target -PathType Container) {
                throw "Expected a file at '$target', but found a directory."
            }
        } else {
            $parent = Split-Path -Parent $target
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target
        }
    }
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Copy-SystemFileWithoutReplacing {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (Test-Path -LiteralPath $Destination) {
        $sourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
        $destinationHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
        if ($sourceHash -ne $destinationHash) {
            throw "Refusing to replace existing system file '$Destination'. Review it manually first."
        }
        return
    }

    Copy-Item -LiteralPath $Source -Destination $Destination
}

$disc1 = [IO.Path]::GetFullPath($Disc1Path)
$game = [IO.Path]::GetFullPath($GamePath)
$data = Join-Path $disc1 'INSTALL\DATA'
$controlsSourceName = if ($Controls -eq 'wasd') { 'ACTION' } else { $Controls.ToUpperInvariant() }
$controlsSource = Join-Path $data $controlsSourceName
$gameExe = Join-Path $data 'HG.EXE'
$inputMap = Join-Path $controlsSource 'INPUTW.MAP'
$codec = $null
$unshieldExecutable = $null
$codecCabinet = $null
$temporaryCodecDirectory = $null

if ($ExistingInstall) {
    foreach ($name in @('HG.EXE', 'HGSHELL.DLL', 'HGSIM.DLL')) {
        if (-not (Test-Path -LiteralPath (Join-Path $game $name) -PathType Leaf)) {
            throw "The existing game folder '$game' is missing $name."
        }
    }
    Write-Host "Using the existing game installation at $game (game files and controls are preserved)"
} else {
    if (-not (Test-Path -LiteralPath $gameExe -PathType Leaf)) {
        throw "Could not find '$gameExe'. Disc1Path must point to the root of the Heavy Gear disc 1 files."
    }
    if (-not (Test-Path -LiteralPath $inputMap -PathType Leaf)) {
        throw "The $Controls control scheme is incomplete: '$inputMap' was not found."
    }
}

if ($InstallSystemComponents) {
    if (-not (Test-IsAdministrator)) {
        throw 'InstallSystemComponents requires an elevated PowerShell session. Re-run PowerShell as Administrator.'
    }
    $fonts = @(Get-ChildItem -LiteralPath (Join-Path $disc1 'INSTALL') -Filter '*.TTF' -File)
    if ($fonts.Count -eq 0) {
        throw "No game fonts (*.TTF) were found in '$disc1\INSTALL'."
    }

    $systemDirectory = if ([Environment]::Is64BitOperatingSystem) {
        Join-Path $env:WINDIR 'SysWOW64'
    } else {
        Join-Path $env:WINDIR 'System32'
    }
    $codec = $null
    $temporaryCodecDirectory = $null
    if ($CodecPath) {
        $codec = (Resolve-Path -LiteralPath $CodecPath).Path
        if ([IO.Path]::GetFileName($codec) -ine 'ir50_32.dll') {
            throw "CodecPath must point to ir50_32.dll, not '$codec'."
        }
    } else {
        $installedCodec = Join-Path $systemDirectory 'ir50_32.dll'
        if (Test-Path -LiteralPath $installedCodec -PathType Leaf) {
            $codec = $installedCodec
        } else {
            $cabinet = Join-Path $disc1 'INSTALL\DATA1.CAB'
            if (-not (Test-Path -LiteralPath $cabinet -PathType Leaf)) {
                throw "The disc's Indeo codec cabinet was not found at '$cabinet'. Provide -CodecPath with an extracted ir50_32.dll."
            }
            $unshieldCommand = if ($UnshieldPath) {
                Get-Command -Name $UnshieldPath -CommandType Application -ErrorAction SilentlyContinue
            } else {
                Get-Command -Name 'unshield' -CommandType Application -ErrorAction SilentlyContinue
            }
            if (-not $unshieldCommand) {
                throw 'To install the cutscene codec automatically, install unshield and make it available on PATH, or pass -CodecPath with an extracted ir50_32.dll.'
            }
            $unshieldExecutable = $unshieldCommand.Source
            $codecCabinet = $cabinet
        }
    }
}

if (-not $ExistingInstall) {
    Write-Host "Copying game files to $game (existing files are kept)"
    Copy-MissingFiles -Source $data -Destination $game
    Write-Host "Installing the $Controls control scheme"
    Copy-MissingFiles -Source $controlsSource -Destination $game

    $helpSource = Join-Path $disc1 'HELP'
    if (Test-Path -LiteralPath $helpSource -PathType Container) {
        Copy-MissingFiles -Source $helpSource -Destination (Join-Path $game 'HELP')
    }
}

if ($Controls -eq 'wasd') {
    $controlsTool = Join-Path (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist') 'hg_controls.exe'
    $controlsScript = Join-Path (Split-Path -Parent $PSScriptRoot) 'patcher\hg_controls.py'
    $wasdScript = Join-Path (Split-Path -Parent $PSScriptRoot) 'mods\wasd\INPUTW.MAP.ed'
    if (-not (Test-Path -LiteralPath $wasdScript -PathType Leaf)) {
        throw "The WASD control definition was not found at '$wasdScript'."
    }
    $gameKeyMap = Join-Path $game 'GAMEKEY.MAP'
    if ($ExistingInstall -and -not (Test-Path -LiteralPath $gameKeyMap -PathType Leaf)) {
        throw "The existing game folder '$game' is missing GAMEKEY.MAP, which is required to apply WASD controls."
    }
    if (-not $ExistingInstall -and -not (Test-Path -LiteralPath (Join-Path $data 'GAMEKEY.MAP') -PathType Leaf)) {
        throw "The disc source '$data' is missing GAMEKEY.MAP, which is required to apply WASD controls."
    }
    $controlsExeCommand = if (Test-Path -LiteralPath $controlsTool -PathType Leaf) {
        Get-Command -Name $controlsTool -CommandType Application -ErrorAction Stop
    } else {
        $null
    }
    $pythonLauncher = Get-Command -Name 'py' -CommandType Application -ErrorAction SilentlyContinue
    $pythonCommand = Get-Command -Name 'python' -CommandType Application -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch '\\WindowsApps\\' } |
        Select-Object -First 1
    if (-not $controlsExeCommand -and -not $pythonLauncher -and -not $pythonCommand) {
        throw "Could not find dist\hg_controls.exe or Python 3 to install the WASD controls. Build the executable with windows\build-exe.ps1 or install Python 3."
    }
}

if ($Controls -eq 'wasd') {
    Write-Host 'Installing the WASD control layout'
    foreach ($mapName in @('INPUTW.MAP', 'GAMEKEY.MAP')) {
        $mapPath = Join-Path $game $mapName
        if (-not (Test-Path -LiteralPath $mapPath -PathType Leaf)) {
            throw "Cannot install WASD controls because '$mapPath' was not found."
        }
        try {
            $attributes = [IO.File]::GetAttributes($mapPath)
            if (($attributes -band [IO.FileAttributes]::ReadOnly) -ne 0) {
                [IO.File]::SetAttributes(
                    $mapPath,
                    $attributes -band (-bnot [IO.FileAttributes]::ReadOnly)
                )
            }
            $attributes = [IO.File]::GetAttributes($mapPath)
            if (($attributes -band [IO.FileAttributes]::ReadOnly) -ne 0) {
                throw 'The read-only attribute is still set.'
            }
            $writeProbe = [IO.File]::Open(
                $mapPath,
                [IO.FileMode]::Open,
                [IO.FileAccess]::ReadWrite,
                [IO.FileShare]::None
            )
            $writeProbe.Dispose()
        } catch {
            throw "The WASD installer cannot write '$mapPath'. Close Heavy Gear if it is running, and check this file's permissions. Details: $($_.Exception.Message)"
        }
    }

    $controlsExecutable = $null
    $controlsArguments = @()
    if ($controlsExeCommand) {
        $controlsExecutable = $controlsExeCommand.Source
        $controlsArguments = @($game, 'wasd')
    } elseif ($pythonLauncher) {
        $controlsExecutable = $pythonLauncher.Source
        $controlsArguments = @('-3', $controlsScript, $game, 'wasd')
    } else {
        $controlsExecutable = $pythonCommand.Source
        $controlsArguments = @($controlsScript, $game, 'wasd')
    }

    $outputBase = Join-Path ([IO.Path]::GetTempPath()) (
        'heavygear-controls-{0}-{1}' -f $PID, [Guid]::NewGuid().ToString('N')
    )
    $stdoutPath = "$outputBase.stdout"
    $stderrPath = "$outputBase.stderr"
    try {
        $argumentLine = ($controlsArguments | ForEach-Object {
            ConvertTo-ProcessArgument ([string]$_)
        }) -join ' '
        $controlsProcess = Start-Process -FilePath $controlsExecutable `
            -ArgumentList $argumentLine -Wait -PassThru -NoNewWindow `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $controlsExitCode = $controlsProcess.ExitCode
        $controlsOutput = @()
        if (Test-Path -LiteralPath $stdoutPath -PathType Leaf) {
            $controlsOutput += Get-Content -LiteralPath $stdoutPath
        }
        if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
            $controlsOutput += Get-Content -LiteralPath $stderrPath
        }
    } catch {
        throw "The WASD control installer could not be started: $($_.Exception.Message)"
    } finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
    if ($controlsOutput.Count -gt 0) {
        $controlsOutput | ForEach-Object { Write-Host $_ }
    }
    if ($controlsExitCode -ne 0) {
        $diagnostic = ($controlsOutput | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
        if (-not $diagnostic) {
            $diagnostic = 'The control tool did not provide additional error details.'
        }
        throw "The WASD control installer failed with exit code $controlsExitCode.`r`n$diagnostic"
    }
}

if ($InstallSystemComponents) {
    try {
        if (-not $codec) {
            $temporaryCodecDirectory = Join-Path ([IO.Path]::GetTempPath()) (
                'heavygear-codec-{0}-{1}' -f $PID, [Guid]::NewGuid().ToString('N')
            )
            New-Item -ItemType Directory -Path $temporaryCodecDirectory | Out-Null
            & $unshieldExecutable -d $temporaryCodecDirectory x $codecCabinet
            if ($LASTEXITCODE -ne 0) {
                throw "unshield failed with exit code $LASTEXITCODE while extracting '$codecCabinet'."
            }
            $codecFile = Get-ChildItem -LiteralPath $temporaryCodecDirectory -Filter 'ir50_32.dll' -File -Recurse |
                Select-Object -First 1
            if (-not $codecFile) {
                throw "ir50_32.dll was not found in '$codecCabinet' after extracting it with unshield."
            }
            $codec = $codecFile.FullName
        }
        $codecDestination = Join-Path $systemDirectory 'ir50_32.dll'
        Copy-SystemFileWithoutReplacing -Source $codec -Destination $codecDestination

        $codecRegistry = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
            [Microsoft.Win32.RegistryHive]::LocalMachine,
            [Microsoft.Win32.RegistryView]::Registry32
        )
        try {
            $drivers = $codecRegistry.CreateSubKey('Software\Microsoft\Windows NT\CurrentVersion\Drivers32')
            try {
                $registeredCodec = $drivers.GetValue('vidc.iv50', $null)
                if ($registeredCodec -and $registeredCodec -ine 'ir50_32.dll') {
                    throw "The 32-bit Indeo codec is already registered as '$registeredCodec'; refusing to replace it."
                }
                $drivers.SetValue('vidc.iv50', 'ir50_32.dll', [Microsoft.Win32.RegistryValueKind]::String)
            } finally {
                $drivers.Dispose()
            }
        } finally {
            $codecRegistry.Dispose()
        }

        $fontView = if ([Environment]::Is64BitOperatingSystem) {
            [Microsoft.Win32.RegistryView]::Registry64
        } else {
            [Microsoft.Win32.RegistryView]::Registry32
        }
        $fontRegistry = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
            [Microsoft.Win32.RegistryHive]::LocalMachine,
            $fontView
        )
        try {
            $fontKey = $fontRegistry.CreateSubKey('SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts')
            try {
                Add-Type -AssemblyName System.Drawing
                foreach ($font in $fonts) {
                    $fontDestination = Join-Path (Join-Path $env:WINDIR 'Fonts') $font.Name
                    Copy-SystemFileWithoutReplacing -Source $font.FullName -Destination $fontDestination

                    $fontCollection = New-Object System.Drawing.Text.PrivateFontCollection
                    try {
                        $fontCollection.AddFontFile($fontDestination)
                        if ($fontCollection.Families.Count -ne 1) {
                            throw "Expected one font family in '$($font.Name)'."
                        }
                        $fontName = "$($fontCollection.Families[0].Name) $($font.BaseName) (TrueType)"
                    } finally {
                        $fontCollection.Dispose()
                    }
                    $registeredFont = $fontKey.GetValue($fontName, $null)
                    if ($registeredFont -and $registeredFont -ine $font.Name) {
                        throw "The font '$fontName' is already registered as '$registeredFont'; refusing to replace it."
                    }
                    $fontKey.SetValue($fontName, $font.Name, [Microsoft.Win32.RegistryValueKind]::String)
                }
            } finally {
                $fontKey.Dispose()
            }
        } finally {
            $fontRegistry.Dispose()
        }
    } finally {
        if ($temporaryCodecDirectory -and (Test-Path -LiteralPath $temporaryCodecDirectory -PathType Container)) {
            Remove-Item -LiteralPath $temporaryCodecDirectory -Recurse -Force
        }
    }

    Write-Host 'Registered Indeo 5 for 32-bit video playback and installed the game fonts.'
}

Write-Host ''
Write-Host "Heavy Gear is ready in: $game"
Write-Host 'Insert or mount disc 2 in the first CD/DVD drive before playing; music requires CD audio.'
if (-not $InstallSystemComponents) {
    Write-Host 'System-wide font and Indeo 5 installation was skipped. For cutscene support, re-run with -InstallSystemComponents (and -CodecPath if you have an extracted codec DLL).'
}
Write-Host 'Direct3D 9 renderer is not installed during game setup; it requires the official 1.2 update.'
