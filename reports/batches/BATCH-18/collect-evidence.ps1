param([string]$CodeCommit = '3712a170969998e32b56d33e3d59c7b21a04f19d')
$ErrorActionPreference = 'Stop'
$repoRoot = (Get-Location).Path
$base = 'f507e37d94c0532f377a9475de2129c52f75d584'
$authorityRoot = 'C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松'

function Get-GitBlob([string]$Commit, [string]$Path) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = 'git'
    $start.WorkingDirectory = $repoRoot
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.ArgumentList.Add('show')
    $start.ArgumentList.Add($Commit + ':' + $Path)
    $process = [Diagnostics.Process]::Start($start)
    $errors = $process.StandardError.ReadToEndAsync()
    $buffer = [IO.MemoryStream]::new()
    $process.StandardOutput.BaseStream.CopyTo($buffer)
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw $errors.GetAwaiter().GetResult() }
    $bytes = $buffer.ToArray()
    $buffer.Dispose()
    $process.Dispose()
    return ,$bytes
}
function Get-BlobEvidence([string]$Commit, [string]$Path) {
    $bytes = Get-GitBlob $Commit $Path
    return [ordered]@{
        path=$Path; commit=$Commit; byte_length=$bytes.Length
        sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))
        basis=('git show ' + $Commit + ':' + $Path + ' raw blob bytes')
    }
}
function Normalize-Name([string]$Name) { return ($Name.ToLowerInvariant() -replace '[-_.]+','-') }
function Get-PinMap([string]$Content) {
    $map = @{}
    foreach ($line in ($Content -split '\r?\n')) {
        if ($line -match '^([^#= ]+)==([^ ]+)$') {
            $map[(Normalize-Name $Matches[1])] = $Matches[2]
        }
    }
    return $map
}

$head = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $CodeCommit) { throw 'Unexpected implementation HEAD' }
$codePaths = @(git diff --name-only $base $CodeCommit)
if ($LASTEXITCODE -ne 0) { throw 'Cannot read code delta' }
foreach ($path in $codePaths) {
    if ($path -notmatch '^backend/(src/covenia_b/storage|tests/storage)/') {
        throw ('Code scope violation: ' + $path)
    }
}
$uncommittedCode = @(git diff --name-only $CodeCommit -- backend/src/covenia_b/storage backend/tests/storage backend/requirements-dev.lock)
if ($LASTEXITCODE -ne 0 -or $uncommittedCode.Count -ne 0) { throw 'Implementation/lock changed after preserved code commit' }
$commands = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'command-output') -Filter '*.json' -File |
    ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json } |
    Sort-Object started_at,id)
$byId = @{}
foreach ($command in $commands) { $byId[$command.id] = $command }
$requiredIds = @('required-01-interpreter','required-02-install-lock-offline','required-03-editable-backend',
    'required-04-import-preflight','required-05-storage-pytest-final','required-06-pip-list',
    'required-07-pip-check','required-08-git-diff-check','required-09-git-status',
    'supplemental-ruff-delivery-approved','supplemental-environment-preflight','freeze-before','freeze-after')
