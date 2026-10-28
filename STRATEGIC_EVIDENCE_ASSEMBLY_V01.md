# Strategic Evidence Assembly v0.1

Montagem pura e determinística de envelopes já emitidos. Valida consistência de
identidades, suporte e fatos; não deriva risco, segurança, disponibilidade ou ação.

## Interface e schemas

```python
assembly = assemble_farm_evidence(seed, risk, safety, availability, execution)
# Passos explícitos, somente em testes nesta etapa:
context = compose_farm_context(seed, assembly.strategic_evidence, assembly.execution)
decision = farm_cycle.plan(context)
```

Argumentos:

- seed: DecisionContextSeed real, autoridade de binding;
- risk: RiskAwarenessEvidence;
- safety: tuple[OptionSafetyEvidence, ...];
- availability: tuple[OptionAvailabilityEvidence, ...];
- execution: Execution fornecida explicitamente.

FarmOptionEvidencePair congelado contém option_id, action, availability completo e
safety completo. FarmEvidenceAssembly congelado contém assembly_id, seed_id, risk
completo, option_pairs, strategic_evidence: FarmStrategicEvidence, execution e
ruleset = `strategic.farm_evidence_assembly.v1`.

Não se guardam apenas Claims ou IDs dos envelopes. Após compor DecisionContext,
assembly continua permitindo consultar risco, safety/availability de cada opção,
refs/reasons/rulesets e execução usados. O chamador conserva também o seed real
para consultar suas dimensões e referências de snapshots; assembly guarda seed_id.

## Pareamento exato e rejeições

1. Exige RiskAwarenessEvidence.seed_id == seed.seed_id.
2. Recusa option_id duplicado dentro de cada coleção, mesmo envelope idêntico.
3. Exige os mesmos option_ids nas duas coleções. Órfãos causam
   unpaired_option_safety ou unpaired_option_availability; nenhum é descartado.
4. Para cada candidato localizado por option_id, antes de extrair Claims, chama:
   safety.validate_binding(seed.seed_id, risk) e
   availability.validate_binding(seed.seed_id, safety.option_id, safety.action).
5. Só aceita o par quando seed, option_id, action e vínculo upstream de risco
   correspondem. option_id é índice de busca, não critério suficiente de aceitação.
   Posição de tupla e ação isolada não pareiam envelopes.
6. Recusa múltiplos option_ids para a mesma ação:
   multiple_options_per_action_not_supported. Não seleciona rota/camp.

Coleções vazias de ambos os lados são válidas. A montagem contém risco e zero opções.
Ações são somente PRODUCTIVE_ACTIONS já aceitas. Não há ranking ou escolha de ação.
Ordenação por option_id serve somente à representação canônica.

## Fatos, suporte e Claims

O assembler valida tipo/imutabilidade estrutural dos envelopes, metadata de
identidade, tuplas de ObservedFact e referências de Claims. Em seguida:

- risco deve ter cada evidence_ref em suas próprias observations;
- safety pode referenciar suas observations ou as observations do risco aceito;
- availability deve ter cada ref em suas próprias observations;
- nenhuma opção pode preencher suporte ausente de outra opção;
- Claims sem refs permanecem como recebidas; o resolver legado continua decidindo
  se existe suporte suficiente, sem promoção automática pelo assembler.

Não se recalculam regras MISSING/NEARBY/AWAY, exposição/cobertura ou presença/acesso.
Os validate_binding existentes são reutilizados conforme o contrato; Safety faz
também sua validação já aceita do suporte upstream. Isso não é uma segunda
implementação das regras de risco.

Fatos são mesclados na ordem risco, safety, availability. Mesmo ref só é deduplicado
se ObservedFact for integralmente igual (ref, Truth, freshness, source). Qualquer
diferença gera conflicting_observation_ref, inclusive dentro de um envelope.
Não há first/last-write-wins para conteúdo diferente. O conjunto final é ordenado
por ref, sem modificar os envelopes de origem.

Para cada par, cria exatamente:

```python
OptionAssessment(pair.option_id, pair.action,
                 pair.availability.availability, pair.safety.safety)
```

FarmStrategicEvidence usa seed.seed_id, fatos mesclados, assessments e exatamente
risk.increased_risk. As três Claims são os mesmos objetos recebidos: nenhum valor,
rule_ref, evidence_ref ou fonte é reescrito. Assembly.ruleset identifica montagem,
nunca uma origem de verdade estratégica.

## Elegibilidade, execução e provenance

