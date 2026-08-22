[CmdletBinding()]
param(
    [string]$DataRoot,
    [string]$StateRoot
)

$ErrorActionPreference = "Stop"
if (-not $DataRoot) {
    $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME "AppData\Local" }
    $DataRoot = Join-Path $base "ClaudeCodeCodegraphHarness"
}
if (-not $StateRoot) { $StateRoot = Join-Path $DataRoot "state" }
$receiptPath = Join-Path $StateRoot "current\receipt.json"
if (-not (Test-Path -LiteralPath $receiptPath)) { throw "No installation receipt found at $receiptPath" }

$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
$pluginWarning = $false
if (-not $receipt.pluginSkipped -and (Get-Command claude -ErrorAction SilentlyContinue)) {
    & claude plugin uninstall $receipt.pluginId --scope user --yes
    if ($LASTEXITCODE -ne 0) { $pluginWarning = $true }
    & claude plugin marketplace remove codegraph-harness --scope user
    if ($LASTEXITCODE -ne 0) { $pluginWarning = $true }
}
elseif (-not $receipt.pluginSkipped) {
    $pluginWarning = $true
    Write-Warning "Claude Code was not found; plugin removal could not be verified"
}

$preserved = $false
if (Test-Path -LiteralPath $receipt.ruleTarget) {
    $currentHash = (Get-FileHash -LiteralPath $receipt.ruleTarget -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($currentHash -eq $receipt.ruleInstalledSha256) {
        if ($receipt.ruleBackup -and (Test-Path -LiteralPath $receipt.ruleBackup)) {
            Copy-Item -LiteralPath $receipt.ruleBackup -Destination $receipt.ruleTarget -Force
        }
        else { Remove-Item -LiteralPath $receipt.ruleTarget -Force }
    }
    else {
        $preserved = $true
        Write-Warning "Preserved user-modified Rule: $($receipt.ruleTarget)"
    }
}

Remove-Item -LiteralPath $receiptPath -Force
if ($preserved -or $pluginWarning) {
    @{status="warning"; summary="Uninstall completed with items requiring review"; next_actions=@("Verify plugin removal and review any preserved Rule"); artifacts=@($receipt.ruleTarget)} | ConvertTo-Json -Compress
}
else {
    @{status="success"; summary="Codegraph harness uninstalled"; next_actions=@(); artifacts=@()} | ConvertTo-Json -Compress
}
