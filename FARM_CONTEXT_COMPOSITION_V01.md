# Farm Context Composition v0.1

Fronteira pura e explícita:

```text
State -> adapt_state -> RuntimeObservation -> build_context_seed
      -> DecisionContextSeed + FarmStrategicEvidence + Execution
      -> compose_farm_context -> DecisionContext
```

A implementação termina em DecisionContext. Somente testes chamam farm_cycle.plan
depois da composição. Não há import/call novo no entry point, services, GSI, Policy,
runtime_adapter, context_builder ou farm_cycle. Nenhuma saída live é criada.

## Seam e contrato de entrada

```python
compose_farm_context(seed, strategic_evidence, execution) -> DecisionContext
```

FarmStrategicEvidence é uma dataclass congelada com:

- seed_id: vínculo obrigatório com o seed exato;
- observations: tuple[ObservedFact, ...], suporte observacional fornecido;
- assessments: tuple[OptionAssessment, ...], opções estratégicas fornecidas;
- increased_risk: Claim explícita;
- assessment_source: Source.EXPERT_HEURISTIC, única origem de assessment suportada
  pelo resolver existente nesta versão.

Não existe segundo conjunto knowledge/player. O seed contém suas referências
versionadas, e a comparação seed_id vincula a evidência a esses ids/versões e à
projeção runtime. Evidência de outro seed é recusada. Alterar o seed exige fornecer
explicitamente evidência vinculada ao novo seed; o composer não a revalida sozinho.
Esse vínculo verifica consistência, não autentica a veracidade das avaliações.

As opções reutilizam OptionAssessment(plan_id, action, available, safe). Availability,
safety e risco reutilizam Claim(value: Truth, evidence_refs, rule_ref). ObservedFact
reutiliza Truth e Freshness já existentes. Execution é argumento obrigatório e usa
NOT_STARTED/IN_PROGRESS/plan_id do contrato aceito. Não há movimento inferido.

Os três tipos produtivos continuam TAKE_ONE_MORE_WAVE, LEAVE_TO_SAFE_FARM e
SAFE_RESOURCE_THEN_REEVALUATE. Duplicatas de ação/plano e ações inválidas continuam
rejeitadas pelo build_context existente. Uma opção omitida fica omitida; não vira
disponível nem NO. Um risco desconhecido deve ser fornecido como Claim UNKNOWN,
com rule_ref explícito (evidence_refs pode ser vazio).

## Gate de elegibilidade

Seeds INELIGIBLE ou INSUFFICIENT_DATA são recusados com ValueError('seed_not_eligible').
Nenhum DecisionContext parcial acionável é retornado. ELIGIBLE permite compor;
não significa que qualquer opção estratégica seja segura ou disponível.

Como a dataclass do seed permite construção manual/replace, o composer usa o
build_context_seed existente para verificar sua consistência com dimensions,
observation_id e lineage. Seed com eligibility ou seed_id adulterado falha como
inconsistent_seed. Não há segunda implementação das regras de elegibilidade.

## Reuso integral da resolução

Após o gate, cria-se um RuntimeObservation transitório com a observation_id do
seed e **somente observations fornecidas**. As dimensões escalares nunca são
convertidas em ObservedFact nem usadas para satisfazer Claim.evidence_refs.
O contexto final é retornado diretamente por decision.build_context, com knowledge,
player e execution preservados.

Nenhuma lógica de lookup, freshness, construção de Condition/Provenance ou UNKNOWN
foi duplicada. O comportamento herdado é:

- evidência ausente resolve como ObservedFact UNKNOWN/STALE;
- suporte UNKNOWN impede promover a Claim, mesmo se ela declarar YES;
- qualquer suporte STALE torna a condição STALE/UNKNOWN;
- Claim sem suporte é UNKNOWN, inclusive se declarar YES;
- com suporte fresco e conhecido, preserva-se o valor da Claim fornecida.

Um suporte conhecido pode ter Truth.NO e ainda ser evidência conhecida (por exemplo,
uma ausência observada). Isso não transforma automaticamente a Claim em NO. O
resolver não prova que a interpretação estratégica decorre logicamente do suporte;
ela continua uma avaliação explícita do autor, identificada por rule_ref. Não se
declara que uma heurística é mecanicamente verificada ou universalmente correta.

