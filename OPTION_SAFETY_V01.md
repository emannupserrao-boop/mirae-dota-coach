# Option Safety Assessment v0.1 — Farm Exposure Core

Avaliação isolada de aceitabilidade por opção, com risco global já derivado e
observações de exposição/cobertura explicitamente fornecidas. Nenhuma ação é
escolhida, disponibilidade inferida ou saída de coaching emitida.

```python
results = build_option_safety(seed.seed_id, risk, option_observations)
for result in results:
    result.validate_binding(seed.seed_id, risk)
    # Somente testes nesta etapa: combinar result.safety com availability independente.
```

## Contratos exatos

Entrada congelada `FarmOptionSafetyObservation`:

- seed_id: str não vazia, identidade exata do DecisionContextSeed;
- option_id: str ASCII não vazia, letras/dígitos/underscore/hífen;
- action: Action, um dos PRODUCTIVE_ACTIONS existentes;
- exposure: Exposure.LOW / HIGH / UNKNOWN;
- exposure_freshness: Freshness.FRESH / STALE;
- coverage: Truth.YES / NO / UNKNOWN;
- coverage_freshness: Freshness.FRESH / STALE.

`build_option_safety(seed_id: str, risk: RiskAwarenessEvidence,
options: tuple[FarmOptionSafetyObservation, ...]) -> tuple[OptionSafetyEvidence, ...]`.

A função recebe o ID do seed; não acessa suas dimensões ou conteúdo de snapshots.
O chamador fornece relevância de ameaças, observações globais, exposição por opção,
cobertura e freshness. Não são observações live nesta versão. LOW/HIGH não são
calculados por coordenadas, distância, tempo, herói, item, MMR, ouro, GPM ou LH.

Nenhum enum Truth/Freshness/Source/Action é duplicado. Ações permitidas:
TAKE_ONE_MORE_WAVE, LEAVE_TO_SAFE_FARM e SAFE_RESOURCE_THEN_REEVALUATE.
A ação é identidade fornecida, não recomendação. A mesma regra avalia os três tipos.
IDs repetidos são recusados. Tupla vazia retorna tupla vazia, sem fabricar opções.

Saída congelada `OptionSafetyEvidence`:

- evidence_id: str;
- seed_id: str;
- option_id: str;
- action: Action fornecida;
- observations: tuple[ObservedFact, ...];
- safety: Claim;
- reasons: tuple[OptionSafetyReason, ...];
- ruleset: `safety.option_assessment.v1`;
- upstream_risk_evidence_id: str.

Não contém availability, recommended_action, score ou probabilidade de gank.

## Regras exatas

| Risco global recebido | Exposição | Cobertura da opção | Freshness da opção | safety |
|---|---|---|---|---|
| YES | HIGH | NO | Ambas FRESH | NO |
| NO | LOW | YES | Ambas FRESH | YES |
| Qualquer outra combinação válida | Qualquer | Qualquer | Qualquer | UNKNOWN |

YES significa **aceitável sob esta heurística estreita e os dados fornecidos**.
Não significa garantidamente seguro, impossível morrer ou verdade mecanicamente
verificada de Dota. NO significa **não sustentado como aceitável sob essas
condições**, não certeza de morte. UNKNOWN significa suporte insuficiente para YES
ou NO. Toda conclusão continua EXPERT_HEURISTIC v0.1.

Risco YES não contamina automaticamente todas as opções: LOW e/ou cobertura YES
não satisfazem a única regra NO. Risco NO não certifica HIGH nem LOW sem cobertura.
Risco UNKNOWN, exposição UNKNOWN/STALE ou cobertura UNKNOWN/STALE não sustentam
YES/NO. Não há regra de override, score, peso, percentual, limiar numérico ou TTL.

## Facts, suporte e provenance

Cada opção gera:

- `safety.option.<option_id>.exposure_low`;
- `safety.option.<option_id>.exposure_high`;
- `safety.option.<option_id>.coverage_sufficient`.

Exposição conhecida codifica predicado correspondente YES e outro NO; exposição
UNKNOWN codifica ambos UNKNOWN. Freshness original é preservado. Cobertura mantém
Truth/freshness recebidos. Todos usam ObservationSource.SAFETY_EVIDENCE, nunca
State.* ou uma nova categoria de fonte.

A saída inclui também os fatos originais de RiskAwarenessEvidence, sem relabeling.
Na regra NO, a Claim referencia os refs usados pela Claim de risco, exposure_high
e coverage_sufficient. Na regra YES, referencia o suporte do risco, exposure_low e
coverage_sufficient. UNKNOWN conserva os refs upstream e os três refs da opção.
Os refs são ordenados e únicos. Fatos upstream não relacionados ficam na auditoria,
mas não passam a ser dependências da Claim. UNKNOWN/STALE não relacionado não
apaga suporte independente fresco.

O risk_evidence_id é lineage, não fato usado como prova opaca. Não se cria um
ObservedFact para a conclusão de risco. A validação upstream checa estrutura,
referências e suporte conhecido/fresco para Claims definitivas; **não recalcula as
regras de ameaças** nem reinterpreta MISSING/NEARBY/AWAY. Uma evidência upstream
malformada é recusada; um risco UNKNOWN válido é preservado como incerteza.

