# Validação — 23/09/2026

## Executado neste ambiente

- `python3 -m unittest discover -s tests -v`: **26 testes aprovados**.
- Compilação sintática de módulos, entrada e testes: sem erros.
- Entrada real `run.py --headless` em processo separado: abriu porta 32123,
  recebeu dois POSTs autenticados, persistiu `farm_low` e encerrou com sucesso.
- HTTP e SQLite reais; não foram substituídos por mocks nos testes de integração.
- Os payloads são fixtures sintéticas, **não capturas de uma partida real**.
- Ambiente: Linux com Python/Tk disponíveis; sem Windows, Dota ou display gráfico.

Cobertura: campos principais e ausentes, valores numéricos inválidos, spectator,
atividade não-playing, remoção de itens, farm e recuperação, mortes, nível,
buyback, item alvo, itens importantes sem repetição por movimentação, quedas de
GPM/XPM, pausa, relógio regressivo, nova partida, desativação do coach, autenticação,
rejeição de Origin/JSON inválido/corpos grandes, reconexão, diagnóstico sem token,
registro de snapshot, avaliação e histórico, exportação, persistência em outra
conexão SQLite e instalação GSI sem apagar configurações de outros programas.

Erro encontrado e corrigido durante os testes: a primeira detecção de spectator
confundia `team_name` com um nó de time. Agora só considera estruturas aninhadas.
Revisão adicional removeu uma inversão potencial de locks na notificação da voz.

## Ainda não validado

- Abertura e layout da interface em Windows, DPI e escalas diferentes.
- Execução dos `.cmd` no Windows e detecção real por tasklist.
- System.Speech, disponibilidade de voz pt-BR e cancelamento de áudio real.
- Campos e frequência enviados pela versão instalada do Dota 2.
- Latência percebida, consumo de CPU/RAM e efeito em FPS durante uma partida.
- Qualidade estratégica das heurísticas; exigirá avaliações do usuário.

Não existe alegação de teste de VAC, aprovação da Valve ou garantia de ausência
de sanções. O código não usa técnicas de acesso ao processo do jogo.

## Aceitação no PC do usuário

1. Abrir Start-Coach.cmd e ouvir Testar voz.
2. Instalar o arquivo GSI pela interface e acrescentar -gamestateintegration.
3. Reiniciar Dota e entrar como jogador em treino com bots.
4. Confirmar LIVE, Dota detectado SIM, GSI conectado e pacotes crescentes.
5. Comparar herói, relógio, LH, ouro e nível com o jogo.
6. Comprar item e verificar atualização da aba Itens.
7. Exportar diagnóstico e tirar print. Este é o primeiro marco real.
8. Validar uma recomendação e sua avaliação; exportar JSON para a próxima análise.

Interromper expansão de escopo após essa aceitação para revisar os resultados.
