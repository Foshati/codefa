param(
    [switch] $Yes,
    [switch] $VoiceNim,
    [switch] $VoiceLocal,
    [switch] $VoiceAll,
    [string] $TorchBackend = "",
    [switch] $DryRun,
    [switch] $Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]] $RemainingArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoArchiveUrl = "https://github.com/Foshati/codefa/archive/refs/heads/main.zip"
$PythonVersion = "3.14.0"
$MinUvVersion = "0.11.16"
$ClaudeInstallUrl = "https://claude.ai/install.ps1"
$CodexInstallUrl = "https://chatgpt.com/codex/install.ps1"

$UvInstallUrl = "https://astral.sh/uv/install.ps1"
$CodefaCommands = @(
    "codefa-server",
    "codefa-claude",
    "codefax",
    "codefa-init",
    "codefa"
)

function Show-Usage {
    @"
Usage: install.ps1 [options]

Installs Claude Code and Codex if missing, ensures a compatible uv, and installs or updates codefa.

Options:
  -Yes                   Automatically accept interactive prompts.
  -VoiceNim              Install NVIDIA NIM voice transcription support.
  -VoiceLocal            Install local Whisper voice transcription support.
  -VoiceAll              Install all voice transcription backends.
  -TorchBackend VALUE    Use a uv PyTorch backend, such as cu130. Requires local voice.
  -DryRun                Print commands without running them.
  -Help                  Show this help text.
"@
}

function Write-Step {
    param([string] $Message)

    Write-Host "  " -NoNewline
    Write-Host "✔ " -ForegroundColor Green -NoNewline
    Write-Host "$Message"
}

function Confirm-Choice {
    param([string] $Message)

    if ($Yes) {
        return $true
    }

    Write-Host "  ? " -ForegroundColor Cyan -NoNewline
    Write-Host "$Message [Y/n] " -NoNewline
    $response = Read-Host
    if ([string]::IsNullOrWhiteSpace($response) -or $response -match '^[yY]') {
        return $true
    }
    return $false
}

function Format-Argument {
    param([string] $Value)

    if ($Value -match '^[A-Za-z0-9_./:@%+=,\[\]\\-]+$') {
        return $Value
    }

    return "'" + ($Value -replace "'", "''") + "'"
}

function Format-Command {
    param(
        [string] $FilePath,
        [string[]] $Arguments = @()
    )

    $parts = @($FilePath) + $Arguments
    return ($parts | ForEach-Object { Format-Argument ([string] $_) }) -join " "
}

function Invoke-NativeCommand {
    param(
        [string] $FilePath,
        [string[]] $Arguments = @()
    )

    $commandText = Format-Command -FilePath $FilePath -Arguments $Arguments
    Write-Host "+ $commandText"
    if ($DryRun) {
        return
    }

    $global:LASTEXITCODE = 0
    & $FilePath @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Command failed with exit code ${exitCode}: $commandText"
    }
}

function Invoke-NativeCapture {
    param(
        [string] $FilePath,
        [string[]] $Arguments = @()
    )

    $commandText = Format-Command -FilePath $FilePath -Arguments $Arguments
    Write-Host "+ $commandText"
    $global:LASTEXITCODE = 0
    $output = & $FilePath @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Command failed with exit code ${exitCode}: $commandText"
    }

    return ($output | Out-String).Trim()
}

function Get-ApplicationCommand {
    param([string] $Name)

    $commands = @(Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue)
    if ($commands.Count -eq 0) {
        return $null
    }

    return $commands[0]
}

function Get-PowerShellExecutable {
    param([string] $PowerShellHome = $PSHOME)

    $executableName = if ($PSVersionTable.PSEdition -eq "Core") {
        "pwsh.exe"
    }
    else {
        "powershell.exe"
    }
    $bundledExecutable = Join-Path $PowerShellHome $executableName
    if (Test-Path -LiteralPath $bundledExecutable -PathType Leaf) {
        return $bundledExecutable
    }

    $pathCommand = Get-ApplicationCommand ([IO.Path]::GetFileNameWithoutExtension($executableName))
    if ($pathCommand) {
        return $pathCommand.Source
    }

    throw "Unable to locate a PowerShell executable for the downloaded installer."
}

function Add-PathEntry {
    param([string] $PathEntry)

    if ([string]::IsNullOrWhiteSpace($PathEntry)) {
        return
    }

    $separator = [IO.Path]::PathSeparator
    $entries = @()
    if (-not [string]::IsNullOrEmpty($env:Path)) {
        $entries = $env:Path -split [regex]::Escape([string] $separator)
    }

    if ($entries -notcontains $PathEntry) {
        $env:Path = "$PathEntry$separator$env:Path"
    }
}

