<#
.SYNOPSIS
  Hermes Agent update script for custom branches (e.g. release).
  Stays on current branch and merges upstream/main, then updates deps.
#>

$repoRoot = Resolve-Path "$PSScriptRoot/.."
Set-Location -LiteralPath $repoRoot

$currentBranch = git rev-parse --abbrev-ref HEAD
Write-Host "╔══════════════════════════════════════════════╗"
Write-Host "║  Hermes Update (stay on $currentBranch)"
Write-Host "╚══════════════════════════════════════════════╝"
Write-Host ""

# ── Fetch ──────────────────────────────────────────────
Write-Host "→ Fetching upstream/main..."
git fetch upstream main
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to fetch upstream/main"
    Write-Host "  Check: git remote -v"
    exit 1
}

# ── Merge ──────────────────────────────────────────────
Write-Host "→ Merging upstream/main into '$currentBranch' ..."
git merge upstream/main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════════════╗"
    Write-Host "║  Merge conflict(s) — resolve manually, then run:           ║"
    Write-Host "║                                                            ║"
    Write-Host "║    cd $repoRoot                                          ║"
    Write-Host "║    # fix conflicts                                        ║"
    Write-Host "║    git add -A                                             ║"
    Write-Host "║    git commit                                             ║"
    Write-Host "║    uv pip install -e '`$repoRoot[all]'                    ║"
    Write-Host "║                                                            ║"
    Write-Host "╚══════════════════════════════════════════════════════════════╝"
    exit 1
}

# ── Python deps ────────────────────────────────────────
Write-Host "→ Updating Python dependencies..."
$venvPip = "$repoRoot/venv/Scripts/pip.exe"
$uvBin = (Get-Command "uv" -ErrorAction SilentlyContinue).Source
if ($uvBin) {
    $env:VIRTUAL_ENV = "$repoRoot/venv"
    & $uvBin pip install -e "$repoRoot[all]"
} elseif (Test-Path $venvPip) {
    & $venvPip install -e "$repoRoot[all]"
} else {
    python -m pip install -e "$repoRoot[all]"
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠ Python deps install had warnings (non-fatal)."
}

# ── Re-apply local patches ──────────────────────────
# ``hermes_bootstrap.py`` is overwritten by upstream and loses our
# Windows Chinese locale fixes.  Re-inject the import line so
# ``local_patches.py`` (which survives the update) gets loaded.
$bootstrap = "$repoRoot/hermes_bootstrap.py"
$patchLine = "from local_patches import apply_all; apply_all()  # applied by hermes-hus"
if (Test-Path $bootstrap) {
    $content = Get-Content $bootstrap -Raw
    if ($content -notmatch [regex]::Escape("from local_patches")) {
        # Insert before activate_durable_lazy_target() so ordering stays clean
        $content = $content -replace '(activate_durable_lazy_target\(\))', "$patchLine`n`$1"
        Set-Content -Path $bootstrap -Value $content -NoNewline
        Write-Host "→ Patched hermes_bootstrap.py (local_patches)"
    } else {
        Write-Host "→ local_patches already present in hermes_bootstrap.py"
    }
}

# ── Clear stale bytecode ──────────────────────────────
Get-ChildItem -Path $repoRoot -Recurse -Directory __pycache__ -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# ── Done ──────────────────────────────────────────────
Write-Host ""
Write-Host "✓ Update complete! Restart hermes to use the new version."
