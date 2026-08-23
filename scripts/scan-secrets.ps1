$ErrorActionPreference = "Stop"

$trackedEnv = @(
    git ls-files ".env*" |
        Where-Object { $_ -notmatch '(^|/)\.env(?:\.[^/]+)*\.example$' }
)
if ($trackedEnv.Count -gt 0) {
    throw "Tracked environment override detected: $($trackedEnv -join ', ')"
}

$trackedTaskBoard = @(git ls-files "TASK_BOARD.md")
if ($trackedTaskBoard.Count -gt 0) {
    throw "TASK_BOARD.md must remain local-only."
}

$patterns = @(
    'sk-[A-Za-z0-9]{20,}',
    'gh[pousr]_[A-Za-z0-9]{20,}',
    'AKIA[0-9A-Z]{16}',
    '-----BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY-----'
)
foreach ($pattern in $patterns) {
    $matches = @(git grep -n -I -E -e $pattern -- ':!docs/superpowers/plans/**' ':!docs/superpowers/specs/**' 2>$null)
    if ($LASTEXITCODE -notin @(0, 1)) {
        throw "Secret scan could not evaluate pattern safely (git grep exit $LASTEXITCODE)."
    }
    if ($matches.Count -gt 0) {
        throw "Potential secret pattern detected ($pattern): $($matches -join '; ')"
    }
}

$global:LASTEXITCODE = 0
Write-Output "secret_scan=pass"
