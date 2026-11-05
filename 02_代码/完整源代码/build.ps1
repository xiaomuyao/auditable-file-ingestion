param([string]$OutputDirectory = (Join-Path $PSScriptRoot 'bin'))
$ErrorActionPreference='Stop'
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows x64 .NET Framework 4.x csc.exe is required.' }
$bin=[IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $bin,(Join-Path $bin 'plugins'),(Join-Path $bin 'testplugins') | Out-Null
$refs=@('/nologo','/optimize+','/platform:x64','/r:System.Core.dll','/r:System.Web.Extensions.dll','/r:System.Xml.Linq.dll','/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll')
function Compile([string[]]$Arguments) { & $compiler @refs @Arguments; if ($LASTEXITCODE -ne 0) { throw "C# compile failed: $LASTEXITCODE" } }
Compile @('/target:library',"/out:$bin\Contracts.dll",(Join-Path $PSScriptRoot 'src\Contracts\Contracts.cs'))
Compile @('/target:library',"/out:$bin\PipelineCore.dll","/r:$bin\Contracts.dll",(Join-Path $PSScriptRoot 'src\Persistence\NativeSqlite.cs'),(Join-Path $PSScriptRoot 'src\Host\Core.cs'))
$names=@('Csv','Xlsx','Sqlite','Docx','Pdf')
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'plugins\JsonPlugin\JsonPlugin.cs')) { $names += 'Json' }
$pluginSources=@()
foreach ($name in $names) {
 $source=Join-Path $PSScriptRoot "plugins\${name}Plugin\${name}Plugin.cs"
 $pluginSources += $source
 Compile @('/target:library',"/out:$bin\plugins\${name}Plugin.dll","/r:$bin\Contracts.dll","/r:$bin\PipelineCore.dll",(Join-Path $PSScriptRoot 'plugins\Shared\AdapterHelpers.cs'),$source)
}
Compile @('/target:exe',"/out:$bin\Host.exe","/r:$bin\Contracts.dll","/r:$bin\PipelineCore.dll",(Join-Path $PSScriptRoot 'src\Host\Entry.cs'),(Join-Path $PSScriptRoot 'src\Host\DynamicFactory.cs'))
# Remove per-DLL AssemblyVersion attributes only from temporary baseline source copies.
$baselineTemp=Join-Path $PSScriptRoot 'build-temp'
New-Item -ItemType Directory -Force -Path $baselineTemp | Out-Null
$baselineSources=@()
foreach ($source in $pluginSources) { $target=Join-Path $baselineTemp ([IO.Path]::GetFileName($source)); (Get-Content -LiteralPath $source -Raw).Replace('[assembly:AssemblyVersion("1.0.0.0")]','') | Set-Content -LiteralPath $target -Encoding UTF8; $baselineSources += $target }
$baselineArgs=@('/target:exe',"/out:$bin\Baseline.exe","/r:$bin\Contracts.dll","/r:$bin\PipelineCore.dll",(Join-Path $PSScriptRoot 'src\Host\Entry.cs'),(Join-Path $PSScriptRoot 'baseline\MonolithBaseline\StaticFactory.cs'),(Join-Path $PSScriptRoot 'plugins\Shared\AdapterHelpers.cs'))+$baselineSources
Compile $baselineArgs
Compile @('/target:library',"/out:$bin\testplugins\ThrowingPlugin.dll","/r:$bin\Contracts.dll",(Join-Path $PSScriptRoot 'tests\ThrowingPlugin.cs'))
Write-Output "Built dynamic Host, static Baseline and available plugin DLLs: $bin"

