param(
  [ValidateRange(1024, 65535)][int]$Port = 8002,
  [string]$Rscript = 'D:\R\R-4.6.1\bin\x64\Rscript.exe'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$qaRoot = Join-Path (Split-Path -Parent $repoRoot) 'test_data\r_interactive_20261013'
$python = Join-Path $repoRoot 'python_app\.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $Rscript) -or !(Test-Path -LiteralPath $python)) { throw 'Existing R or Python runtime is missing.' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "Port $Port is occupied; no existing service was stopped." }
New-Item -ItemType Directory -Path $qaRoot -Force | Out-Null
$env:R_LIBS_USER = 'D:/R/library/4.6'
$env:PORT = [string]$Port
$env:R_VIZ_API_TOKEN = [Guid]::NewGuid().ToString('N')
$env:R_VIZ_BASE_URL = "http://127.0.0.1:$Port"
$env:PYTHONUTF8 = '1'
$helper = Start-Process -FilePath $Rscript -ArgumentList @('run_local.R') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $qaRoot 'renderer.stdout.log') -RedirectStandardError (Join-Path $qaRoot 'renderer.stderr.log') -PassThru
try {
  $ready = $false
  for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try { $health = Invoke-RestMethod -Uri "$env:R_VIZ_BASE_URL/health" -TimeoutSec 2; if ($health.rendererVersion -eq 'r-viz-0.4.0') { $ready = $true; break } } catch {}
    Start-Sleep -Milliseconds 500
  }
  if (!$ready) { throw 'Renderer did not become ready.' }
  Push-Location $repoRoot
  try {
    & $python 'r_viz/prepare_demo_gallery.py'; if ($LASTEXITCODE -ne 0) { throw 'Demo regeneration failed.' }
    & $python 'r_viz/prepare_public_gallery.py'; if ($LASTEXITCODE -ne 0) { throw 'Public example rendering failed.' }
  } finally { Pop-Location }
  Push-Location $PSScriptRoot
  try {
    & $Rscript 'tests/style_contract.R'; if ($LASTEXITCODE -ne 0) { throw 'R style regression failed.' }
    & $Rscript 'tests/interactive_contract.R'; if ($LASTEXITCODE -ne 0) { throw 'R interactive regression failed.' }
    & $Rscript 'tests/render_grayscale.R' $qaRoot; if ($LASTEXITCODE -ne 0) { throw 'Grayscale review render failed.' }
  } finally { Pop-Location }
} finally {
  # Windows' bin/Rscript.exe can launch an architecture-specific child process.
  $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($helper.Id)" -ErrorAction SilentlyContinue
  foreach ($child in $children) {
    if ($child.ExecutablePath -like '*\Rscript.exe' -and $child.CommandLine -match 'run_local\.R') {
      Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
    }
  }
  $helper.Refresh()
  if (!$helper.HasExited) { Stop-Process -Id $helper.Id }
  Write-Output 'Temporary authenticated R renderer stopped; existing services and task artifacts unchanged.'
}
