<#
.SYNOPSIS
Source-release verification and independent retrospective reproduction.
.DESCRIPTION
Verify checks released source/public-data hashes. FreshCode additionally prepares
117 fixtures offline: nontruncated files are generated, and the registered damaged
files are hash-verified and copied byte for byte. It then compiles the C# source and
runs development/late-extension integration checks. Reproduce adds all-partition correctness, 216 performance
processes, 80 fault trials, independent result verification and figure generation.
All is an alias for Reproduce. Recorded original measurements are not required.
#>
param(
 [ValidateSet('Verify','FreshCode','Reproduce','All')][string]$Phase='FreshCode',
 [string]$PythonExecutable='python',
 [string]$OutputDirectory=''
)
$ErrorActionPreference='Stop'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$CodePackageRoot=$PSScriptRoot
$packageRoot=Split-Path $CodePackageRoot -Parent
$SourceCodeRoot=Join-Path $CodePackageRoot '完整源代码'
$DataRoot=Join-Path $packageRoot '03_数据'
$ScriptsRoot=Join-Path $CodePackageRoot 'scripts'
$DataPreparationRoot=Join-Path $CodePackageRoot 'data_preparation'
$RunnerRoot=Join-Path $CodePackageRoot 'benchmarks\Runner'
$FaultInjectorRoot=Join-Path $CodePackageRoot 'benchmarks\FaultInjector'
$releaseManifest=Join-Path $packageRoot 'release_manifest.json'
$helper=Join-Path $ScriptsRoot 'verify_release.py'
$pythonCommand=Get-Command $PythonExecutable -ErrorAction Stop
$PythonExecutable=$pythonCommand.Source
if(!$PythonExecutable){throw 'PythonExecutable must resolve to an executable file.'}
if(!$OutputDirectory){$OutputDirectory=Join-Path $packageRoot ('reproduction-runs\'+$Phase+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))}
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
$repositoryPrefix=[IO.Path]::GetFullPath($packageRoot).TrimEnd('\')+'\'
$runsPrefix=(Join-Path $repositoryPrefix 'reproduction-runs').TrimEnd('\')+'\'
if($OutputDirectory.StartsWith($repositoryPrefix,[StringComparison]::OrdinalIgnoreCase) -and !$OutputDirectory.StartsWith($runsPrefix,[StringComparison]::OrdinalIgnoreCase)){
 throw 'Outputs inside the repository must use the ignored reproduction-runs directory.'
}
foreach($protected in @($CodePackageRoot,$DataRoot)){
 $prefix=[IO.Path]::GetFullPath($protected).TrimEnd('\')+'\'
 if($OutputDirectory.Equals($prefix.TrimEnd('\'),[StringComparison]::OrdinalIgnoreCase) -or $OutputDirectory.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){
  throw 'OutputDirectory must be outside the released source and reference-data directories.'
 }
}
if(Test-Path -LiteralPath $OutputDirectory){throw 'A new output directory is required; earlier observations will not be overwritten.'}
New-Item -ItemType Directory -Force -Path $OutputDirectory,(Join-Path $OutputDirectory 'logs') | Out-Null
$journal=[Collections.Generic.List[object]]::new()
function Save-Journal {
 [ordered]@{phase=$Phase;purpose='independent retrospective reproduction, never pooled with the original formal study';steps=$journal.ToArray()} | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'execution_journal.json') -Encoding utf8
}
function Invoke-Python([string]$Name,[string[]]$Arguments){
 $timer=[Diagnostics.Stopwatch]::StartNew();$began=[DateTime]::UtcNow.ToString('o');$code=-1;$errorText=''
 try{& $PythonExecutable @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $OutputDirectory ('logs\'+$Name+'.log'));$code=$LASTEXITCODE;if($code -ne 0){throw "$Name exited $code"}}
 catch{$errorText=$_.Exception.Message;throw}
 finally{$journal.Add([ordered]@{name=$Name;started_utc=$began;finished_utc=[DateTime]::UtcNow.ToString('o');elapsed_seconds=$timer.Elapsed.TotalSeconds;arguments=$Arguments;exit_code=$code;error=$errorText});Save-Journal}
}
function Invoke-Build([string]$Source,[string]$Bin){
 $began=[DateTime]::UtcNow.ToString('o');$okay=$false
 try{& (Join-Path $Source 'build.ps1') -OutputDirectory $Bin 2>&1 | Tee-Object -FilePath (Join-Path $OutputDirectory 'logs\fresh-build.log');$okay=$true}
 finally{$journal.Add([ordered]@{name='fresh-build';started_utc=$began;finished_utc=[DateTime]::UtcNow.ToString('o');source=$Source;output_bin=$Bin;passed=$okay});Save-Journal}
}
try{
 Invoke-Python 'release-hashes-before' @($helper,'verify','--root',$packageRoot,'--output',(Join-Path $OutputDirectory 'verification\release_before.json'))
 if($Phase -ne 'Verify'){
  Invoke-Python 'dependencies' @('-c','import sys,numpy,matplotlib,pypdf,docx,reportlab,openpyxl; print(sys.version); print("Dependency imports passed; no packages installed.")')
  $rebuiltData=Join-Path $OutputDirectory 'data'
  Invoke-Python 'offline-fixture-preparation' @((Join-Path $DataPreparationRoot 'offline_rebuild.py'),'--reference-data',$DataRoot,'--output',$rebuiltData)
  $runtimeCode=Join-Path $OutputDirectory 'runtime_code'
  $receipt=Get-Content -LiteralPath $releaseManifest -Raw -Encoding UTF8 | ConvertFrom-Json
  $sourcePrefix='02_代码/完整源代码/'
  foreach($item in $receipt.files){
   if(!$item.path.StartsWith($sourcePrefix)){continue}
   $relative=$item.path.Substring($sourcePrefix.Length)
   $target=Join-Path $runtimeCode $relative
   New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
   Copy-Item -LiteralPath (Join-Path $SourceCodeRoot $relative) -Destination $target
  }
  $runtimeBin=Join-Path $runtimeCode 'bin';Invoke-Build $runtimeCode $runtimeBin
  $runtimeManifest=Join-Path $runtimeCode 'reproduction_manifest.json'
  Invoke-Python 'fresh-runtime-manifest' @($helper,'runtime','--root',$packageRoot,'--code',$runtimeCode,'--output',$runtimeManifest)
  foreach($part in @('base','late_json')){
   Invoke-Python ('integration-'+$part) @((Join-Path $runtimeCode 'tests\IntegrationTests\integration.py'),'--data',(Join-Path $rebuiltData $part),'--output',(Join-Path $OutputDirectory ('integration\'+$part)),'--bin',$runtimeBin,'--python',$PythonExecutable)
  }
  if($Phase -ne 'FreshCode'){
   $correctness=Join-Path $OutputDirectory 'correctness'
   foreach($part in @('base','late_json','holdout')){
    Invoke-Python ('correctness-'+$part) @((Join-Path $ScriptsRoot 'run_correctness.py'),'--data',$rebuiltData,'--partition',$part,'--host',(Join-Path $runtimeBin 'Host.exe'),'--plugins',(Join-Path $runtimeBin 'plugins'),'--python',$PythonExecutable,'--freeze',$runtimeManifest,'--code',$runtimeCode,'--output',(Join-Path $correctness ($part+'_formal')),'--reproduction')
   }
   $performance=Join-Path $OutputDirectory 'performance'
   Invoke-Python 'performance-216-processes' @((Join-Path $RunnerRoot 'run_performance.py'),'--truth',(Join-Path $rebuiltData 'base\canonical_ground_truth.csv'),'--protocol',(Join-Path $RunnerRoot 'protocol.json'),'--dynamic',(Join-Path $runtimeBin 'Host.exe'),'--static',(Join-Path $runtimeBin 'Baseline.exe'),'--plugins',(Join-Path $runtimeBin 'plugins'),'--python',$PythonExecutable,'--output',$performance)
   $faults=Join-Path $OutputDirectory 'faults'
   Invoke-Python 'faults-80-trials' @((Join-Path $FaultInjectorRoot 'run_faults.py'),'--host',(Join-Path $runtimeBin 'Host.exe'),'--plugins',(Join-Path $runtimeBin 'plugins'),'--throwing-plugin',(Join-Path $runtimeBin 'testplugins\ThrowingPlugin.dll'),'--freeze-manifest',$runtimeManifest,'--repeats','10','--lock-ms','300','--output',$faults)
   Invoke-Python 'analysis' @((Join-Path $ScriptsRoot 'analyze_results.py'),'--performance',$performance,'--base',(Join-Path $correctness 'base_formal'),'--late',(Join-Path $correctness 'late_json_formal'),'--holdout',(Join-Path $correctness 'holdout_formal'),'--faults',$faults,'--out',(Join-Path $OutputDirectory 'summary'))
   Invoke-Python 'fault-oracle' @((Join-Path $FaultInjectorRoot 'verify_and_summarize.py'),'--input',$faults,'--output',(Join-Path $OutputDirectory 'fault_independent_verification'))
   Invoke-Python 'figures' @((Join-Path $ScriptsRoot 'make_figures.py'),'--analysis',(Join-Path $OutputDirectory 'summary'),'--faults',$faults,'--output',(Join-Path $OutputDirectory 'figures'))
  }
  Invoke-Python 'runtime-hashes-after' @($helper,'verify-runtime','--code',$runtimeCode,'--manifest',$runtimeManifest,'--output',(Join-Path $OutputDirectory 'verification\runtime_after.json'))
 }
 Invoke-Python 'release-hashes-after' @($helper,'verify','--root',$packageRoot,'--output',(Join-Path $OutputDirectory 'verification\release_after.json'))
 [ordered]@{status='passed';phase=$Phase;complete_experimental_reproduction=($Phase -in @('Reproduce','All'));new_measurements_pooled_with_original=$false;fixture_preparation='generate nontruncated fixtures; hash-verify and copy registered truncated inputs byte for byte; counts in data/offline_reproduction_report.json';purpose=if($Phase -eq 'Verify'){'source-release and reference-data hash verification'}elseif($Phase -eq 'FreshCode'){'fresh build, offline fixture preparation and development/late-extension integration; not a full experiment rerun'}else{'offline retrospective fresh-build correctness, 216-process and 80-fault reproduction'};completed_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDirectory 'reproduction_report.json') -Encoding utf8
 Write-Output "Completed $Phase. Evidence: $OutputDirectory"
}catch{
 [ordered]@{status='failed';phase=$Phase;error=$_.Exception.Message;observations_retained=$true;completed_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDirectory 'reproduction_report.json') -Encoding utf8
 throw
}
