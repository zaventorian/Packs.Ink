<#
pop_run.ps1 - the weekly PSA population refresh, start to finish.

  powershell -File scripts\pop_run.ps1              # open Chrome, pull, dry-run load
  ... -DryRun          print what it would do and stop
  ... -SkipLoad        pull only
  ... -Commit          write to graded_pop instead of dry-running the load
  ... -KeepChrome      reuse a Chrome that is already on 9222

WHY THIS IS A LOCAL SCRIPT AND NOT A GITHUB ACTION
--------------------------------------------------
It cannot be one. PSA (collectors.com) is Cloudflare-fronted and serves a
datacenter IP its interstitial, and every page below /Pop redirects to
collectors.com/signin without a login. So the pull needs a real browser, on a
residential IP, signed in as Zaven. A runner has none of the three. The
REMEMBERING half is automated instead: scripts/reconcile_catalog.py --watch
reads max(graded_pop.pulled_at) daily and goes red once it is over a week old,
which rides the existing catalog-watch email. Running this clears that by
itself - there is no "mark done" to forget.

  ⚠ NEVER automate the sign-in. If Chrome comes up signed out, this stops and
  asks you to sign in by hand. That is a real account with real purchase
  history behind it, and a scripted login is exactly what gets one flagged.

  ⚠ A wall is a full stop, never a retry. psa_pop_pull.mjs treats a non-200, a
  sign-in redirect or a challenge-shaped body as fatal on purpose. If this dies
  that way, wait a day - do not re-run it in a loop, and do not change IP.

It shares the burner Chrome profile with graded_run.ps1, so the collectors.com
session persists between weeks and you usually will not have to sign in at all.
Unlike graded_run.ps1 it does NOT kill a running Chrome: that script needs a
fresh one because Terapeak freezes its date window, and PSA has no such window.
#>
param(
  [switch]$DryRun,
  [switch]$SkipLoad,
  [switch]$Commit,
  [switch]$KeepChrome
)

$ErrorActionPreference = "Stop"

$Repo       = Split-Path -Parent $PSScriptRoot
$Py         = "C:\Users\zaven\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$ChromeExe  = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$ProfileDir = "C:\Users\zaven\terapeak-chrome"
# The landing page is the NEWEST year heading, read out of psa_pop_pull.mjs's own
# YEARS table rather than written here. A hand-copied heading is one number in two
# files: the day a 2027 row is added, a stale copy here opens a page that still
# exists and still renders, so nothing errors - you just sign in on the wrong year.
$PullJs = Join-Path $PSScriptRoot "psa_pop_pull.mjs"
$Years  = [regex]::Matches((Get-Content -Raw $PullJs), 'year:\s*(\d{4}),\s*headingID:\s*(\d+)')
if (-not $Years.Count) { Write-Host "[pop] STOP: could not read YEARS out of psa_pop_pull.mjs" -ForegroundColor Red; exit 1 }
$Newest = $Years | Sort-Object { [int]$_.Groups[1].Value } | Select-Object -Last 1
$PopUrl = "https://www.psacard.com/pop/tcg-cards/{0}/{1}" -f $Newest.Groups[1].Value, $Newest.Groups[2].Value
$Cdp        = "http://localhost:9222"

function Say($m) { Write-Host "[pop] $m" }
function Die($m, $code) { Write-Host "[pop] STOP: $m" -ForegroundColor Red; exit $code }

if (-not (Test-Path $Py))        { Die "python not found at $Py" 1 }
if (-not (Test-Path $ChromeExe)) { Die "chrome not found at $ChromeExe" 1 }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Die "node not on PATH" 1 }

function Cdp-Alive {
  try { Invoke-RestMethod "$Cdp/json/version" -TimeoutSec 3 | Out-Null; return $true }
  catch { return $false }
}

