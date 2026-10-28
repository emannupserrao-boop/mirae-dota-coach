# Git Bootstrap + Canonical Architecture Freeze v0.1

## Registro versionado de fatos pré-commit

Este relatório documenta a retomada autorizada do bootstrap local. Git foi inicializado em main, a identidade foi configurada somente neste repositório, as exclusões foram verificadas e o baseline passou. Commit, tags e regressão pós-commit são as próximas verificações da mesma operação; seus resultados efetivos serão registrados EXTERNAMENTE. Este arquivo não declara antecipadamente sua conclusão.

Raiz canônica: `C:\Users\user\Documents\Dota AI Coach Project\Dota-AI-Coach-Alpha-0.2\Dota-AI-Coach-Alpha-0.2`.

Resultado anterior: GIT_BOOTSTRAP_CANONICAL_FREEZE_V01_BLOCKED. A retomada autorizou explicitamente editar somente .gitignore e este relatório, forneceu identidade local e resolveu a autorreferência do SHA. O manifesto de76 arquivos na retomada coincide com o manifesto da tentativa bloqueada;18 hashes aceitos foram confirmados. Git estava ausente antes da retomada.

## Identidade, branch e escopo

- Branch atual: main, ainda antes do primeiro commit na preparação deste relatório.
- Author local autorizado: Emannuel Serrão <332245450+emannupserrao-boop@users.noreply.github.com>.
- Configuração: user.name e user.email em .git/config, nunca --global.
- Configurações globais conferidas por hash e preservadas.
- core.autocrlf=false configurado somente localmente para preservar bytes dos blobs/checkout no Windows.
- Nenhum remote configurado; nenhuma operação de push, PR, GitHub ou rede externa.
- Hooks e fsmonitor externos desabilitados nas invocações operacionais; nenhum hook personalizado será executado para o commit.

## Baseline observado

Python canônico Windows: `3.13.15 (tags/v3.13.15:4061bc4, Aug  5 2026, 13:05:39) [MSC v.1944 64 bit (AMD64)]`.

Executável: `C:\Users\user\Documents\Dota AI Coach Project\Dota-AI-Coach-Alpha-0.2\Dota-AI-Coach-Alpha-0.2\.venv\Scripts\python.exe`.

Uma execução pré-Git:460 descobertos,460 executados,460 aprovados,0 falhas,0 erros,0 skips. Sem retries. Harness anterior com guardas de destinos externos e estímulos reais preservado. Transporte do oversized no baseline: WinError 10053 estreito aceito pelo teste existente; nenhum WinError10054. O teste HTTP exige rejeição e recuperação, sem enfraquecimento da proteção de tamanho.

A suíte completa pós-commit será executada UMA vez, depois das tags. Seu resultado ainda não era conhecido ao preparar este relatório e será registrado externamente. WinError10054 ou outra falha bloqueia a aceitação, sem retry ou reparo de código.

## Auditoria de sensíveis e gerados

76 arquivos candidatos auditados antes de staging: nenhum segredo/credencial real encontrado. As ocorrências de token nos fontes são geração em runtime, referências de payload de testes e uma fixture sintética de caractere repetido. Referências em documentação descrevem proteção de tokens. Valores de segredos não foram impressos.

Nenhum .env, credential file, SQLite runtime, log, arquivo temporário ou metadata local de IDE/OS está entre os76 candidatos. .venv possui2608 arquivos e caches __pycache__17; ficam fora do versionamento. A auditoria não confunde esses diretórios gerados com conteúdo canônico.

Documentação histórica aceita mantida: docs/baseline-verification.json, docs/baseline-sha256.json e docs/test-results.txt. Esses registros já pertencem ao manifesto aceito e não são novos diagnósticos desta execução. Evidências desta operação ficam fora da árvore versionada.

A verificação combina nomes/tipos de arquivo, padrões de credenciais e revisão estrutural das atribuições de tokens. Não é certificação universal de detecção de todo segredo possível; nenhum indício real foi encontrado no conteúdo preparado.

## Alteração autorizada de .gitignore

Todos os bytes/regras anteriores foram preservados como prefixo; apenas três regras foram acrescentadas: .env, .env.* e !.env.example. Não houve substituição por template ou reformatação de linhas anteriores.

```gitignore
__pycache__/
*.pyc
.venv/
build/
dist/
*.sqlite3*
settings.json
*.log
.env
.env.*
!.env.example
```

