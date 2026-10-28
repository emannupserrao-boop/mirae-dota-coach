# Decisões arquitetônicas — Alpha 0.2

## Separação e continuidade

Aplicação desktop Python/Tkinter, transporte HTTP local e SQLite. Mantém a stack
funcional do 0.1 para reduzir o risco da mudança. Regras e arbitragem são módulos
puros, sem Tk/Windows: poderão ser reutilizados num serviço futuro. TTS, captura,
UI e persistência são adaptadores separados. Não há backend, mobile ou LLM aqui.

`coach/` é a cópia íntegra do 0.1; o runtime 0.2 reutiliza seu receptor GSI,
normalizador, detecção de processo por nome e formatadores do painel. `run.py`
inicia somente Service/Window novos. O teste legado executa o serviço antigo
isoladamente; não prova execução das regras antigas no 0.2.

Recepção GSI enfileira snapshots numa fila limitada a 256. Um worker possui regras,
prioridade e gravações. Áudio, visão, métricas e exportação usam workers separados.
Snapshots com mais de 2s na fila são descartados, referências reiniciadas e descarte
contado. Uma lacuna GSI superior a 15s reinicia referências; sem sinal não há calls
novas. UI atualiza a cada 500ms. Avaliações pendentes são drenadas ao fechar.

## Regras conservadoras

- Farm: taxa recente, meta configurável ou janela anterior, confirmação e recuperação
  com histerese. Ausência de LH/estado vivo não é zero. Janela normal 90s, teste 20s.
- Itens: transição observada de inventário, sem anunciar o primeiro snapshot, sem
  repetir ao mover/remover/recomprar o mesmo nome. Custo restante não implementado.
- Mortes: incrementos observados de uma morte numa janela; saltos não recebem horários
  inventados. Uma call por grupo, rearm após a contagem cair abaixo do limiar.
- Buyback: ouro, custo e cooldown explícitos; mudança confirmada. NORMAL a partir
  de 20min. Não identifica importância estratégica real da luta.
- Vision: uma call por episódio de desaparecimento do mid; suporte e aliado modulam
  risco. Não se repete em escalada do mesmo episódio. Papéis definidos manualmente.

Rule IDs/version=1 e snapshots completos em cada candidato, aceito ou suprimido.
Policy ordena prioridade 1–4, aplica cooldown global, por regra e semântico. Uma
call crítica pode superar o global se a anterior tinha prioridade menor. Eventos
suprimidos não são adiados: evita recomendações antigas. Estado da regra pode
mudar mesmo quando a call é suprimida; registro explica essa decisão.

## Voz

System.Speech via Windows PowerShell, texto enviado como JSON no stdin, nunca
interpolado num comando executável. Preferência pt-BR habilitada, fallback para voz
padrão instalada. Sem API paga/rede. Fila de 3 pendentes, prazo de 15s, prioridade
descarta pendentes inferiores e cancela fala inferior ainda não iniciada. Uma frase
já iniciada não é interrompida por outra prioridade; desativar/reset/fechar pode
interrompê-la. Assim uma call crítica pode esperar o fim de uma frase curta.

SpeakStarted/SpeakCompleted registram síntese assíncrona. Latência mede recepção →
decisão e criação → evento SpeakStarted, não o som físico no fone. Processo
PowerShell é criado por fala (simplicidade de isolamento, custo de inicialização
mensurável); timeout de segurança. A validação de voz simulada não valida C#,
vozes instaladas, dispositivo de som ou latência Windows. Eventos do botão de teste
ficam em diagnostics/voice_test_event, separados de calls reais.

## Visão experimental

MSS captura só ROI manual de 100–600px por dimensão. OpenCV compara quatro pequenos
recortes por correlação; não é um modelo aprendido e não reconhece heróis/papéis
sozinho. Ambiguidade de dois picos e colisão entre papéis produzem UNKNOWN.
Confirmação em múltiplos frames, limiares diferentes, âncora no próprio ícone;
queda da captura, Alt+Tab, pausa ou herói morto suspendem a leitura.

NORMAL impede ativação. TEST exige confirmação manual de bots na interface e
calibração dos quatro papéis. O software não consegue provar que a partida é bots:
a confirmação é do usuário. Vision e TEST nunca ficam ativados em configuração
persistida. Nova sessão desativa Vision e exige conferir os ícones.

Somente pixels atualmente disponíveis ao jogador, sem spectator ou dados de
inimigos via GSI. Não há leitura de memória, DLL injection, alteração do processo,
packet sniffing ou controle de mouse/teclado. A leitura da posição do cursor serve
somente para definir o retângulo. Não se afirma aprovação da Valve: uso competitivo
e distribuição pública exigem revisão específica das políticas atuais. Bot test only.

Invisibilidade, morte, retratos animados, círculos de seleção, interface sobreposta
ou correlação ruim podem parecer desaparecimento. O mecanismo não distingue todas
essas causas; confidence é score, não probabilidade. Não confirma gank nem destino,
nem detecta automaticamente side lane/posição Carry. Aplicabilidade é manual.

## Dados e métricas

SQLite WAL separado por modo e UUID de execução/sessão, pois bots podem ter matchid
0. Sem SteamID, nomes de jogadores ou token no relatório. Matchid permitido é
mantido. Role do jogador não é inferida; rótulos visuais são manuais. Exportação é da
execução corrente; banco conserva histórico e revisões de avaliação. Snapshots e
settings são JSON dentro do SQLite/relatório para auditabilidade.

CPU/RAM/threads do próprio aplicativo e filhos TTS amostrados a cada 2s, histórico
limitado aos últimos 24min. CPU máquina é normalizada pelo número de CPUs lógicas;
processos TTS muito breves podem escapar à amostragem. Não mede FPS do Dota.
Capture FPS e latências usam janelas limitadas. Trace visual tem até 600 amostras
a no máximo 2Hz, somente metadados, sem gravação contínua de tela. Contadores do
rastreador reiniciam quando a continuidade é perdida; não são total garantido de
uma partida. Falsos positivos/negativos são marcações humanas com contexto.

## Limites deliberados

Sem classificação de teamfight: UNSUPPORTED explícito no diagnóstico. Sem alerta
de proximidade de item, previsão estratégica, overlay ou serviço externo.
GPM/XPM são exibidos/registrados, mas não têm uma sexta família de calls no 0.2.
Performance em Windows e precisão visual estão pendentes de medição real.

## Referências técnicas

- System.Speech SpeakStarted/SpeakCompleted, Microsoft Learn:
  https://learn.microsoft.com/en-us/dotnet/api/system.speech.synthesis.speechsynthesizer.speakcompleted
- Template matching, documentação OpenCV:
  https://docs.opencv.org/4.13.0/d4/dc6/tutorial_py_template_matching.html
- GSI: mantém o contrato e normalizador já testados no Alpha 0.1 do usuário.
  Nenhum campo de minimapa GSI foi assumido disponível/confiável para este caminho.