## Provenance e separação de fontes

ObservedFact é a categoria observacional já aceita e mantém provenance
RUNTIME_OBSERVATION através do resolver. Claim é categoria diferente: sua
interpretação preserva EXPERT_HEURISTIC e rule_ref. Nenhuma Claim é convertida
em ObservedFact para torná-la suporte da própria conclusão.

As fixtures usam observações booleanas sintéticas como `fixture.enemy-visible` e
`fixture.wave-observed`. Sua etiqueta runtime identifica a categoria contratual;
não afirma que GSI real ou Safety Builder tenha produzido essas fixtures. As
avaliações como `fixture.wave-safety.v1` são explicitamente heurísticas fornecidas.

Uma assessment_source diferente de EXPERT_HEURISTIC é rejeitada, pois build_context
não tem contrato para preservar outras origens de assessment. Não se relabela
KNOWLEDGE_SNAPSHOT, PLAYER_MODEL ou RUNTIME_OBSERVATION como heurística ou vice-versa.
Suporte future Safety/Map requer um contrato explícito futuro; não existe aqui.

O namespace `State.*` é recusado nos refs de suporte e nos evidence_refs das Claims.
Isso impede usar o nome de um escalar runtime como atalho para evidência estratégica.
Não há derivação por GPM, tempo, nível, herói, ouro, LH, XPM, itens ou mecânicas.

Para auditar “por que wave safety é YES?”, Condition conserva o fato referenciado,
seu freshness e a provenance com o rule_ref do autor. O chamador deve guardar
seed + FarmStrategicEvidence + contexto: o DecisionContext legado não armazena
seed_id nem todas as dimensões. Sua observation_id e referências knowledge/player
permanecem intactas. Nenhum schema antigo foi ampliado.

## Determinismo, imutabilidade e limites

Não há ID novo de composição: usa-se context_id do DecisionContext existente.
Mesmas entradas produzem contexto igual e mesma identidade; ordem das opções e
do conjunto de observações não muda a resolução. Ordem das dependencies de uma
Claim continua a ordem explícita do autor, conforme o resolver já aceito.

Dataclass congelada e tuplas mantêm o novo input imutável. Valores/ref strings e
tipos aceitos são validados; plan_id mutável de Execution é recusado para preservar
imutabilidade do resultado. Claims/opções/execution/observações não são alterados.

Sem IO, rede, relógio, ambiente, processos, cache ou histórico. KnowledgeSnapshotRef
e PlayerModelSnapshotRef são só lineage. Conteúdo de Data Foundation/Player Model
não é carregado. Nenhum score, threshold, pathfinding ou previsão de ameaça existe.

São adiados Safety/Map Evidence Builders, tracking de inimigos, visão, Fight/Objective
planners, arbitragem, integração GSI -> planner, adapter v0.2 e partidas reais.

## Testes e preservação

tests/test_farm_context.py demonstra a cadeia offline completa até Decision, com
planner chamado explicitamente nos testes: wave segura fornecida, fallback farm,
recurso curto com informação insuficiente, risco sem rota, mudança de rota ativa
para unsafe, UNKNOWN/STALE/missing support e recusa de seeds sem elegibilidade.

Também cobre lineage, versões incompatíveis, integridade do seed, Execution,
determinismo, imutabilidade, provenance, ausência de inferência estratégica por
escalares, campos inválidos e isolamento de IO/imports. O teste de IO bloqueia o
planner enquanto chama apenas compose_farm_context e verifica restauração dos mocks.

Gates: baseline completo uma vez, focal farm-context uma vez, context-builder uma
vez, adapter uma vez, farm-cycle uma vez e regressão completa uma vez. Destinos
externos são bloqueados. O contrato HTTP canônico permanece intacto; WinError 10054
continua erro bloqueante e nenhum retry-until-green é permitido.

Novos arquivos apenas: farm_context.py, test_farm_context.py e este documento.
Manifestos e resultados ficam externamente em outputs/FARM_CONTEXT_COMPOSITION_V01_20260929.
