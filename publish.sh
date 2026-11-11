#!/usr/bin/env bash
# Publish the TeleCourse source to the owner's public GitHub repository.
set -euo pipefail
cd "$(dirname "$0")"

for cmd in git gh; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Instale $cmd antes de publicar." >&2; exit 1; }
done

gh auth status >/dev/null || { echo 'Autentique com: gh auth login' >&2; exit 1; }
account="$(gh api user --jq .login)"
if [[ "$account" != "Thomerlin" ]]; then
  echo "GitHub autenticado como $account; esperado: Thomerlin. Rode: gh auth switch" >&2
  exit 1
fi

if [[ ! -d .git ]]; then
  git init -b main
fi

git add .
# Never accidentally publish real Telegram sessions, databases or credentials.
if git ls-files | grep -Ei '(^|/)(\.env$|data/|.*\.session(-journal)?$|.*\.(db|sqlite|sqlite3)$)' | grep -v '^\.env\.example$'; then
  echo 'Foram encontrados arquivos privados rastreados pelo git. Publicação cancelada.' >&2
  exit 1
fi

if ! git diff --cached --quiet; then
  git commit -m 'feat: publish TeleCourse open source MVP'
fi

repo="Thomerlin/telecourse"
if gh repo view "$repo" >/dev/null 2>&1; then
  visibility="$(gh repo view "$repo" --json visibility --jq '.visibility')"
  if [[ "$visibility" != 'PUBLIC' ]]; then
    echo "O repositório existe mas não é público ($visibility). Publicação cancelada." >&2
    exit 1
  fi
  if git remote get-url origin >/dev/null 2>&1; then
    actual="$(git remote get-url origin)"
    if [[ "$actual" != "https://github.com/$repo.git" && "$actual" != "git@github.com:$repo.git" ]]; then
      echo "O remoto origin aponta para $actual, não $repo. Publicação cancelada." >&2
      exit 1
    fi
  else
    git remote add origin "https://github.com/$repo.git"
  fi
  git push -u origin main
else
  gh repo create "$repo" --public --source=. --remote=origin --push --description 'Biblioteca pessoal de cursos do Telegram com organização e progresso local.'
fi

echo "Publicação concluída: https://github.com/$repo"
