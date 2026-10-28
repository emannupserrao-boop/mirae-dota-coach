# Safety Evidence Builder v0.1 — Risk Awareness Core

Pergunta única: existe suporte para risco de exposição aumentado? Não calcula
segurança de wave/rota, posição inimiga, probabilidade de gank, melhor ação ou destino.

```python
risk = build_risk_awareness(seed.seed_id, relevant_threats, coverage)
```

A função termina em RiskAwarenessEvidence. Não importa nem chama composer, planner,
runtime, visão ou saída. A associação ao composer ocorre somente nos testes desta
etapa, com avaliações de opções fornecidas separadamente.

## Entradas e binding

- seed_id: string não vazia obtida do DecisionContextSeed exato.
- threats: tupla de RelevantThreatObservation(threat_id, state, freshness).
- coverage: CoverageObservation(sufficient: Truth, freshness: Freshness).

ThreatState tem VISIBLE_NEARBY, VISIBLE_AWAY, MISSING e UNKNOWN. Relevância, NEARBY,
AWAY e suficiência de cobertura são explicitamente fornecidas pelo chamador. Não
há seleção de ameaças, coordenadas, distância, tempo de deslocamento, ward geometry,
MMR, herói, itens ou conteúdos de Knowledge/Player Model.

threat_id é identificador ASCII não vazio com letras, dígitos, underscore ou hífen.
IDs duplicados são recusados, não mesclados. Não há normalização silenciosa ou
colisões de namespace. Inputs usam enums e freshness explícitos, sem coerção de bool
ou strings. Tupla vazia de ameaças é válida e resulta em UNKNOWN.

O builder recebe apenas o ID do seed, sem acesso a suas dimensões ou snapshots.
RiskAwarenessEvidence conserva esse ID; FarmStrategicEvidence deve receber o mesmo
valor ao transportar o risco. O composer existente rejeita mismatch com o seed.
Esse vínculo não autentica a origem dos dados e não carrega conteúdo dos snapshots.

## Tabela qualitativa, ordem de precedência

| Prioridade | Condição fornecida | increased_risk |
|---|---|---|
| A | Alguma ameaça relevante VISIBLE_NEARBY e FRESH | YES |
| B | Sem A; alguma MISSING/FRESH e cobertura NO/FRESH | YES |
| C | Ao menos uma ameaça; todas VISIBLE_AWAY/FRESH e cobertura YES/FRESH | NO |
| D/E/F | Qualquer outro caso | UNKNOWN |

MISSING com cobertura YES é UNKNOWN, não NO. Cobertura não localiza um inimigo
ausente. UNKNOWN/STALE não viram ausência de risco. VISIBLE_AWAY com cobertura NO
também é UNKNOWN. Empty não significa seguro. Uma ameaça missing já é suficiente
para B; não existe limiar numérico de quantidade, score, peso, percentual ou TTL.

A tem precedência sobre incerteza e staleness não relacionados; B também pode
estabelecer suporte positivo independente se suas próprias dependências forem
frescas. C exige suporte forte de todos os inputs relevantes. Freshness é fornecido,
nunca calculado; localização antiga não é promovida a localização atual.

YES significa apenas risco aumentado suportado por esta heurística. Não significa
gank confirmado, inimigo vindo para cá ou morte certa. NO significa somente que o
ruleset estreito não sustenta risco aumentado sob aqueles inputs. **NO não é SAFE**
e não gera avaliação de segurança de wave/rota.

## Schema de saída e auditoria

RiskAwarenessEvidence é congelada e contém:

- evidence_id;
- seed_id;
- observations: tuple[ObservedFact, ...];
- increased_risk: Claim;
- reasons: tuple[RiskReason, ...];
- ruleset = `safety.risk_awareness.v1`.

Não há safe, lane_safe, route_safe, wave_safe, gank_probability ou recommended_action.

Cada ameaça gera três fatos booleanos auditáveis:

- `safety.threat.<id>.visible_nearby`
- `safety.threat.<id>.visible_away`
- `safety.threat.<id>.missing`

Para categoria conhecida, seu predicado é YES e os demais NO, conservando freshness.
Para UNKNOWN, todos os predicados são UNKNOWN. Coverage gera
`safety.coverage.sufficient`, com Truth/freshness intactos. Isso codifica o estado
fornecido, sem inferir posição, segurança ou rota. Nenhum ref começa por State.*.

Todos os fatos, inclusive desconhecidos e stale, são preservados. A Claim positiva
de A referencia somente os predicados NEARBY frescos; B referencia MISSING frescos
e cobertura; C referencia todos os AWAY e cobertura. Assim, o resolver conservador
existente não dilui um trigger positivo independente com suporte irrelevante
UNKNOWN/STALE. Claims UNKNOWN conservam referências a todos os fatos disponíveis.

## Reasons e regras

RiskReason fornece identificadores estáveis:

