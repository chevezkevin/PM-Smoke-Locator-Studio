$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$app = Join-Path $scriptDir "smoke_locator_studio.py"
$dist = Join-Path $projectRoot "dist"
$work = Join-Path $projectRoot "build"
$tools = Join-Path $projectRoot "work\tools"
$assets = Join-Path $scriptDir "assets"
$exeName = "PMSmokeLocatorStudio_v0.3.6"
$genericExeName = "PMSmokeLocatorStudio"

if (!(Test-Path -LiteralPath $app)) {
    throw "No se encontro smoke_locator_studio.py"
}

if (!(Test-Path -LiteralPath $tools)) {
    throw "No se encontro work\tools con converter_pix y conversion_tools."
}

$oldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
python -m PyInstaller --version *> $null
$pyInstallerExit = $LASTEXITCODE
$ErrorActionPreference = $oldPreference

if ($pyInstallerExit -ne 0) {
    Write-Host "Instalando PyInstaller..."
    python -m pip install --user pyinstaller
}

python -m pip install --user pillow

$addTools = "$tools;work\tools"
$addAssets = "$assets;SmokeLocatorStudio\assets"

Set-Location -LiteralPath $projectRoot

python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name "$exeName" `
    --distpath "$dist" `
    --workpath "$work\pyinstaller" `
    --specpath "$work" `
    --add-data "$addTools" `
    --add-data "$addAssets" `
    --hidden-import PIL `
    --hidden-import PIL.Image `
    --hidden-import PIL.ImageOps `
    "$app"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller fallo creando el EXE."
}

Write-Host ""
Write-Host "EXE creado:"
Write-Host (Join-Path $dist "$exeName.exe")

Copy-Item -LiteralPath (Join-Path $dist "$exeName.exe") -Destination (Join-Path $dist "$genericExeName.exe") -Force
Write-Host (Join-Path $dist "$genericExeName.exe")


