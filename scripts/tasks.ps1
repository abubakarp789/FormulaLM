<#
.SYNOPSIS
  Windows task runner (equivalent of the Makefile).
.EXAMPLE
  .\scripts\tasks.ps1 test
  .\scripts\tasks.ps1 data -- --config config/default.yaml
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'setup', 'test', 'lint', 'format', 'sheets', 'data', 'eval', 'reqs')]
    [string]$Task = 'help',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

function Invoke-Step([string]$Exe, [string[]]$ArgList) {
    & $Exe @ArgList
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Task) {
    'help'   { Get-Help $PSCommandPath -Detailed; 'Tasks: setup test lint format sheets data eval reqs' }
    'setup'  { Invoke-Step uv @('sync') }
    'test'   { Invoke-Step uv (@('run', 'pytest') + $Rest) }
    'lint'   { Invoke-Step uv @('run', 'ruff', 'check', '.'); Invoke-Step uv @('run', 'ruff', 'format', '--check', '.') }
    'format' { Invoke-Step uv @('run', 'ruff', 'format', '.'); Invoke-Step uv @('run', 'ruff', 'check', '--fix', '.') }
    'sheets' { Invoke-Step uv (@('run', 'python', '-m', 'src.data.sheets') + $Rest) }
    'data'   { Invoke-Step uv (@('run', 'python', 'scripts/generate_data.py') + $Rest) }
    'eval'   { Invoke-Step uv (@('run', 'python', 'scripts/evaluate.py') + $Rest) }
    'reqs'   {
        Invoke-Step uv @('export', '--format', 'requirements-txt', '--no-hashes', '--no-emit-project', '-o', 'requirements.txt')
        Invoke-Step uv @('pip', 'compile', 'requirements-train.in', '-o', 'requirements-train.txt', '--python-version', '3.12', '--python-platform', 'x86_64-manylinux_2_28', '--no-header')
    }
}