# --- Stage 1: never two drivers against one Chrome tab -----------------------
# The Terapeak scrapers drive the same browser. Two at once causes redirects and
# stalls, and here it would also look like burst traffic to the side we are
# being most careful with.
$live = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'terapeak_(topup|scrape|backfill_loop)|raw_topup' -and $_.ProcessId -ne $PID }
if ($live) {
  $live | ForEach-Object { Say ("  running: PID {0}  {1}" -f $_.ProcessId, $_.CommandLine) }
  Die "a Terapeak scraper is already using this Chrome. Let it finish and re-run." 1
}

if ($DryRun) {
  Say "dry run: would open $PopUrl in the burner Chrome, then:"
  Say "  node scripts\psa_pop_pull.mjs"
  if (-not $SkipLoad) {
    Say ("  $Py -u scripts\psa_pop_load.py" + $(if ($Commit) { " --commit" } else { "" }))
  }
  exit 0
}

# --- Stage 2: Chrome, on the PSA pop page ------------------------------------
if (-not (Cdp-Alive)) {
  Say "launching Chrome (burner profile, CDP 9222)"
  Start-Process -FilePath $ChromeExe -ArgumentList @(
    "--remote-debugging-port=9222",
    "--user-data-dir=$ProfileDir",
    "--disable-blink-features=AutomationControlled",
    $PopUrl
  ) | Out-Null
} elseif ($KeepChrome) {
  Say "reusing the running Chrome (-KeepChrome)"
} else {
  # Chrome is up but may be sitting on eBay. The pull attaches to a tab whose
  # URL contains psacard.com, so open one rather than navigating an existing tab
  # out from under whatever else is using it.
  Say "Chrome already on 9222 - opening a PSA tab in it"
  Start-Process -FilePath $ChromeExe -ArgumentList @("--user-data-dir=$ProfileDir", $PopUrl) | Out-Null
}

# --- Stage 3: confirm a PSA tab exists AND is signed in ----------------------
# Signed out, psacard.com still renders: it is the pop pages BELOW it that
# redirect. So a tab being present proves nothing and the pull's own wall check
# is what finally decides - this loop only gets you to a page you can sign in on.
$tab = $null
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  try { $pages = Invoke-RestMethod "$Cdp/json" -TimeoutSec 5 | Where-Object { $_.type -eq "page" } }
  catch { continue }
  $tab = $pages | Where-Object { $_.url -match "psacard\.com" } | Select-Object -First 1
  if ($tab) { break }
}
if (-not $tab) { Die "no psacard.com tab appeared. Open $PopUrl by hand and re-run with -KeepChrome." 2 }
Say "PSA tab ready: $($tab.url)"
Say "If you are signed out, sign in NOW in that window - the pull stops dead on a sign-in redirect."

Push-Location $Repo
try {
  # --- Stage 4: pull ---------------------------------------------------------
  # Sequential and jittered inside the script; ~70 requests, ~4 minutes. A set
  # already pulled today is skipped, so re-running after a wall resumes.
  Say "pulling PSA population (~4 min)"
  node scripts\psa_pop_pull.mjs
  if ($LASTEXITCODE -ne 0) {
    Die "the pull stopped. If it named a wall or a sign-in, sign in by hand and re-run TOMORROW - do not loop." 3
  }

  # --- Stage 5: load ---------------------------------------------------------
  if ($SkipLoad) { Say "-SkipLoad: pulled files are in scripts\pop_output, nothing written."; exit 0 }

  if ($Commit) {
    Say "loading into graded_pop (--commit)"
    & $Py -u scripts\psa_pop_load.py --commit
  } else {
    Say "dry-run load (read the counts, then re-run with -Commit)"
    & $Py -u scripts\psa_pop_load.py
  }
  if ($LASTEXITCODE -ne 0) { Die "the load failed - nothing partial was written unless it said so." 4 }
}
finally { Pop-Location }

if ($Commit) {
  Say "done. The catalog-watch pop_stale alert clears itself on the next run."
} else {
  Say "done (dry run). Commit it with:  powershell -File scripts\pop_run.ps1 -KeepChrome -Commit"
  Say "  (or just: $Py scripts\psa_pop_load.py --commit  - the files are already pulled)"
}
