<#
.SYNOPSIS
Verify or reproduce the auditable file-ingestion experiments on Windows x64.
.DESCRIPTION
Requires .NET Framework 4.x csc.exe, system winsqlite3.dll and Python dependencies
listed in 02_代码/requirements.lock.txt. Install dependencies before running:
  python -m pip install -r .\02_代码\requirements.lock.txt
Every run uses a new output directory. Original source files and public reference
data remain unchanged. New measurements are independent retrospective results.
Nontruncated fixtures are generated from raw data. Registered truncated fixtures
are hash-verified and copied byte for byte; reports distinguish both methods.
.EXAMPLE
.\run_all.ps1 -Phase Verify -PythonExecutable python
.EXAMPLE
.\run_all.ps1 -Phase FreshCode -PythonExecutable C:\Python312\python.exe
.EXAMPLE
.\run_all.ps1 -Phase Reproduce -PythonExecutable python -OutputDirectory D:\reproduction\run-001
#>
param(
 [ValidateSet('Verify','FreshCode','Reproduce','All')][string]$Phase='FreshCode',
 [string]$PythonExecutable='python',
 [string]$OutputDirectory=''
)
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot '02_代码\run_all.ps1') -Phase $Phase -PythonExecutable $PythonExecutable -OutputDirectory $OutputDirectory
