# Context Builder v0.1 — Runtime Semantic Seed

Uso explícito e exclusivamente offline:

```python
observation = adapt_state(normalized_state)
seed = build_context_seed(observation, knowledge_ref, player_ref)
```

A fronteira termina em `DecisionContextSeed`. O builder não chama planner,
build_context, authorize_output, Service, GSI, Policy, UI, voz ou visão. Não cria
o DecisionContext da vertical farm-cycle nem opções/ações para ele. Os contratos
anteriores e todos os seus consumidores permanecem intactos.

## Projeção de entrada realmente disponível

RuntimeObservation contém observation_id, facts (fatos booleanos das fixtures
offline) e scalars. Este builder consome somente os scalars e a identidade;
facts não substitui um escalar ausente. O adapter atual produz facts vazio.

Os 15 nomes são State.active, State.local, State.match_id, State.time, State.hero,
State.level, State.alive, State.gold, State.lh, State.gpm, State.xpm, State.deaths,
State.buyback, State.buyback_cost e State.buyback_cooldown. As listas imutáveis de
tipos vêm do próprio runtime_adapter; importar essas constantes não chama adapt_state.
Não existe campo novo no adapter ou State.

## Elegibilidade: conjunto obrigatório e precedência

| Ref obrigatória | Suporte necessário | Justificativa |
|---|---|---|
| State.active | KNOWN, FRESH, True | Propriedade legada que permite contexto de partida ativa |
| State.local | KNOWN, FRESH, True | Contexto do jogador local, não spectator |
| State.alive | KNOWN, FRESH, True | Jogador vivo para futuro processamento de atividade |
| State.hero | KNOWN, FRESH, string não vazia | Identificação disponível do herói, sem validar mecânicas |
| State.time | KNOWN, FRESH, número finito, sem bool | Referência temporal da partida fornecida pelo snapshot |

Elegibilidade autoriza apenas uma futura avaliação; não afirma segurança, qualidade
do farm, disponibilidade de ação ou que um conselho deva ser emitido.

1. Qualquer active/local/alive conhecido e fresco igual a False produz INELIGIBLE.
2. Sem esse bloqueio, qualquer obrigatório ausente, UNKNOWN ou STALE produz
   INSUFFICIENT_DATA.
3. Apenas com todos os obrigatórios positivamente suportados resulta ELIGIBLE.

Bloqueios explícitos têm precedência, mas não apagam incertezas. Por exemplo,
alive=False e hero UNKNOWN dão INELIGIBLE, PLAYER_DEAD e HERO_UNKNOWN; o herói
continua desconhecido. Não há early return que descarte as outras dependências.

Gold/LH/GPM/XPM/level e demais dimensões opcionais não determinam elegibilidade.
match_id é preservado como valor opcional; a identidade de observação já assegura
lineage do snapshot. A falta de match_id não é transformada em contexto não local.

## Limites legados preservados

active e buyback são propriedades calculadas do State, não raw GSI. O builder não
recalcula nenhuma delas e não atribui causa raw a active=False. No State atual,
time=None pode produzir active=False: a cadeia real resultará INELIGIBLE, com
MATCH_NOT_ACTIVE e MATCH_TIME_UNKNOWN, preservando ambos. Uma observação fornecida
com active=True e time UNKNOWN terá INSUFFICIENT_DATA. Não são casos equivalentes.

O builder não adiciona limites de tempo, níveis, economia ou mecânicas. Identificadores
como a string literal "None", se já normalizados assim, não recuperam ausência
perdida. active não exige alive no legado; por isso o bloqueio de alive é separado.

## Schema e reasons

Todos os tipos novos ficam em coach02/context_builder.py; decision.py não muda.

DecisionContextSeed é uma dataclass congelada com:

- seed_id e observation_id;
- knowledge: KnowledgeSnapshotRef e player: PlayerModelSnapshotRef;
- eligibility: ELIGIBLE / INELIGIBLE / INSUFFICIENT_DATA;
- eligibility_refs: tupla das cinco dependências obrigatórias;
- reasons: tupla de RuntimeReason(code, ref);
- dimensions: tupla ordenada dos ScalarObservation fornecidos;
- unknown_required: refs obrigatórias ausentes ou explicitamente UNKNOWN;
- stale_required: refs obrigatórias marcadas STALE pelo chamador.

SeedReason fornece códigos estáveis `runtime_seed.<nome>.v1` para MATCH_NOT_ACTIVE,
NON_LOCAL_PLAYER, PLAYER_DEAD, ACTIVE_UNKNOWN, LOCAL_UNKNOWN, ALIVE_UNKNOWN,
HERO_UNKNOWN, MATCH_TIME_UNKNOWN e REQUIRED_STALE. São interpretações conservadoras,
não fatos adicionais recebidos do GSI nem expert heuristics.

