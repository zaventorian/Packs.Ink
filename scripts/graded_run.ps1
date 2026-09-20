<#
graded_run.ps1 - Stages 1-4 of the graded-sales update.

Relaunches a FRESH burner Chrome over CDP, scrapes the Terapeak delta for all
six graders, and loads it insert-only into graded_sales. Stages 5-6 (OCR
reconcile + conflation audit) are judgment calls and run after this - see
.claude/skills/graded-scrape/SKILL.md.

  powershell -ExecutionPolicy Bypass -File scripts\graded_run.ps1
  ... -Grader PSA     resume / run a single grader
  ... -SkipLoad       scrape only
  ... -DryRun         checks only, launches and scrapes nothing
  ... -KeepChrome     reuse a running Chrome (stale date window - avoid)
  ... -Raw            scrape RAW (ungraded) sales for the raw_watchlist promos
                      into raw_sales instead. Same Chrome, same captcha rules.
  ... -Deep           with -Raw: ignore per-query cutoffs and pull each query to
                      exhaustion (the right mode for a first run).

Exit codes: 0 ok | 2 Chrome/login/captcha before scraping | 3 captcha mid-scrape
(progress saved, re-run resumes) | 1 anything else.
#>
[CmdletBinding()]
param(
  [string]$Grader = "ALL",
  [switch]$DryRun,
  [switch]$SkipLoad,
  [switch]$KeepChrome,
  [switch]$Raw,
  [switch]$Deep
)

$ErrorActionPreference = "Stop"

$Repo    = Split-Path -Parent $PSScriptRoot
$Py      = "C:\Users\zaven\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$ChromeExe = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$ProfileDir = "C:\Users\zaven\terapeak-chrome"
$LogDir  = Join-Path $Repo "scripts\terapeak_output"
$Cdp     = "http://localhost:9222"

function Say($m) { Write-Host "[graded] $m" }
function Die($m, $code) { Write-Host "[graded] STOP: $m" -ForegroundColor Red; exit $code }

if (-not (Test-Path $Py))        { Die "python not found at $Py" 1 }
if (-not (Test-Path $ChromeExe)) { Die "chrome not found at $ChromeExe" 1 }
if (-not (Test-Path $LogDir))    { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# --- Stage 1a: never two scrapers against the same tab -----------------------
$live = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'terapeak_(topup|scrape|backfill_loop)|raw_topup' -and $_.ProcessId -ne $PID }
if ($live) {
  $live | ForEach-Object { Say ("  running: PID {0}  {1}" -f $_.ProcessId, $_.CommandLine) }
  Die "a Terapeak scraper is already running - two against one Chrome tab causes redirects and stalls. Let it finish or taskkill it (NOT the dev_server.py PIDs)." 1
}

function Cdp-Alive {
  try { Invoke-RestMethod "$Cdp/json/version" -TimeoutSec 3 | Out-Null; return $true }
  catch { return $false }
}

# --- Stage 1b: FRESH Chrome (a day-old one freezes the Terapeak date window) --
if ($KeepChrome) {
  Say "reusing the running Chrome (-KeepChrome): the SPA date window may be stale."
} else {
  $burner = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
            Where-Object { $_.CommandLine -match [regex]::Escape($ProfileDir) }
  if ($burner) {
    $verb = if ($DryRun) { "would close" } else { "closing" }
    Say ("{0} {1} burner Chrome process(es) for a fresh date window" -f $verb, @($burner).Count)
    if (-not $DryRun) {
      $burner | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
      for ($i = 0; $i -lt 15 -and (Cdp-Alive); $i++) { Start-Sleep -Seconds 1 }
      if (Cdp-Alive) { Die "port 9222 still answering after killing the burner Chrome - close it by hand." 1 }
    }
  }
}

if ($DryRun) {
  Say "dry run: would launch Chrome on the burner profile, then:"
  if ($Raw) {
    Say "  $Py -u scripts\raw_topup.py$(if($Deep){' --deep'})"
    if (-not $SkipLoad) { Say "  $Py -u scripts\raw_load.py --from-jsonl   (dry run; --commit is yours)" }
  } else {
    Say "  $Py -u scripts\terapeak_topup.py $Grader"
    if (-not $SkipLoad) {
      Say "  $Py -u scripts\terapeak_load.py --new-only"
      Say "  $Py -u scripts\rematch_graded_unmatched.py --commit"
    }
  }
  exit 0
}

if (-not (Cdp-Alive)) {
  Say "launching Chrome (burner profile, CDP 9222)"
  Start-Process -FilePath $ChromeExe -ArgumentList @(
    "--remote-debugging-port=9222",
    "--user-data-dir=$ProfileDir",
    "--disable-blink-features=AutomationControlled",
    "https://www.ebay.com/sh/research"
  ) | Out-Null
}

