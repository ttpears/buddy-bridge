<#
  manage.ps1 — control the M5Stick BLE relay.
    .\manage.ps1 -Install     create the logon Startup shortcut + start it now
    .\manage.ps1 -Uninstall   remove the Startup shortcut + stop it
    .\manage.ps1 -Restart     stop all relay processes, start one fresh
    .\manage.ps1 -Stop        stop all relay processes
    .\manage.ps1 -Status      show running PID(s) + hub reachability
    .\manage.ps1 -Logs        tail relay.log
#>
param(
  [switch]$Install, [switch]$Uninstall, [switch]$Restart,
  [switch]$Stop, [switch]$Status, [switch]$Logs
)

$dir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw   = "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe"
$relay = Join-Path $dir 'relay.py'
$log   = Join-Path $dir 'relay.log'
$lnk   = Join-Path ([Environment]::GetFolderPath('Startup')) 'ClaudeBuddyRelay.lnk'

function Get-RelayProcs {
  Get-CimInstance Win32_Process -Filter "name='python.exe' or name='pythonw.exe' or name='cmd.exe' or name='wscript.exe'" |
    Where-Object { $_.CommandLine -match 'relay' }
}
function Stop-Relay {
  Get-RelayProcs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
function Start-Relay {
  Start-Process -FilePath $pyw -ArgumentList "`"$relay`"" -WorkingDirectory $dir -WindowStyle Hidden
}

if ($Stop)    { Stop-Relay; 'stopped'; return }
if ($Restart) { Stop-Relay; Start-Sleep -Milliseconds 800; Start-Relay; 'restarted'; return }
if ($Logs)    { if (Test-Path $log) { Get-Content $log -Tail 40 -Wait } else { 'no relay.log yet' }; return }
if ($Status)  {
  $p = @(Get-RelayProcs)
  if ($p.Count) { "relay: running (PID $($p.ProcessId -join ','))" } else { 'relay: not running' }
  try { $c = New-Object Net.Sockets.TcpClient('127.0.0.1', 8790); 'hub: reachable'; $c.Close() }
  catch { 'hub: unreachable (is buddyhub up in WSL?)' }
  return
}
if ($Uninstall) {
  if (Test-Path $lnk) { Remove-Item $lnk -Force }
  Stop-Relay
  'uninstalled (Startup shortcut removed, relay stopped)'
  return
}
if ($Install) {
  $ws = New-Object -ComObject WScript.Shell
  $sc = $ws.CreateShortcut($lnk)
  $sc.TargetPath       = $pyw
  $sc.Arguments        = "`"$relay`""
  $sc.WorkingDirectory = $dir
  $sc.WindowStyle      = 7            # minimized/hidden
  $sc.Description       = 'Claude Buddy BLE relay'
  $sc.Save()
  "installed Startup shortcut -> $lnk"
  Stop-Relay; Start-Sleep -Milliseconds 800; Start-Relay
  'relay started (single-instance guarded)'
  return
}
'usage: manage.ps1 -Install | -Uninstall | -Restart | -Stop | -Status | -Logs'
