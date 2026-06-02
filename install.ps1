#Requires -Version 5
$ErrorActionPreference = "Stop"

function Find-Python {
    foreach ($cand in @("py", "python", "python3")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) {
            if ($cand -eq "py") { return ,@("py", "-3") }
            return ,@($cand)
        }
    }
    return $null
}

Write-Host ""
Write-Host "  installing xcoding…" -ForegroundColor Cyan

$py = Find-Python
if (-not $py) {
    Write-Host "  Python not found. Install it from https://python.org (check 'Add to PATH')." -ForegroundColor Red
    return
}

$exe = $py[0]
$pre = @()
if ($py.Count -gt 1) { $pre = $py[1..($py.Count - 1)] }

& $exe @pre -m pip install --upgrade --user xcoding
if ($LASTEXITCODE -ne 0) {
    & $exe @pre -m pip install --upgrade xcoding
}

$scripts = (& $exe @pre -c "import sysconfig; print(sysconfig.get_path('scripts'))").Trim()
$userScripts = (& $exe @pre -c "import site,sysconfig; print(sysconfig.get_path('scripts', scheme='nt_user'))" 2>$null)
if ($userScripts) { $userScripts = $userScripts.Trim() }

foreach ($dir in @($scripts, $userScripts)) {
    if ($dir -and (Test-Path $dir)) {
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if (-not $userPath) { $userPath = "" }
        if ($userPath -notlike "*$dir*") {
            [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(';') + ";" + $dir), "User")
            Write-Host "  added to PATH: $dir" -ForegroundColor DarkGray
        }
        if ($env:Path -notlike "*$dir*") { $env:Path = $env:Path.TrimEnd(';') + ";" + $dir }
    }
}

Write-Host ""
Write-Host "  done. type " -NoNewline -ForegroundColor Green
Write-Host "xcode" -NoNewline -ForegroundColor White
Write-Host " or " -NoNewline -ForegroundColor Green
Write-Host "xcoding" -NoNewline -ForegroundColor White
Write-Host " to start." -ForegroundColor Green
Write-Host "  (if not found, open a NEW terminal, or run: " -NoNewline -ForegroundColor DarkGray
Write-Host "$exe -m xcode" -NoNewline -ForegroundColor Gray
Write-Host ")" -ForegroundColor DarkGray
Write-Host ""
