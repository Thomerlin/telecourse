# Publica o TeleCourse como repo público no GitHub do proprietário.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

foreach ($command in @('git', 'gh')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Instale $command antes de publicar."
    }
}

gh auth status 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Faça login primeiro: gh auth login' }
$account = (gh api user --jq .login).Trim()
if ($LASTEXITCODE -ne 0 -or $account -ne 'Thomerlin') {
    throw "Conta conectada: $account. Entre na conta Thomerlin com gh auth login / gh auth switch."
}

if (-not (Test-Path .git)) {
    git init -b main
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível inicializar o Git.' }
}
git add .
if ($LASTEXITCODE -ne 0) { throw 'git add falhou.' }
$tracked = @(git ls-files)
foreach ($f in $tracked) {
    if ($f -match '(^|/)(\.env$|data/|.*\.session(-journal)?$|.*\.(db|sqlite|sqlite3)$)' -and $f -ne '.env.example') {
        throw "Arquivo privado rastreado, publicação cancelada: $f"
    }
}

git diff --cached --quiet
if ($LASTEXITCODE -eq 1) {
    git commit -m 'feat: publish TeleCourse open source MVP'
    if ($LASTEXITCODE -ne 0) { throw 'Commit falhou. Configure git user.name e user.email.' }
} elseif ($LASTEXITCODE -ne 0) {
    throw 'Falha ao verificar mudanças do Git.'
}

$repo = 'Thomerlin/telecourse'
gh repo view $repo *> $null
$exists = ($LASTEXITCODE -eq 0)
if ($exists) {
    $visibility = (gh repo view $repo --json visibility --jq '.visibility').Trim()
    if ($visibility -ne 'PUBLIC') { throw "O repositório não é público ($visibility)." }
    $origin = (git remote get-url origin 2>$null)
    if ($LASTEXITCODE -eq 0) {
        if ($origin -ne "https://github.com/$repo.git" -and $origin -ne "git@github.com:$repo.git") {
            throw "O remoto origin aponta para $origin, não $repo."
        }
    } else {
        git remote add origin "https://github.com/$repo.git"
        if ($LASTEXITCODE -ne 0) { throw 'Não foi possível adicionar origin.' }
    }
    git push -u origin main
    if ($LASTEXITCODE -ne 0) { throw 'Git push falhou.' }
} else {
    gh repo create $repo --public --source=. --remote=origin --push --description 'Biblioteca pessoal de cursos do Telegram com organização e progresso local.'
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar e publicar o repositório.' }
}
Write-Host "Publicação concluída: https://github.com/$repo"
