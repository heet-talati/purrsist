$data = [Console]::In.ReadToEnd() | ConvertFrom-Json
$file = $data.tool_input.file_path

if ($file -and $file -like '*.py') {
    uv run ruff format $file 2>&1 | Out-Null
    $out = uv run ruff check --fix $file 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Output $out
        exit 2
    }
}