function Add-KnownBinDirectories {
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        Add-PathEntry (Join-Path $env:USERPROFILE ".local\bin")
    }
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        Add-PathEntry (Join-Path $env:LOCALAPPDATA "Programs\OpenAI\Codex\bin")

    }
}



function Assert-NoCodefaProcessesRunning {
    $running = @()
    foreach ($commandName in $CodefaCommands) {
        $processes = @(Get-Process -Name $commandName -ErrorAction SilentlyContinue)
        foreach ($process in $processes) {
            $running += "$commandName (PID $($process.Id))"
        }
    }

    if ($running.Count -gt 0) {
        throw "codefa is still running ($($running -join ', ')). Stop those processes, then rerun the installer."
    }
}

function Invoke-DownloadedPowerShellInstaller {
    param(
        [string] $Url,
        [string] $Name,
        [switch] $NonInteractive
    )

    if ($DryRun) {
        Write-Host "+ irm $Url -OutFile <temporary-script>"
        $prefix = if ($NonInteractive) { "CODEX_NON_INTERACTIVE=1 " } else { "" }
        Write-Host "+ ${prefix}powershell -NoProfile -ExecutionPolicy Bypass -File <temporary-script>"
        return
    }

    $temporaryScript = Join-Path ([IO.Path]::GetTempPath()) ("codefa-install-" + [guid]::NewGuid().ToString("N") + ".ps1")
    try {
        Write-Host "+ irm $Url -OutFile $(Format-Argument $temporaryScript)"
        Invoke-RestMethod -Uri $Url -OutFile $temporaryScript -ErrorAction Stop
        if ((-not (Test-Path -LiteralPath $temporaryScript)) -or ((Get-Item -LiteralPath $temporaryScript).Length -eq 0)) {
            throw "The downloaded $Name installer was empty."
        }

        $powerShellPath = Get-PowerShellExecutable

        $hadNonInteractive = Test-Path Env:CODEX_NON_INTERACTIVE
        $previousNonInteractive = $env:CODEX_NON_INTERACTIVE
        try {
            if ($NonInteractive) {
                $env:CODEX_NON_INTERACTIVE = "1"
            }
            Invoke-NativeCommand -FilePath $powerShellPath -Arguments @(
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                $temporaryScript
            )
        }
        finally {
            if ($hadNonInteractive) {
                $env:CODEX_NON_INTERACTIVE = $previousNonInteractive
            }
            else {
                Remove-Item Env:CODEX_NON_INTERACTIVE -ErrorAction SilentlyContinue
            }
        }
    }
    finally {
        Remove-Item -LiteralPath $temporaryScript -Force -ErrorAction SilentlyContinue
    }
}

function Confirm-Application {
    param(
        [string] $CommandName,
        [string] $DisplayName
    )

    if ($DryRun) {
        Write-Host "+ $CommandName --version"
        return
    }

    $command = Get-ApplicationCommand $CommandName
    if (-not $command) {
        throw "$DisplayName was installed, but '$CommandName' is not available on PATH."
    }
    Invoke-NativeCommand -FilePath $command.Source -Arguments @("--version")
}


function Get-CommandVersion {
    param([string] $CommandName)

    $command = Get-ApplicationCommand $CommandName
    if ($command) {
        $raw = (& $command.Source --version 2>$null | Select-Object -First 1 | Out-String).Trim()
        if ($raw -match '(?<ver>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z.-]*)?)') {
            return "v" + $Matches["ver"]
        }
    }
    return ""
}

function Ensure-ClaudeCode {
    $existing = Get-ApplicationCommand "claude"
    if ($existing) {
        Confirm-Application -CommandName "claude" -DisplayName "Claude Code"
        $ver = Get-CommandVersion "claude"
        if ($ver) {
            Write-Step "Claude Code verified ($ver)"
        }
        else {
            Write-Step "Claude Code verified"
        }
        return
    }

    if (Confirm-Choice "Install Claude Code (Anthropic CLI)?") {
        Invoke-DownloadedPowerShellInstaller -Url $ClaudeInstallUrl -Name "Claude Code"
        Add-KnownBinDirectories
        Confirm-Application -CommandName "claude" -DisplayName "Claude Code"
        $ver = Get-CommandVersion "claude"
        if ($ver) {
            Write-Step "Claude Code installed and verified ($ver)"
        }
        else {
            Write-Step "Claude Code installed and verified"
        }
    }
    else {
        Write-Host "  ✦ Claude Code installation skipped" -ForegroundColor Gray
    }
}

