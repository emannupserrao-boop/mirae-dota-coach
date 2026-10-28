# Roteiro de aceitação — Alpha 0.2

Execute a instalação e configuração do README. Use Start-Bot-Test.cmd, uma
partida SOLO contra bots e mantenha Coach ON / Voz ON. O botão Salvar aplica
os controles. Alterar meta ou parâmetros reinicia as referências das regras;
aguarde a janela de observação novamente. Pause só depois de ouvir uma call.

**Os testes abaixo ainda precisam ser executados no seu Windows.** Não há injeção
de eventos falsos nestes passos: as condições devem acontecer na partida.

## 1. FARM LOW

1. Meta LH/min = **5**, frequência normal, clique Salvar.
2. Depois do relógio chegar a 00:00, permaneça vivo e sem pausa.
3. Fique **30 segundos sem last hits**; mantenha a recepção GSI.
4. Espere “Seu ritmo de farm caiu. Procure uma rota segura.”
5. Confira última recomendação `farm_low_v1`, ouça e clique Boa/Ruim/Irrelevante.
6. Continue sem LH mais 30 segundos: a mesma situação não deve repetir a call.

TEST usa janela recente de 20s e confirmação de 5s. A regra mede LH, não denies.
Uma call mais prioritária simultânea pode suprimir esta: confira a exportação.
Para tentar novamente, altere a meta, salve e retorne a 5, salvando de novo.

## 2. FARM RECOVERED

1. Faça primeiro o FARM LOW acima, sem alterar parâmetros depois.
2. Consiga **3 ou mais last hits em 20 segundos**, continue vivo e farmando.
3. Mantenha esse ritmo por pelo menos mais 5 segundos.
4. Espere “Seu ritmo de farm voltou a melhorar.” (`farm_recovered_v1`).

Meta 0 muda para comparação com a janela anterior; precisa de aproximadamente
40s de histórico em TEST e de um ritmo anterior significativo. Não é o caminho
mais simples para o primeiro teste.

## 3. ITEM POWER SPIKE

1. Inicie o app antes de receber o item importante.
2. Junte ouro e complete **Maelstrom**, Battle Fury, Manta ou BKB na loja do jogo.
3. Espere o item chegar ao inventário do seu herói; só estar no stash não basta.
4. Espere a call com o nome do item e `item_power_spike_v1`.
5. Mova o item entre slots: não deve repetir a call.

Não anuncia itens presentes no primeiro estado recebido. Não calcula custo
restante nem promete timing ideal. Detecta recebimento, não comprova compra.
Backpack faz parte do inventário; o texto não garante que o item esteja ativo.
Lista configurável no botão Parâmetros, seção `important_items`.

## 4. DEATH PATTERN

1. Para isolar este teste, Meta LH/min = 0, Salvar; permaneça sem farm por 40s.
2. Durante a partida contra bots, observe duas mortes do seu herói dentro de
   5 minutos, mantendo o app conectado durante as duas.
3. Depois da segunda, espere `death_pattern_v1`: “Mortes próximas umas das outras…”
4. Uma terceira morte no mesmo grupo não deve provocar outra repreensão.

Não é preciso alterar o processo do jogo nem usar comandos/cheats. Se ocorrer
uma interrupção longa do GSI, refaça o teste: o app não inventa os horários perdidos.
NORMAL exige três mortes e usa cooldown maior. Para rearmar, a contagem da janela
precisa cair abaixo do limiar.

## 5. BUYBACK

1. Observe no painel **Buyback custo** e **cooldown**. Se N/D, pare este teste:
   o app não deve inferir disponibilidade.
2. Com cooldown 0, acumule ouro suficiente para superar o custo mostrado.
3. Mantenha por pelo menos **3 segundos** de partida sem pausa. Se houve mudança
   de indisponível para disponível, deve anunciar ouro e cooldown prontos.
4. Compre itens de forma que o ouro fique abaixo do custo atualizado; aguarde
   pelo menos 3 segundos para a call de indisponível.
5. Deixe pelo menos **10 segundos** entre transições para não atingir o cooldown.

O primeiro estado conhecido só estabelece a referência; não gera call.
TEST permite o teste cedo. NORMAL só considera mudanças a partir de **20:00**.
“Ouro e cooldown prontos” não significa apertar buyback: o app não compra nada.

## 6. ENEMY MISSING / GANK RISK — experimental

Faça somente depois que voz e GSI funcionarem. Use Dota em janela sem bordas,
resolução e escala fixas. Comece em 5 FPS. Não há reconhecimento automático de
papel: você precisa identificar qual inimigo é mid, qual é o suporte da outra
rota e qual aliado é seu suporte. Ícones precisam ser visualmente distintos.
Se a aparência atual do minimapa não permite distingui-los, não ative a regra.

