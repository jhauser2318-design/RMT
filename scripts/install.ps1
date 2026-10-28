# ---------------------------------------------------------------------------
# RMT (Risky Money Time) - Windows installer
#
# Run it by double-clicking INSTALL.bat in the project folder. It:
#   1. finds Python (and installs it for you if it's missing)
#   2. copies the app to  C:\Users\<you>\RMT
#   3. installs the Python packages the app needs
#   4. asks for your Anthropic API key (or reuses Life Control Center's) and saves it in .env
#   5. puts an "RMT" icon on your Desktop and in the Start menu
#   6. starts RMT and opens it in its own window
#
# Safe to run again: your .env file (keys) and data folder are never overwritten.
# ---------------------------------------------------------------------------
$ErrorActionPreference = "Stop"

$Source = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path.TrimEnd("\")
$Target = Join-Path $env:USERPROFILE "RMT"
$AppName = "RMT"

function Say($msg, $color = "Cyan") { Write-Host $msg -ForegroundColor $color }
function Fail($msg) {
    Write-Host ""
    Write-Host $msg -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to close this window"
    exit 1
}

Write-Host ""
Say "=============================================="
Say "   $AppName - setup"
Say "=============================================="
Write-Host ""

# --- 1. Python -------------------------------------------------------------

function Test-Python($exe) {
    try {
        $v = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -and ([version]$v.Trim() -ge [version]"3.10")) { return $true }
    } catch {}
    return $false
}

function Find-Python {
    $candidates = @()
    foreach ($name in @("py", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        # Skip the "python" shortcut that only opens the Microsoft Store.
        if ($cmd -and $cmd.Source -notlike "*WindowsApps*") { $candidates += $cmd.Source }
    }
    $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    $candidates += Get-ChildItem "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    foreach ($c in $candidates) { if (Test-Python $c) { return $c } }
    return $null
}

Say "[1/5] Looking for Python..."
$Python = Find-Python
if (-not $Python) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Start-Process "https://www.python.org/downloads/"
        Fail ("Python isn't installed, and it couldn't be installed automatically.`n" +
              "The Python download page just opened in your browser. Install it, making sure to tick`n" +
              "'Add python.exe to PATH', then double-click INSTALL.bat again.")
    }
    Say "      Python not found - installing it now (this can take a few minutes)..." "Yellow"
    & winget install --exact --id Python.Python.3.12 --scope user --silent `
        --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "Machine")
    $Python = Find-Python
    if (-not $Python) {
        Fail ("Python was installed but can't be found yet.`n" +
              "Please restart your computer, then double-click INSTALL.bat again.")
    }
}
Say "      Using Python: $Python" "Green"

# --- 2. Copy the app to its permanent home ---------------------------------

Say "[2/5] Copying the app to $Target ..."
if ($Source -ne $Target.TrimEnd("\")) {
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    # /E = include subfolders. Never copy over your data, key, or the Python environment.
    & robocopy $Source $Target /E /XD .venv data __pycache__ .git /XF .env /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "Copying the files failed (robocopy error $LASTEXITCODE)." }
}
New-Item -ItemType Directory -Force -Path (Join-Path $Target "data") | Out-Null
Say "      Done." "Green"

# --- 3. Python packages ----------------------------------------------------

Say "[3/5] Installing the packages the app needs (first time takes a minute)..."
$VenvPython = Join-Path $Target ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    & $Python -m venv (Join-Path $Target ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "Couldn't create the Python environment." }
}
& $VenvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $Target "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "Installing packages failed. Check your internet connection and run INSTALL.bat again." }
Say "      Done." "Green"

# --- 4. API key ------------------------------------------------------------

Say "[4/5] Anthropic API key"
$EnvFile = Join-Path $Target ".env"
$HasKey = (Test-Path $EnvFile) -and
          (Select-String -Path $EnvFile -Pattern "^\s*ANTHROPIC_API_KEY\s*=\s*sk-ant-" -Quiet)

