# Runtime Adapter v0.1 — Scalar Core

Fronteira única, chamada explicitamente: `adapt_state(State) -> RuntimeObservation`.
Não há ligação com Service, GSI, Policy, UI, voz, Data Foundation ou planner.

## State real inspecionado

O contrato de `coach/state.py` tem 20 campos:

```text
match_id, time, phase, paused, local, hero, level, kills, deaths, assists,
lh, denies, gold, gpm, xpm, buyback_cost, buyback_cooldown, alive, items, abilities
```

Também expõe as propriedades calculadas existentes `active` e `buyback`.
`normalize` produz números finitos ou None nos campos numéricos; não aceita bool
como número. `alive` aceita apenas booleano ou None. Para contexto não local,
inclusive spectator, retira os dados de player/herói e as coleções. Match/time
permanecem dados de mapa. Identificadores são strings, com vazio como valor default.

O Alpha 0.2 utiliza esse State herdado: service recebe/enfileira snapshots; rules
consome active, time, match/hero, alive, LH, deaths, itens e buyback. Esta tarefa
não altera esses consumidores nem amplia o contrato do State.

## Projeção escalar exata

| Grupo | Campos mapeados |
| --- | --- |
| Número finito, sem coerção | time, level, gold, lh, gpm, xpm, deaths, buyback_cost, buyback_cooldown |
| Booleano estrito | local, alive, active, buyback |
| String não vazia | match_id, hero |

Total: 15. `buyback_cooldown` é somente o escalar já existente do State; não há
mapeamento de cooldowns de abilities ou inventário. `active`/`buyback` reportam as
propriedades do próprio State, não inferências novas nem campos raw GSI. Por exemplo,
active não exige alive no legado; o adapter preserva exatamente esse comportamento.

HP/max HP e mana/max mana **não existem no State canônico**: não são mapeados nem
substituídos por campos fictícios UNKNOWN. Informações de mana observadas em outra
projeção diagnóstica não são acessíveis a este adapter.

Itens, abilities, inventário/stash, cooldowns estruturados, visão e posições de
inimigos continuam fora do escopo. Também ficam adiados os escalares phase, paused,
kills, assists e denies. phase/paused participam apenas da propriedade active já
definida no State, sem ganhar campos próprios no resultado.

## Extensão compatível de RuntimeObservation

`ObservedFact` e Truth ficam intactos. Foram acrescentados em `coach02/decision.py`:

- `Knownness.KNOWN / UNKNOWN`;
- `ScalarObservation` congelada, com Provenance existente, knownness, valor escalar
  e freshness; só aceita provenance RUNTIME_OBSERVATION;
- `RuntimeObservation.scalars`, tupla com default vazio, preservando o construtor
  anterior `RuntimeObservation(id, facts)`.

KNOWN exige bool/int/float finito/str. UNKNOWN exige value=None, sempre acompanhado
de knownness explícito. Valores mutáveis, NaN/Inf e Truth usado como escalar são
rejeitados no contrato. Refs repetidas dentro/entre facts e scalars são rejeitadas.
A serialização dataclass de RuntimeObservation ganha a chave `scalars`; esse é um
acréscimo ao formato, sem mudar os fatos ou o comportamento do planner existente.

O adapter preenche somente scalars e deixa facts vazio. Não transforma int/string
em Truth, não cria Claim, DecisionContext, Decision ou Output, e não chama planner
ou authorize_output. A extensão existe porque o contrato booleano anterior não
poderia representar fielmente tempo, nome e métricas escalares.

## UNKNOWN, freshness e provenance

None e valores de tipo inválido viram UNKNOWN; zero e False válidos ficam KNOWN.
Não há carry-forward, preenchimento de ausência, cast string→número ou bool→int.
Strings vazias de identificação viram UNKNOWN. Strings já normalizadas como
`"None"` continuam strings: o adapter não consegue recuperar a origem perdida na
normalização. Não há validação estratégica de nomes, níveis ou valores do jogo.

Os refs são `State.time`, `State.hero`, `State.active` etc., não supostos caminhos
raw de GSI. Provenance usa exclusivamente RUNTIME_OBSERVATION; as propriedades
calculadas são identificadas pelo nome da propriedade normalizada.

Todos os valores pertencem ao snapshot fornecido e levam FRESH, inclusive o status
UNKNOWN recém-observado. Isso não comprova idade de recebimento ou conectividade.
O adapter não lê relógio nem aplica TTL. Um chamador que forneça um State antigo
continua fornecendo um snapshot antigo; freshness temporal precisará de outro
contrato em etapa futura.

O parâmetro deve ser State, não payload/dict. Como defesa para State construído
manualmente com valores inválidos, os operandos das propriedades são verificados
por tipo antes de consultá-las. Isso evita interpretar bool como dinheiro/tempo
ou calcular buyback sobre valores inválidos. None mantém o comportamento legado
das propriedades: time=None pode produzir active=False; buyback ausente é UNKNOWN.

## Identidade e imutabilidade

O ID é `alpha-state-scalars-v1:` seguido de SHA-256 do JSON canônico da projeção:
scalars ordenados por ref, chaves ordenadas, separadores fixos, ensure_ascii=True,
allow_nan=False e bytes UTF-8. Não depende de relógio, UUID, processo ou ambiente.
O conteúdo inclui knownness, value, freshness e provenance.

O mesmo State produz resultado e ID iguais. Mudar um valor mapeado muda o ID.
Mudanças em coleções/campos adiados que não alterem a projeção não mudam o ID: ele
identifica a projeção escalar, não o State inteiro. A identidade não é anonimização;
o match_id presente no State é preservado como parte dos valores mapeados.

As estruturas novas usam dataclasses congeladas e tuplas. O adapter não modifica
nem guarda referências ao State ou seus dicionários. Só admite valores escalares
imutáveis. Não possui cache ou estado global mutável.

## Validação e limites

`tests/test_runtime_adapter.py` cobre snapshot normal; numéricos ausentes/inválidos;
booleano desconhecido; contexto não local; determinismo; mudança de valor; ausência
de histórico; imutabilidade; coleções adiadas; falta de HP/mana; schema sem estratégia;
provenance; compatibilidade de fatos booleanos; invalidez do contrato; propriedades
legadas; e chamadas sob bloqueio de IO/ambiente/tempo/camada de decisão.

Os testes farm-cycle permanecem inalterados. A regressão completa usa a .venv
canônica, com localhost dos testes existentes permitido e destinos externos
bloqueados. Logs e manifestos desta etapa ficam fora do projeto, na pasta
`outputs/RUNTIME_ADAPTER_V01_SCALAR_20260929` do workspace de evidências.

Não é um Context Builder, Safety assessment nem integração live. Não foram
introduzidos conselhos, regras de gameplay, arbitragem, voz, LLM/ML ou acesso a
Knowledge Snapshot/Player Model. A próxima etapa exige instrução separada.
