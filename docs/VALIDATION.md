# Validação de entrega — Alpha 0.2.0

Data: 23/09/2026. Status: **preparado para teste real; aceitação pendente**.

## Executado neste ambiente

Ambiente Linux, Python do runtime disponível. Comando equivalente:
`python -m unittest discover -s tests -v`.

**66 testes passaram**, sem falhas ou skips: 26 originais + 40 do Alpha 0.2.
Saída integral: `test-results.txt` (5,346s nesta execução).
Compilação de sintaxe por `compileall` de run.py, coach02 e testes passou.

Cobertura: normalização e receptor HTTP em localhost, autenticação e rejeições,
campos ausentes, snapshots, farm/histerese/recuperação/tendência, itens e stash,
mortes em grupo, buyback, pausa, reset/recuo de relógio, prioridade, cooldown global,
por regra/semântico, deduplicação, logs e versão, feedback SQLite/exportação,
feedback drenado no encerramento, isolamento Test/Normal, fila/expiração/cancelamento
de voz, fallback e timestamps simulados; visão com confirmação múltipla, UNKNOWN,
rearm, distância do aliado, âncora, gaps e matching OpenCV com pixels artificiais.

Voz usa backend falso nos testes. Imagens são **SINTÉTICAS**, não screenshots de
Dota. Não demonstram voz Windows, precisão real do minimapa ou custo no seu notebook.
O teste HTTP usa receptor real com payload sintético. Não é partida real.

Foi encontrado e corrigido um teste de mortes que também recebia farm low; ele
agora isola sua regra. Também foram corrigidas recuperação por tendência após
janela zerada e persistência de feedback no encerramento, com regressões adicionais.

Dependências fixadas: psutil 7.2.2, numpy 2.3.5, OpenCV headless 4.13.0.92,
MSS 10.1.0, Pillow 12.3.0. Wheels Windows x64/Python 3.13 foram obtidos na preparação;
isso comprova disponibilidade dos arquivos, não execução no Windows. O teste
OpenCV rodou com 4.13.0 no runtime Linux. Install.cmd instala as mesmas versões.

Preservação: 21 arquivos originais comparados ao manifesto, zero diferenças;
12 arquivos compartilhados/legados na cópia comparados, zero diferenças.
ZIP Alpha 0.1 SHA256 continua
`0589c65a55433ef5f9270fc8de2a6cc70bdc2b77124ee6dea2dd0657cd424bbb`.
Evidência: `baseline-verification.json`.

## O que já foi validado pelo usuário antes

Alpha 0.1, Windows + Dota real: GSI conectado, centenas de pacotes, Juggernaut,
tempo, level, K/D/A, LH/denies, gold, GPM/XPM, itens e habilidades. Isso sustenta
reutilizar transporte/normalização. Não substitui o reteste do receptor na porta
32124, nem valida as regras novas.

## O que ainda NÃO foi validado aqui

- Inicializadores .cmd e janela Tk no Windows real.
- Execução do adaptador System.Speech/C#, voz audível, pt-BR/fallback e latência real.
- Calls das cinco famílias durante partida real contra bots.
- Captura MSS Windows/DPI, templates reais, precisão e estabilidade dos ícones.
- Impacto sobre FPS/fluidez do Dota e carga do notebook.
- Conformidade para uso competitivo/distribuição pública da visão experimental.

Não foi produzido EXE autônomo. O pacote é executável com Python e instaladores
.cmd. A regra de proximidade de item e teamfight detection estão explicitamente
fora, por falta de dados confiáveis. Não há alegação de “zero impacto” ou aprovação
oficial. A calibração visual manual pode ser frágil e precisar de revisão após o
primeiro relatório real.

Próximo marco: execute `TESTE_REAL.md`, avalie as recomendações, exporte o JSON e
reenvie. Paramos no Alpha 0.2; não iniciamos o Alpha 0.3.
