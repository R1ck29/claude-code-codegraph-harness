[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$SkipPlugin,
    [string]$ClaudeConfigDir,
    [string]$DataRoot,
    [string]$StateRoot
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $ClaudeConfigDir) {
    $ClaudeConfigDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
}
if (-not $DataRoot) {
    $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME "AppData\Local" }
    $DataRoot = Join-Path $base "ClaudeCodeCodegraphHarness"
}
if (-not $StateRoot) { $StateRoot = Join-Path $DataRoot "state" }

function Fail([string]$Message) { throw $Message }

$required = @(
    "VERSION",
    "SHA256SUMS",
    "bundle-manifest.json",
    "profile.json",
    "install.sh",
    "uninstall.sh",
    "install.ps1",
    "uninstall.ps1",
    "payload\marketplace\.claude-plugin\marketplace.json",
    "payload\marketplace\plugins\codegraph-evaluator\.claude-plugin\plugin.json",
    "payload\rules\codegraph-harness.md"
)
foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $ScriptDir $relative))) { Fail "Bundle is missing $relative" }
}

$verifiedChecksums = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $ScriptDir "SHA256SUMS")) {
    if (-not $line.Trim()) { continue }
    if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') { Fail "Invalid SHA256SUMS line" }
    $expected = $Matches[1].ToLowerInvariant()
    $relative = $Matches[2]
    if ([IO.Path]::IsPathRooted($relative) -or ($relative -split '[\\/]' -contains '..')) { Fail "Unsafe checksum path: $relative" }
    $path = Join-Path $ScriptDir $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail "Missing checksummed file: $relative" }
    if ($verifiedChecksums.ContainsKey($relative)) { Fail "Duplicate SHA256SUMS entry: $relative" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { Fail "Checksum mismatch: $relative" }
    $verifiedChecksums[$relative] = $true
}
foreach ($relative in $required | Where-Object { $_ -ne "SHA256SUMS" }) {
    $checksumRelative = $relative.Replace('\', '/')
    if (-not $verifiedChecksums.ContainsKey($checksumRelative)) { Fail "Mandatory file is not checksummed: $relative" }
}

$Version = (Get-Content -LiteralPath (Join-Path $ScriptDir "VERSION") -Raw).Trim()
if ($Version -notmatch '^[A-Za-z0-9._-]+$') { Fail "Unsafe VERSION value" }

$InstallRoot = Join-Path $DataRoot "versions\$Version"
$CurrentRoot = Join-Path $StateRoot "current"
$RuleTarget = Join-Path $ClaudeConfigDir "rules\codegraph-harness.md"
$PluginId = "codegraph-evaluator@codegraph-harness"
$priorRuleBackup = $null
$isReinstall = $false

Write-Host "Plan:"
Write-Host "  plugin marketplace: $(Join-Path $InstallRoot 'marketplace')"
Write-Host "  plugin: $PluginId"
Write-Host "  rule: $RuleTarget"
Write-Host "  state: $StateRoot"

if ($DryRun) {
    @{status="success"; summary="Dry run completed; no files changed"; next_actions=@("Run install.ps1 without -DryRun"); artifacts=@()} | ConvertTo-Json -Compress
    exit 0
}

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { Fail "Claude Code executable was not found on PATH" }

$receiptPath = Join-Path $CurrentRoot "receipt.json"
if (Test-Path -LiteralPath $RuleTarget) {
    if (-not (Test-Path -LiteralPath $receiptPath)) { Fail "Rule target exists and is not owned by this extension: $RuleTarget" }
    $oldReceipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    $currentHash = (Get-FileHash -LiteralPath $RuleTarget -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($oldReceipt.ruleTarget -ne $RuleTarget -or $oldReceipt.ruleInstalledSha256 -ne $currentHash) {
        Fail "Rule target was changed or is not owned by this extension: $RuleTarget"
    }
    $priorRuleBackup = $oldReceipt.ruleBackup
    $isReinstall = $true
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $InstallRoot), $StateRoot | Out-Null
$staging = Join-Path $DataRoot ".staging-$Version-$PID"
if (Test-Path -LiteralPath $staging) { Fail "Staging path already exists" }

$rollbackRulePath = $null
$ruleWritten = $false
$pluginInstalled = $false
$marketplaceAdded = $false
try {
    New-Item -ItemType Directory -Path $staging | Out-Null
    Copy-Item -LiteralPath (Join-Path $ScriptDir "payload\marketplace") -Destination (Join-Path $staging "marketplace") -Recurse
    Copy-Item -LiteralPath (Join-Path $ScriptDir "VERSION") -Destination (Join-Path $staging "VERSION")
    Copy-Item -LiteralPath (Join-Path $ScriptDir "bundle-manifest.json") -Destination (Join-Path $staging "bundle-manifest.json")
    if (-not (Test-Path -LiteralPath $InstallRoot)) { Move-Item -LiteralPath $staging -Destination $InstallRoot }

    if ($isReinstall) {
        $backupRoot = Join-Path $StateRoot ("backups\" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ"))
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        $rollbackRulePath = Join-Path $backupRoot "codegraph-harness.md"
        Copy-Item -LiteralPath $RuleTarget -Destination $rollbackRulePath
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $RuleTarget) | Out-Null
    Copy-Item -LiteralPath (Join-Path $ScriptDir "payload\rules\codegraph-harness.md") -Destination $RuleTarget -Force
    $ruleWritten = $true

    if (-not $SkipPlugin) {
        & claude plugin marketplace add (Join-Path $InstallRoot "marketplace") --scope user
        if ($LASTEXITCODE -ne 0) { Fail "Failed to add local marketplace" }
        $marketplaceAdded = $true
        & claude plugin install $PluginId --scope user --yes
        if ($LASTEXITCODE -ne 0) { Fail "Failed to install plugin" }
        $pluginInstalled = $true
    }

    New-Item -ItemType Directory -Force -Path $CurrentRoot | Out-Null
    $receipt = @{
        schemaVersion = 1
        version = $Version
        installRoot = $InstallRoot
        ruleTarget = $RuleTarget
        ruleBackup = $priorRuleBackup
        ruleInstalledSha256 = (Get-FileHash -LiteralPath $RuleTarget -Algorithm SHA256).Hash.ToLowerInvariant()
        pluginId = $PluginId
        pluginSkipped = [bool]$SkipPlugin
    }
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding UTF8
}
catch {
    if ($pluginInstalled) {
        & claude plugin uninstall $PluginId --scope user --yes 2>$null
    }
    if ($marketplaceAdded) {
        & claude plugin marketplace remove codegraph-harness --scope user 2>$null
    }
    if ($ruleWritten) {
        if ($rollbackRulePath -and (Test-Path -LiteralPath $rollbackRulePath)) { Copy-Item -LiteralPath $rollbackRulePath -Destination $RuleTarget -Force }
        else { Remove-Item -LiteralPath $RuleTarget -Force -ErrorAction SilentlyContinue }
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    if ($rollbackRulePath -and (Test-Path -LiteralPath $rollbackRulePath)) { Remove-Item -LiteralPath $rollbackRulePath -Force }
}

@{status="success"; summary="Codegraph harness installed"; next_actions=@("Restart Claude Code or run /reload-plugins"); artifacts=@($receiptPath)} | ConvertTo-Json -Compress
