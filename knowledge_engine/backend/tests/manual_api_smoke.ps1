param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$WorkDir = ".manual-api-work"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

$sample1 = Join-Path $WorkDir "cyber-law-v1.txt"
$sample2 = Join-Path $WorkDir "cyber-law-v2.txt"
@(
    "第一章 总则",
    "第二十一条 网络运营者应当按照网络安全等级保护制度的要求，履行安全保护义务。",
    "第二十二条 网络产品、服务应当符合相关国家标准的强制性要求。"
) | Set-Content -Encoding utf8 -Path $sample1
@(
    "第一章 总则",
    "第二十一条 网络运营者应当按照网络安全等级保护制度的要求，履行安全保护义务。",
    "第二十二条 网络产品、服务应当符合相关国家标准的强制性要求。",
    "第二十三条 网络关键设备和网络安全专用产品应当按照相关国家标准进行安全认证或者安全检测。"
) | Set-Content -Encoding utf8 -Path $sample2

function Invoke-JsonCurl {
    param([string]$Name, [string[]]$Args)
    Write-Host "`n===== $Name ====="
    & curl.exe @Args
    if ($LASTEXITCODE -ne 0) { throw "curl failed for $Name" }
}

Invoke-JsonCurl "root health" @("-sS", "$BaseUrl/health")
Invoke-JsonCurl "ready health" @("-sS", "$BaseUrl/api/v1/health/ready")

$uploadResponse = & curl.exe -sS -X POST "$BaseUrl/api/v1/documents/upload" `
    -F "file=@$sample1;type=text/plain" `
    -F "title=手工测试网络安全法" `
    -F "doc_type=law" `
    -F "security_domain=network-security,compliance" `
    -F "tags=manual,smoke"
if ($LASTEXITCODE -ne 0) { throw "upload failed" }
Write-Host "`n===== upload ====="
Write-Host $uploadResponse
$upload = $uploadResponse | ConvertFrom-Json
$documentId = $upload.document_id

Write-Host "`n等待 Celery ingest 处理（默认 8 秒，可按实际 worker 日志调整）..."
Start-Sleep -Seconds 8

Invoke-JsonCurl "query retrieve" @(
    "-sS", "-X", "POST", "$BaseUrl/api/v1/query/retrieve",
    "-H", "Content-Type: application/json",
    "-d", '{"query":"网络运营者应当履行哪些安全保护义务？","top_k":5,"filters":{"doc_type":["law"]},"debug":true}'
)

Invoke-JsonCurl "query rewrite" @(
    "-sS", "-X", "POST", "$BaseUrl/api/v1/query/rewrite",
    "-H", "Content-Type: application/json",
    "-d", '{"query":"网络运营者安全义务","filters":{"doc_type":["law"]}}'
)

Invoke-JsonCurl "query answer" @(
    "-sS", "-X", "POST", "$BaseUrl/api/v1/query/answer",
    "-H", "Content-Type: application/json",
    "-d", '{"query":"网络运营者应当履行哪些安全保护义务？","top_k":5,"filters":{"doc_type":["law"]},"debug":true}'
)

$replaceResponse = & curl.exe -sS -X POST "$BaseUrl/api/v1/documents/$documentId/replace" `
    -F "file=@$sample2;type=text/plain" `
    -F "change_summary=手工 smoke：新增第二十三条"
if ($LASTEXITCODE -ne 0) { throw "replace failed" }
Write-Host "`n===== replace ====="
Write-Host $replaceResponse

Write-Host "`n等待 Celery replace 处理（默认 8 秒，可按实际 worker 日志调整）..."
Start-Sleep -Seconds 8

Invoke-JsonCurl "query answer after replace" @(
    "-sS", "-X", "POST", "$BaseUrl/api/v1/query/answer",
    "-H", "Content-Type: application/json",
    "-d", '{"query":"第二十三条要求什么？","top_k":5,"filters":{"doc_type":["law"]},"debug":true}'
)

Invoke-JsonCurl "eval run" @(
    "-sS", "-X", "POST", "$BaseUrl/api/v1/eval/run",
    "-H", "Content-Type: application/json",
    "-d", '{}'
)

Invoke-JsonCurl "soft delete" @("-sS", "-X", "DELETE", "$BaseUrl/api/v1/documents/$documentId")