Não há nova taxonomia de provenance, knownness ou freshness: reutilizam-se as de
decision.py. Eligibility e SeedReason representam somente o novo resultado semântico.

## Provenance, desconhecimento e freshness

Cada reason aponta a um ref State.* da observação identificada por observation_id.
Os fatos de suporte e sua Provenance original permanecem em dimensions. Para
ELIGIBLE, eligibility_refs explicita todas as dependências positivas. Lineage de
knowledge/player permanece separado e nunca é evidência runtime.

Se um obrigatório estiver ausente, seu ref é registrado em unknown_required e no
reason, mas **nenhum ScalarObservation é inventado**. Um escalar fornecido UNKNOWN
permanece explicitamente UNKNOWN/None em dimensions. A distinção ausência versus
valor desconhecido pode ser inspecionada nessa tupla. Falso e zero conhecidos
continuam conhecidos; bool em um campo numérico é rejeitado, nunca convertido.

FRESH/STale são informações fornecidas, sem relógio nem TTL. Um obrigatório STALE
não sustenta nem ELIGIBLE nem um bloqueio atual: gera REQUIRED_STALE e insuficiência,
salvo outro bloqueio fresco. Seu valor original permanece intacto. Um UNKNOWN/STale
aparece nas duas listas, sem confundir knownness com freshness. STALE opcional é
preservado, sem bloquear elegibilidade. O adapter atual produz FRESH para o snapshot
fornecido; isso não certifica idade de recebimento ou conectividade.

Entradas que violem tipos de campo do adapter ou tragam nomes fora da projeção são
rejeitadas explicitamente. Não há coerção nem tradução de fatos booleanos antigos.
Construção suportada: build_context_seed com RuntimeObservation validada pelos
contratos aceitos e referências de snapshot tipadas, com id/versão string não vazios.

## Identidade, pureza e lineage

seed_id é `runtime-context-seed-v1:` + SHA-256 do JSON da dataclass sem seed_id,
com sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False e
UTF-8. Dimensions são ordenadas por ref; reasons e dependências seguem ordem fixa.
O hash inclui a projeção, resultado semântico, incertezas e as duas refs versionadas.

Mudar id/versão de KnowledgeSnapshotRef ou PlayerModelSnapshotRef muda seed_id,
sem mudar a interpretação runtime. O conteúdo desses snapshots não é carregado,
validado, consultado nem inferido. O builder não lê histórico de jogador ou mecânicas.
Mesmo se um chamador reutilizar observation_id com valores diferentes, o hash do
seed muda porque inclui as dimensões. Reordenar os mesmos escalares não muda o seed.

Não há IO, rede, ambiente, clock, UUID, processo, cache, estado entre frames ou
mutação das entradas. As refs e ScalarObservation existentes são imutáveis e podem
ser compartilhados; o seed não guarda State, dicionários de itens ou objetos mutáveis.

## Domínios não suportados

O schema omite threat, safety, movimento inimigo, suficiência de visão, reinforcement,
wave safety, route safety, fight quality, objective value, eficiência de farm,
item timing, power spike, recomendações, opção de rota e arbitragem. Também não
inventa HP, mana, posições, itens ou abilities ausentes da projeção escalar.
Nenhum placeholder SAFE/LOW/NORMAL é criado. UNKNOWN não equivale a segurança.

Composição com safety/map evidence, Knowledge Snapshot content, Player Model content
ou avaliações de domínio é uma etapa futura. farm_cycle.plan continua aceitando
apenas seu DecisionContext anterior; o seed não oferece options e não é convertido.

## Testes e preservação

tests/test_context_builder.py cobre os gates positivos/negativos, incerteza,
propriedades legadas, spectator real, lineage, determinismo, imutabilidade, falta de
histórico, STALE fornecido, entradas incompatíveis e isolamento de IO/imports.
O teste de bloqueio de IO usa ExitStack e verifica a restauração dos alvos e ambiente.
A cadeia sintética termina no seed, sem invocar plan ou authorize_output.

Validação desta etapa: baseline completo uma vez, focal builder uma vez, focal
adapter uma vez, focal farm-cycle uma vez, regressão completa uma vez. Destinos
externos bloqueados; somente HTTP local legado permitido. A exceção histórica
WinError 10054 continua bloqueante e não foi adicionada ao contrato HTTP.
Manifestos/logs ficam fora da árvore canônica, em outputs/CONTEXT_BUILDER_V01_20260929.

Nada conecta este módulo ao entry point ou ao runtime. Não há autorização implícita
para Context Composition, Safety Builder, planner live, adapter v0.2 ou arbiter.
