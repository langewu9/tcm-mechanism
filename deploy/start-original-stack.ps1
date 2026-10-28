param([switch]$NoBrowser, [switch]$NoPopup)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$logRoot = Join-Path $projectRoot 'var\launcher'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ('startup-{0}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$mutex = New-Object System.Threading.Mutex($false, 'Local\YuanzhiOriginalDatabaseLauncher')
$ownsMutex = $false
$transcribing = $false
$exitCode = 0

function Show-Notice([string]$Message, [bool]$IsError = $false) {
    if (!$NoPopup) {
        $notice = New-Object -ComObject WScript.Shell
        $icon = if ($IsError) { 16 } else { 64 }
        $null = $notice.Popup($Message, 20, 'Yuanzhi Platform', $icon)
    }
}

function Invoke-DockerChecked([string[]]$DockerArguments) {
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $commandOutput = & $script:dockerBin @DockerArguments 2>&1
        $commandExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    $commandOutput | ForEach-Object { Write-Host $_ }
    if ($commandExit -ne 0) {
        throw ('Docker command failed ({0}): docker {1}' -f $commandExit, ($DockerArguments -join ' '))
    }
}

function Test-DockerReady {
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $null = & $script:dockerBin info --format '{{.ServerVersion}}' 2>$null
        return ($LASTEXITCODE -eq 0)
    } finally { $ErrorActionPreference = $savedPreference }
}

function Wait-Http([string]$Url, [int]$TimeoutSeconds = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
            if ($response.StatusCode -eq 200) { return $response }
        } catch { }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Url"
}

