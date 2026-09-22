# Build locale di Image Creator Free: test, eseguibile, installer.
# Uso:  .\build.ps1            build completa
#       .\build.ps1 -SkipTests salta i test
#       .\build.ps1 -NoInstaller  solo l'eseguibile portatile
param(
    [switch]$SkipTests,
    [switch]$NoInstaller
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$init = Get-Content "src/imagecreator/__init__.py" -Raw
if ($init -notmatch '__version__\s*=\s*"([^"]+)"') { throw "Versione non trovata in src/imagecreator/__init__.py" }
$version = $Matches[1]
Write-Host "Image Creator Free $version" -ForegroundColor Cyan

if (-not $SkipTests) {
    Write-Host "`n== Test ==" -ForegroundColor Cyan
    python -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw "Test falliti" }
}

Write-Host "`n== Informazioni di versione ==" -ForegroundColor Cyan
$parts = $version.Split(".")
while ($parts.Count -lt 4) { $parts += "0" }
$filevers = ($parts[0..3] -join ", ")
New-Item -ItemType Directory -Force -Path build | Out-Null
@"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($filevers), prodvers=($filevers),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'bais.info'),
      StringStruct('FileDescription', 'Image Creator Free - Qwen-Image-2.1 in locale'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', 'ImageCreatorFree'),
      StringStruct('LegalCopyright', 'MIT - github.com/bdbais/image-creator-free'),
      StringStruct('OriginalFilename', 'ImageCreatorFree.exe'),
      StringStruct('ProductName', 'Image Creator Free'),
      StringStruct('ProductVersion', '$version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Encoding UTF8 build/version_info.txt

Write-Host "`n== PyInstaller ==" -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean ImageCreatorFree.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallito" }

$exe = "dist/ImageCreatorFree.exe"
if (-not (Test-Path $exe)) { throw "Eseguibile non prodotto" }

Write-Host "`n== Self test dell'eseguibile ==" -ForegroundColor Cyan
& $exe --self-test | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Self test fallito (codice $LASTEXITCODE)" }
Write-Host "ok" -ForegroundColor Green

Copy-Item $exe "dist/ImageCreatorFree-portable.exe" -Force

if (-not $NoInstaller) {
    $iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if ($iscc) {
        Write-Host "`n== Inno Setup ==" -ForegroundColor Cyan
        & $iscc /Q "/DAppVersion=$version" installer\ImageCreatorFree.iss
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallito" }
    } else {
        Write-Host "Inno Setup 6 non trovato: salto l'installer." -ForegroundColor Yellow
    }
}

Write-Host "`n== Checksum ==" -ForegroundColor Cyan
$files = @("dist/ImageCreatorFree-portable.exe")
if (Test-Path "installer/Output/ImageCreatorFree-Setup.exe") {
    $files += "installer/Output/ImageCreatorFree-Setup.exe"
}
$lines = foreach ($f in $files) {
    $h = (Get-FileHash $f -Algorithm SHA256).Hash.ToLower()
    "$h  $(Split-Path $f -Leaf)"
}
$lines | Set-Content -Encoding ASCII dist/SHA256SUMS.txt
$lines | ForEach-Object { Write-Host $_ }

Write-Host "`nFatto. File in dist\" -ForegroundColor Green
