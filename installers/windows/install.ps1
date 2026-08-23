[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$AdapterOnly,
    [switch]$SkipPlugin,
    [string]$ClaudeConfigDir,
    [string]$CodexSkillRoot,
    [string]$DataRoot,
    [string]$StateRoot,
    [string]$AllowedRoot
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $ClaudeConfigDir) {
    $ClaudeConfigDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
}
if (-not $CodexSkillRoot) {
    $CodexSkillRoot = if ($env:CODEGRAPH_CODEX_SKILLS_ROOT) { $env:CODEGRAPH_CODEX_SKILLS_ROOT } else { Join-Path $HOME ".agents\skills" }
}
if (-not $DataRoot) {
    $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME "AppData\Local" }
    $DataRoot = Join-Path $base "CompanyCodegraph"
}
if (-not $StateRoot) { $StateRoot = Join-Path $DataRoot "state" }

$ClaudeConfigDir = [IO.Path]::GetFullPath($ClaudeConfigDir)
$CodexSkillRoot = [IO.Path]::GetFullPath($CodexSkillRoot)
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
$StateRoot = [IO.Path]::GetFullPath($StateRoot)
if ([IO.Path]::GetPathRoot($DataRoot) -eq $DataRoot -or $DataRoot -eq [IO.Path]::GetFullPath($HOME)) { throw "Unsafe data root" }
if ([IO.Path]::GetPathRoot($StateRoot) -eq $StateRoot -or $StateRoot -eq [IO.Path]::GetFullPath($HOME)) { throw "Unsafe state root" }
if ($AllowedRoot) {
    $AllowedRoot = [IO.Path]::GetFullPath($AllowedRoot)
    if (-not (Test-Path -LiteralPath $AllowedRoot -PathType Container)) { throw "-AllowedRoot must be an existing directory" }
    $allowedRootItem = Get-Item -LiteralPath $AllowedRoot -Force
    if ($allowedRootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "-AllowedRoot must not be a reparse point" }
    $AllowedRoot = $allowedRootItem.FullName
    if ([IO.Path]::GetPathRoot($AllowedRoot) -eq $AllowedRoot -or $AllowedRoot -eq [IO.Path]::GetFullPath($HOME)) { throw "Unsafe allowed root" }
}