function Ensure-Codex {
    $existing = Get-ApplicationCommand "codex"
    if ($existing) {
        Confirm-Application -CommandName "codex" -DisplayName "Codex"
        $ver = Get-CommandVersion "codex"
        if ($ver) {
            Write-Step "Codex CLI verified ($ver)"
        }
        else {
            Write-Step "Codex CLI verified"
        }
        return
    }

    if (Confirm-Choice "Install Codex CLI (OpenAI CLI)?") {
        Invoke-DownloadedPowerShellInstaller -Url $CodexInstallUrl -Name "Codex" -NonInteractive
        Add-KnownBinDirectories
        Confirm-Application -CommandName "codex" -DisplayName "Codex"
        $ver = Get-CommandVersion "codex"
        if ($ver) {
            Write-Step "Codex CLI installed and verified ($ver)"
        }
        else {
            Write-Step "Codex CLI installed and verified"
        }
    }
    else {
        Write-Host "  ✦ Codex CLI installation skipped" -ForegroundColor Gray
    }
}


function Convert-UvVersionOutput {
    param([string] $Output)

    if ([string]::IsNullOrWhiteSpace($Output)) {
        return ""
    }

    if ($Output -match '(?m)(?:^|\s)(?:uv\s+)?(?<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z][0-9A-Za-z.-]*)?)\b') {
        return $Matches["version"]
    }

    return ""
}

function Get-UvVersion {
    param([string] $UvPath)

    $output = Invoke-NativeCapture -FilePath $UvPath -Arguments @("--version")
    $version = Convert-UvVersionOutput $output
    if ([string]::IsNullOrWhiteSpace($version)) {
        throw "uv is present, but 'uv --version' did not return a valid version."
    }

    return $version
}

function Test-SupportedUvVersion {
    param(
        [string] $Version,
        [string] $Minimum
    )

    $parsedVersion = Convert-UvVersionOutput $Version
    $parsedMinimum = Convert-UvVersionOutput $Minimum
    if ([string]::IsNullOrWhiteSpace($parsedVersion) -or [string]::IsNullOrWhiteSpace($parsedMinimum)) {
        throw "Unable to compare uv versions."
    }
    if ($parsedVersion.Contains("-")) {
        return $false
    }

    $normalizedVersion = $parsedVersion -replace '\+.*$', ''
    $normalizedMinimum = $parsedMinimum -replace '\+.*$', ''

    return ([version] $normalizedVersion) -ge ([version] $normalizedMinimum)
}

function Confirm-Uv {
    if ($DryRun) {
        Write-Host "+ uv --version"
        return
    }

    $uvCommand = Get-ApplicationCommand "uv"
    if (-not $uvCommand) {
        throw "uv was installed, but it is not available on PATH."
    }

    $version = Get-UvVersion $uvCommand.Source
    if (-not (Test-SupportedUvVersion -Version $version -Minimum $MinUvVersion)) {
        throw "Stable uv $MinUvVersion or newer is required; found uv $version after installation."
    }
    Write-Host "Verified uv $version."
}

function Ensure-Uv {
    if ($DryRun) {
        if (Get-ApplicationCommand "uv") {
            Write-Host "+ uv --version"
            Write-Host "A compatible existing uv will be left unchanged; an obsolete one will be replaced by the standalone installer."
        }
        else {
            Write-Host "uv is not installed; the current standalone uv would be installed."
            Invoke-DownloadedPowerShellInstaller -Url $UvInstallUrl -Name "uv"
            Confirm-Uv
        }
        return
    }

    $uvCommand = Get-ApplicationCommand "uv"
    if ($uvCommand) {
        $version = Get-UvVersion $uvCommand.Source
        if (Test-SupportedUvVersion -Version $version -Minimum $MinUvVersion) {
            Write-Host "uv $version already satisfies >=$MinUvVersion; leaving it unchanged."
            return
        }
        Write-Host "uv $version does not satisfy stable >=$MinUvVersion; installing the current standalone uv."
    }
    else {
        Write-Host "uv is not installed; installing the current standalone uv."
    }

    Invoke-DownloadedPowerShellInstaller -Url $UvInstallUrl -Name "uv"
    Add-KnownBinDirectories
    Confirm-Uv
}

function Get-PackageSpec {
    $includeNim = $VoiceNim
    $includeLocal = $VoiceLocal

    if ($VoiceAll) {
        $includeNim = $true
        $includeLocal = $true
    }

    if ($includeNim -and $includeLocal) {
        return "codefa[voice,voice_local] @ $RepoArchiveUrl"
    }
    if ($includeNim) {
        return "codefa[voice] @ $RepoArchiveUrl"
    }
    if ($includeLocal) {
        return "codefa[voice_local] @ $RepoArchiveUrl"
    }
    return "codefa @ $RepoArchiveUrl"
}

