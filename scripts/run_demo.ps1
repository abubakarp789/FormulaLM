<#
.SYNOPSIS
  One-command launcher for the local FormulaLM Gradio demo (Windows PowerShell).
.DESCRIPTION
  Enforces OLLAMA_MAX_LOADED_MODELS=1 (for 8 GB RAM laptops). Works on a clean clone
  without a pre-populated models/ folder:
  1. If 'formulalm' is already registered in Ollama (e.g. from the Quick-Start), uses it directly.
  2. Otherwise checks models\gguf_v2\formulalm-qwen3-1.7b-v2-q5_k_m.gguf; if absent, downloads it
     automatically from Hugging Face (-DownloadSource hf) or ModelScope (-DownloadSource modelscope)
     into models\gguf_v2\ and runs 'ollama create formulalm -f deploy/Modelfile'.
.EXAMPLE
  .\scripts\run_demo.ps1
  .\scripts\run_demo.ps1 -DownloadSource modelscope
  .\scripts\run_demo.ps1 -Backend mock
#>
param(
    [ValidateSet('ollama', 'llamacpp', 'mock')]
    [string]$Backend = 'ollama',
    [string]$Model = 'formulalm',
    [string]$BaseUrl = '',
    [int]$Port = 7860,
    [ValidateSet('hf', 'modelscope')]
    [string]$DownloadSource = 'hf'
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
        throw "Ollama CLI not found on PATH. Install Ollama (https://ollama.com) or run with -Backend mock."
    }

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

    $tagsJson = (Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5)
    $existingNames = @($tagsJson.models | ForEach-Object { $_.name })
    $hasTag = ($existingNames -contains $Model) -or ($existingNames -contains "${Model}:latest")

    if (-not $hasTag -and $Model -eq 'formulalm') {
        $ggufDir = Join-Path $RepoRoot 'models\gguf_v2'
        $ggufFile = 'formulalm-qwen3-1.7b-v2-q5_k_m.gguf'
        $ggufPath = Join-Path $ggufDir $ggufFile
        $modelfilePath = Join-Path $RepoRoot 'deploy\Modelfile'

        if (-not (Test-Path $ggufPath)) {
            New-Item -ItemType Directory -Force -Path $ggufDir | Out-Null
            if ($DownloadSource -eq 'modelscope') {
                $url = "https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-gguf/resolve/master/$ggufFile"
            } else {
                $url = "https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf/resolve/main/$ggufFile"
            }
            Write-Host "Downloading $ggufFile (~1.20 GB) from $url -> $ggufPath ..."
            & curl.exe -L --fail -o $ggufPath $url
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to download $ggufFile from $url"
            }
        }

        Write-Host "Registering '$Model' in Ollama from deploy/Modelfile..."
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("formulalm_ollama_" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tmpDir | Out-Null
        try {
            $dstGguf = Join-Path $tmpDir $ggufFile
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
