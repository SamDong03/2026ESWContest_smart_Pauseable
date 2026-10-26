param(
    [string]$SecretConfig = "android-test.secrets.json"
)

$ErrorActionPreference = "Stop"
$flutterRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$configPath = if ([System.IO.Path]::IsPathRooted($SecretConfig)) {
    $SecretConfig
} else {
    Join-Path $flutterRoot $SecretConfig
}
$googleConfigPath = Join-Path $flutterRoot "android/app/google-services.json"

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw "Flutter SDK is required. Add its bin directory to PATH first."
}
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "Create android-test.secrets.json with the existing Render app token first."
}
if (-not (Test-Path -LiteralPath $googleConfigPath -PathType Leaf)) {
    throw "Download Firebase Android config to android/app/google-services.json first."
}
try {
    $buildConfig = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $googleConfig = Get-Content -LiteralPath $googleConfigPath -Raw | ConvertFrom-Json
} catch {
    throw "The build config or Google services config is not valid JSON."
}
if ($buildConfig.APP_TOKEN -isnot [string] -or
    [string]::IsNullOrWhiteSpace($buildConfig.APP_TOKEN) -or
    $buildConfig.APP_TOKEN -match '\s|REPLACE|PLACEHOLDER') {
    throw "APP_TOKEN must contain the existing Render app token. Its value is never printed."
}
if ($buildConfig.API_BASE_URL -ne "https://pauseable-api.onrender.com" -or
    $buildConfig.PATIENT_ID -ne "byunwoojin") {
    throw "For this demo, set API_BASE_URL to the existing Render service and PATIENT_ID to byunwoojin."
}
$matchingClients = @($googleConfig.client | Where-Object {
    $_.client_info.android_client_info.package_name -eq "com.pauseable.pauseable_guardian"
})
if ($matchingClients.Count -eq 0 -or
    [string]::IsNullOrWhiteSpace($googleConfig.project_info.project_id)) {
    throw "Firebase Android config must register package com.pauseable.pauseable_guardian."
}

Push-Location -LiteralPath $flutterRoot
try {
    & flutter pub get
    if ($LASTEXITCODE -ne 0) { throw "flutter pub get failed." }
    & flutter analyze
    if ($LASTEXITCODE -ne 0) { throw "flutter analyze failed." }
    & flutter test
    if ($LASTEXITCODE -ne 0) { throw "flutter test failed." }
    & flutter build apk --release "--dart-define-from-file=$configPath"
    if ($LASTEXITCODE -ne 0) { throw "Release APK build failed." }
    $apkPath = Join-Path $flutterRoot "build/app/outputs/flutter-apk/app-release.apk"
    if (-not (Test-Path -LiteralPath $apkPath -PathType Leaf)) {
        throw "The expected APK was not produced."
    }
    Write-Output "APK: $apkPath"
    Write-Output "SHA256: $((Get-FileHash -LiteralPath $apkPath -Algorithm SHA256).Hash)"
} finally {
    Pop-Location
}