if ($HasKey) {
    Say "      Your API key is already saved. Keeping it." "Green"
} else {
    # Already set up Life Control Center? Reuse its key.
    $Key = ""
    $LccEnv = Join-Path $env:USERPROFILE "LifeControlCenter\.env"
    if (Test-Path $LccEnv) {
        $line = Select-String -Path $LccEnv -Pattern "^\s*ANTHROPIC_API_KEY\s*=\s*(sk-ant-\S+)" | Select-Object -First 1
        if ($line -and $line.Matches[0].Groups[1].Value -notlike "*your-key*") {
            $Key = $line.Matches[0].Groups[1].Value
            Say "      Found your key from Life Control Center. Using it for RMT too." "Green"
        }
    }
    if (-not $Key) {
        Write-Host ""
        Write-Host "      The 'Ask RMT' AI chat uses Claude, which needs an API key from"
        Write-Host "      https://console.anthropic.com  (Settings > API Keys > Create Key)."
        Write-Host "      It starts with sk-ant-  . To paste here: right-click, or press Ctrl+V."
        Write-Host "      (No key yet? Just press Enter. Everything else in RMT works without it.)"
        Write-Host ""
        while ($true) {
            $Key = (Read-Host "      Paste your API key").Trim().Trim('"')
            if ($Key -eq "" -or $Key.StartsWith("sk-ant-")) { break }
            Say "      That doesn't look like an Anthropic key (it should start with sk-ant-). Try again." "Yellow"
        }
    }
    $lines = Get-Content (Join-Path $Target ".env.example")
    if (Test-Path $EnvFile) { $lines = Get-Content $EnvFile }
    if ($Key) {
        $lines = $lines | ForEach-Object {
            if ($_ -match "^\s*ANTHROPIC_API_KEY\s*=") { "ANTHROPIC_API_KEY=$Key" } else { $_ }
        }
    }
    # ASCII: no invisible "BOM" bytes at the start of the file.
    Set-Content -Path $EnvFile -Value $lines -Encoding Ascii
    if ($Key) {
        Say "      Saved in $EnvFile (this file stays on your computer)." "Green"
    } else {
        Say "      Skipped. Later, open $EnvFile in Notepad and paste it after ANTHROPIC_API_KEY=" "Yellow"
    }
}

# --- 5. Shortcuts ----------------------------------------------------------

Say "[5/5] Adding '$AppName' to your Desktop and Start menu..."
$shell = New-Object -ComObject WScript.Shell
$places = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
foreach ($dir in $places) {
    if (-not $dir) { continue }
    $lnk = $shell.CreateShortcut((Join-Path $dir "$AppName.lnk"))
    # pythonw.exe runs the launcher without a black console window. The launcher
    # starts the app and opens it in its own window (see launcher.pyw).
    $lnk.TargetPath = Join-Path $Target ".venv\Scripts\pythonw.exe"
    $lnk.Arguments = '"' + (Join-Path $Target "launcher.pyw") + '"'
    $lnk.WorkingDirectory = $Target
    $lnk.IconLocation = (Join-Path $Target "frontend\icon.ico") + ",0"
    $lnk.Description = "Open $AppName"
    $lnk.Save()
}
Say "      Done." "Green"

Write-Host ""
Say "==============================================" "Green"
Say "   All set!" "Green"
Say "==============================================" "Green"
Write-Host ""
Write-Host "   From now on, just double-click  '$AppName'  on your Desktop."
Write-Host "   (It's also in the Start menu.) RMT opens in its own window;"
Write-Host "   closing that window closes RMT. To get a new version, click the"
Write-Host "   gear icon inside RMT, then Update."
Write-Host ""
Write-Host "   RMT lives in: $Target   (your keys are in .env there)"
Write-Host "   You can delete the downloaded ZIP and folder now."
Write-Host ""
Write-Host "   Starting the app for you now..."
Start-Process -FilePath (Join-Path $Target ".venv\Scripts\pythonw.exe") `
    -ArgumentList ('"' + (Join-Path $Target "launcher.pyw") + '"') -WorkingDirectory $Target
Start-Sleep -Seconds 3
