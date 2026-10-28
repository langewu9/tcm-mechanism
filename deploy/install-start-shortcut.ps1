$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot 'start-original-stack.ps1'
if (!(Test-Path -LiteralPath $launcher)) { throw 'Launcher file is missing.' }
$shortcutName = -join ([char[]]@(0x8fdc, 0x5fd7, 0x5e73, 0x53f0, 0x4e00, 0x952e, 0x542f, 0x52a8))
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop ($shortcutName + '.lnk')
if (Test-Path -LiteralPath $shortcutPath) { throw "Shortcut already exists; no existing shortcut was replaced: $shortcutPath" }
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '"'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = 'Start Docker Desktop, original-database Django, R, analysis queues and the Yuanzhi website.'
$shortcut.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',13'
$shortcut.Save()
Write-Output "Created desktop shortcut: $shortcutPath"
