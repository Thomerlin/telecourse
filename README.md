# TeleCourse 📺

**Sua biblioteca pessoal de cursos do Telegram, com sequência, player e progresso local.**

TeleCourse é um projeto **open source (MIT)** voltado a uso pessoal: conecte a **sua própria conta** do Telegram, escolha canais/grupos privados que você já pode acessar, revise as aulas, organize módulos e assista a partir do navegador. Os arquivos continuam no Telegram; o SQLite local guarda o catálogo e o progresso.

> ⚠️ Estado: MVP funcional testado localmente **sem uma conta Telegram real**. O login e o streaming precisam ser validados no seu computador com seus próprios arquivos. Não é uma ferramenta para contornar proteções de canais ou redistribuir conteúdo.

## Funcionalidades

- **Biblioteca** com busca, retomada e indicadores de conclusão.
- **Assistente de importação**: seleção de canal/grupo, varredura apenas de metadados, prévia de vídeos e PDFs, revisão de nomes/módulos e publicação.
- **Organização conservadora**: reconhece `Módulo 02 / Aula 03` e `mod02_aula03` no título ou nome do arquivo; sinaliza nomes ambíguos para revisão.
- **Editor**: criar/renomear módulos, renomear aulas, transferir entre módulos, reordenar via arrastar/soltar ou setas.
- **Player HTTP Range** para formatos reconhecidos pelo navegador, com carregamento por partes usando Telethon (sem baixar tudo antecipadamente).
- **Progresso no SQLite**: posição da reprodução, tempo assistido e concluído/desmarcado, salvos durante a reprodução.
- **Backup** por SQLite online backup, restauração com o servidor parado e exportação de progresso para JSON.
- **Segurança básica**: bind somente em `127.0.0.1`, proteção de Host, CSP e dados privados excluídos do controle de versão.

## Requisitos

