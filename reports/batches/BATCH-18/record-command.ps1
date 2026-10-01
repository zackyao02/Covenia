param(
    [Parameter(Mandatory=$true)][string]$Id,
    [Parameter(Mandatory=$true)][string]$Executable,
    [Parameter(Mandatory=$true)][string[]]$Arguments,
    [string]$Mode = 'UNIT'
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$evidenceRoot = Join-Path $PSScriptRoot 'command-output'
New-Item -ItemType Directory -Path $evidenceRoot -Force | Out-Null
$started = Get-Date
$watch = [Diagnostics.Stopwatch]::StartNew()
$oldNative = $PSNativeCommandUseErrorActionPreference
$PSNativeCommandUseErrorActionPreference = $false
try {
    $output = & $Executable @Arguments 2>&1 | Out-String
    $code = $LASTEXITCODE
} finally {
    $PSNativeCommandUseErrorActionPreference = $oldNative
    $watch.Stop()
}
$record = [ordered]@{
    id=$Id; executable=$Executable; arguments=$Arguments
    command=('& "{0}" {1}' -f $Executable, (($Arguments | ForEach-Object { '"' + $_.Replace('"','`"') + '"' }) -join ' '))
    cwd=(Get-Location).Path; started_at=$started.ToString('o')
    exit_code=$code; duration_seconds=$watch.Elapsed.TotalSeconds; mode=$Mode
    output=$output; output_path=('reports/batches/BATCH-18/command-output/' + $Id + '.json')
}
$record | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $evidenceRoot ($Id + '.json')) -Encoding utf8NoBOM
Write-Output $output
Write-Output ('{0}: exit={1}, seconds={2:N3}' -f $Id,$code,$watch.Elapsed.TotalSeconds)
exit $code
