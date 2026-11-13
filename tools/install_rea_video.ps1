$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root 'output\_shared\rea-video-runtime'
$python = Join-Path $runtime 'Scripts\python.exe'
$commit = '356815c0d61291811551a2b8813b2b571d9b3238'

if (-not (Test-Path -LiteralPath $python)) {
    py -3.13 -m venv $runtime
}
& $python -m pip install --disable-pip-version-check "git+https://github.com/JuneYaooo/rea-video.git@$commit"
$env:PYTHONUTF8 = '1'
& (Join-Path $runtime 'Scripts\rea-video.exe') --help
