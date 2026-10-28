# Mirae / Alpha 0.2 — primeira vertical de decisão offline

Escopo: protótipo determinístico isolado. Nenhum import foi adicionado ao
entrypoint, serviço, receptor, State ou regras atuais do Alpha. O código só roda
quando chamado explicitamente pelos testes ou por outro consumidor Python.

## Fronteiras implementadas

```text
RuntimeObservation + KnowledgeSnapshotRef + PlayerModelSnapshotRef
                  + avaliações semânticas explícitas da fixture
                                |
                         build_context()
                                |
                         DecisionContext
                                |
                       farm_cycle.plan()
                                |
                            Decision
                                |
                      authorize_output()
                                |
                    Output estruturado em memória
```

`coach02/decision.py` contém os contratos e a validação. `coach02/farm_cycle.py`
contém o único planner. Todos usam apenas a biblioteca padrão. Não acessam relógio,
disco, rede, banco, GSI ou dados externos. Dataclasses congeladas, tuplas e enums
mantêm os snapshots/resultados imutáveis; referências de conhecimento e jogador
exigem identificador e versão.

`RuntimeObservation` carrega fatos booleanos observados, como visibilidade e
presença de recurso, com `YES`, `NO` ou `UNKNOWN` e `FRESH`/`STALE`. Não carrega
conclusões como “esta rota é segura”. O subconjunto booleano é suficiente para
esta vertical; não se tentou modelar toda a telemetria do Dota.

As fixtures fornecem separadamente `Claim`/`OptionAssessment`: disponibilidade e
segurança aceitável de uma opção, além de evidência de risco aumentado. São
avaliações semânticas fornecidas por um autor, identificadas como
`EXPERT_HEURISTIC`, não fatos observados ou resultados mecânicos comprovados.
`build_context` resolve suas dependências contra o snapshot: suporte ausente,
desconhecido ou stale torna a conclusão `UNKNOWN`. Não há fallback para SAFE.
Cada condição preserva fatos, freshness e referência da heurística.

**Limite deliberado:** o protótipo não calcula segurança de rotas a partir de
posições/visão. Isso criaria lógica fora da vertical solicitada. Ele valida a
fronteira entre observação e avaliação semântica, cuja interpretação continua
explicitamente fornecida por fixtures. Nenhuma heurística está validada
estatisticamente ou como verdade universal de Dota.

As referências `KNOWLEDGE_SNAPSHOT` e `PLAYER_MODEL` são somente lineage. Não
carregam dados, custos, mecânicas ou personalização e não são evidência de que
esses conteúdos tenham sido consultados. Alterar suas versões invalida uma decisão
anterior. Provenance de regras e observações permanece separada dessas referências.

## Escolha qualitativa

Uma opção produtiva precisa ter disponibilidade confirmada **e** segurança
aceitável confirmada por evidência fresca. O planner admite uma opção fornecida
por tipo de ação; múltiplas rotas do mesmo tipo são rejeitadas explicitamente.
Os IDs das opções são opacos: o planner não calcula caminhos.

| Contexto fornecido | Resultado |
| --- | --- |
| Wave disponível e com segurança aceitável confirmada | TAKE_ONE_MORE_WAVE / DIRECTIVE |
| Wave não confirmada; farm alternativo confirmado | LEAVE_TO_SAFE_FARM / DIRECTIVE |
| Informação insuficiente; apenas recurso curto seguro confirmado | SAFE_RESOURCE_THEN_REEVALUATE / DIRECTIVE |
| Risco aumentado suportado; nenhuma rota justificável | NO_DIRECTIVE / AWARENESS |
| Sem suporte para risco específico ou ação produtiva | HOLD_AND_REEVALUATE / ADVISORY |
| Rota iniciada e ainda confirmada | Manter a ação da rota / DIRECTIVE |
| Rota iniciada com segurança explicitamente rejeitada por suporte fresco | ABORT_CURRENT_ROUTE / DIRECTIVE |
| Rota iniciada sem confirmação atual, inclusive stale | HOLD_AND_REEVALUATE / ADVISORY |

