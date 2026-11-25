<#
.SYNOPSIS
  One-command launcher for the local FormulaLM Gradio demo (Windows PowerShell).
.DESCRIPTION
  Enforces OLLAMA_MAX_LOADED_MODELS=1 (for 8 GB RAM laptops), ensures the local
  'formulalm' Ollama model tag exists from deploy/Modelfile + Q5_K_M GGUF when
  using the default Ollama backend, and launches app/app.py on localhost:7860.
.EXAMPLE
  .\scripts\run_demo.ps1
  .\scripts\run_demo.ps1 -Backend mock
  .\scripts\run_demo.ps1 -Port 7861
#>
param(
    [ValidateSet('ollama', 'llamacpp', 'mock')]
    [string]$Backend = 'ollama',
    [string]$Model = 'formulalm',
    [string]$BaseUrl = '',
    [int]$Port = 7860
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# Protect 8 GB laptop RAM: never keep more than 1 model loaded in Ollama.
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_NUM_PARALLEL = '1'

if ($Backend -eq 'ollama') {
    $ollamaExe = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollamaExe) {
        throw "Ollama CLI not found on PATH. Install Ollama or run with -Backend mock."
    }

    # Start Ollama server in the background if it is not already listening on 127.0.0.1:11434.
    $healthy = $false
    try {
        $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $healthy = $true }
    } catch {
        $healthy = $false
    }

    if (-not $healthy) {
        Write-Host "Starting local Ollama server with OLLAMA_MAX_LOADED_MODELS=1..."
        Start-Process -FilePath $ollamaExe.Source -ArgumentList @('serve') -WindowStyle Hidden
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Seconds 1
            try {
                $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -UseBasicParsing -TimeoutSec 2
                if ($resp.StatusCode -eq 200) { $healthy = $true; break }
            } catch {}
        }
        if (-not $healthy) {
            throw "Ollama server did not become ready on http://127.0.0.1:11434."
        }
    }

    # Ensure the requested model tag (default 'formulalm' from deploy/Modelfile) is registered.
    $tagsJson = (Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5)
    $existingNames = @($tagsJson.models | ForEach-Object { $_.name })
    $hasTag = ($existingNames -contains $Model) -or ($existingNames -contains "${Model}:latest")

    if (-not $hasTag -and $Model -eq 'formulalm') {
        $ggufPath = Join-Path $RepoRoot 'models\gguf_v2\formulalm-qwen3-1.7b-v2-q5_k_m.gguf'
        $modelfilePath = Join-Path $RepoRoot 'deploy\Modelfile'
        if (-not (Test-Path $ggufPath)) {
            throw "Primary GGUF not found at $ggufPath. Download formulalm-qwen3-1.7b-v2-q5_k_m.gguf from abubakar56/formulalm-qwen3-1.7b-gguf first."
        }
        Write-Host "Registering '$Model' in Ollama from deploy/Modelfile (isolated temp hardlink)..."
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("formulalm_ollama_" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tmpDir | Out-Null
        try {
            $dstGguf = Join-Path $tmpDir 'formulalm-qwen3-1.7b-v2-q5_k_m.gguf'
            $dstMf = Join-Path $tmpDir 'Modelfile'
            cmd /c mklink /H "$dstGguf" "$ggufPath" | Out-Null
            if ($LASTEXITCODE -ne 0) { Copy-Item $ggufPath $dstGguf }
            Copy-Item $modelfilePath $dstMf
            Push-Location $tmpDir
            try {
                & $ollamaExe.Source create $Model -f Modelfile
                if ($LASTEXITCODE -ne 0) { throw "ollama create failed with exit code $LASTEXITCODE" }
            } finally {
                Pop-Location
            }
        } finally {
            Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
        }
    }
}

$cmdArgs = @('run', 'python', 'app/app.py', '--backend', $Backend, '--model', $Model, '--port', "$Port")
if ($BaseUrl) {
    $cmdArgs += @('--base-url', $BaseUrl)
}

Write-Host "Launching FormulaLM Gradio demo on http://127.0.0.1:$Port (backend=$Backend, model=$Model)..."
& uv @cmdArgs
exit $LASTEXITCODE
