# Publicar o TeleCourse no GitHub (open source)

Este projeto foi preparado para um repositório **público** com licença MIT.

## Opção rápida: criar e publicar automaticamente usando GitHub CLI

Instale [Git](https://git-scm.com/) e [GitHub CLI](https://cli.github.com/), abra o terminal **na pasta extraída `telecourse`**, e execute `gh auth login` (com a conta `Thomerlin`). Então:

- **Windows / PowerShell:** `./publish.ps1` (ou `powershell -NoProfile -ExecutionPolicy Bypass -File .\publish.ps1` quando a política de execução bloquear o script).
- **Linux / macOS / Git Bash:** `bash publish.sh`.

O script verifica a conta autenticada e arquivos privados antes de criar o repositório público `Thomerlin/telecourse` e fazer `git push`. Ele não inclui dados da sessão do Telegram. Se o repositório já existir, só faz o push caso seja público e o remoto aponte ao destino esperado. **Revise o código antes de publicá-lo.**

## Opção manual

### 1. Criar o repositório

No [GitHub](https://github.com/new), selecione:

- **Owner**: `Thomerlin`
- **Repository name**: `telecourse`
- **Visibility**: **Public**
- Não marque **Add a README file**, **Add .gitignore** ou **Choose a license**. Os três já estão incluídos no projeto.

### 2. Subir pelo terminal

Extraia o ZIP, abra um terminal **dentro da pasta `telecourse`** e execute:

```bash
git init -b main
git add .
git status --short   # Revise os arquivos; NÃO inclua data/, .env ou sessões do Telegram
git commit -m "feat: initial open source TeleCourse MVP"
git remote add origin https://github.com/Thomerlin/telecourse.git
git push -u origin main
```

É preciso estar autenticado no GitHub com permissão de escrita (por exemplo, via `gh auth login`, Git Credential Manager ou SSH). **Não** inclua tokens no código ou no comando remoto.

Se você já tiver iniciado Git ou tiver um remoto configurado, confira com `git remote -v` antes de adicionar `origin`.

### 3. Configuração do projeto no GitHub

- Na descrição do repositório, use: `Transforme canais privados do Telegram em uma biblioteca pessoal de cursos, com organização e progresso local.`
- Topics sugeridos: `telegram`, `python`, `fastapi`, `sqlite`, `elearning`, `self-hosted`, `open-source`.
- A workflow `.github/workflows/tests.yml` executará os testes offline em push e pull request.
- Configure proteção da branch `main` e revisão de pull requests se houver colaboradores.

### 4. Segurança

O repositório é público, mas **as suas credenciais, dados pessoais e mídias não são**. Verifique se nenhuma destas entradas foi incluída:

```text
.env
data/
*.session
*.session-journal
*.db
*.sqlite*
```

Nunca envie capturas de grupos privados, histórico de mensagens, tokens, códigos de autenticação ou títulos de cursos pessoais em logs públicos de issues.

### 5. Verificação

Após fazer o push, o endereço esperado será **https://github.com/Thomerlin/telecourse**.

Se aparecer `Permission denied`, `403` ou `repository not found`, revise a autenticação e as permissões de escrita da conta. O projeto também pode ser publicado pelo GitHub Desktop, selecionando a pasta local e **Publish repository**, com visibilidade **Public**.