| Nome | Código |
|---|---|
| VISIBLE_RELEVANT_THREAT | safety.risk.visible_relevant_threat.v1 |
| MISSING_THREAT_WITHOUT_COVERAGE | safety.risk.missing_without_coverage.v1 |
| ALL_RELEVANT_THREATS_VISIBLE_AWAY_WITH_COVERAGE | safety.risk.all_away_with_coverage.v1 |
| MISSING_THREAT_WITH_COVERAGE | safety.risk.missing_with_coverage.v1 |
| THREAT_INFORMATION_UNKNOWN | safety.risk.threat_unknown.v1 |
| THREAT_INFORMATION_STALE | safety.risk.threat_stale.v1 |
| COVERAGE_UNKNOWN | safety.risk.coverage_unknown.v1 |
| COVERAGE_STALE | safety.risk.coverage_stale.v1 |
| NO_RELEVANT_THREAT_EVIDENCE | safety.risk.no_threat_evidence.v1 |
| INSUFFICIENT_RISK_SUPPORT | safety.risk.insufficient_support.v1 |

A/B/C usam o código correspondente como Claim.rule_ref. UNKNOWN usa
insufficient_support.v1 e razões específicas adicionais. Nenhum texto de conselho
é produzido. Regras são EXPERT_HEURISTIC v0.1, não verdade universal de Dota.

## Extensão mínima de provenance e compatibilidade

O Source existente permanece com seus quatro membros. Um teste legado exige que
uma decisão antiga cubra exatamente set(Source); acrescentar um membro àquele enum
quebraria o contrato/teste que esta tarefa exige preservar sem edição.

Foi acrescentado **ObservationSource.SAFETY_EVIDENCE**, uma extensão fechada sem
duplicar categorias runtime/knowledge/player/heuristic. Provenance.source e
ObservedFact.source aceitam a união tipada. ObservedFact permite exatamente:

- Source.RUNTIME_OBSERVATION — default das chamadas antigas de três argumentos;
- ObservationSource.SAFETY_EVIDENCE — uso explícito dos fatos Safety.

KnowledgeSnapshot, PlayerModel e ExpertHeuristic não são aceitos como fontes de
ObservedFact; strings arbitrárias também não. ScalarObservation continua permitindo
somente runtime, sem modificação. Não há registro dinâmico/arbitrary-source.

build_context agora usa f.source ao gerar provenance de evidência. A Claim ainda
recebe EXPERT_HEURISTIC + rule_ref. Essa é a única mudança na resolução; freshness,
Truth, lookup, missing support, options e Execution continuam iguais. O composer
não foi modificado, pois já transporta ObservedFact sem reclassificá-lo.

Fatos Safety produzidos aqui são conversões de inputs explícitos/sintéticos do
domínio, não recebimento real de State/GSI nem visão. Sua origem SAFETY_EVIDENCE
permanece distinta do suporte runtime das opções fornecidas em fixtures.

Compatibilidade é de construtor, semântica e resolução. **asdict(ObservedFact)
ganha source**; hashes de contextos/decisões que serializam esses fatos são
recalculados com essa informação adicional e não se promete identidade binária
com IDs pré-extensão. IDs de adapter/seed, que usam escalares, não mudam. Nenhum
arquivo antigo de testes foi alterado. Diff e hashes estão no relatório externo.

O fallback legado para ref ausente continua sendo um placeholder UNKNOWN/STALE
com default runtime; isso não é evidência recebida. O builder inclui todos os refs
que emite nas suas Claims, portanto fatos Safety presentes preservam fonte exata.
Inferir fonte de fatos ausentes pelo prefixo seria uma regra nova não implementada.

## Determinismo e imutabilidade

O ID é ruleset + ':' + SHA-256 do JSON da dataclass sem evidence_id: chaves ordenadas,
separadores compactos, ensure_ascii=True, allow_nan=False, UTF-8. Ameaças são
ordenadas por threat_id; fatos por ref. Mesmos inputs em ordem diferente produzem
saída e ID iguais. Binding, valores, freshness, fonte, reasons e Claim participam
da identidade. Dados opcionais irrelevantes à regra ainda permanecem auditáveis.

Sem IO, rede, clock, ambiente, UUID, processos, cache ou frame anterior. Tipos
congelados, tuplas e enums; nenhuma entrada mutada. Nenhum conteúdo externo lido.

## Compatibilidade de composição — somente testes

Os testes criam State -> adapter -> seed -> RiskAwarenessEvidence. Depois combinam
os fatos/Claim de risco com opções de farm/recurso curto fornecidas separadamente,
chamam compose_farm_context e, explicitamente no teste, farm_cycle.plan.

- Risco YES sem rota justificável: NO_DIRECTIVE / AWARENESS.
- Risco UNKNOWN com recurso curto seguro explicitamente fornecido: ação produtiva
  continua possível segundo o planner existente.
- Risco YES sozinho não produz LEAVE_TO_SAFE_FARM; essa opção só aparece quando sua
  disponibilidade e segurança forem fornecidas independentemente.

Não há produção automática de FarmStrategicEvidence ou chamada ao planner no builder.
Não há Safety Builder conectado a GSI, visão ou serviço. Nenhuma geometria/template
ou real-match test foi implementado.

## Validação e encerramento

Gates, cada um uma vez: baseline completo, Safety focal, Farm Context, Context
Builder, Runtime Adapter, Farm Cycle e regressão completa. Rede externa proibida,
loopback legado permitido. 10053 conserva seu contrato restrito; 10054 permanece
bloqueante. Sem retries.

Novos arquivos: safety_evidence.py, test_safety_evidence.py e este documento.
Único existente alterado: decision.py, para a extensão de provenance descrita.
Evidências externas: outputs/SAFETY_EVIDENCE_V01_20260929.
Próximas etapas dependem de revisão humana, sem início automático.
