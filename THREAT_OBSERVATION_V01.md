# Threat Observation v0.1 — Explicit Sighting Semantics + Exact Temporal Binding

## Escopo

Este componente vincula uma classificação de sighting explicitamente fornecida pelo caller a uma ocorrência exata de Observation Event e a uma avaliação do Temporal Evidence. Não é um detector real de Dota e não escolhe se uma ameaça é relevante.

ThreatProximity contém SOMENTE NEARBY e AWAY. Não contém MISSING, UNKNOWN, DEAD, INVISIBLE, SAFE ou DANGEROUS. Sem sighting suportado não existe ThreatObservation. Silêncio, ausência de claim e STALE nunca criam MISSING.

NEARBY/AWAY são alegações explícitas do upstream, não distâncias calculadas. O componente valida bindings e preserva metadados; não comprova a verdade da alegação. Não acessa GSI, imagem, minimapa, coordinates, pathfinding, hero, itens, dano, mobilidade, TP, objetivo, score, role ou matchup.

## Contratos

Todos os outputs construídos e claims são frozen dataclasses; coleções são tuples.

| Contrato | Campos |
|---|---|
| ThreatSightingClaim | threat_id, ref, proximity, temporal_policy_id |
| ThreatObservation | threat_id, ref, proximity, source_id, observed_tick, temporal_status, last_observed_tick, age_ticks, temporal_policy_id, max_age_ticks |
| ThreatObservationSnapshot | timeline_id, event_id, projection_id, tracker_state_id, temporal_snapshot_id, selected_clock_id, selected_tick, evaluated_at_tick, observations |

O ID é propriedade determinística snapshot_id; propriedades não entram em asdict, portanto uma futura exportação deve incluí-lo explicitamente se necessário.

Identidades do claim exigem str exata, não vazia nem somente whitespace, consistente com Temporal Evidence. Strings válidas não são aparadas nem reinterpretadas; por exemplo, espaços que acompanham um texto válido continuam no identificador. Proximity deve ser instância do enum, não string equivalente. Claims exigem tuple; listas e elementos de tipo errado são rejeitados.

**ACCEPTED_V01_LIMITATION:** one semantic sighting claim per threat_id per ThreatObservationSnapshot. IDs repetidos falham, mesmo se claims forem idênticos ou tiverem refs/políticas diferentes. Não há escolher primeiro/último, nearest/latest ou reconciliar sinais. Vários threat_ids distintos são aceitos e ordenados por (threat_id, ref, temporal_policy_id).

## Builder e linhagem exata

API: `build_threat_observations(event, projection, temporal_snapshot, claims)`.

Exige tipos concretos ObservationEvent, TemporalProjection, TemporalSnapshot e ThreatSightingClaim. Valida:

1. projection.event_id = event.event_id.
2. projection.timeline_id = event.timeline_id.
3. projection.source_id = event.source.source_id.
4. projection.refs = event.refs, canonicalmente.
5. temporal_snapshot.timeline_id = event.timeline_id.
6. temporal_snapshot.clock_id = projection.selected_clock_id.
7. evaluated_at_tick >= selected_tick, com tick int exato.
8. O clock/tick selecionado realmente corresponde ao source_stamp ou receipt_stamp do evento conforme a base explícita da projeção. Uma projeção manual com tick inventado é rejeitada; não há projeção nova ou seleção automática de política.

Para cada claim, ref deve ter sido emitida pelo evento. Lookup é pela chave EXATA (ref, temporal_policy_id). Zero matches falham; chaves ambíguas falham. NEVER_SEEN selecionado falha explicitamente. Exige last_observed_tick == projection.selected_tick, não apenas <=. Tanto ocorrência mais antiga quanto renovação mais recente são rejeitadas.

Campos de entrada temporal são verificados defensivamente: tuple de TemporalEvidenceStatus, enum correto, refs/políticas válidas, limites inteiros não negativos, chaves únicas, policy_id sem limiares conflitantes. Para a entrada selecionada, last_observed_tick/age_ticks exigem int exato e age_ticks = evaluated_at_tick - last_observed_tick. Erro não altera nenhum input nem produz saída parcial.

Não calcula um TTL e não escolhe política. O status FRESH/STALE é copiado da saída recebida do Temporal Evidence; não há reclassificação estratégica nem uma segunda implementação do classificador TTL. Espera-se que o snapshot seja produzido pela API aceita de Temporal Evidence. A validação de binding não autentica objetos manualmente fabricados: não recebe o tracker inteiro para reconstituir tracker_state_id nem refaz o cálculo autoritativo de status/TTL.

O temporal_snapshot_id adicional vincula todo o envelope temporal fornecido, preservando mais auditoria além do tracker_state_id. O caller deve guardar os envelopes upstream completos; os hashes não reconstroem seus conteúdos.

## STALE e ausência de claim

NEARBY/STALE significa apenas que houve uma classificação explícita de NEARBY naquela ocorrência e ela não é atual sob a política informada. Não significa que a ameaça continua perto, moveu-se, desapareceu, morreu ou oferece perigo agora. AWAY/STALE igualmente preserva só a classificação histórica.

Nenhum ramo transforma STALE em MISSING. Ausência de claim não é falta de inimigos ou segurança. claims=() gera snapshot vazio válido após a validação da linhagem. Nada gera zero risk, safe ou ausência de ameaças.

## Contaminação entre eventos e limites de identidade

Evento A ref=r, tick100; evento B mesma ref, tick110. Se Temporal agora informa last_observed_tick110, tentar usar esse snapshot para a claim de A falha. A não recebe a freshness de B. B, com seu próprio envelope e ocorrência110, pode ser validado.