foreach ($id in $requiredIds) {
    if (-not $byId.ContainsKey($id) -or $byId[$id].exit_code -ne 0) { throw ('Missing successful evidence: ' + $id) }
}
$preflight = $byId['supplemental-environment-preflight'].output | ConvertFrom-Json
$runDir = Split-Path $preflight.sys_prefix -Parent
if ($runDir.Length -gt 60 -or $preflight.venv_longest_path_length -ge 250 -or -not $preflight.venv_direct_child) {
    throw 'Short RUN_DIR/venv constraints not satisfied'
}
$before = Get-PinMap $byId['freeze-before'].output
$after = Get-PinMap $byId['freeze-after'].output
$lockBytes = Get-GitBlob $base 'backend/requirements-dev.lock'
$lockPins = Get-PinMap ([Text.Encoding]::UTF8.GetString($lockBytes))
$installed = $byId['required-06-pip-list'].output | ConvertFrom-Json
$installedMap = @{}
foreach ($package in $installed) { $installedMap[(Normalize-Name $package.name)] = $package.version }
$pinChecks = @()
foreach ($name in ($lockPins.Keys | Sort-Object)) {
    $version = $lockPins[$name]
    $unchanged = $before[$name] -eq $version -and $after[$name] -eq $version -and $installedMap[$name] -eq $version
    if (-not $unchanged) { throw ('Existing pin drift: ' + $name) }
    $pinChecks += [ordered]@{name=$name; locked_version=$version; freeze_before=$before[$name]
        freeze_after=$after[$name]; installed_version=$installedMap[$name]; unchanged=$unchanged}
}
$beforeLines = @($byId['freeze-before'].output -split '\r?\n' | Where-Object { $_.Trim() })
$afterLines = @($byId['freeze-after'].output -split '\r?\n' | Where-Object { $_.Trim() })
$added = @($afterLines | Where-Object { $_ -notin $beforeLines })
$removed = @($beforeLines | Where-Object { $_ -notin $afterLines })
if ($removed.Count -ne 0 -or @($added | Where-Object { $_ -notlike '-e *#egg=covenia_b*' }).Count -ne 0) {
    throw 'Unexpected third-party freeze difference'
}
$lockBlobs = @(
    Get-BlobEvidence 'bfc1f911c8dad8be0daf9b3bbb4e3bf2b4c0ae23' 'backend/requirements-dev.lock'
    Get-BlobEvidence $base 'backend/requirements-dev.lock'
    Get-BlobEvidence $CodeCommit 'backend/requirements-dev.lock'
    Get-BlobEvidence 'cc82915b260ac108137ada27ffda56d1b4b1bc3d' 'backend/requirements-dev.lock'
)
if (@($lockBlobs.sha256 | Select-Object -Unique).Count -ne 1) { throw 'Lock Git blobs differ' }
$canonicalPlans = @()
foreach ($path in @('MASTER_PLAN.md','batches.json')) {
    $source = Join-Path $authorityRoot $path
    $canonicalPlans += [ordered]@{path=$source; sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
        basis='User-designated external canonical planning snapshot; raw source bytes, not checkout CRLF bytes'}
}
if ($canonicalPlans[0].sha256 -ne 'DBE269F06F4BBE3D8C1F915DD8E4A2D78E0E4F021ABB396270C8B846D5FFA74E' -or
    $canonicalPlans[1].sha256 -ne '18DA555CE5ADEA5062F680837AEC8214158F58CBC1A918CF6BBC31EF48448E2E') {
    throw 'Canonical plan hash changed'
}
$package = Get-Content -Raw -LiteralPath (Join-Path $authorityRoot 'scheduler-packages/BATCH-18.json') | ConvertFrom-Json
$receiptPath = 'C:\Users\WONG Tsun Ming\covenia-orchestration\runs\covenia-b-20260910-01\integration-receipts\BATCH-04.json'
$receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
$verdictBytes = Get-GitBlob $base 'reports/batches/BATCH-04/VERIFICATION_REPORT.json'
$verdict = [Text.Encoding]::UTF8.GetString($verdictBytes) | ConvertFrom-Json
if ($verdict.verdict -ne 'PASS' -or $receipt.status -ne 'SUCCESS' -or @($receipt.failed).Count -ne 0) { throw 'Dependency gate not met' }
foreach ($sha in @($receipt.reviewed_code_commit,$receipt.verification_report_commit)) {
    git merge-base --is-ancestor $sha $base
    if ($LASTEXITCODE -ne 0) { throw 'Dependency not integrated in baseline' }
}
[xml]$junit = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'storage-pytest-final.xml')
$suite = $junit.testsuites.testsuite
if ([int]$suite.tests -ne 38 -or [int]$suite.failures -ne 0 -or [int]$suite.errors -ne 0 -or [int]$suite.skipped -ne 0) { throw 'Final retained test result differs' }
$testCases = @($suite.testcase | ForEach-Object { [ordered]@{name=$_.name; classname=$_.classname; time_seconds=[double]$_.time; result='PASSED'} })
$blobEvidence = @($codePaths | ForEach-Object { Get-BlobEvidence $CodeCommit $_ })
$dependencyBlobs = @(
    Get-BlobEvidence $base 'reports/batches/BATCH-04/IMPLEMENTATION_REPORT.json'
    Get-BlobEvidence $base 'reports/batches/BATCH-04/VERIFICATION_REPORT.json'
    Get-BlobEvidence $base 'docs/contracts/b-contract-lock.json'
    Get-BlobEvidence $base 'schemas/accountability-state.schema.json'
    Get-BlobEvidence $base 'docs/approvals/b-decisions.json'
)
$planCheckoutBlobs = @(
    Get-BlobEvidence $CodeCommit 'MASTER_PLAN.md'
    Get-BlobEvidence $CodeCommit 'batches.json'
)
$resume = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'resume-evidence.json') | ConvertFrom-Json
$result = [ordered]@{
    captured_at=(Get-Date -Format o); repo_root=$repoRoot; branch=(git branch --show-current).Trim()
    base=$base; code_commit=$CodeCommit; code_paths=$codePaths; code_artifacts=$blobEvidence
    commands=$commands; required_ids=$requiredIds; preflight=$preflight; run_dir=$runDir
    installed_packages=$installed; old_pin_checks=$pinChecks; lock_blobs=$lockBlobs
    freeze_diff=[ordered]@{added=$added; removed=$removed; new_third_party_dependencies=@(); local_project_only=$true}
    canonical_plans=$canonicalPlans; checkout_plan_blobs=$planCheckoutBlobs; package=$package
    dependency_receipt_path=$receiptPath; dependency_receipt=$receipt; dependency_artifacts=$dependencyBlobs
    test_cases=$testCases; test_count=38; tests_rerun_on_resume=$false; resume=$resume
    core_autocrlf=@(git config --show-origin --get core.autocrlf)
    lock_eol=@(git ls-files --eol backend/requirements-dev.lock)
}
$result | ConvertTo-Json -Depth 35
