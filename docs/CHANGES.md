# Mudanças e rollback

Baseline Alpha 0.1 mantido fora desta pasta, sem sobrescrever arquivos ou dados.
O manifesto `baseline-sha256.json` registra os hashes anteriores. A comparação
automatizada está em `baseline-verification.json`.

Novos módulos: `coach02/__init__.py`, `config.py`, `rules.py`, `policy.py`,
`voice.py`, `vision.py`, `storage.py`, `performance.py`, `service.py`, `ui.py`.
Novos arquivos: `requirements-vision.txt`, `Install.cmd`, `Start-Bot-Test.cmd`,
`LEIA_PRIMEIRO.txt`, `tests/test_alpha02.py`, documentação/relatórios Alpha 0.2.
Alterados só na cópia 0.2: `run.py`, `requirements.txt`, `Start-Coach.cmd`,
`Run-Tests.cmd`, `README.md`.
Documentação antiga movida para `docs/alpha01-reference/` e rotulada como histórica.
`Test-Demo.cmd` foi removido somente da cópia 0.2 para não confundir teste real
com estímulos sintéticos. O código legado de demo permanece para testes.
`coach/` e `tests/test_alpha.py` mantidos byte a byte.

Correções encontradas na preparação: teste de mortes isolado do alerta de farm;
recuperação de farm por tendência mesmo depois de janela anterior zerada;
feedback pendente gravado ao fechar; visão suspensa com herói morto/desconhecido;
calibração com rolagem e edição dos limiares visuais; eventos do teste de voz
incluídos no diagnóstico. Todas essas alterações pertencem ao escopo 0.2.

## Voltar ao Alpha 0.1

1. Feche o Coach 0.2 e o Dota.
2. Na pasta `dota 2 beta\game\dota\cfg\gamestate_integration`, renomeie somente
   `gamestate_integration_dota_ai_coach_alpha02.cfg` para
   `gamestate_integration_dota_ai_coach_alpha02.cfg.disabled`.
3. Preserve o CFG antigo do Alpha 0.1 e a opção `-gamestateintegration`.
4. Abra Start-Coach.cmd da sua pasta original Alpha 0.1 e reinicie o Dota.
5. Dados antigos continuam em `%LOCALAPPDATA%\DotaAICoach`; os novos estão em
   `%LOCALAPPDATA%\DotaAICoach02`. Nenhuma migração ou exclusão é necessária.

Para voltar ao teste 0.2, feche o 0.1, restaure a extensão `.cfg` do arquivo 0.2
ou use Configurar GSI 0.2 novamente, e reinicie Dota. Não rode ambos os coaches
falando ao mesmo tempo.
