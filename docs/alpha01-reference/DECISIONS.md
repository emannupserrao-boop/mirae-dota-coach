# Decisões arquitetônicas — 0.1

1. **Python 3.12+ para o núcleo.** Adequado a regras determinísticas e futura
   análise dos dados/ML; pequeno volume GSI não exige uma engine nativa. Modelos e
   regras não importam Tkinter, transporte ou Windows. Evolução para backend Python
   reaproveita esse núcleo; site/mobile seriam clientes novos de uma API futura.
   Esta entrega não cria essa API nem promete compartilhar a UI com mobile.
2. **Tkinter como adaptador desktop do Alpha.** Janela nativa sem navegador,
   dependências extras ou servidor de UI. É substituível; não foi escolhido como
   limite de experiência visual do produto comercial. C#/WPF seria uma boa UI
   Windows, mas acoplaria mais o início à plataforma; Electron adicionaria um
   runtime maior sem necessidade para este painel. Tradeoff: distribuição deste
   Alpha exige Python, e a UI comercial provavelmente precisará ser reescrita.
3. **GSI HTTP em loopback.** Porta explícita e token por instalação. Limite de
   corpo, timeout por conexão, sem CORS ou endpoints de controle acessíveis a sites.
   Servidor serial limita concorrência e preserva ordem; fluxo esperado é um
   cliente local. Um software local malicioso ainda pode causar indisponibilidade.
4. **Snapshot de cada envio.** Não misturar campos omitidos com valores antigos.
   Campos desconhecidos são ignorados; `previously`/`added` não são estado atual.
   Payloads aninhados de espectador são rejeitados para coaching. Sem chamadas
   a APIs externas, dados de adversários ou inferência de posições.
5. **Relógio do jogo e histerese.** Pausa não produz coaching. Mudança de partida,
   herói, regressão de relógio ou reconexão após 15s reinicia baselines. Conectar
   no meio da partida não anuncia itens antigos como recém-concluídos.
6. **SQLite para coleta local.** WAL e trava na conexão compartilhada. Cada
   recomendação emitida é persistida antes da voz, com snapshot e versão. Histórico
   de avaliações preservado. Sem escrever um snapshot a cada 500ms, reduzindo I/O.
7. **Voz fora da UI/receptor.** Worker com fila limitada e prazo, System.Speech
   pelo Windows PowerShell; texto entra por stdin como JSON, sem interpolar comando.
   Falha de áudio não derruba telemetria. Não muda ExecutionPolicy e não requer
   rede. Inicializar a voz por alerta pode adicionar latência; medir no Windows
   antes de trocar por worker persistente.
8. **Sem overlay neste marco.** Evita atrasar o teste de integração. Uma futura
   janela topmost click-through usaria APIs da própria janela, sem tocar no Dota,
   e precisaria de validação específica em Borderless.
9. **Sem tabelas de preços não verificadas.** Item alvo e custo restante são
   configuração manual; power spikes e metas são heurísticas explícitas. Uma
   futura base por patch precisará de fonte/versionamento e testes próprios.

Limites conhecidos: eventos pontuais durante cooldown global são descartados,
não enfileirados; listas/receitas por herói e identificação de componentes não
existem. Voz depende de um sintetizador instalado e não foi validada em Windows
neste ambiente. Métricas de latência e FPS aguardam o teste de aceitação real.
