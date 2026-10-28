# Observation Event Foundation v0.1

## Contrato e limite de autoridade

`coach02/observation_event.py` fornece um envelope puro, imutável, determinístico e neutro para ocorrências explícitas. Responde quais refs uma fonte reportou em uma timeline, quais timestamps foram fornecidos e qual timestamp uma política explícita selecionou para eventual orquestração futura.

O módulo NÃO observa o jogo, certifica verdade, atribui significado, infere MISSING por silêncio, avalia segurança/disponibilidade ou calcula freshness/TTL. Não escolhe relógio live, unidade, política por fonte, latência aceitável ou estratégia. Nenhum caminho live ou core existente importa este módulo. Não há GSI, visão, Data Foundation, APIs, scheduler ou observer real.

Fluxo permitido: futuro observer -> ObservationEvent -> política explícita de timestamp -> TemporalProjection. A implementação termina na projeção. Não chama Temporal Evidence. Somente os testes incluem uma ponte explícita para demonstrar compatibilidade.

## Contratos

| Contrato frozen | Campos |
|---|---|
| ObservationSource | source_id, source_kind, schema_id |
| ClockStamp | clock_id, tick |
| ObservationEvent | timeline_id, source, refs, receipt_stamp obrigatório, source_stamp opcional |
| ObservationTimingPolicy | policy_id, basis obrigatório |
| TemporalProjection | event_id, timeline_id, source_id, refs, selected_clock_id, selected_tick, timing_policy_id, timestamp_basis |

`ObservationSource` neste módulo é identidade do produtor; não modifica nem substitui a taxonomia de provenance do core. source_id identifica o produtor, source_kind sua categoria somente para auditoria e schema_id seu contrato/versão. Não existe enum GSI/VISION nem branch por categoria.

Strings devem ser str exatas e não vazias. São preservadas literalmente, inclusive whitespace, case e Unicode, sem trim, normalização ou interpretação de namespaces. Whitespace sozinho não é a string vazia e não recebe significado especial. A orquestração futura é responsável por fornecer identificadores compatíveis com todos os consumidores; as validações existentes do Temporal continuam intactas.

ClockStamp exige int exato: bool, float, None e strings são recusados; tick negativo/zero é aceito. ClockStamp transporta somente identidade e valor. Não define unidade, origem, pause, drift, sincronização ou conversão.

Refs exigem tuple de strings não vazias. A ordenação lexicográfica canonicaliza o conjunto; duplicatas são erro. Um ref inválido faz falhar a construção inteira sem mutar input. A tuple vazia é permitida: reporta zero ocorrências, sem inferir ausência, saúde da fonte ou silêncio semântico. Não há valor anexado às refs.

Os contratos usam dataclasses frozen e tuples; nested contracts também são validados por tipo exato. Os IDs são propriedades calculadas a partir do conteúdo, não IDs livremente fornecidos nos eventos. Em exportações com `asdict`, incluir `event_id`/`projection_id` explicitamente quando desejado, pois propriedades não são campos da dataclass.

## SOURCE TIME versus RECEIPT TIME

SOURCE TIME: timestamp que a fonte forneceu/associou à ocorrência. É opcional e não se fabrica quando ausente.

RECEIPT TIME: timestamp que o caller forneceu para a recepção/aceitação do evento em seu domínio de recebimento. É obrigatório.

**Nenhum deles é autoritativo por padrão.** Ambos são preservados independentemente. Nenhum é lido de um relógio interno. Não há effective tick padrão, preferência silenciosa ou fallback.

Se source_stamp existir e os dois clock_id forem EXATAMENTE iguais, source.tick deve ser <= receipt.tick. Igualdade e ticks negativos são válidos. Source no futuro relativamente ao receipt no mesmo domínio é erro.

Se os clock_id diferirem, seus valores numéricos não são comparados nem subtraídos. Mesmo source com número maior que receipt é aceito em clocks distintos. Não há conversão ou helper de latência nesta versão.

## Política e projeção

TimestampBasis possui somente SOURCE e RECEIPT. ObservationTimingPolicy exige policy_id não vazio e uma instância desse enum; strings equivalentes e bool não são aceitos como basis. Não existe default.

`project_event_time(event, timing_policy, expected_clock_id=None)` seleciona exatamente a base informada:

- SOURCE exige source_stamp; a ausência é erro explícito.
- RECEIPT usa receipt_stamp, mesmo se source_stamp estiver ausente.
- expected_clock_id opcional é somente uma checagem de binding: precisa ser string válida e coincidir exatamente com o domínio selecionado. Divergência é erro. Não converte clocks nem muda a base para satisfazer o expected.

A projeção mantém refs, timeline, source_id, event_id, política/base e clock/tick selecionados. O event_id vincula também source_kind, schema_id e o timestamp não selecionado. O caller deve reter o evento completo junto à projeção para auditoria; o hash não reconstrói o conteúdo.

expected_clock_id não entra no ID da projeção: é uma condição de aceitação sem mudança de conteúdo. Com ou sem a checagem bem-sucedida, a projeção é a mesma.

