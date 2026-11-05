# Extension build: do not rebuild or modify the frozen Host/Core/Contracts/base DLLs.
$ErrorActionPreference='Stop'
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$bin=Join-Path $PSScriptRoot 'bin'
$stable=@('Host.exe','PipelineCore.dll','Contracts.dll','plugins\CsvPlugin.dll','plugins\XlsxPlugin.dll','plugins\SqlitePlugin.dll','plugins\DocxPlugin.dll','plugins\PdfPlugin.dll')
$before=@{}
foreach($name in $stable){$before[$name]=(Get-FileHash -LiteralPath (Join-Path $bin $name) -Algorithm SHA256).Hash}
$refs=@('/nologo','/optimize+','/platform:x64','/r:System.Core.dll','/r:System.Web.Extensions.dll','/r:System.Xml.Linq.dll','/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll',"/r:$bin\Contracts.dll","/r:$bin\PipelineCore.dll")
& $compiler @refs /target:library "/out:$bin\plugins\JsonPlugin.dll" (Join-Path $PSScriptRoot 'plugins\JsonPlugin\JsonPlugin.cs')
if($LASTEXITCODE -ne 0){throw 'JSON DLL compilation failed'}
$temp=Join-Path $PSScriptRoot 'build-temp'
New-Item -ItemType Directory -Force -Path $temp | Out-Null
$sources=@()
foreach($name in @('Csv','Xlsx','Sqlite','Docx','Pdf','Json')){
 $source=Join-Path $PSScriptRoot "plugins\${name}Plugin\${name}Plugin.cs"
 $target=Join-Path $temp "${name}Plugin.cs"
 (Get-Content -LiteralPath $source -Raw).Replace('[assembly:AssemblyVersion("1.0.0.0")]','') | Set-Content -LiteralPath $target -Encoding UTF8
 $sources += $target
}
& $compiler @refs /target:exe "/out:$bin\Baseline.exe" (Join-Path $PSScriptRoot 'src\Host\Entry.cs') (Join-Path $PSScriptRoot 'baseline\MonolithBaseline\StaticFactory.cs') (Join-Path $PSScriptRoot 'plugins\Shared\AdapterHelpers.cs') @sources
if($LASTEXITCODE -ne 0){throw 'Static baseline extension compilation failed'}
foreach($name in $stable){if((Get-FileHash -LiteralPath (Join-Path $bin $name) -Algorithm SHA256).Hash -ne $before[$name]){throw "Frozen file changed: $name"}}
Write-Output 'Added JSON DLL and rebuilt the static baseline. Frozen Host/Core/Contracts/five base DLL bytes unchanged.'
