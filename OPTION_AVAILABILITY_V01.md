# Option Availability v0.1 — Farm Resource Presence Core

Builder isolado de disponibilidade por presença/acesso fornecidos. Não avalia
segurança, risco, caminho, eficiência, tempo, respawn ou ação recomendada.

## Contratos

```python
results = build_option_availability(seed.seed_id, option_observations)
# Somente testes nesta etapa, antes de extrair Claims para o composer:
safe.validate_binding(seed.seed_id, risk)
available.validate_binding(seed.seed_id, safe.option_id, safe.action)
```

Entrada congelada FarmOptionAvailabilityObservation:

- seed_id: str não vazia, ID exato do DecisionContextSeed;
- option_id: str ASCII não vazia, letras/dígitos/underscore/hífen;
- action: Action, um dos PRODUCTIVE_ACTIONS existentes;
- resource_presence: Truth.YES / NO / UNKNOWN;
- presence_freshness: Freshness.FRESH / STALE;
- access_state: Truth.YES / NO / UNKNOWN;
- access_freshness: Freshness.FRESH / STALE.

`build_option_availability(seed_id: str,
options: tuple[FarmOptionAvailabilityObservation, ...]) -> tuple[OptionAvailabilityEvidence, ...]`.

A função recebe somente a identidade do seed, não suas dimensões ou snapshots.
Access significa que o chamador declarou o recurso acessível como opção sob este
contrato. Não significa caminho seguro, chegada a tempo, ausência de contestação
ou pathfinding validado. Não há coordenadas, creep count, camp IDs reais, timers,
ouro, geometria, hero/item logic ou Knowledge/Player content.

Mesma regra para TAKE_ONE_MORE_WAVE, LEAVE_TO_SAFE_FARM e
SAFE_RESOURCE_THEN_REEVALUATE. Action é identidade fornecida. IDs duplicados ou
enums malformados são recusados, sem coerção silenciosa. Tupla vazia retorna tupla
vazia; opções não fornecidas não são fabricadas.

Saída congelada OptionAvailabilityEvidence:

- evidence_id;
- seed_id;
- option_id;
- action;
- observations: tuple[ObservedFact, ...];
- availability: Claim;
- reasons: tuple[AvailabilityReason, ...];
- ruleset = `availability.option_presence.v1`.

Sem campos safety, risk, recommended_action, timers ou scores.

## Tabela e semântica

| Prioridade | Observações explícitas | availability |
|---|---|---|
| B | presence NO/FRESH OU access NO/FRESH | NO |
| A | presence YES/FRESH E access YES/FRESH | YES |
| C | Todo outro caso válido | UNKNOWN |
| D | Opção não fornecida | Nenhum objeto |

YES significa disponível sob a evidência estreita de presença/acesso; não significa
seguro, ótimo, recomendado, alcançável por rota segura ou vantajoso. NO significa
indisponibilidade explícita sob os dados fornecidos, não perigo, ausência permanente
ou inexistência na partida. UNKNOWN significa suporte insuficiente ou stale.

Um NO fresco domina outro fato UNKNOWN/STALE. Um NO stale não é ausência atual.
YES exige ambos conhecidos e frescos; nenhum unknown/stale pode virar YES.
Não se deduz a causa da indisponibilidade. Não há score, porcentagem, limiar temporal
ou lógica de respawn/wave/stack/Roshan.

## Fatos, suporte e provenance

Dois fatos por opção, com Truth/freshness originais preservados:

- `availability.option.<option_id>.resource_present`;
- `availability.option.<option_id>.accessible`.

Reutiliza ObservationSource.SAFETY_EVIDENCE como categoria observacional de domínio
de opções já usada pelo Alpha. Aqui sua semântica é **origem sintética/de domínio**,
não prova de segurança nem conclusão de risco. O namespace availability distingue
presença/acesso de safety.option e safety.threat. Nenhum dado é rotulado como
State ou RUNTIME_OBSERVATION; nenhum fato recebe EXPERT_HEURISTIC.

Essa reutilização é apropriada para os inputs fornecidos desta versão e evita
inventar uma categoria paralela ou modificar decision.py. Não afirma recebimento
real de GSI, visão ou RuntimeObservation. A derivação availability permanece
EXPERT_HEURISTIC + rule_ref no resolver existente.

A Claim NO referencia somente os fatos NO/FRESH que a sustentam; assim UNKNOWN ou
STALE do outro fato não dilui uma ausência explícita na composição. Ambos os fatos
continuam na saída para auditoria. YES referencia ambos; UNKNOWN referencia ambos.
Não se converte a conclusão availability em ObservedFact.

