[CmdletBinding()]
param(
    [string]$D3D9IncludePath,
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$renderer = Join-Path $project 'renderer\hgd3d9'
if (-not $OutputPath) {
    $OutputPath = Join-Path $project 'dist\3dfx_hgd3d9.dll'
} elseif (-not [IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath = Join-Path $project $OutputPath
}
$OutputPath = [IO.Path]::GetFullPath($OutputPath)

function Resolve-Tool([string]$Name) {
    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Required build tool '$Name' was not found on PATH. Install the LLVM Windows toolchain and reopen PowerShell."
    }
    return $command.Source
}

function Resolve-Python {
    $candidates = @()
    if ($env:HG_PYTHON) {
        $configured = Get-Command $env:HG_PYTHON -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($configured) {
            $candidates += [pscustomobject]@{ Path = [string]$configured.Source; Prefix = @() }
        }
    }
    foreach ($name in @('python', 'py')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if (-not $command) {
            continue
        }
        if ($name -eq 'py') {
            $candidates += [pscustomobject]@{ Path = [string]$command.Source; Prefix = @('-3') }
        } else {
            $candidates += [pscustomobject]@{ Path = [string]$command.Source; Prefix = @() }
        }
    }

    foreach ($candidate in $candidates) {
        $prefix = @($candidate.Prefix)
        & $candidate.Path @prefix -c 'import sys; raise SystemExit(sys.version_info.major != 3)' *> $null
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }
    throw 'Python 3 was not found. Install Python 3 from python.org, then reopen PowerShell.'
}

function Resolve-D3D9Include([string]$RequestedPath) {
    $directories = @()
    if ($RequestedPath) {
        $directories += [IO.Path]::GetFullPath($RequestedPath)
    }

    $sdkRoots = @()
    if ($env:WindowsSdkDir) {
        $sdkRoots += (Join-Path $env:WindowsSdkDir 'Include')
    }
    $registry = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots' `
        -Name KitsRoot10 -ErrorAction SilentlyContinue
    if ($registry -and $registry.KitsRoot10) {
        $sdkRoots += (Join-Path $registry.KitsRoot10 'Include')
    }
    foreach ($root in ($sdkRoots | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $root -PathType Container) {
            $versions = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
                Sort-Object { try { [version]$_.Name } catch { [version]'0.0' } } -Descending
            foreach ($version in $versions) {
                $directories += (Join-Path $version.FullName 'um')
                $directories += (Join-Path $version.FullName 'shared')
            }
        }
    }
    foreach ($programFiles in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if ($programFiles) {
            $directories += (Join-Path $programFiles 'Microsoft DirectX SDK (June 2010)\Include')
        }
    }

    foreach ($directory in ($directories | Select-Object -Unique)) {
        if ($directory -and
            (Test-Path -LiteralPath (Join-Path $directory 'd3d9.h') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $directory 'd3d9types.h') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $directory 'd3d9caps.h') -PathType Leaf)) {
            return $directory
        }
    }
    throw 'Direct3D 9 headers were not found. Install the Windows 10/11 SDK or DirectX SDK (June 2010), or pass their header directory with -D3D9IncludePath.'
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "'$Executable' failed with exit code $LASTEXITCODE."
    }
}

$clang = Resolve-Tool 'clang'
$dlltool = Resolve-Tool 'llvm-dlltool'
$linker = Resolve-Tool 'lld-link'
$readobj = Resolve-Tool 'llvm-readobj'
$python = Resolve-Python
$d3d9Include = Resolve-D3D9Include $D3D9IncludePath

$outputDirectory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$work = Join-Path ([IO.Path]::GetTempPath()) ("heavygear-renderer-{0}-{1}" -f $PID, [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null

try {
    Copy-Item -Path (Join-Path $renderer '*.c') -Destination $work
    Copy-Item -Path (Join-Path $renderer '*.h') -Destination $work
    foreach ($definition in @('kernel32.def', 'user32.def', 'd3d9.def')) {
        Copy-Item -LiteralPath (Join-Path $renderer $definition) -Destination $work
    }

    Invoke-Checked $python.Path ($python.Prefix + @(
        (Join-Path $renderer 'gen_d3d9_min.py'),
        '--d3d9-include', $d3d9Include,
        '--out', (Join-Path $work 'd3d9_min.h')
    ))
    Invoke-Checked $python.Path ($python.Prefix + @(
        (Join-Path $renderer 'gen_shaders.py'),
        (Join-Path $work 'shaders.h')
    ))

    $kernel32Lib = Join-Path $work 'k32.lib'
    $user32Lib = Join-Path $work 'u32.lib'
    $d3d9Lib = Join-Path $work 'd3d9.lib'
    Invoke-Checked $dlltool @('-m', 'i386', '-d', (Join-Path $work 'kernel32.def'), '-l', $kernel32Lib, '-k')
    Invoke-Checked $dlltool @('-m', 'i386', '-d', (Join-Path $work 'user32.def'), '-l', $user32Lib, '-k')
    Invoke-Checked $dlltool @('-m', 'i386', '-d', (Join-Path $work 'd3d9.def'), '-l', $d3d9Lib, '-k')

    $sources = @('hgd3d9', 'convert', 'texcache', 'capture', 'null_backend', 'rt', 'd3d9')
    $objects = @()
    $flags = @(
        '--target=i686-pc-windows-msvc', '-std=c11', '-Wall', '-Wextra', '-O2',
        '-ffreestanding', '-fno-stack-protector', '-fno-builtin',
        '-DHG_BACKEND=hg_backend_d3d9'
    )
    foreach ($source in $sources) {
        $object = Join-Path $work "$source.obj"
        Invoke-Checked $clang ($flags + @('-c', (Join-Path $work "$source.c"), '-o', $object))
        $objects += $object
    }

    Invoke-Checked $linker (@(
        '/dll', '/nodefaultlib', '/entry:DllMain', '/machine:x86', "/out:$OutputPath"
    ) + $objects + @($kernel32Lib, $user32Lib, $d3d9Lib))

    $headers = & $readobj '--file-headers' $OutputPath
    if ($LASTEXITCODE -ne 0 -or ($headers -join "`n") -notmatch 'IMAGE_FILE_MACHINE_I386') {
        throw "The renderer output is not a valid x86 Windows DLL: $OutputPath"
    }
    $exports = & $readobj '--coff-exports' $OutputPath
    if ($LASTEXITCODE -ne 0 -or ($exports -join "`n") -notmatch '\bCheckFunc\b') {
        throw "The renderer DLL is missing its required CheckFunc export: $OutputPath"
    }

    Write-Host "Built and verified x86 renderer DLL: $OutputPath"
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force
}
