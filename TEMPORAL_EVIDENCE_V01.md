# Temporal Evidence Tracker v0.1 — Explicit Freshness State

## Escopo e autoridade

Este componente responde somente: quando uma referência foi explicitamente observada e, sob uma política explícita, ela está FRESH, STALE ou NEVER_SEEN no tick informado?

O caller fornece ocorrência, timeline, domínio de relógio, tick e política. O tracker não observa o jogo. Não armazena o valor semântico da ocorrência. `enemy_mid.visible_away` é uma string opaca: registrar essa ref não demonstra que alguém permaneceu longe, ficou missing ou oferece risco.

Silêncio apenas envelhece a ocorrência conhecida. Não produz MISSING, ausência, indisponibilidade, perigo, segurança, morte ou movimento. STALE não é evidência atual. FRESH certifica apenas idade dentro do limite fornecido; não certifica verdade, confiabilidade da fonte ou utilidade estratégica.

A temporalidade fica fora do Offline Decision Core v0.1 congelado. Nenhum arquivo anterior é alterado. Nenhum consumidor de produção importa este módulo. Não há integração com Service, GSI, Policy, visão, Data Foundation, OpenDota, construtores estratégicos ou planner.

## Contratos imutáveis

Todos os contratos são dataclasses frozen; coleções são tuples. Não existe singleton, cache global, estado entre chamadas ou previous frame oculto.

| Contrato | Campos |
|---|---|
| ObservationMark | ref, last_observed_tick |
| TemporalTrackerState | timeline_id, clock_id, last_tick opcional, marks |
| FreshnessPolicy | policy_id, max_age_ticks |
| TemporalQuery | ref, policy |
| TemporalEvidenceStatus | ref, status, last_observed_tick opcional, age_ticks opcional, policy_id, max_age_ticks |
| TemporalSnapshot | timeline_id, clock_id, evaluated_at_tick, tracker_state_id, entries |

`state_id` e `snapshot_id` são propriedades determinísticas calculadas, sem campo de ID fornecido pelo chamador que possa divergir do conteúdo. Ao exportar com `dataclasses.asdict`, incluir explicitamente essas propriedades se o formato de auditoria precisar delas; `asdict` inclui somente os campos das dataclasses.

Somente occurrence/time metadata é retido. Nenhum Truth, ThreatState, risco, safety, availability, hero, item, route, action ou recommendation é armazenado. A política não pertence aos marks: a mesma ocorrência pode ser consultada sob diferentes políticas.

## APIs e ciclo de vida

`new_temporal_state(timeline_id, clock_id)` cria sempre marks vazios e last_tick=None. Os IDs são strings opacas não vazias/não somente whitespace. Não são interpretados nem aparados. O tracker não lê State.match_id nem RuntimeObservation e não detecta automaticamente mudança de sessão. O chamador deve criar um novo estado vazio para uma nova timeline, sem copiar marks antigos.

`record_observations(state, refs, tick)` valida todo o lote e retorna um NOVO estado imutável. O estado anterior permanece intacto, inclusive em erro. Refs são strings opacas não vazias/não somente whitespace; o conteúdo não é normalizado. A ordenação por ref canonicaliza o conjunto. Duplicatas em um lote são rejeitadas explicitamente. Refs precisam ser tuple; listas e objetos semânticos são recusados. Reobservação atualiza apenas as refs fornecidas. Todas as refs do lote recebem o mesmo tick.

Tick deve ser int exato (bool e float são recusados). Ticks negativos e iguais são válidos; a unidade se chama tick, sem compromisso com segundos ou milissegundos. Tick menor que state.last_tick é erro, em record e evaluate. Não há reset automático. Construtores também validam marks únicos, imutáveis e nunca posteriores a last_tick.

Lote vazio `record_observations(state, (), tick)` avança apenas last_tick, sem criar ocorrências nem alterar seus timestamps. Esse é o mecanismo explícito de registrar progresso da timeline durante silêncio.