```python
from coach02.observation_event import (
    ClockStamp, ObservationSource, ObservationEvent,
    ObservationTimingPolicy, TimestampBasis, project_event_time,
)
source = ObservationSource('producer-1', 'opaque-category', 'schema-v1')
event = ObservationEvent(
    timeline_id='timeline-A', source=source,
    refs=('observer.example',),
    source_stamp=ClockStamp('example-clock', 100),
    receipt_stamp=ClockStamp('example-clock', 103),
)
policy = ObservationTimingPolicy('explicit-source-policy-v1', TimestampBasis.SOURCE)
projection = project_event_time(event, policy, expected_clock_id='example-clock')
# selected_tick = 100. RECEIPT, se explicitamente escolhido, produziria 103.
# Nenhuma chamada ao Temporal Tracker é feita aqui.
```

O exemplo é sintético e não recomenda SOURCE em produção.

## Timeline, stream, eventos tardios e pause

Timeline sempre é fornecida pelo caller. Não se deriva de State.match_id, tempo, fonte, processo, hero ou servidor. Não há reset automático, detecção de partida ou alteração de estado anterior. Duas construções independentes com conteúdo idêntico podem compartilhar event_id; isso NÃO conclui retransmissão.

Não existe previous event, sequence tracker, dedupe cache, buffer, reorder ou high-water mark neste componente.

Caso tardio explícito: tracker com last_tick=120; source tick=110; receipt tick=125. SOURCE preserva 110 e, se timeline/clock coincidirem, uma futura inserção explícita é rejeitada pelo Temporal porque 110<120. RECEIPT preserva125 e só é compatível se seu domínio for o clock aceito pelo tracker. Se receipt usar outro clock, a ponte deve rejeitar por binding; não basta o número ser maior.

v0.1 não resolve esse caso: não clampa110 para120, não troca SOURCE por RECEIPT, não reordena, não tolera lateness e não reescreve last_observed_tick. Escolher a política adequada e decidir o destino de eventos tardios pertence à futura orquestração validada.

**Pause semantics belong to the selected clock contract, not ObservationEvent.** Ticks iguais são preservados sem inferir pause. Não se decide se o relógio deve parar ou continuar.

## Compatibilidade somente nos testes

`tests/test_observation_event.py` usa um helper que exige igualdade de timeline e clock antes de chamar explicitamente `record_observations(state, projection.refs, projection.selected_tick)`. Prova SOURCE e RECEIPT, guards de mismatch, ausência de source time e rejeição temporal de evento tardio. Nenhuma ponte é adicionada à produção; Temporal Evidence, seus testes e documentação permanecem byte-for-byte preservados.

## Identidades determinísticas

RULESET = `observation.event_envelope.v1`.

Event ID: `ruleset:event:SHA-256(JSON canônico do evento completo)`.

Projection ID: `ruleset:projection:SHA-256(JSON canônico da projeção completa)`.

JSON usa sort_keys=True, separators compactos, ensure_ascii=True e UTF-8. Refs são ordenadas. Event inclui timeline, todos os campos da fonte, refs, source_stamp (inclusive None) e receipt_stamp. Projection inclui event_id, timeline/source, refs, clock/tick, policy_id e basis.

Alterações relevantes, inclusive no timestamp não selecionado ou schema do produtor, mudam o binding pertinente. Ordem original de refs não muda identidade. Sem UUID, random, endereço de memória, processo ou wall clock. IDs são vínculos por conteúdo, não autenticação ou prova de veracidade.

## Auditorias e testes

68 testes determinísticos: requisitos01–56, adversariais A–H nos métodos57–64 e quatro verificações adicionais65–68. Cobrem inputs, imutabilidade, timestamps, clocks incomparáveis, políticas, identidades, ausência de efeitos, late events e hashes congelados. Os exemplos são inteiramente sintéticos.

Produção importa apenas dataclasses, enum, hashlib e json. Os testes restringem imports via AST e bloqueiam sinks de IO/network/clock/environment/random. Verificam ausência de globals mutáveis, global/nonlocal, async scheduler, memória de stream e imports/calls reversos nos arquivos de produção. Não existe threading, socket, SQLite, subprocess ou leitura de ambiente no módulo.

O baseline392 deve passar uma vez antes de instalar arquivos. A validação focal e regressões são registradas no pacote externo `OBSERVATION_EVENT_FOUNDATION_V01_20260930`, sem retry-until-green. WinError10054 permanece bloqueador; a exceção estrita existente para10053 não é alterada.

## Decisões futuras ainda NÃO resolvidas

- Fonte real do relógio live.
- Unidade live e contrato do clock_id.
- Comportamento durante pause.
- Política SOURCE versus RECEIPT por observer.
- Confiabilidade/autenticidade dos timestamps de origem.
- Tratamento e implicações de latência.
- Tratamento de eventos tardios.
- Reordenação e buffering.
- Ownership de sessão/timeline.
- Sincronização e conversão entre clocks.
- Ciclo de vida de source_id e schema_id.

Limitações: só ocorre validação estrutural e de ordem no mesmo clock; não se valida que timestamps ou refs são verdadeiros. Não há semântica, deduplicação de stream, persistência, serialização pública de transporte ou relógio real. A imutabilidade segue frozen dataclasses, sem proteção contra reflexão deliberada em Python. Instanciar manualmente uma projeção não autentica seu event_id; o produtor normal é project_event_time e o caller deve reter seu evento.

Nenhum arquivo anterior, caminho live, regra estratégica ou enum do core é alterado. Nenhum observer, GSI/vision wiring, Shadow Mode, Data Foundation ou teste de partida real é iniciado nesta tarefa.