## Reasons e regras

| AvailabilityReason | Código |
|---|---|
| RESOURCE_PRESENT_AND_ACCESSIBLE | availability.option.present_and_accessible.v1 |
| RESOURCE_NOT_PRESENT | availability.option.not_present.v1 |
| RESOURCE_NOT_ACCESSIBLE | availability.option.not_accessible.v1 |
| RESOURCE_PRESENCE_UNKNOWN | availability.option.presence_unknown.v1 |
| RESOURCE_PRESENCE_STALE | availability.option.presence_stale.v1 |
| RESOURCE_ACCESS_UNKNOWN | availability.option.access_unknown.v1 |
| RESOURCE_ACCESS_STALE | availability.option.access_stale.v1 |
| INSUFFICIENT_AVAILABILITY_SUPPORT | availability.option.insufficient_support.v1 |

YES usa present_and_accessible. NO usa a primeira razão negativa na ordem presence,
access; quando ambos são NO/FRESH conserva as duas razões e os dois refs. UNKNOWN
usa insufficient_support como rule_ref e reasons específicos de unknown/stale.
Nenhum texto para jogador é gerado.

## Binding e composição somente em testes

O builder exige que seed_id solicitado coincida com cada input. Cada saída conserva
seed_id, option_id e action e os inclui na identidade determinística.
`validate_binding(seed_id, option_id, action)` recusa separadamente mismatches.
Não importa nem interpreta Option Safety. O chamador deve fornecer a identidade
do envelope com o qual pretende combinar a disponibilidade.

O helper de testes primeiro valida Safety contra seed/risco, depois Availability
contra seed/option_id/action de Safety. Só então extrai os fatos/Claims para
OptionAssessment(available=..., safe=...). Fatos compartilhados são deduplicados
por ref/igualdade; conflitos são recusados. Não há assembler de produção.

FarmStrategicEvidence/DecisionContext legados não conservam os envelopes completos.
Consumidores futuros devem validar antes de extraí-los e conservar seed + risk +
availability + safety + contexto para auditoria. A identidade verifica consistência,
não autentica veracidade. O builder não revalida elegibilidade do seed; o composer
existente continua responsável pelo seu gate, sem alteração.

Disponibilidade YES com safety UNKNOWN/NO não produz opção segura acionável;
safety YES com disponibilidade UNKNOWN/NO também não. Wave indisponível permite
farm disponível+seguro pela ordem já existente do planner. Todas indisponíveis não
fabricam ação segura. Essas cadeias são sintéticas, com planner explícito em testes.

## Determinismo e limites

Opções ordenadas por option_id; fatos por ref; reasons em ordem fixa. ID é ruleset
+ ':' + SHA-256 do JSON de asdict(resultado) sem evidence_id, sort_keys=True,
separadores compactos, ensure_ascii=True, allow_nan=False, UTF-8. Mesmos inputs,
mesmo resultado; permutação de opções não muda saída. Dataclasses congeladas,
tuplas, enums; nenhuma mutação de entrada, estado anterior, cache, clock, ambiente,
random/UUID, IO ou rede.

Não importa option_safety, safety_evidence ou farm_cycle. Não recebe risco, ameaça,
exposição, cobertura ou enemy state. Não calcula disponibilidade a partir de herói,
itens ou timing. Presença e acesso são fornecidos, não observabilidade real.
Freshness também é fornecido, sem TTL. Uma ação pode identificar várias opções no
builder, mas o composer atual conserva seu limite de uma opção por ação.

## Validação e preservação

Gates uma vez cada: baseline, Availability focal, Option Safety, Safety Evidence,
Farm Context, Context Builder, Runtime Adapter, Farm Cycle e suíte completa.
Sem retries. Rede externa bloqueada; HTTP localhost permitido. 10053 conserva
contrato legado; 10054 permanece bloqueante.

Novos arquivos somente: coach02/option_availability.py,
tests/test_option_availability.py e este documento. Nenhum arquivo anterior alterado.
Resultados/manifests externos em outputs/OPTION_AVAILABILITY_V01_20260929.
Sem Git inicializado, sem alteração de artefatos anteriores ou Data Foundation.

run/services/GSI/Policy/adapter/context/Safety/Option Safety/composer/planner/vision
não importam nem chamam o builder. Nenhuma Decision live. Sem Strategic Evidence
Assembly, scheduling, visão real, tracking, partida real, arbiter ou adapter v0.2.
Encerramento para revisão humana, sem etapa seguinte automática.