Validação git check-ignore, sem criar conteúdo: .venv/probe.txt, __pycache__/probe.pyc, probe.pyc, .env e .env.local ignorados; .env.example permitido. .env.example não existe no projeto, mas sua exceção foi testada com caminho sintético sem arquivo.

## Inventário candidato ao staging

| Grupo | Arquivos |
|---|---:|
| production | 33 |
| tests | 13 |
| documentation | 23 |
| configuration | 7 |
| data_static | 0 |

Total76. A lista nominal e a conferência dos blobs staged ficam no pacote externo. Stage será limitado explicitamente a esses caminhos relativos da raiz, sem git add genérico de diretórios externos. Os blobs serão comparados aos bytes de cada arquivo antes do commit.

## Preservação

Somente .gitignore e GIT_BOOTSTRAP_CANONICAL_FREEZE_V01.md foram autorizados a mudar. Todos os outros74 arquivos preexistentes, incluindo código, testes e docs arquiteturais aceitos, permanecem byte-for-byte preservados. Nenhum arquivo novo de conteúdo canônico foi necessário; .git é metadata interna.

Os18 hashes aceitos são os seguintes e não foram alterados:

| Arquivo | SHA-256 aceito |
|---|---|
| coach/state.py | `35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5` |
| coach02/decision.py | `E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD` |
| coach02/runtime_adapter.py | `586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B` |
| coach02/context_builder.py | `066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13` |
| coach02/safety_evidence.py | `E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199` |
| coach02/option_safety.py | `05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C` |
| coach02/option_availability.py | `E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494` |
| coach02/strategic_evidence.py | `CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5` |
| coach02/farm_context.py | `F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E` |
| coach02/farm_cycle.py | `B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD` |
| OFFLINE_CORE_V01.md | `082F087D423A109C8F36EE7BB1718476476A156F0B0A695E4A68A6959F381FBB` |
| tests/test_offline_core.py | `D9FAFCC4A34DFBDBA1A0B09D7C20F21087C17D40E080E9D34CA2C783A4461076` |
| TEMPORAL_EVIDENCE_V01.md | `CFDE8BB450A5B864B652B9291329F36D538C90164DF0D2C6EC34853669AC918B` |
| coach02/temporal_evidence.py | `D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57` |
| tests/test_temporal_evidence.py | `77D4537252F81111C7ACB3F5535D823E26F1427F8CA2C7C6E84BE6B081F443B8` |
| OBSERVATION_EVENT_FOUNDATION_V01.md | `B198EAB49761C3533A6D9449783A96DA481817B66984BE09BE6C50980D0697A9` |
| coach02/observation_event.py | `BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355` |
| tests/test_observation_event.py | `25296D0A39B91CEDA6713E46F4DB7ECD6E5A3901AD8258406DE71794FBF0C921` |

Nenhuma modificação de gameplay, runtime, Data Foundation, dependência ou instalação. Nenhuma etapa arquitetural nova.

## Commit e tags planejados

Será criado exatamente UM commit inicial, sem história sintética nem amend para inserir SHA:

`chore: freeze Mirae canonical alpha foundation`

Tags anotadas locais, todas destinadas ao mesmo commit inicial:

- offline-core-v0.1
- temporal-evidence-v0.1
- observation-event-v0.1
- canonical-foundation-v0.1

Mensagens das tags explicarão que os componentes já haviam sido aceitos antes do bootstrap e estão sendo ancorados no primeiro commit canônico. Não serão enviadas a remote.

**The literal SHA of the commit containing this report is recorded externally after commit creation to avoid self-referential commit content.**

O SHA final, short SHA, contagem de commits, alvos efetivos das tags, estado da árvore, hashes finais e resultado pós-commit serão obtidos após a criação e registrados somente na resposta final e em evidência externa. Este relatório NÃO será editado depois do commit para incorporar fatos posteriores.

## Limitação histórica e encerramento

Git history begins at this bootstrap point. Earlier development history is not reconstructible from Git. Tags for earlier accepted components anchor their presence at this first commit; they do not imply separate historical commits or dates before Git existed.

Este freeze registra a presença aceita de Alpha runtime/GSI foundation, Offline Carry Farm Decision Core v0.1, Temporal Evidence Tracker v0.1 e Observation Event Foundation v0.1. Não transforma evidências históricas externas em commits históricos.

Próxima etapa arquitetural autorizada: NENHUMA. Após a aceitação externa desta operação, parar para revisão humana. Não iniciar Threat/Coverage/Exposure/Resource Observation, live clock selection, orchestration, GSI integration, Shadow Mode ou partidas reais.