`evaluate_freshness(state, tick, queries)` é uma consulta pura: não avança last_tick nem retorna um estado atualizado. A checagem de monotonicidade usa o last_tick do estado recebido. Avaliações sucessivas não criam um high-water mark oculto. O caller deve reter o estado retornado por record e avançar com lote vazio quando precisar impedir consultas anteriores ao último tick avaliado. Reutilizar uma versão antiga do estado representa consultar aquele snapshot histórico, não atualizar a timeline atual. Não há proteção contra o caller deliberadamente reconstruir ou reutilizar estados antigos.

Exemplo completo com progresso explicitamente retido (ticks e política sintéticos, sem recomendação de TTL para Dota):

```python
from coach02.temporal_evidence import (
    FreshnessPolicy, TemporalQuery, new_temporal_state,
    record_observations, evaluate_freshness,
)
state = new_temporal_state('session-A', 'validated-clock-contract')
state = record_observations(state, ('observer.example',), tick=100)
policy = FreshnessPolicy('example-policy-v1', max_age_ticks=10)
queries = (TemporalQuery('observer.example', policy),)
state = record_observations(state, (), tick=111)
result = evaluate_freshness(state, tick=111, queries=queries)
# STALE; last observed=100, age=11; nada se conclui sobre o jogo.
# A próxima operação nesta timeline deve receber este state, não uma cópia antiga.
```

## Política e consultas

Nenhuma política/TTL padrão existe em produção. `policy_id` é string opaca válida; max_age_ticks é int exato >=0; bool é recusado. A política é obrigatória na query. Não há limiar por prefixo, hero, role, fonte ou tipo de evidência.

Para uma ref conhecida, age_ticks = evaluated_at_tick - last_observed_tick:

- age_ticks <= max_age_ticks: FRESH, inclusive na fronteira.
- age_ticks > max_age_ticks: STALE.
- TTL zero: FRESH somente no mesmo tick.
- Ref jamais observada: NEVER_SEEN, last_observed_tick=None e age_ticks=None; sem zero, infinito ou STALE inventado.

Pode-se consultar apenas parte dos marks, refs nunca vistas ou nenhuma ref. Entries são ordenadas por (ref, policy_id). Diferentes políticas podem consultar a mesma ref; a chave (ref, policy_id) duplicada é recusada. Em uma avaliação, policy_id deve ter um único max_age_ticks em todas as queries; limiares conflitantes são erro. Entre snapshots é permitido fornecer uma política revisada; o limiar participa integralmente do ID. Versionar policy_id quando o contrato mudar é responsabilidade do caller.

Sob a MESMA política e ticks NÃO DECRESCENTES, uma ocorrência STALE não fica FRESH sem nova observação. Uma política explicitamente mais permissiva pode reclassificar a MESMA idade; isso é reavaliação, não renovação da ocorrência. Da mesma forma, consultar um estado histórico não é progresso da timeline. O tracker não escolhe, altera ou relaxa políticas automaticamente.

## Identidades e auditoria

Ruleset: `temporal.explicit_freshness.v1`.

IDs são `ruleset:state:SHA-256` e `ruleset:snapshot:SHA-256`. O hash usa JSON canônico com sort_keys=True, separators compactos, ensure_ascii=True e UTF-8. Não usa relógio, UUID, random, processo ou ambiente.

State ID inclui timeline_id, clock_id, last_tick e todos os marks/ref/ticks ordenados. Snapshot ID inclui timeline_id, clock_id, tick avaliado, state_id e entries completas (ref, status, timestamps/idade e identidade/limiar da política). Assim, uma ocorrência não consultada ainda muda o binding do snapshot quando muda o estado; a ausência de consulta não apaga a ocorrência.

A ordem de refs no mesmo lote e a ordem de queries não mudam IDs. Mesmo tick com o mesmo conjunto de ocorrências é idempotente por conteúdo, embora record retorne outro objeto. Modificar tempo, timeline, clock, ref ou política muda a identidade pertinente. IDs são integridade/reprodutibilidade por conteúdo, não autenticação de origem.