Não revalida elegibilidade, não carrega Knowledge/Player content e não interpreta
dimensões do seed. compose_farm_context continua responsável por eligibility e
consistência do seed. A montagem pode existir para seed inelegível, mas o composer
o recusa. Binding não autentica veracidade dos dados.

Execution NOT_STARTED/IN_PROGRESS é preservada por identidade, sem inferência de
movimento, rota ou ação. plan_id mutável é recusado. Rota ativa ausente das opções
não é inventada: downstream mantém seu comportamento conservador.

Fatos SAFETY_EVIDENCE e RUNTIME_OBSERVATION conservam fonte original. Claims
conservam EXPERT_HEURISTIC através do resolver e seus rule refs upstream. Não há
nova fonte estratégica criada pelo assembler.

**Dívida de nomenclatura para Offline Core Gate:** Option Availability ainda usa
ObservationSource.SAFETY_EVIDENCE para fatos sintéticos/de domínio. Essa etiqueta
não significa conclusão de segurança. Foi preservada, sem rename/refactor.

## Identidade e imutabilidade

assembly_id = ruleset + ':' + SHA-256 do JSON canônico de asdict(assembly), excluindo
assembly_id. Inclui seed_id, envelopes completos com seus evidence_ids, option_id,
action, Claims/fatos/reasons, strategic_evidence e execution state/plan_id.

option_pairs/assessments são ordenados por option_id; fatos mesclados por ref. Na
cópia usada exclusivamente pelo hash, observations internas são ordenadas por ref.
Assim, permutar coleções de entrada não altera resultado; permutar fatos de um
envelope não altera assembly_id. Envelopes completos são conservados como recebidos.
Ordem dos evidence_refs/reasons de uma Claim é preservada, não reinterpretada.

JSON: sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False,
UTF-8. Conteúdo completo é incluído para que uma mudança significativa seja visível
mesmo se um envelope manual conservar indevidamente o mesmo evidence_id. Isso não
autentica hash/autoria upstream. Sem clock, UUID/random, ambiente, IO, rede, cache,
estado anterior ou globais mutáveis. Dataclasses congeladas e tuplas.

## Pipeline offline e fixtures independentes

Os novos testes não constroem OptionAssessment/FarmStrategicEvidence nem mesclam
fatos manualmente. Eles chamam State -> adapter -> seed -> Risk Awareness -> Option
Safety -> Option Availability -> assembler -> composer -> planner -> Decision.

Cobrem wave segura, farm seguro quando wave não se justifica, espera produtiva com
recurso curto, risco sem rota, UNKNOWN, mudança de rota ativa para unsafe, opções
indisponíveis/inseguras, órfãos, mismatches, colisões, limite por ação e empty.

O ruleset Option Safety v0.1 não produz YES quando risco é YES/UNKNOWN. Para os
cenários exigidos de farm/recurso curto **independentemente seguros**, o teste
fornece OptionSafetyEvidence explícita, marcada fixture.independent_option_safety.v1
em ID/ruleset/reasons/rule_ref, com fato próprio e vínculo ao risco exato. Não é
apresentada como saída do builder v0.1, nem como segurança real verificada. O
assembler verifica estrutura/binding, não decide se essa heurística é verdadeira.

Helpers manuais das suítes anteriores permanecem intactos para preservar os testes
aceitos. O novo pipeline substitui sua necessidade por assemble_farm_evidence; não
foi feito refactor dos arquivos anteriores.

## Isolamento e entrega

Adições somente: coach02/strategic_evidence.py, tests/test_strategic_evidence.py,
STRATEGIC_EVIDENCE_ASSEMBLY_V01.md. Zero arquivos existentes modificados.
O módulo não chama composer/planner/builders; apenas valida envelopes, monta tipos
e calcula identidade. Nenhum caminho live o importa ou chama.

Gates uma vez cada: baseline, Strategic Evidence, Availability, Option Safety,
Safety Evidence, Farm Context, Context Builder, Runtime Adapter, Farm Cycle e full.
Sem retries. HTTP localhost permitido; rede externa bloqueada. Contrato 10053
intacto; 10054 bloqueante. Resultados/manifests externos em
outputs/STRATEGIC_EVIDENCE_ASSEMBLY_V01_20260929.

Sem Data Foundation, nova regra de gameplay, visão, scheduling, ranking, rota,
saída de coaching ou Decision live. Sem Git inicializado ou artefatos reescritos.
Encerrado para revisão humana; Offline Core Gate não iniciado automaticamente.