# --- Stage 1c: confirm the research tool is actually loaded + logged in -------
$ResearchTitleRe = "Product Research|Research products"
$title = $null
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Seconds 2
  try {
    $pages = Invoke-RestMethod "$Cdp/json" -TimeoutSec 5 | Where-Object { $_.type -eq "page" }
  } catch { continue }
  # eBay has used both "Product Research" and "Research products" as the page title.
  $hit = $pages | Where-Object { $_.title -match $ResearchTitleRe }
  if ($hit) { $title = $hit[0].title; break }
  $blocked = $pages | Where-Object { $_.url -match "splashui|captcha|signin" }
  if ($blocked) { $title = $blocked[0].title; break }
}

if (-not $title) { Die "Chrome never showed the Terapeak research page. Open it by hand at https://www.ebay.com/sh/research and re-run." 2 }
if ($title -notmatch $ResearchTitleRe) {
  Die "eBay is challenging the session (page: '$title'). Solve it by hand in the Chrome window, then re-run. Do NOT clear cookies/cache and do NOT change VPN/IP - the block is IP-based and temporary." 2
}
Say "Chrome ready: $title"

Push-Location $Repo
try {
  # --- Stage 3: scrape -------------------------------------------------------
  # -Raw drives the SAME Chrome through the SAME SPA; only the query list and the
  # destination differ (card names -> scripts/raw_output/ -> raw_sales). Sharing
  # this driver rather than forking it is deliberate: stages 1a-1c hold the
  # stale-Chrome and captcha knowledge, and a second copy would drift from it.
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  if ($Raw) {
    $rawArgs = @()
    if ($Deep) { $rawArgs += "--deep" }
    Say "scraping RAW watchlist queries - All-sites SPA, newest-first"
    & $Py -u "scripts\raw_topup.py" @rawArgs | Tee-Object -FilePath (Join-Path $LogDir "_run_rawtopup_$stamp.log")
  } else {
    Say "scraping ($Grader) - All-sites SPA, newest-first, bounded to the last-scrape date"
    & $Py -u "scripts\terapeak_topup.py" $Grader | Tee-Object -FilePath (Join-Path $LogDir "_run_topup_$stamp.log")
  }
  $rc = $LASTEXITCODE
  if ($rc -eq 3) { Die "eBay threw a captcha mid-scrape. Progress is saved - solve it in the Chrome window, then re-run (already-done graders no-op via JSONL dedup)." 3 }
  if ($rc -ne 0) { Die "terapeak_topup.py exited $rc - see the log in $LogDir" 1 }

  if ($SkipLoad) { Say "scrape done (-SkipLoad); stopping before the DB load."; exit 0 }

  if ($Raw) {
    # ⚠ NOT --commit. raw_load.py is dry-run by default on purpose: these cards
    # are on the watchlist BECAUSE the site shows a fossil or a dash for them, so
    # any number published is believed, and every mis-attribution available is an
    # order of magnitude wrong. Read the review report it prints (per-card price
    # spread, multi-quantity listings, outliers), then re-run with --commit.
    Say "loading raw_sales - DRY RUN; read the report, then re-run with --commit"
    & $Py -u "scripts\raw_load.py" --from-jsonl | Tee-Object -FilePath (Join-Path $LogDir "_run_rawload_$stamp.log")
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { Die "raw_load.py exited $rc - see the log in $LogDir" 1 }
    Say "raw scrape done. Review the report, then: $Py scripts\raw_load.py --from-jsonl --commit"
    exit 0
  }

  # --- Stage 4: insert-only load --------------------------------------------
  Say "loading into graded_sales (--new-only: never updates existing rows)"
  & $Py -u "scripts\terapeak_load.py" --new-only | Tee-Object -FilePath (Join-Path $LogDir "_run_load_$stamp.log")
  $rc = $LASTEXITCODE
  if ($rc -ne 0) { Die "terapeak_load.py exited $rc - see the log in $LogDir" 1 }

  # --- Stage 4b: re-ask the CURRENT matcher about never-attributed rows ------
  # --new-only above is ON CONFLICT DO NOTHING, so matcher improvements never
  # reach rows already in the table: a sale that failed attribution the day it
  # was scraped stays failed, and silently, because an unmatched row is also
  # auto-excluded. That is how a $39,100 PSA 10 sale sat invisible for three
  # months. This pass only ever touches rows with card_id IS NULL and no
  # concrete exclude_reason -- it cannot reach a hand-made fix -- and it prints
  # every still-unattributed sale over $500 so the next one gets NOTICED.
  Say "re-matching never-attributed rows (safe: card_id IS NULL only)"
  & $Py -u "scripts\rematch_graded_unmatched.py" --commit | Tee-Object -FilePath (Join-Path $LogDir "_run_rematch_$stamp.log")
  $rc = $LASTEXITCODE
  if ($rc -ne 0) { Die "rematch_graded_unmatched.py exited $rc - see the log in $LogDir" 1 }
}
finally { Pop-Location }

Say "Stages 1-4 done. Next: verify max(sold_date) + per-day counts, then Stage 5 (terapeak_ocr_reconcile.py) and the Stage 6 audit."
exit 0
