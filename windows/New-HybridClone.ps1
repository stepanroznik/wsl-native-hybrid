[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SourceDistro,
    [string]$Destination = 'C:\HybridWSL\root\ubuntu.vhdx'
)
$ErrorActionPreference = 'Stop'
$Destination = [IO.Path]::GetFullPath($Destination)
if ([IO.Path]::GetExtension($Destination) -ne '.vhdx') { throw 'Destination must end in .vhdx.' }
$running = @(& wsl.exe --list --running --quiet | ForEach-Object { ($_ -replace "`0", '').Trim().Trim([char]0xfeff) })
if ($LASTEXITCODE -ne 0) { throw 'Could not list running WSL distros.' }
if ($running -contains $SourceDistro) { throw 'Stop your workloads and the source distro before exporting it.' }
$directory = Split-Path -Parent $Destination
$partial = $Destination + '.partial.vhdx'
if ((Test-Path -LiteralPath $Destination) -or (Test-Path -LiteralPath $partial)) { throw 'Destination or partial export already exists.' }
$registrations = @(Get-ChildItem -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | ForEach-Object {
    Get-ItemProperty -LiteralPath $_.PSPath
} | Where-Object DistributionName -eq $SourceDistro)
if ($registrations.Count -ne 1 -or $registrations[0].Version -ne 2) { throw 'Source must be an existing WSL2 distro.' }
$source = $registrations[0]
$file = if ($source.VhdFileName) { $source.VhdFileName } else { 'ext4.vhdx' }
$sourceDisk = Get-Item -LiteralPath ([IO.Path]::Combine($source.BasePath, $file))
$drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Destination))
if ($drive.DriveFormat -ne 'NTFS' -or $drive.DriveType -ne 'Fixed') { throw 'Use a local fixed NTFS volume.' }
if ($drive.AvailableFreeSpace -lt ($sourceDisk.Length + 20GB)) { throw 'Allow space for the clone plus a 20 GiB reserve.' }
New-Item -ItemType Directory -Path $directory -Force | Out-Null
Write-Host 'Exporting the stopped source. Leave the source distro stopped until this finishes.'
& wsl.exe --export $SourceDistro $partial --vhd
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $partial -PathType Leaf)) { throw 'VHDX export failed. Inspect the partial file before retrying.' }
if ((Get-Item -LiteralPath $partial).Length -le 0) { throw 'Export produced an empty file.' }
Move-Item -LiteralPath $partial -Destination $Destination
Write-Host "Clone ready at $Destination. Inspect it before registering it with --import-in-place."