Na composição, fatos mantêm SAFETY_EVIDENCE; safety.rule_ref mantém
EXPERT_HEURISTIC. A Condition de risco preserva seu próprio rule_ref, separadamente.
Para auditoria completa, conservar seed + risk + OptionSafetyEvidence + contexto.

## Reasons e rule refs

| OptionSafetyReason | Código |
|---|---|
| HIGH_EXPOSURE_WITH_INCREASED_RISK_AND_NO_COVERAGE | safety.option.high_risk_exposed_uncovered.v1 |
| LOW_EXPOSURE_WITH_LOW_RISK_AND_COVERAGE | safety.option.low_risk_low_exposure_covered.v1 |
| GLOBAL_RISK_UNKNOWN | safety.option.global_risk_unknown.v1 |
| GLOBAL_RISK_INCREASED_BUT_OPTION_MITIGATED | safety.option.increased_risk_mitigated.v1 |
| GLOBAL_RISK_LOW_BUT_OPTION_EXPOSURE_HIGH | safety.option.low_risk_high_exposure.v1 |
| OPTION_EXPOSURE_UNKNOWN | safety.option.exposure_unknown.v1 |
| OPTION_EXPOSURE_STALE | safety.option.exposure_stale.v1 |
| OPTION_COVERAGE_UNKNOWN | safety.option.coverage_unknown.v1 |
| OPTION_COVERAGE_STALE | safety.option.coverage_stale.v1 |
| INSUFFICIENT_OPTION_SAFETY_SUPPORT | safety.option.insufficient_support.v1 |

YES/NO usam a razão correspondente como rule_ref. UNKNOWN usa insufficient_support
como regra e acumula reasons específicos em ordem estável. Mitigated descreve apenas
LOW/cobertura YES frescos fornecidos, não uma certificação de segurança. Nenhum
texto voltado ao jogador é produzido.

## Binding e consumo

O builder exige igualdade entre seed_id solicitado, risk.seed_id e cada input.
Cada saída guarda o seed exato e upstream_risk_evidence_id.
`result.validate_binding(seed_id, risk)` recusa seed diferente e risco diferente,
mesmo se R1/R2 tiverem o mesmo valor Truth. Essa verificação deve ocorrer **antes**
de extrair Claim/facts para os contratos legados, e é realizada pelo helper dos
testes end-to-end.

FarmStrategicEvidence/DecisionContext legados não carregam upstream_risk_evidence_id.
Não é possível verificar R1/R2 neles depois que o chamador descartou o envelope.
Consumidores futuros devem usar validate_binding e conservar lineage. Não houve
mudança em decision.py ou farm_context para esconder esse limite. IDs verificam
consistência declarada, não autenticam autor/veracidade; objetos construídos
manualmente não são certificados como emitidos pelo builder upstream.

## Determinismo e composição offline

Opções ordenadas por option_id; fatos por ref; refs da Claim ordenados/únicos.
Identidade: ruleset + ':' + SHA-256 de asdict(resultado), sem evidence_id, JSON
sort_keys=True, separadores compactos, ensure_ascii=True, allow_nan=False, UTF-8.
Seed, opção/ação, upstream ID, fatos/freshness/fontes, Claim e reasons entram no hash.
Mesmos inputs e permutações sem significado produzem a mesma saída. Sem IO, rede,
ambiente, clock, random/UUID, cache, estado anterior ou mutação das entradas.

Somente testes fazem State -> adapter -> seed -> risk -> option safety -> composer
-> planner. Availability e Execution são fornecidos separadamente. Fatos comuns
upstream são deduplicados por ref e igualdade no helper; conflitos são recusados.
O builder não constrói OptionAssessment nem chama composer/planner.

Para risco YES, esta versão não produz safety YES para nenhuma opção. O cenário
wave NO -> farm seguro usa **evidência independente de farm**, explicitamente
fornecida pela fixture; a regra não deduz farm seguro a partir de wave insegura.
Availability desconhecida impede opção acionável mesmo quando safety YES; safety
UNKNOWN também impede ação segura quando availability YES.

O builder pode avaliar opções distintas da mesma categoria sem copiá-las entre si.
O composer/planner atual continua limitando uma opção por ação; seleção entre
várias rotas/camps da mesma categoria fica fora do escopo.

## Validação e isolamento

Gates uma vez cada: baseline completo, Option Safety, Safety Evidence, Farm Context,
Context Builder, Runtime Adapter, Farm Cycle e suíte completa. Sem retry-until-green.
Loopback canônico permitido; destinos externos bloqueados. 10053 conserva o contrato
HTTP legado; 10054 continua bloqueante.

Novos arquivos apenas: coach02/option_safety.py, tests/test_option_safety.py e este
documento. Nenhum arquivo existente modificado. Relatório, manifests e logs externos
em outputs/OPTION_SAFETY_V01_20260929. Sem Git novo ou artefatos anteriores reescritos.

Nada foi conectado a run/services/GSI/Policy/adapter/context/Safety/composer/planner/
vision. Sem Data Foundation, LLM/ML, dados reais de mapa, captura, tracking, partidas,
availability builder, arbiter, saída live ou adapter v0.2. Encerramento para revisão
humana, sem próxima etapa automática.
