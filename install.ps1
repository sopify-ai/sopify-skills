Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoOwner = "sopify-ai"
$RepoName = "sopify"
$AssetName = "install.ps1"
$SourceChannel = "dev"
$SourceRef = "main"

function Show-Usage {
  @"
Usage: install.ps1 [--target <host:lang>] [--ref <tag-or-branch>]

Thin Sopify installer entrypoint.

Options:
  --target <host:lang>   Install target. Required in non-interactive mode.
  --ref <tag-or-branch>  Optional source override. Expert / maintainer use only.
  --workspace <path>     Internal-only project prewarm path. Default user flow bootstraps on first project trigger.
  -h, --help             Show this help message.
"@
}

function Fail-Install {
  param(
    [string]$Phase,
    [string]$ReasonCode,
    [string]$Detail,
    [string]$NextStep
  )

  [Console]::Error.WriteLine("Sopify install failed:")
  [Console]::Error.WriteLine("  phase: $Phase")
  [Console]::Error.WriteLine("  reason_code: $ReasonCode")
  [Console]::Error.WriteLine("  detail: $Detail")
  [Console]::Error.WriteLine("  next_step: $NextStep")
  exit 1
}

function Resolve-PythonCommand {
  $python3 = Get-Command python3 -ErrorAction SilentlyContinue
  if ($null -ne $python3) {
    return @{
      executable = $python3.Path
      prefixArgs = @()
    }
  }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($null -ne $python) {
    return @{
      executable = $python.Path
      prefixArgs = @()
    }
  }

  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($null -ne $py) {
    return @{
      executable = $py.Path
      prefixArgs = @("-3")
    }
  }

  Fail-Install -Phase "preflight" -ReasonCode "MISSING_PYTHON" -Detail "None of `python3`, `python`, or `py -3` is available." -NextStep "Install Python 3, then rerun the installer."
}

$forwardedArgs = New-Object System.Collections.Generic.List[string]
$refOverride = $null
for ($i = 0; $i -lt $args.Count; $i++) {
  $arg = $args[$i]
  switch -Regex ($arg) {
    '^(-h|--help)$' {
      Show-Usage
      exit 0
    }
    '^--ref=(.+)$' {
      $refOverride = $Matches[1]
      $forwardedArgs.Add($arg)
      continue
    }
    '^--ref$' {
      if ($i + 1 -ge $args.Count) {
        Fail-Install -Phase "input" -ReasonCode "MISSING_REF_VALUE" -Detail "`--ref` requires a value." -NextStep "Pass --ref <tag-or-branch>, or omit the flag."
      }
      $refOverride = $args[$i + 1]
      $forwardedArgs.Add($arg)
      $forwardedArgs.Add($args[$i + 1])
      $i++
      continue
    }
    default {
      $forwardedArgs.Add($arg)
    }
  }
}

$resolvedRef = if ([string]::IsNullOrWhiteSpace($refOverride)) { $SourceRef } else { $refOverride }
if ([string]::IsNullOrWhiteSpace($resolvedRef)) {
  Fail-Install -Phase "input" -ReasonCode "MISSING_SOURCE_REF" -Detail "No source ref was resolved for the installer." -NextStep "Retry with --ref <tag-or-branch>, or inspect the release asset rendering."
}

$pythonCommand = Resolve-PythonCommand
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sopify-install-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null

try {
  $archiveUrl = "https://codeload.github.com/$RepoOwner/$RepoName/zip/$resolvedRef"
  $archivePath = Join-Path $tempRoot "source.zip"

  try {
    Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath | Out-Null
  } catch {
    Fail-Install -Phase "download" -ReasonCode "SOURCE_FETCH_FAILED" -Detail "Failed to download source archive: $archiveUrl" -NextStep "Check network access, verify the ref exists, or use the inspect-first path."
  }

  try {
    Expand-Archive -Path $archivePath -DestinationPath $tempRoot -Force
  } catch {
    Fail-Install -Phase "unpack" -ReasonCode "SOURCE_EXTRACT_FAILED" -Detail "Failed to extract source archive: $archivePath" -NextStep "Retry the installer or inspect the downloaded archive locally."
  }

  $sourceDir = Get-ChildItem -Path $tempRoot -Directory | Where-Object { $_.FullName -ne $tempRoot } | Select-Object -First 1
  if ($null -eq $sourceDir) {
    Fail-Install -Phase "unpack" -ReasonCode "SOURCE_ROOT_MISSING" -Detail "The extracted source archive did not contain a repository root directory." -NextStep "Retry the installer or inspect the downloaded archive locally."
  }

  $entrypoint = Join-Path $sourceDir.FullName "scripts/install_sopify.py"
  if (-not (Test-Path -LiteralPath $entrypoint)) {
    Fail-Install -Phase "unpack" -ReasonCode "INSTALL_ENTRYPOINT_MISSING" -Detail "Missing install entrypoint inside source archive: $entrypoint" -NextStep "Retry the installer or inspect the downloaded archive locally."
  }

  $pythonArgs = @()
  $pythonArgs += $pythonCommand.prefixArgs
  $pythonArgs += @(
    $entrypoint,
    "--source-channel",
    $SourceChannel,
    "--source-resolved-ref",
    $resolvedRef,
    "--source-asset-name",
    $AssetName
  )
  $pythonArgs += $forwardedArgs.ToArray()

  & $pythonCommand.executable @pythonArgs
  exit $LASTEXITCODE
} finally {
  if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}