function Fail([string]$Message) { throw $Message }
function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

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
    "payload\rules\codegraph-harness.md",
    "payload\clients\routing-policy.json",
    "payload\codex\.codex-plugin\plugin.json",
    "payload\codex\skills\company-codegraph\SKILL.md",
    "payload\codex\config.example.toml"
)
foreach ($relative in $required) {
    $requiredPath = Join-Path $ScriptDir $relative
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { Fail "Bundle is missing $relative" }
    if ((Get-Item -LiteralPath $requiredPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail "Bundle file must not be a reparse point: $relative" }
}

$verifiedChecksums = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $ScriptDir "SHA256SUMS")) {
    if (-not $line.Trim()) { continue }
    if ($line -notmatch '^([0-9a-f]{64})  (.+)$') { Fail "Invalid SHA256SUMS line" }
    $expected = $Matches[1]
    $relative = $Matches[2]
    if ([IO.Path]::IsPathRooted($relative) -or ($relative -split '[\\/]' -contains '..')) { Fail "Unsafe checksum path: $relative" }
    $path = Join-Path $ScriptDir $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail "Missing checksummed file: $relative" }
    if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail "Bundle file must not be a reparse point: $relative" }
    if ($verifiedChecksums.ContainsKey($relative)) { Fail "Duplicate SHA256SUMS entry: $relative" }
    if ((Get-Sha256 $path) -ne $expected) { Fail "Checksum mismatch: $relative" }
    $verifiedChecksums[$relative] = $true
}
foreach ($relative in $required | Where-Object { $_ -ne "SHA256SUMS" }) {
    $checksumRelative = $relative.Replace('\', '/')
    if (-not $verifiedChecksums.ContainsKey($checksumRelative)) { Fail "Mandatory file is not checksummed: $relative" }
}
foreach ($item in Get-ChildItem -LiteralPath $ScriptDir -Force -Recurse) {
    $relative = [IO.Path]::GetRelativePath($ScriptDir, $item.FullName).Replace('\', '/')
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail "Bundle entry must not be a reparse point: $relative" }
    if ($item.PSIsContainer) { continue }
    if ($relative -ne "SHA256SUMS" -and -not $verifiedChecksums.ContainsKey($relative)) {
        Fail "Unchecksummed bundle file: $relative"
    }
}

$Version = (Get-Content -LiteralPath (Join-Path $ScriptDir "VERSION") -Raw).Trim()
if ($Version -notmatch '^[A-Za-z0-9._-]+$') { Fail "Unsafe VERSION value" }

$platform = "windows"
if ($env:CODEGRAPH_ALLOW_TEST_OS -eq "1" -and $env:CODEGRAPH_TEST_PLATFORM) { $platform = $env:CODEGRAPH_TEST_PLATFORM }
if ($platform -ne "windows") { Fail "Unsupported platform: $platform" }
$rawArch = if ($env:CODEGRAPH_ALLOW_TEST_OS -eq "1" -and $env:CODEGRAPH_TEST_ARCH) {
    $env:CODEGRAPH_TEST_ARCH
} else {
    [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
}
$arch = switch -Regex ($rawArch.ToLowerInvariant()) {
    '^(arm64|aarch64)$' { "arm64"; break }
    '^(x64|amd64|x86_64)$' { "x86_64"; break }
    default { Fail "Unsupported architecture: $rawArch" }
}

$InstallRoot = Join-Path $DataRoot "versions\$Version"
$CurrentRoot = Join-Path $StateRoot "current"
$receiptPath = Join-Path $CurrentRoot "receipt.json"
$RuleTarget = Join-Path $ClaudeConfigDir "rules\codegraph-harness.md"
$CodexSkillTarget = Join-Path $CodexSkillRoot "company-codegraph\SKILL.md"
$PluginId = "codegraph-evaluator@codegraph-harness"
$ClaudeMcpId = "company-codegraph"
$CodexMcpId = "company_codegraph"
$RuntimeSourceRoot = Join-Path $ScriptDir "runtime\$platform-$arch"
$RuntimeTargetRoot = Join-Path $DataRoot "runtime\$platform-$arch"
$configPath = Join-Path $InstallRoot "clients\routing-policy.json"
$GatewaySource = Join-Path $RuntimeSourceRoot "bin\codegraph-gateway.exe"
$BackendSource = Join-Path $RuntimeSourceRoot "bin\codebase-memory-mcp.exe"
$GatewayTarget = Join-Path $RuntimeTargetRoot "bin\codegraph-gateway.exe"
$BackendTarget = Join-Path $RuntimeTargetRoot "bin\codebase-memory-mcp.exe"
$runtimeInstall = $false
$gatewaySha256 = ""
$backendSha256 = ""
$configSha256 = Get-Sha256 (Join-Path $ScriptDir "payload\clients\routing-policy.json")
$gitBinary = ""
$gitSha256 = ""

$runtimeManifest = Join-Path $ScriptDir "runtime\manifest.json"
if (Test-Path -LiteralPath $runtimeManifest -PathType Leaf) {
    if (-not $verifiedChecksums.ContainsKey("runtime/manifest.json")) { Fail "Mandatory file is not checksummed: runtime/manifest.json" }
    if (-not (Test-Path -LiteralPath $GatewaySource -PathType Leaf)) { Fail "Bundle has no runtime for $platform/$arch" }
    if (-not (Test-Path -LiteralPath $BackendSource -PathType Leaf)) { Fail "Bundle has no runtime for $platform/$arch" }
    foreach ($relative in @(
        "runtime/$platform-$arch/bin/codegraph-gateway.exe",
        "runtime/$platform-$arch/bin/codebase-memory-mcp.exe"
    )) {
        if (-not $verifiedChecksums.ContainsKey($relative)) { Fail "Mandatory file is not checksummed: $relative" }
    }
    $gatewaySha256 = Get-Sha256 $GatewaySource
    $backendSha256 = Get-Sha256 $BackendSource
    if (-not $AdapterOnly) {
        if (-not $AllowedRoot) { Fail "-AllowedRoot is required for runtime installation" }
        $gitCommand = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $gitCommand) { Fail "A managed Git executable is required for runtime installation" }
        $gitBinary = [IO.Path]::GetFullPath($gitCommand.Path)
        $gitSha256 = Get-Sha256 $gitBinary
        $runtimeInstall = $true
    }
}

Write-Host "Plan:"
Write-Host "  Claude plugin marketplace: $(Join-Path $InstallRoot 'marketplace')"
Write-Host "  Claude Rule: $RuleTarget"
Write-Host "  Codex skill: $CodexSkillTarget"
Write-Host "  selected runtime: $platform/$arch ($runtimeInstall)"
Write-Host "  state: $StateRoot"

if ($DryRun) {
    @{status="success"; summary="Dry run completed; no files changed"; next_actions=@("Run install.ps1 without -DryRun"); artifacts=@()} | ConvertTo-Json -Compress
    exit 0
}

$isReinstall = Test-Path -LiteralPath $receiptPath -PathType Leaf
$oldReceipt = if ($isReinstall) { Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json } else { $null }

function Assert-OwnedFile([string]$Target, [string]$ReceiptTarget, [string]$ReceiptHash, [string]$Label) {
    if ((Test-Path -LiteralPath $Target) -and ((Get-Item -LiteralPath $Target -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { Fail "$Label target must not be a reparse point: $Target" }
    if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
        if ($isReinstall) { Fail "Owned $Label is missing: $Target" }
        return
    }
    if (-not $isReinstall) {
        if ($Label -eq "Rule") { Fail "Rule target exists and is not owned by this extension: $Target" }
        Fail "$Label target exists and is not owned by this extension: $Target"
    }
    if ($ReceiptTarget -ne $Target -or $ReceiptHash -ne (Get-Sha256 $Target)) { Fail "$Label target was changed or is not owned: $Target" }
}

Assert-OwnedFile $RuleTarget $oldReceipt.ruleTarget $oldReceipt.ruleInstalledSha256 "Rule"
Assert-OwnedFile $CodexSkillTarget $oldReceipt.codexSkillTarget $oldReceipt.codexSkillInstalledSha256 "Codex skill"

if ($runtimeInstall -and (Test-Path -LiteralPath $RuntimeTargetRoot)) {
    if (-not $isReinstall -or -not $oldReceipt.runtimeInstalled) { Fail "Runtime target exists and is not owned by this extension: $RuntimeTargetRoot" }
    if ($oldReceipt.gatewayPath -ne $GatewayTarget -or $oldReceipt.backendPath -ne $BackendTarget) { Fail "Runtime path is not owned by this extension" }
    if (-not (Test-Path -LiteralPath $GatewayTarget -PathType Leaf) -or -not (Test-Path -LiteralPath $BackendTarget -PathType Leaf)) { Fail "Owned runtime is incomplete" }
    if ($oldReceipt.gatewaySha256 -ne (Get-Sha256 $GatewayTarget)) { Fail "Gateway was changed after installation" }
    if ($oldReceipt.backendSha256 -ne (Get-Sha256 $BackendTarget)) { Fail "Backend was changed after installation" }
    if ($oldReceipt.gitBinary -ne $gitBinary -or $oldReceipt.gitSha256 -ne $gitSha256) { Fail "Managed Git changed since installation" }
    if ($oldReceipt.allowedRoot -ne $AllowedRoot) { Fail "Allowed root changed since installation" }
}

function Get-RegistrationHash([string]$Client, [string]$Name) {
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($Client -eq "claude") { $output = & claude mcp get $Name 2>$null }
        else { $output = & codex mcp get $Name --json 2>$null }
        if ($LASTEXITCODE -ne 0) { return $null }
        $bytes = [Text.Encoding]::UTF8.GetBytes(($output -join "`n"))
        return ([Security.Cryptography.SHA256]::Create().ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join ""
    }
    finally { $ErrorActionPreference = $savedPreference }
}

function Assert-NoMcpCollision([string]$Client, [string]$Name, [bool]$WasRegistered, [string]$ReceiptHash) {
    if (-not (Get-Command $Client -ErrorAction SilentlyContinue)) { return }
    $currentHash = Get-RegistrationHash $Client $Name
    if (-not $currentHash) { return }
    if (-not $isReinstall -or -not $WasRegistered) { Fail "MCP registration already exists and is not owned: $Name" }
    if ($currentHash -ne $ReceiptHash) { Fail "Owned MCP registration was changed: $Name" }
}

if ($runtimeInstall) {
    Assert-NoMcpCollision "claude" $ClaudeMcpId ([bool]$oldReceipt.claudeMcpRegistered) $oldReceipt.claudeMcpSha256
    Assert-NoMcpCollision "codex" $CodexMcpId ([bool]$oldReceipt.codexMcpRegistered) $oldReceipt.codexMcpSha256
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $InstallRoot), $StateRoot | Out-Null
$staging = Join-Path $DataRoot ".staging-$Version-$PID"
if (Test-Path -LiteralPath $staging) { Fail "Staging path already exists" }

$ruleWritten = $false
$skillWritten = $false
$pluginInstalled = $false
$marketplaceAdded = $false
$claudeMcpRegistered = $false
$codexMcpRegistered = $false
$claudeMcpSha256 = ""
$codexMcpSha256 = ""
$installRootCreated = $false
$runtimeCreated = $false
try {
    New-Item -ItemType Directory -Path $staging | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $staging "install") | Out-Null
    Copy-Item -LiteralPath (Join-Path $ScriptDir "payload\marketplace") -Destination (Join-Path $staging "install\marketplace") -Recurse
    Copy-Item -LiteralPath (Join-Path $ScriptDir "payload\clients") -Destination (Join-Path $staging "install\clients") -Recurse
    Copy-Item -LiteralPath (Join-Path $ScriptDir "payload\codex") -Destination (Join-Path $staging "install\codex") -Recurse
    Copy-Item -LiteralPath (Join-Path $ScriptDir "VERSION") -Destination (Join-Path $staging "install\VERSION")
    Copy-Item -LiteralPath (Join-Path $ScriptDir "bundle-manifest.json") -Destination (Join-Path $staging "install\bundle-manifest.json")
    if (-not (Test-Path -LiteralPath $InstallRoot)) {
        Move-Item -LiteralPath (Join-Path $staging "install") -Destination $InstallRoot
        $installRootCreated = $true
    }
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) { Fail "Installed routing policy is missing" }
    if ((Get-Item -LiteralPath $configPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail "Installed routing policy must not be a reparse point" }
    if ((Get-Sha256 $configPath) -ne $configSha256) { Fail "Installed routing policy differs from this bundle" }
    if ($isReinstall -and ($oldReceipt.configPath -ne $configPath -or $oldReceipt.configSha256 -ne $configSha256)) { Fail "Routing policy changed since installation" }

    if ($runtimeInstall) {
        if (-not (Test-Path -LiteralPath $RuntimeTargetRoot)) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $GatewayTarget) | Out-Null
            Copy-Item -LiteralPath $GatewaySource -Destination $GatewayTarget
            Copy-Item -LiteralPath $BackendSource -Destination $BackendTarget
            $runtimeCreated = $true
        }
        elseif ((Get-Sha256 $GatewayTarget) -ne $gatewaySha256 -or (Get-Sha256 $BackendTarget) -ne $backendSha256) {
            Fail "Installed runtime differs from this bundle"
        }
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $RuleTarget), (Split-Path -Parent $CodexSkillTarget) | Out-Null
    if ($isReinstall) {
        Copy-Item -LiteralPath $RuleTarget -Destination (Join-Path $staging "rollback-rule")
        Copy-Item -LiteralPath $CodexSkillTarget -Destination (Join-Path $staging "rollback-codex-skill")
    }
    Copy-Item -LiteralPath (Join-Path $ScriptDir "payload\rules\codegraph-harness.md") -Destination $RuleTarget -Force
    $ruleWritten = $true
    Copy-Item -LiteralPath (Join-Path $ScriptDir "payload\codex\skills\company-codegraph\SKILL.md") -Destination $CodexSkillTarget -Force
    $skillWritten = $true

    if (-not $SkipPlugin -and (Get-Command claude -ErrorAction SilentlyContinue)) {
        & claude plugin marketplace add (Join-Path $InstallRoot "marketplace") --scope user
        if ($LASTEXITCODE -ne 0) { Fail "Failed to add local marketplace" }
        $marketplaceAdded = $true
        & claude plugin install $PluginId --scope user --yes
        if ($LASTEXITCODE -ne 0) { Fail "Failed to install plugin" }
        $pluginInstalled = $true
    }

    # One canonical immutable argument list is shared by both client registrations.
    $commonGatewayArgs = @(
        "serve", "--allowed-root", $AllowedRoot,
        "--data-classification", "public-fixture",
        "--state-dir", (Join-Path $DataRoot "graph-state"),
        "--cbm-binary", $BackendTarget,
        "--backend-sha256", $backendSha256,
        "--config", $configPath,
        "--config-sha256", $configSha256,
        "--git-binary", $gitBinary,
        "--git-sha256", $gitSha256
    )
    if ($runtimeInstall -and (Get-Command claude -ErrorAction SilentlyContinue)) {
        if ($isReinstall -and $oldReceipt.claudeMcpRegistered) {
            $claudeMcpRegistered = $true
            $claudeMcpSha256 = $oldReceipt.claudeMcpSha256
        }
        else {
            & claude mcp add --scope user --transport stdio $ClaudeMcpId -- $GatewayTarget @commonGatewayArgs
            if ($LASTEXITCODE -ne 0) { Fail "Failed to register Claude MCP" }
            $claudeMcpRegistered = $true
            $claudeMcpSha256 = Get-RegistrationHash "claude" $ClaudeMcpId
            if (-not $claudeMcpSha256) { Fail "Could not verify Claude MCP registration" }
        }
    }
    if ($runtimeInstall -and (Get-Command codex -ErrorAction SilentlyContinue)) {
        if ($isReinstall -and $oldReceipt.codexMcpRegistered) {
            $codexMcpRegistered = $true
            $codexMcpSha256 = $oldReceipt.codexMcpSha256
        }
        else {
            & codex mcp add $CodexMcpId -- $GatewayTarget @commonGatewayArgs
            if ($LASTEXITCODE -ne 0) { Fail "Failed to register Codex MCP" }
            $codexMcpRegistered = $true
            $codexMcpSha256 = Get-RegistrationHash "codex" $CodexMcpId
            if (-not $codexMcpSha256) { Fail "Could not verify Codex MCP registration" }
        }
    }

    New-Item -ItemType Directory -Force -Path $CurrentRoot | Out-Null
    $receipt = @{
        schemaVersion = 3
        version = $Version
        installRoot = $InstallRoot
        ruleTarget = $RuleTarget
        ruleInstalledSha256 = Get-Sha256 $RuleTarget
        codexSkillTarget = $CodexSkillTarget
        codexSkillInstalledSha256 = Get-Sha256 $CodexSkillTarget
        pluginId = $PluginId
        pluginInstalled = $pluginInstalled
        marketplaceAdded = $marketplaceAdded
        runtimeInstalled = $runtimeInstall
        runtimePlatform = $platform
        runtimeArch = $arch
        runtimeRoot = $RuntimeTargetRoot
        gatewayPath = $GatewayTarget
        backendPath = $BackendTarget
        gatewaySha256 = $gatewaySha256
        backendSha256 = $backendSha256
        claudeGatewaySha256 = $gatewaySha256
        claudeBackendSha256 = $backendSha256
        codexGatewaySha256 = $gatewaySha256
        codexBackendSha256 = $backendSha256
        configPath = $configPath
        configSha256 = $configSha256
        gitBinary = $gitBinary
        gitSha256 = $gitSha256
        allowedRoot = $AllowedRoot
        claudeMcpRegistered = $claudeMcpRegistered
        claudeMcpSha256 = $claudeMcpSha256
        codexMcpRegistered = $codexMcpRegistered
        codexMcpSha256 = $codexMcpSha256
    }
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding UTF8
}
catch {
    if ($codexMcpRegistered -and -not $isReinstall) { & codex mcp remove $CodexMcpId 2>$null }
    if ($claudeMcpRegistered -and -not $isReinstall) { & claude mcp remove --scope user $ClaudeMcpId 2>$null }
    if ($pluginInstalled) { & claude plugin uninstall $PluginId --scope user --yes 2>$null }
    if ($marketplaceAdded) { & claude plugin marketplace remove codegraph-harness --scope user 2>$null }
    if ($ruleWritten) {
        if ($isReinstall) { Copy-Item -LiteralPath (Join-Path $staging "rollback-rule") -Destination $RuleTarget -Force }
        else { Remove-Item -LiteralPath $RuleTarget -Force -ErrorAction SilentlyContinue }
    }
    if ($skillWritten) {
        if ($isReinstall) { Copy-Item -LiteralPath (Join-Path $staging "rollback-codex-skill") -Destination $CodexSkillTarget -Force }
        else { Remove-Item -LiteralPath $CodexSkillTarget -Force -ErrorAction SilentlyContinue }
    }
    if ($runtimeCreated) {
        Remove-Item -LiteralPath $GatewayTarget -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $BackendTarget -Force -ErrorAction SilentlyContinue
    }
    if ($installRootCreated) { Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue }
    throw
}
finally {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
}

@{status="success"; summary="Codegraph harness installed"; next_actions=@("Restart Claude Code and Codex; build indexes explicitly from approved repositories"); artifacts=@($receiptPath)} | ConvertTo-Json -Compress
