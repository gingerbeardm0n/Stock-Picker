# CheckPowerSettings.ps1
# Verify all power settings are configured for unattended overnight operation

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  POWER SETTINGS - OVERNIGHT RUN CHECK" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

$pass = "[PASS]"
$fail = "[FAIL]"
$green = "Green"
$red = "Red"

# Helper: get powercfg AC value
function Get-PowerValue($subgroup, $setting) {
    $raw = powercfg /query SCHEME_CURRENT $subgroup $setting 2>$null
    $line = $raw | Select-String "Current AC Power Setting Index"
    if ($line) {
        return [Convert]::ToInt32(($line -replace '.*:\s*0x', ''), 16)
    }
    return $null
}

# 1. Sleep timeout
$sleep = Get-PowerValue "SUB_SLEEP" "STANDBYIDLE"
if ($sleep -eq 0) {
    Write-Host "$pass Sleep timeout (AC): NEVER" -ForegroundColor $green
} else {
    Write-Host "$fail Sleep timeout (AC): $sleep seconds -- SHOULD BE 0" -ForegroundColor $red
}

# 2. Hibernate timeout
$hibernate = Get-PowerValue "SUB_SLEEP" "HIBERNATEIDLE"
if ($hibernate -eq 0) {
    Write-Host "$pass Hibernate timeout (AC): NEVER" -ForegroundColor $green
} else {
    Write-Host "$fail Hibernate timeout (AC): $hibernate seconds -- SHOULD BE 0" -ForegroundColor $red
}

# 3. Wake timers
$waketimers = Get-PowerValue "SUB_SLEEP" "RTCWAKE"
if ($waketimers -eq 1) {
    Write-Host "$pass Wake timers: ENABLED (Task Scheduler can wake machine)" -ForegroundColor $green
} else {
    Write-Host "$fail Wake timers: DISABLED -- Task Scheduler cannot wake machine" -ForegroundColor $red
}

# 4. Display timeout
$display = Get-PowerValue "SUB_VIDEO" "VIDEOIDLE"
if ($display -eq 0) {
    Write-Host "$pass Display timeout (AC): NEVER" -ForegroundColor $green
} else {
    Write-Host "$fail Display timeout (AC): $display seconds -- may drop remote sessions" -ForegroundColor $red
}

# 5. USB selective suspend
$usb = Get-PowerValue "2a737441-1930-4402-8d77-b2bebba308a3" "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"
if ($usb -eq 0) {
    Write-Host "$pass USB selective suspend: DISABLED (dock stays alive)" -ForegroundColor $green
} else {
    Write-Host "$fail USB selective suspend: ENABLED -- may kill dock mid-session" -ForegroundColor $red
}

# 6. Hibernate file
$hiberfil = Test-Path "C:\hiberfil.sys"
if (-not $hiberfil) {
    Write-Host "$pass Hibernate file (hiberfil.sys): REMOVED" -ForegroundColor $green
} else {
    Write-Host "$fail Hibernate file exists -- hibernation not fully disabled" -ForegroundColor $red
}

# 7. Scheduled tasks
Write-Host "`n--- Scheduled Tasks ---" -ForegroundColor Cyan
foreach ($tn in @("TranscriptCompression-2300", "TranscriptCompression-0400")) {
    $task = schtasks /query /tn $tn 2>$null
    if ($task) {
        $nextRun = ($task | Select-String "^\S").ToString() -replace '\s+', ' '
        Write-Host "$pass Task '$tn': EXISTS" -ForegroundColor $green
        $task | Select-String "Next Run Time" | ForEach-Object { Write-Host "       $_" }
    } else {
        Write-Host "$fail Task '$tn': NOT FOUND" -ForegroundColor $red
    }
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Done. All $pass = ready for overnight run." -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan
