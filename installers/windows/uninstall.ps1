[CmdletBinding()]
param(
    [string]$DataRoot,
    [string]$StateRoot,
    [switch]$PurgeGraphState
)

$ErrorActionPreference = "Stop"
if (-not $DataRoot) {
    $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME "AppData\Local" }
    $DataRoot = Join-Path $base "CompanyCodegraph"
}
if (-not $StateRoot) { $StateRoot = Join-Path $DataRoot "state" }
$receiptPath = Join-Path $StateRoot "current\receipt.json"
if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { throw "No installation receipt found at $receiptPath" }

$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
$warning = $false
$preserveRuntime = $false

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
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

function Remove-OwnedRegistration([string]$Client, [string]$Name, [bool]$Registered, [string]$InstalledHash) {
    if (-not $Registered) { return }
    if (-not (Get-Command $Client -ErrorAction SilentlyContinue)) {
        $script:warning = $true
        $script:preserveRuntime = $true
        Write-Warning "$Client was not found; MCP registration was preserved"
        return
    }
    $currentHash = Get-RegistrationHash $Client $Name
    if (-not $currentHash -or $currentHash -ne $InstalledHash) {
        $script:warning = $true
        $script:preserveRuntime = $true
        Write-Warning "Preserved user-modified MCP registration: $Name"
        return
    }
    if ($Client -eq "claude") { & claude mcp remove --scope user $Name }
    else { & codex mcp remove $Name }
    if ($LASTEXITCODE -ne 0) {
        $script:warning = $true
        $script:preserveRuntime = $true
    }
}

Remove-OwnedRegistration "claude" "company-codegraph" ([bool]$receipt.claudeMcpRegistered) $receipt.claudeMcpSha256
Remove-OwnedRegistration "codex" "company_codegraph" ([bool]$receipt.codexMcpRegistered) $receipt.codexMcpSha256

if ($receipt.pluginInstalled -and (Get-Command claude -ErrorAction SilentlyContinue)) {
    & claude plugin uninstall $receipt.pluginId --scope user --yes
    if ($LASTEXITCODE -ne 0) { $warning = $true }
}
elseif ($receipt.pluginInstalled) {
    $warning = $true
    Write-Warning "Claude Code was not found; plugin removal could not be verified"
}
if ($receipt.marketplaceAdded -and (Get-Command claude -ErrorAction SilentlyContinue)) {
    & claude plugin marketplace remove codegraph-harness --scope user
    if ($LASTEXITCODE -ne 0) { $warning = $true }
}

function Remove-OwnedFile([string]$Target, [string]$InstalledHash, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) { return }
    if ((Get-Sha256 $Target) -eq $InstalledHash) { Remove-Item -LiteralPath $Target -Force }
    else {
        $script:warning = $true
        if ($Label -eq "Rule") { Write-Warning "Preserved user-modified Rule: $Target" }
        elseif ($Label -eq "Codex skill") { Write-Warning "Preserved user-modified Codex skill: $Target" }
        else { Write-Warning "Preserved user-modified $Label`: $Target" }
    }
}

Remove-OwnedFile $receipt.ruleTarget $receipt.ruleInstalledSha256 "Rule"
Remove-OwnedFile $receipt.codexSkillTarget $receipt.codexSkillInstalledSha256 "Codex skill"

if ($receipt.runtimeInstalled) {
    $gatewayValid = (Test-Path -LiteralPath $receipt.gatewayPath -PathType Leaf) -and ((Get-Sha256 $receipt.gatewayPath) -eq $receipt.gatewaySha256)
    $backendValid = (Test-Path -LiteralPath $receipt.backendPath -PathType Leaf) -and ((Get-Sha256 $receipt.backendPath) -eq $receipt.backendSha256)
    if ($preserveRuntime) {
        $warning = $true
        Write-Warning "Preserved runtime because an MCP registration remains"
    }
    elseif ($gatewayValid -and $backendValid) {
        Remove-Item -LiteralPath $receipt.gatewayPath -Force
        Remove-Item -LiteralPath $receipt.backendPath -Force
        $binRoot = Split-Path -Parent $receipt.gatewayPath
        if ((Test-Path -LiteralPath $binRoot) -and -not (Get-ChildItem -LiteralPath $binRoot -Force)) { Remove-Item -LiteralPath $binRoot -Force }
        if ((Test-Path -LiteralPath $receipt.runtimeRoot) -and -not (Get-ChildItem -LiteralPath $receipt.runtimeRoot -Force)) { Remove-Item -LiteralPath $receipt.runtimeRoot -Force }
    }
    elseif (Test-Path -LiteralPath $receipt.runtimeRoot) {
        $warning = $true
        Write-Warning "Preserved user-modified runtime: $($receipt.runtimeRoot)"
    }
}

Remove-Item -LiteralPath $receiptPath -Force
if ($PurgeGraphState) {
    $graphStateRoot = Join-Path $DataRoot "graph-state"
    if (Test-Path -LiteralPath $graphStateRoot) {
        if ((Get-Item -LiteralPath $graphStateRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Graph state root must not be a reparse point"
        }
        Remove-Item -LiteralPath $graphStateRoot -Recurse -Force
    }
}
if ($warning) {
    @{status="warning"; summary="Uninstall completed with preserved user-modified or unverifiable items"; next_actions=@("Review warnings and remove retained graph state if required"); artifacts=@()} | ConvertTo-Json -Compress
}
else {
    if ($PurgeGraphState) {
        @{status="success"; summary="Codegraph harness and derived graph state uninstalled"; next_actions=@(); artifacts=@()} | ConvertTo-Json -Compress
    }
    else {
        @{status="success"; summary="Codegraph harness uninstalled; derived graph state retained"; next_actions=@("Delete the retained graph-state directory through the approved internal procedure if policy requires it"); artifacts=@()} | ConvertTo-Json -Compress
    }
}
