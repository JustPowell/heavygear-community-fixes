# build-exe.ps1 - build the Heavy Gear app (and developer tools) as one-file exes.
# Run from the repository folder on Windows:
#   powershell -ExecutionPolicy Bypass -File windows\build-exe.ps1 [-Target app|tools|all]
# Needs Python 3 (python.org). Output goes to dist\. The app also needs dist\3dfx_hgd3d9.dll, dist\hgcd.dll and
# dist\glide2x.dll (the 3Dfx particle-fix proxy from tools/glidelog).
param([ValidateSet('app', 'tools', 'all')][string]$Target = 'all')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
# Which Python: $env:HG_PYTHON if set, else the py launcher, else python on PATH.
if ($env:HG_PYTHON) { $py = @($env:HG_PYTHON) }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $py = @('py', '-3') }
else { $py = @('python') }
$exe, $pre = $py[0], @($py | Select-Object -Skip 1)
function Run { & $exe @pre @args; if ($LASTEXITCODE) { throw "failed: $exe $args" } }
function Run-Executable {
    param([string]$Path, [string[]]$Arguments)
    & $Path @Arguments
    if ($LASTEXITCODE) { throw "failed: $Path $Arguments" }
}
# Pinned so release builds are reproducible; bump deliberately after testing a build.
Run -m pip install pyinstaller==6.22.3
if ($Target -in 'tools', 'all') {
    Run -m PyInstaller --onefile --clean --name hgfix patcher\hgfix.py
    Run-Executable .\dist\hgfix.exe @('.', '--platform', 'windows', '--list', '--fix', 'partdepth')
    Run -m PyInstaller --onefile --clean --name hg_controls --add-data "mods;mods" patcher\hg_controls.py
    Write-Host 'Developer tools: dist\hgfix.exe, dist\hg_controls.exe'
}
if ($Target -in 'app', 'all') {
    if (-not (Test-Path -LiteralPath .\dist\3dfx_hgd3d9.dll -PathType Leaf)) {
        throw 'The x86 Direct3D 9 renderer must be built or downloaded to dist\3dfx_hgd3d9.dll before packaging the app.'
    }
    if (-not (Test-Path -LiteralPath .\dist\hgcd.dll -PathType Leaf)) {
        throw 'The music proxy must be built (tools/cdaudio/build.sh) or downloaded to dist\hgcd.dll before packaging the app.'
    }
    if (-not (Test-Path -LiteralPath .\dist\glide2x.dll -PathType Leaf)) {
        throw 'The 3Dfx particle-fix proxy must be built (tools/glidelog/build.sh, then copy its glide2x.dll) or downloaded to dist\glide2x.dll before packaging the app.'
    }
    Run -m PyInstaller --onefile --windowed --clean --name HeavyGearFixes `
        --paths app --paths patcher --paths windows --paths linux --add-data "mods;mods" `
        --add-data "dist\3dfx_hgd3d9.dll;." --add-data "dist\hgcd.dll;." --add-data "dist\glide2x.dll;." app\heavygear.py
    Run-Executable .\dist\HeavyGearFixes.exe @('--self-test')
    Write-Host 'Built: dist\HeavyGearFixes.exe (install, fixes, renderer choice, play)'
}
