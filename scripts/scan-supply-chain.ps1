param(
    [string]$Image = "devradar-app:local",
    [string]$CrawlerImage = "devradar-crawler:local",
    [string]$EnvFile = ".env.example"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Environment template was not found: $EnvFile"
}
if (-not (Test-Path -LiteralPath "web/package-lock.json")) {
    throw "web/package-lock.json is required for reproducible npm installs."
}

Push-Location web
try {
    npm audit --audit-level=high
    if ($LASTEXITCODE -ne 0) { throw "npm audit reported a high/critical finding." }
}
finally {
    Pop-Location
}

& ".venv\Scripts\python.exe" -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check failed." }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required for the container scan."
}

$trivyImage = "aquasec/trivy@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969"
$images = @($Image, $CrawlerImage)

foreach ($containerImage in $images) {
    docker image inspect $containerImage *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Container image was not found locally: $containerImage"
    }

    $errorPath = [System.IO.Path]::GetTempFileName()
    try {
        $fullJson = & docker run --rm `
            --volume /var/run/docker.sock:/var/run/docker.sock `
            $trivyImage image --quiet --format json --severity HIGH,CRITICAL `
            --ignore-unfixed=false --exit-code 0 $containerImage 2>$errorPath
        if ($LASTEXITCODE -ne 0) {
            $detail = Get-Content -Raw -LiteralPath $errorPath
            throw "Trivy full report failed for ${containerImage}: $detail"
        }
        if (-not $fullJson) {
            throw "Trivy returned an empty full report for $containerImage."
        }

        $report = ($fullJson -join [Environment]::NewLine) | ConvertFrom-Json
        $total = 0
        $fixed = 0
        $unfixed = 0
        foreach ($result in @($report.Results)) {
            foreach ($vulnerability in @($result.Vulnerabilities)) {
                $total++
                if ([string]::IsNullOrWhiteSpace([string]$vulnerability.FixedVersion)) {
                    $unfixed++
                }
                else {
                    $fixed++
                }
            }
        }
        Write-Output "container_scan image=$containerImage high_critical_total=$total fixed=$fixed unfixed=$unfixed"
        if ($fixed -gt 0) {
            throw "Trivy found $fixed fixable HIGH/CRITICAL vulnerabilities in $containerImage."
        }

        & docker run --rm `
            --volume /var/run/docker.sock:/var/run/docker.sock `
            $trivyImage image --quiet --format table --severity HIGH,CRITICAL `
            --ignore-unfixed --exit-code 1 $containerImage
        if ($LASTEXITCODE -ne 0) {
            throw "Trivy ignore-unfixed gate failed for $containerImage."
        }
    }
    finally {
        Remove-Item -LiteralPath $errorPath -Force -ErrorAction SilentlyContinue
    }
}

Write-Output "supply_chain_scan=pass"