A exatidão é a definida pelos contratos atuais: ref + policy_id + clock/timeline + timestamp de ocorrência. Temporal Tracker não guarda event_id nem source_id por mark. Dois eventos que reportem a mesma ref no mesmo tick dentro da mesma timeline/clock não podem ser distinguidos apenas por esse mark. O output ainda preserva o event_id/projection_id específico informado. Event uniqueness no mesmo tick e autenticidade da fonte não são garantidos; resolver isso exigiria um contrato futuro, sem alterar Temporal aqui.

O vínculo threat_id -> ref é explicitamente fornecido na claim. Não há parser que descubra a identidade de uma ameaça dentro da ref. Cada claim seleciona somente sua chave, nunca a entrada de outra ref/política como fallback. IDs distintos podem declarar a mesma ref explicitamente; o builder não inventa uma relação de exclusividade não presente no envelope. A correção semântica dessa associação pertence ao upstream.

## Identidade e determinismo

Ruleset: `threat.explicit_sighting.v1`.

snapshot_id = ruleset:snapshot:SHA-256 de asdict(snapshot), com JSON sort_keys=True, separators compactos, ensure_ascii=True, UTF-8. Inclui event_id, projection_id, tracker_state_id, temporal_snapshot_id, timeline, clock/ticks e todas as observações/políticas/idades/statuses ordenadas.

Ordem das claims não altera output nem ID. Mudanças relevantes de identidade, proximity, evento, política de projeção, tracker, avaliação ou status alteram o ID. Nenhum relógio, UUID, random, PID ou endereço de memória. Não há estado entre chamadas, cache, singleton, IO ou side effects.

## Compatibilidade de Safety SOMENTE EM TESTES

Os símbolos existentes inspecionados são `RelevantThreatObservation(threat_id, state, freshness)`, `ThreatState.VISIBLE_NEARBY`, `ThreatState.VISIBLE_AWAY`, `Freshness.FRESH` e `Freshness.STALE`.

Apenas o teste faz conversão explícita NEARBY->VISIBLE_NEARBY, AWAY->VISIBLE_AWAY, FRESH->FRESH e STALE->STALE. Não há mapping para MISSING. A cadeia de fixture chama explicitamente ObservationEvent -> project_event_time -> record_observations -> evaluate_freshness -> build_threat_observations -> helper de teste.

Esse helper NÃO decide relevância, mesmo que o contrato destino se chame RelevantThreatObservation. Demonstra somente compatibilidade de representação com IDs aceitos pelo downstream. Safety tem uma validação de threat_id mais restrita (ASCII alfanumérico/_/-); IDs opacos válidos aqui podem ser rejeitados pelo downstream. O teste mostra essa rejeição, sem normalizar IDs ou alterar Safety.

Produção importa somente stdlib (dataclasses, enum, hashlib, json) e os contratos de observation_event/temporal_evidence. Não chama project_event_time, record_observations, evaluate_freshness ou construtores de Safety/Decision. Nenhum módulo aceito ganha dependência reversa de threat_observation.

## Testes e preservação

84 métodos novos: requisitos01–70, adversariais A–H nos métodos71–78, e seis verificações adicionais79–84. Incluem mixed freshness por políticas explícitas, ambiguidade de keys, snapshots malformados, stamp forjado, inputs imutáveis, lineage e limites do helper downstream. Estímulos são sintéticos, offline, sem observação real.

O baseline canônico460 passou uma vez em main antes da criação de `feature/threat-observation-v0.1`, a partir de ceb15b96d476fa0ca77ef23b5a639077463ea7e3. As mudanças da implementação inicial foram somente arquivos novos nessa branch. Na implementação inicial bloqueada, main, tags,76 arquivos anteriores e18 hashes aceitos foram preservados. Na retomada de aceitação, a manutenção autorizada de duas guardas altera somente os dois testes legados:16 dos18 artefatos originais permanecem idênticos; os dois novos hashes de testes são registrados externamente, sem alterar produção. Nenhum merge, tag, remote, push ou PR é realizado. Resultados efetivos dos gates ficam no pacote externo THREAT_OBSERVATION_V01_20260930.

## Limitações e bloqueadores para etapas futuras

**BLOCKER_BEFORE_REAL_OBSERVATION:** real source of NEARBY/AWAY classification is not yet implemented. Não há coordenadas/distância/zona/travel-time nem detector GSI/visão.

**BLOCKER_BEFORE_LIVE_RISK_INTEGRATION:** real threat relevance policy/source is not implemented. Não conhece capacidade de matar o carry, TP, mobilidade/global spells, power spikes, itens, papel, objetivo ou matchup.

Outros limites aceitos: um evento por build, uma claim por threat_id, sem agregação multi-source/multi-sinal, sem lógica de ausência/MISSING, sem coverage, sem risk/safety/availability/recommendation, sem scores ou confiança. Fonte, verdade da claim, clock live, timestamps, políticas e ownership de timeline continuam externos. Imutabilidade é a de frozen dataclasses/tuples, não proteção contra reflexão deliberada.

Não iniciar observer real, live orchestration ou Shadow Mode. Encerrar para revisão humana.

## Manutenção autorizada das guardas

Two legacy dependency guards were updated to permit the explicitly authorized downstream contract dependency from Threat Observation while preserving reverse/live dependency prohibitions.

Somente coach02/threat_observation.py recebe autorização para importar os contratos especificados. Funções de orquestração continuam proibidas; nenhum arquivo de produção foi alterado. Os resultados da retomada e a classificação16/18 preservados +2 testes mantidos são registrados no pacote externo THREAT_OBSERVATION_GUARD_REPAIR_V01_20260930.