### Calibrar o retângulo

1. Abra a aba Minimapa e marque a confirmação de partida solo contra bots.
2. Clique **Canto 1 em 5s**, volte ao Dota e posicione o cursor no canto superior
   esquerdo do minimapa. Espere 5s; volte ao Coach.
3. Clique **Canto 2 em 5s**, volte ao Dota e posicione no canto inferior direito.
4. Confira X/Y/Largura/Altura. Apenas minimapa, máximo 600×600 pixels.
5. Clique **Capturar ROI em 5s** e volte ao Dota. Pode pausar para esta amostra.
   Depois volte ao Coach: aparece uma imagem estática, não um vídeo ao vivo.

### Calibrar os quatro ícones

1. Escolha `local_player` no seletor e arraste um retângulo justo sobre seu ícone
   na amostra. Tamanho de 8 a 64 pixels em cada dimensão.
2. Faça o mesmo para `allied_support`, `enemy_mid` e `enemy_support_opposite`.
3. Se um ícone não estiver visível, espere visibilidade legítima na partida e
   capture outra amostra. Nunca utilize replay, espectador ou visão de outro time.
4. Pode usar amostras diferentes para cada papel. Recapturar preserva os recortes
   anteriores; mudar o ROI invalida os papéis e exige recalibração dos quatro.
5. A imagem tem barras de rolagem se não couber inteira.
6. Clique **Ativar visão calibrada**. Se pedir aguardar a configuração, aguarde
   um segundo e clique novamente. Volte ao Dota e despause.

### Observar a regra

1. Seu herói precisa estar vivo e seu ícone detectável. Primeiro o mid precisa
   aparecer com confiança por pelo menos três frames.
2. Espere o ícone do mid sair da visão legítima e permanecer ausente por cerca
   de 4s. O sistema deve passar de VISIBLE para MISSING e produzir uma call.
3. Se também sumir o suporte inimigo, risco HIGH; se o aliado estiver visivelmente
   longe, VERY_HIGH. Aliado desconhecido é UNKNOWN, nunca FAR.
4. Ausência contínua não deve repetir a call, mesmo se o risco subir depois.
5. Para rearmar, o mid precisa reaparecer com confiança e sumir novamente.
6. Marque falso positivo se alertou incorretamente; falso negativo se perdeu uma
   situação observada. Essas marcações não são cálculo automático de precisão.

Não sabemos para onde o inimigo foi. A call expressa risco, não rotação confirmada.
Suporte sumido sozinho não dispara call nesta versão. Os ~4s são configuráveis
em Parâmetros → vision → `missing_seconds`; alterações desativam a visão e
exigem reativação. `visible_threshold`, `absent_threshold` e `confirm_frames`
controlam confiança e confirmação; os scores não são probabilidades.

**Alt+Tab ou pausa suspende e reinicia o rastreamento.** Para acompanhar o debug
sem interromper, coloque o Coach num segundo monitor e mantenha Dota em foco.
Em um único monitor, use as calls e exporte as amostras de diagnóstico logo após
observar o evento; não espere que a captura continue enquanto examina o Coach.
Ícones animados, sobrepostos, invisibilidade, morte ou mudança de estilo podem
causar falsos resultados. Se a identificação não se sustentar, desative Vision.

### Comparar 5 / 10 / 15 FPS

Depois de calibrar, faça trechos de 1–2 minutos com cada frequência. Ao trocar,
reative a visão, volte ao Dota e aguarde a detecção inicial. Exporte um arquivo
por trecho (ex.: vision-5fps.json). Compare capture_fps, capture_average_ms,
processing_average_ms, CPU/RAM e sua experiência de jogo. Prefira 5 FPS se
suficiente. Não há garantia de impacto imperceptível antes desse teste real.

## Fechar o ciclo e enviar resultados

1. Avalie a última ID ou uma linha selecionada no histórico. A avaliação da última
   usa exatamente o ID exibido, não uma busca pelo texto.
2. Exporte **antes de encerrar o app**, após a fala terminar.
3. Feche e reabra Start-Bot-Test.cmd; confira a mesma avaliação no histórico.
4. Envie o JSON exportado, capturas pertinentes e diga o que ouviu.
5. Se precisar comprovar diretamente o SQLite, o arquivo é
   `%LOCALAPPDATA%\DotaAICoach02\coach02-test.sqlite3`; copie somente com app fechado.

Aceitação pendente: GSI real no 0.2; call de cada regra; voz audível e volume;
feedback persistido; exportação completa; CPU/RAM aceitáveis. Vision tem aceitação
separada: captura, identificação, missing, call única e rearm em Dota real.
Não avançar para Alpha 0.3 antes da revisão desses resultados.