- Python 3.11+ (recomendado 3.12) e conexão com Telegram.
- Conta pessoal do Telegram com acesso aos canais/grupos onde estão os cursos.
- Credenciais de desenvolvedor **`API_ID` e `API_HASH`**, obtidas em [my.telegram.org](https://my.telegram.org/) → API development tools.

## Instalação (Windows / Linux / macOS)

```bash
git clone https://github.com/Thomerlin/telecourse.git
cd telecourse
python -m venv .venv
```

Ative o ambiente virtual:

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Copie `.env.example` para `.env` e preencha **somente no seu computador**:

```dotenv
API_ID=123456
API_HASH=seu_api_hash_aqui
```

Autentique-se **no terminal** (telefone, código 2FA e senha não são enviados à interface web):

```bash
python login.py
```

Inicie o servidor:

```bash
python run.py
```

Abra **http://127.0.0.1:8000** no navegador. O servidor deve ficar ligado durante a reprodução.

Para instalar a partir do arquivo ZIP desta versão, apenas extraia e execute os mesmos comandos (sem `git clone`).

## Seu primeiro curso

1. Abra **Importar aulas** e selecione um canal/grupo em que sua conta esteja inscrita.
2. Escolha a quantidade de mensagens recentes a analisar (padrão: 600, máximo: 3000 por varredura).
3. Revise os vídeos e PDFs; renomeie, separe os módulos e reorganize a ordem.
4. Escolha **Novo curso** ou **Adicionar a curso existente** e publique.
5. Reproduza no navegador e retome pelo painel **Continuar estudando**.

### Sobre a ordenação

A sequência é inferida de nomes com numeração explícita. Em itens sem número, usa-se a cronologia (ID da mensagem) como ordem aproximada. Em todos os casos, **revise antes de publicar**. Você pode importar lotes adicionais ou combinar fontes diferentes em um curso.

### Onde ficam os dados?

```text
telecourse/
├── .env                  # NUNCA fazer commit
├── data/
│   ├── telecourse.db     # Biblioteca e progresso
│   ├── telegram.session  # Sessão de sua conta Telegram (SENSÍVEL)
│   └── backups/          # Backups SQLite
└── ...                   # Código, testes e interface
```

A pasta `data/` e `.env` estão no `.gitignore`. O progresso pertence à aula (`lesson_id`), não ao nome do arquivo, e permanece intacto ao reorganizar ou renomear módulos.

## Backups e recuperação

Pelo app, clique em **Fazer backup**. Ou no terminal:

```bash
python -m scripts.backup
```

Para restaurar, **pare o servidor** e execute:

```bash
python -m scripts.restore data/backups/telecourse-YYYYMMDDTHHMMSSZ.db --confirmar
```

Uma cópia do banco anterior será criada antes de restaurar, quando houver banco. Também é possível exportar um JSON de progresso no menu lateral. **O export JSON é para consulta, não um importador de restauração.** Para migração entre máquinas, copie `data/telecourse.db`, sua sessão privada e os backups por um canal seguro; não os compartilhe nem envie ao GitHub.

## Executar testes offline

```bash
pip install -r requirements-dev.txt
pytest -q
```

A integração com Telegram **não faz parte** dos testes offline e precisa de testes manuais com uma conta autorizada. Não automatize autenticação por telefone/código em pipelines públicos.

## Limitações conhecidas

- Streaming direto depende de formato de vídeo compatível com o navegador (preferencialmente MP4/H.264/AAC). MKV, codecs não suportados e alguns arquivos com metadados no fim podem não tocar sem remux/conversão local — **conversão não está incluída**.
- Algumas restrições de mídia/canais protegidos são respeitadas; o aplicativo não contorna DRM ou restrições de cópia.
- Não há sincronização automática em segundo plano nem cliente Android/TV nativos; novas aulas são importadas por novas varreduras manuais.
- Sem busca profunda em todos os canais: a listagem inicial cobre até 500 conversas. Vídeos/cursos grandes podem esbarrar em limites ou pausas da API Telegram.
- O programa é **single-user e loopback-only**. Não abra porta em interfaces públicas nem use port forwarding. Acesso remoto exigiria autenticação e outra análise de segurança.
- Um mesmo `source_id + message_id` só pode pertencer a um curso por vez, para evitar duplicação acidental. Se desejar reaproveitar a mesma aula em diferentes trilhas, isso requer uma evolução do modelo de dados.
- Não temos testes com conteúdo privado do usuário; o aplicativo só funcionará se a conta conectada estiver autorizada a acessar a mídia original.

## Segurança e privacidade

Nunca publique `data/`, `.session`, `.env`, o número do telefone, códigos do Telegram, seus arquivos privados ou exports de progresso com títulos de cursos pessoais. Mantenha a sessão restrita à máquina e revogue pelo Telegram caso seja comprometida. Use apenas conteúdo que você tem permissão para acessar e respeite os termos e direitos dos criadores.

## Arquitetura

- `telecourse/server.py`: API FastAPI e streaming de mídia.
- `telecourse/telegram_gateway.py`: autenticação autorizada do Telethon, chats e entities.
- `telecourse/organizer.py`: organização determinística e classificação de arquivos.
- `telecourse/database.py`: esquema SQLite e backups.
- `static/`: interface web sem bibliotecas de frontend.
- `tests/`: testes offline (API, importação, progresso, backup, segurança e ordenação).

## Publicação open source

Para criar o repositório público `Thomerlin/telecourse` e publicar em um comando, instale GitHub CLI, autentique-se com `gh auth login` e rode `./publish.ps1` no Windows (ou `bash publish.sh` no Linux/macOS). Veja detalhes e alternativa manual em [PUBLISHING.md](PUBLISHING.md).

## Contribuição

PRs e issues são bem-vindos. Antes de enviar mudanças, execute `pytest -q`. **Nunca** envie suas sessões Telegram ou dados pessoais aos mantenedores. Código distribuído sob a [MIT License](LICENSE), com dependências de terceiros sob suas próprias licenças.