function Install-FreeClaudeCode {
    Assert-NoCodefaProcessesRunning
    $packageSpec = Get-PackageSpec
    $arguments = @(
        "tool",
        "install",
        "--force",
        "--refresh-package",
        "codefa",
        "--python",
        $PythonVersion
    )
    if (-not [string]::IsNullOrWhiteSpace($TorchBackend)) {
        $arguments += @("--torch-backend", $TorchBackend)
    }
    $arguments += $packageSpec

    $uvPath = "uv"
    if (-not $DryRun) {
        $uvCommand = Get-ApplicationCommand "uv"
        if (-not $uvCommand) {
            throw "uv is not available for the Free Claude Code installation."
        }
        $uvPath = $uvCommand.Source
    }
    Invoke-NativeCommand -FilePath $uvPath -Arguments $arguments
}

function Configure-AndConfirmFreeClaudeCode {
    if ($DryRun) {
        Write-Host "+ uv tool update-shell"
        Write-Host "+ uv tool dir --bin"
        Write-Host "+ verify codefa-server, codefa-claude, and codefax in the uv tool bin directory"
        Write-Host "+ codefa-server --version"
        return
    }

    $uvCommand = Get-ApplicationCommand "uv"
    if (-not $uvCommand) {
        throw "uv is not available for PATH configuration."
    }
    Invoke-NativeCommand -FilePath $uvCommand.Source -Arguments @("tool", "update-shell")
    $toolBin = Invoke-NativeCapture -FilePath $uvCommand.Source -Arguments @("tool", "dir", "--bin")
    if ([string]::IsNullOrWhiteSpace($toolBin)) {
        throw "uv returned an empty tool bin directory."
    }

    Add-PathEntry $toolBin
    $toolBinPath = ([IO.Path]::GetFullPath($toolBin)).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $installedCommands = @{}
    foreach ($commandName in @("codefa-server", "codefa-claude", "codefax")) {
        $command = Get-ApplicationCommand $commandName
        if (-not $command) {
            throw "codefa installation did not create '$commandName'."
        }
        $commandDirectory = ([IO.Path]::GetFullPath((Split-Path -Parent $command.Source))).TrimEnd(
            [IO.Path]::DirectorySeparatorChar,
            [IO.Path]::AltDirectorySeparatorChar
        )
        if (-not $commandDirectory.Equals($toolBinPath, [StringComparison]::OrdinalIgnoreCase)) {
            throw "'$commandName' resolved outside the uv tool bin directory: $($command.Source)"
        }
        $installedCommands[$commandName] = $command.Source
    }

    Invoke-NativeCommand -FilePath $installedCommands["codefa-server"] -Arguments @("--version")
}

if ($Help) {
    Show-Usage
    return
}

if ($RemainingArgs.Count -gt 0) {
    Show-Usage
    throw "Unknown option: $($RemainingArgs -join ' ')"
}

if ((-not [string]::IsNullOrWhiteSpace($TorchBackend)) -and (-not ($VoiceLocal -or $VoiceAll))) {
    throw "-TorchBackend requires -VoiceLocal or -VoiceAll."
}

Add-KnownBinDirectories

Write-Step "Checking for running Free Claude Code processes"
Assert-NoCodefaProcessesRunning

Write-Step "Ensuring Claude Code is installed"
Ensure-ClaudeCode

Write-Step "Ensuring Codex is installed"
Ensure-Codex



Write-Step "Ensuring uv $MinUvVersion or newer is installed"
Ensure-Uv

Write-Step "Installing or updating Free Claude Code"
Install-FreeClaudeCode

Write-Step "Configuring PATH and verifying Free Claude Code"
Configure-AndConfirmFreeClaudeCode

Write-Host ""
if ($DryRun) {
    Write-Host "Dry run complete. No changes were made."
}
else {
    Write-Host "  " -NoNewline
    Write-Host "✔ " -ForegroundColor Green -NoNewline
    Write-Host "codefa is installed and verified."
    Write-Host ""
    Write-Host "  🚀 codefa ready!" -ForegroundColor White
    Write-Host ""
    Write-Host "  Usage:" -ForegroundColor White
    Write-Host "    codefa           " -ForegroundColor Green -NoNewline
    Write-Host "Launch interactive AI assistant chooser"
    Write-Host "    codefa --claude  " -ForegroundColor Green -NoNewline
    Write-Host "Launch Anthropic Claude Code CLI"
    Write-Host "    codefa --codex   " -ForegroundColor Green -NoNewline
    Write-Host "Launch OpenAI Codex CLI"
    Write-Host "    codefa --server  " -ForegroundColor Green -NoNewline
    Write-Host "Start background proxy server (port 8090)"
    Write-Host ""
}