## Compatibilidade sem integração

O teste contém uma conversão EXPLÍCITA e apenas de demonstração: TemporalStatus.FRESH -> Freshness.FRESH; TemporalStatus.STALE -> Freshness.STALE. NEVER_SEEN provoca erro e não converte silenciosamente para nenhum deles. Nenhuma função de integração/conversão é adicionada à produção; o enum existente permanece byte-for-byte preservado.

O módulo temporal importa apenas dataclasses, enum, hashlib e json. O core e caminhos live não o importam. O caller detém estado e snapshots; não existe persistência, thread, lock, scheduler, expiração automática, garbage collection de marks ou transmissão.

## Testes e limites da certificação

`tests/test_temporal_evidence.py` contém 50 métodos: 38 requisitos focais, 6 cenários adversariais A–F e 6 grupos adicionais de validação/limitações. Todas as observações/ticks são sintéticos.

Cenários: 100->110 FRESH/111 STALE; reobservação em 108 e consulta115 FRESH; STALE120 e reobservação121 FRESH; unrelated NEVER_SEEN; nova timeline vazia; ticks iguais sem envelhecimento artificial. Também cobrem negativos/zero, bool recusado, atomicidade, monotonicidade, políticas conflitantes, ausência de defaults, pureza, ausência de interpretação e hashes congelados.

A avaliação só rejeita rewind relativo ao estado recebido. Não pode detectar que o caller reteve um estado antigo ou informou outra ordem de consultas fora dele. Nenhuma memória adicional é introduzida para esconder esse requisito de ownership.

A imutabilidade usa as garantias normais de dataclasses frozen e tuples, não proteção contra alteração deliberada via mecanismos reflexivos de Python. O constructor público de state aceita metadados explícitos válidos, mas não prova origem real. A API não autentica refs e não guarda histórico completo: só a última ocorrência por ref, sem poda automática. Armazenamento cresce com o número de refs distintas. Não há algoritmo para migrar marks entre clock domains/timelines nem converter suas unidades.

## Relógio live permanece NÃO DECIDIDO

v0.1 NÃO escolhe a fonte do relógio live. Antes de qualquer integração, decidir e validar: domínio, unidade, comportamento durante pause, ownership de sessão/timeline, timestamp da fonte versus receipt timestamp e implicações de latência. Nenhuma dessas decisões está embutida no código. Não há captura real ou wiring live nesta etapa.

## Revisão arquitetural

| Pergunta | Resposta |
|---|---|
| 1. Interpreta gameplay? | NÃO |
| 2. Infere MISSING por silêncio? | NÃO |
| 3. Armazena Truth/ThreatState? | NÃO |
| 4. Usa wall clock? | NÃO |
| 5. TTLs explícitos? | SIM |
| 6. TTL Dota hardcoded? | NÃO |
| 7. Estado explícito/imutável? | SIM |
| 8. Timeline A vaza para nova B? | NÃO: factory sempre vazia; caller não deve transplantar marks manualmente |
| 9. NEVER_SEEN distinto de STALE? | SIM |
| 10. STALE fica FRESH sem nova observação? | NÃO com política fixa e tempo não decrescente; mudar explicitamente política ou consultar estado histórico é outra avaliação, documentada acima |
| 11. Reobservação renova idade? | SIM |
| 12. Core congelado mudou? | NÃO |
| 13. Caminho live mudou? | NÃO |
| 14. Relógio live ainda não decidido/documentado? | SIM |

Manifestos, hashes antes/depois, resultados exatos e auditoria de transporte ficam no pacote externo `TEMPORAL_EVIDENCE_V01_20260930`. Os gates são executados uma vez cada; falha de baseline ou WinError 10054 bloqueia sem retry. Este documento especifica o contrato; os resultados observados são registrados no relatório final externo. Nenhuma etapa seguinte é autorizada automaticamente.
