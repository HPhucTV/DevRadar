function New-DockerProcess {
    param([string[]]$Arguments)
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = "docker"
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $Arguments) {
        [void]$startInfo.ArgumentList.Add($argument)
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    return $process
}

function Invoke-DockerOutputToFile {
    param([string[]]$Arguments, [string]$OutputPath)
    $process = New-DockerProcess -Arguments $Arguments
    if (-not $process.Start()) {
        throw "Could not start Docker process."
    }
    $file = [System.IO.File]::Open($OutputPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $copyTask = $process.StandardOutput.BaseStream.CopyToAsync($file)
        $errorTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $copyTask.GetAwaiter().GetResult()
        $errorText = $errorTask.GetAwaiter().GetResult()
    }
    finally {
        $file.Dispose()
    }
    return [pscustomobject]@{ ExitCode = $process.ExitCode; Error = $errorText }
}

function Invoke-DockerInputFromFile {
    param([string[]]$Arguments, [string]$InputPath)
    $process = New-DockerProcess -Arguments $Arguments
    if (-not $process.Start()) {
        throw "Could not start Docker process."
    }
    $file = [System.IO.File]::OpenRead($InputPath)
    try {
        $copyTask = $file.CopyToAsync($process.StandardInput.BaseStream)
        $errorTask = $process.StandardError.ReadToEndAsync()
        $copyTask.GetAwaiter().GetResult()
        $process.StandardInput.Close()
        $process.WaitForExit()
        $errorText = $errorTask.GetAwaiter().GetResult()
    }
    finally {
        $file.Dispose()
    }
    return [pscustomobject]@{ ExitCode = $process.ExitCode; Error = $errorText }
}