try {
    try { $ownsMutex = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (!$ownsMutex) {
        Show-Notice 'The platform is already starting. Please wait for the browser to open.'
        exit 0
    }
    Start-Transcript -Path $logFile | Out-Null
    $transcribing = $true
    Set-Location -LiteralPath $projectRoot
    Write-Host "Project: $projectRoot"
    Write-Host "Startup log: $logFile"

    $databaseFile = Join-Path $projectRoot 'python_app\var\qa.sqlite3'
    if (!(Test-Path -LiteralPath $databaseFile -PathType Leaf) -or (Get-Item -LiteralPath $databaseFile).Length -lt 1MB) {
        throw 'Original database missing or unexpectedly small. Startup refused; no replacement database was created.'
    }
    $composeFile = Join-Path $PSScriptRoot 'compose.original-sqlite.yml'
    $composeArguments = @('compose', '-p', 'deploy', '-f', $composeFile)
    $dockerCandidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    )
    $dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($dockerCommand) { $dockerCandidates += $dockerCommand.Source }
    $script:dockerBin = $dockerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (!$script:dockerBin) { throw 'Docker Desktop is not installed.' }

    Write-Host '[1/5] Starting Docker Desktop and waiting for the Linux engine...'
    if (!(Test-DockerReady)) {
        $desktopCandidates = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
            (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
        )
        $desktopExe = $desktopCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (!$desktopExe) { throw 'Docker Desktop executable was not found.' }
        if (!(Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            Start-Process -FilePath $desktopExe -WindowStyle Hidden | Out-Null
        }
        $engineDeadline = (Get-Date).AddMinutes(5)
        while (!(Test-DockerReady)) {
            if ((Get-Date) -ge $engineDeadline) { throw 'Docker Linux engine did not become ready within 5 minutes. Open Docker Desktop to check its status.' }
            Start-Sleep -Seconds 3
        }
    }

    Write-Host '[2/5] Starting original-database Django, Redis, R and both analysis workers...'
    Invoke-DockerChecked ($composeArguments + @('up', '-d', '--no-build', '--wait', '--wait-timeout', '180', 'redis', 'r-viz', 'api', 'worker', 'r-worker'))

    Write-Host '[3/5] Checking Django, internal R renderer and task queues...'
    $null = Wait-Http 'http://127.0.0.1:8020/api/v1/health/'
    Invoke-DockerChecked @('exec', 'deploy-api-1', 'python', '-c', "import json,urllib.request; r=json.load(urllib.request.urlopen('http://r-viz:8001/health',timeout=10)); assert r.get('status')=='ok',r; print('R renderer healthy:', r.get('rendererVersion'))")
    $normalHostname = (& $script:dockerBin inspect --format '{{.Config.Hostname}}' deploy-worker-1).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not identify the analysis worker.' }
    $rHostname = (& $script:dockerBin inspect --format '{{.Config.Hostname}}' deploy-r-worker-1).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not identify the R worker.' }
    $normalNode = 'original-worker@' + $normalHostname
    $rNode = 'original-r-worker@' + $rHostname
    $queueDeadline = (Get-Date).AddSeconds(60)
    do {
        $savedPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $queueText = & $script:dockerBin exec deploy-api-1 celery -A config inspect active_queues --json --timeout=3 "--destination=$normalNode,$rNode" 2>$null
            $queueExit = $LASTEXITCODE
        } finally { $ErrorActionPreference = $savedPreference }
        try { $queues = ($queueText -join "`n") | ConvertFrom-Json } catch { $queues = $null }
        $queuesReady = $queueExit -eq 0 -and $queues -and @($queues.$normalNode.name) -contains 'celery' -and @($queues.$rNode.name) -contains 'r_visualization'
        if (!$queuesReady) { Start-Sleep -Seconds 2 }
    } until ($queuesReady -or (Get-Date) -ge $queueDeadline)
    if (!$queuesReady) { throw 'One or both analysis workers did not register their expected queues.' }
    Write-Host 'Both analysis queues are ready.'

    Write-Host '[4/5] Starting or reusing the frontend on 127.0.0.1:5173...'
    $webRoot = Join-Path $projectRoot 'web'
    $viteScript = Join-Path $webRoot 'node_modules\vite\bin\vite.js'
    if (!(Test-Path -LiteralPath $viteScript)) { throw 'Frontend dependencies are missing. Run npm ci in the web directory, then retry.' }
    $nodeCandidates = @((Join-Path $env:ProgramFiles 'nodejs\node.exe'), (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe'))
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($nodeCommand) { $nodeCandidates += $nodeCommand.Source }
    $nodeBin = $nodeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (!$nodeBin) { throw 'Node.js was not found.' }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        foreach ($listener in $listeners) {
            $existingNode = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
            if (!$existingNode -or !$existingNode.CommandLine -or $existingNode.CommandLine.IndexOf($viteScript, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
                throw "Port 5173 is occupied by a different process (PID $($listener.OwningProcess)); nothing was stopped."
            }
        }
        Write-Host 'Reusing the existing frontend process.'
    } else {
        $frontendProcess = Start-Process -FilePath $nodeBin -ArgumentList @(('"' + $viteScript + '"'), '--host', '127.0.0.1', '--port', '5173', '--strictPort') -WorkingDirectory $webRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'frontend.stdout.log') -RedirectStandardError (Join-Path $logRoot 'frontend.stderr.log') -PassThru
        @{ processId = $frontendProcess.Id; projectRoot = $projectRoot; startedAt = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot 'frontend-process.json') -Encoding UTF8
        Write-Host "Frontend PID: $($frontendProcess.Id)"
    }
    $websiteUrl = 'http://127.0.0.1:5173/'
    $page = Wait-Http $websiteUrl
    if ($page.Content -notmatch 'AI Scientist') { throw 'Unexpected page on frontend port 5173.' }
    $null = Wait-Http 'http://127.0.0.1:5173/api/v1/health/'
    $stats = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173/api/v1/home-stats/' -TimeoutSec 15).Content | ConvertFrom-Json
    Write-Host ('Original database counts: ' + ($stats.counts | ConvertTo-Json -Compress))

    Write-Host '[5/5] All services are ready.'
    if (!$NoBrowser) { Start-Process $websiteUrl | Out-Null }
    Write-Host "Open: $websiteUrl"
} catch {
    $exitCode = 1
    Write-Host ('Startup failed: ' + $_.Exception.Message) -ForegroundColor Red
    Show-Notice ("Startup failed: " + $_.Exception.Message + "`r`n`r`nLog: " + $logFile) $true
} finally {
    if ($transcribing) { Stop-Transcript | Out-Null }
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
exit $exitCode