A ordem wave → farm alternativo → recurso curto codifica apenas o contrato
qualitativo das fixtures desta vertical. Não é otimização, pontuação, ranking
multi-planner ou regra universal de gameplay. Uma rota em execução é considerada
antes de selecionar uma nova opção, para evitar trocar planos sem necessidade.

HOLD significa suspender compromisso com uma rota e reavaliar; **não** significa
ficar imóvel em um local presumidamente seguro. ABORT cancela a rota em execução;
não prescreve uma rota substituta nem afirma que toda alternativa será segura.
Esses resultados mantêm risco/viabilidade desconhecidos onde não há evidência.

## Decision, validade e autoridade

O objeto preserva identidade determinística, domínio, objetivo, candidatos,
selecionado/next_action, viabilidade, risco, dependências/freshness, expectativa de
estado futuro (intenção, não promessa), execução, condições de invalidação e
preempção, confiança qualitativa, autoridade, reasons estáveis e provenance.
Não há confiança numérica, pesos ou previsão de ganhos de farm.

`validate_decision(decision, supplied_context)` pode retornar VALID, EXPIRED ou
INVALID. Suporte stale expira a decisão mesmo sem mudança do valor observado.
Mudanças de dependências, execução ou versões invalidam a decisão. Uma assinatura
determinística do contexto força reconsideração conservadora diante de qualquer
mudança fornecida, inclusive de um advisory baseado em informação insuficiente.
Não há scheduler nem limiar temporal: a fixture informa freshness.

`authorize_output` retorna apenas um objeto em memória. Decisões vencidas,
inválidas ou com saída desabilitada viram SUPPRESS/NO_DIRECTIVE. Decisões válidas
podem ser DIRECTIVE, ADVISORY ou AWARENESS; esta última não emite rota. A decisão
original continua disponível para auditoria. Não há cooldown de atenção,
deduplicação temporal, UI ou texto de fala.

## Arquitetura adiada

- Adaptador de runtime, execução no Dota e integração Runtime↔Data.
- Carregamento de Knowledge Snapshot e mecânicas de heróis/patches.
- Modelo longitudinal, currículo, hábitos, progressão ou orçamento de desenvolvimento.
- Arbiter completo ou pass-through multi-planner. A interface pura
  `plan(DecisionContext) -> Decision` preserva o ponto de integração futuro.
- Outros planners, pathfinding, resolução de múltiplas rotas, rastreamento de
  movimento e políticas adicionais de atenção.

A `Policy` legada já faz priorização numérica das recomendações antigas. Ela não
foi reutilizada nem modificada: importá-la nesta vertical introduziria arbitragem
fora do escopo. O vocabulário PRESENT/ABSENT do diagnóstico T02 continua intacto;
ele descreve presença/tipo de campos, não conhecimento semântico ou freshness.

## Testes e uso exclusivamente offline

`tests/test_farm_cycle.py` contém 23 testes determinísticos, incluindo os seis
cenários exigidos, expiração, progresso/abort, suporte ausente, referências,
provenance, autoridade, imutabilidade e identidade determinística. Não há testes
que dependam de herói, item, custo, patch ou threshold real de jogo.

O comando legado é `python -m unittest discover -s tests -v` (Run-Tests.cmd).
Como inclui HTTP, esta tarefa usa um runner adicional sem mudar os testes antigos:

```powershell
python -B -I tools/verify_no_network.py --log-dir <diretorio-novo> --site-packages <bibliotecas-locais-existentes>
```

Esse runner bloqueia IO de sockets/HTTP, DNS, processos externos, TTS real e
captura de tela real. Permite somente `gethostname`, que lê o nome local do sistema
sem IO de rede. Registra como skips os 19 testes legados que abrem sockets, inclusive
os que o fazem em setUp; mantém os testes sintéticos de regras, SQLite, voz e visão.
Não permite nem loopback. A lista exata de exclusões aparece nos logs JSON.

Resultados e verificação de preservação desta execução ficam em
`outputs/MIRAE_OFFLINE_FARM_CYCLE_20260929/`, sem substituir artefatos anteriores.
Esta vertical termina aqui, aguardando revisão; não autoriza integração ao runtime.
