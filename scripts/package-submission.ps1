param(
  [string]$OutputPath = (Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'Covenia-Competition-Demo-2026-10-03-v4.zip')
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-RelativePath([string]$BasePath, [string]$TargetPath) {
  $BaseFullPath = [System.IO.Path]::GetFullPath($BasePath).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
  $TargetFullPath = [System.IO.Path]::GetFullPath($TargetPath)
  $BaseUri = [System.Uri]::new($BaseFullPath)
  $TargetUri = [System.Uri]::new($TargetFullPath)
  return [System.Uri]::UnescapeDataString($BaseUri.MakeRelativeUri($TargetUri).ToString()).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
}

$ExcludedDirectoryNames = @('.git', '.presentation-build', '.run', '.pytest_cache', '__pycache__', 'node_modules', 'dist')
$Files = Get-ChildItem -LiteralPath $ProjectRoot -File -Recurse -Force | Where-Object {
  $Relative = Get-RelativePath $ProjectRoot $_.FullName
  $Parts = $Relative -split '[\\/]'
  $HasExcludedDirectory = @($Parts | Where-Object { $ExcludedDirectoryNames -contains $_ }).Count -gt 0
  $IsSecretConfig = ($_.Name -eq '.env') -or ($_.Name -like '.env.*' -and $_.Name -ne '.env.example')
  $IsSupersededDeck = $Relative.Replace('\', '/') -match '^submission/.+-2026-10\.pptx$'
  ($_.FullName -ne $OutputPath) -and (-not $HasExcludedDirectory) -and (-not $IsSecretConfig) -and
  (-not $IsSupersededDeck)
}

if (Test-Path -LiteralPath $OutputPath) { Remove-Item -LiteralPath $OutputPath -Force }
$Stream = [System.IO.File]::Open($OutputPath, [System.IO.FileMode]::CreateNew)
try {
  $Archive = [System.IO.Compression.ZipArchive]::new($Stream, [System.IO.Compression.ZipArchiveMode]::Create)
  try {
    foreach ($File in $Files) {
      $Relative = (Get-RelativePath $ProjectRoot $File.FullName).Replace('\', '/')
      $Entry = $Archive.CreateEntry($Relative, [System.IO.Compression.CompressionLevel]::Optimal)
      $InputStream = [System.IO.File]::OpenRead($File.FullName)
      try {
        $EntryStream = $Entry.Open()
        try { $InputStream.CopyTo($EntryStream) } finally { $EntryStream.Dispose() }
      } finally { $InputStream.Dispose() }
    }
  } finally { $Archive.Dispose() }
} finally { $Stream.Dispose() }

$Check = [System.IO.Compression.ZipFile]::OpenRead($OutputPath)
try {
  $Names = @($Check.Entries | ForEach-Object { $_.FullName })
  $Leaks = @($Names | Where-Object { $_ -match '(^|/)\.env($|/)|(^|/)\.git(/|$)|(^|/)node_modules(/|$)|(^|/)dist(/|$)' })
  if ($Leaks.Count -gt 0) { throw "Package contains excluded files: $($Leaks -join ', ')" }
  $HasStartup = $Names -contains 'START-COVENIA.cmd'
  $HasCurrentPresentation = @($Names | Where-Object { $_ -like 'submission/*v2.pptx' }).Count -gt 0
  if (-not $HasStartup -or -not $HasCurrentPresentation) { throw "Required startup or current presentation file missing from package (startup=$HasStartup, presentation=$HasCurrentPresentation)." }
  "Created $OutputPath with $($Names.Count) files; secret and build directories excluded."
} finally { $Check.Dispose() }
