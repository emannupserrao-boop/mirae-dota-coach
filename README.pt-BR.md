# Dota AI Coach — Alpha 0.2

Pacote de teste Windows: GSI → regras → prioridade → voz → SQLite → avaliação.
O Alpha 0.1 foi preservado. **Preparado para teste; aceitação do Alpha 0.2 depende
agora do teste real no Windows.** Visão experimental começa desligada.

Entrega em código Python executável com inicializadores `.cmd`, não um EXE autônomo.
Não há API paga, servidor externo, leitura de memória ou automação de gameplay.

## Instalar e abrir

1. Extraia o ZIP inteiro em **C:\DotaAICoach02**, separado da versão 0.1.
2. Use Python **3.13 de 64 bits** (3.12 também aceito), com Tcl/Tk e Python Launcher.
   Instalador oficial: https://www.python.org/downloads/windows/ . Não use Python 3.14
   neste pacote: as dependências foram selecionadas para 3.12/3.13.
3. Dê dois cliques em **Install.cmd**. Ele cria `.venv` e instala as dependências
   fixadas. Precisa de internet nesta etapa. Aguarde “Instalacao concluida”.
4. Feche o Coach 0.1. Abra **Start-Bot-Test.cmd**. O título deve indicar **TEST**.
   Não precisa executar como administrador. Mantenha o console aberto.
5. Marque **Coach ON** e **Voz ON**, volume 70. Clique **Testar voz**.
   Deve ouvir uma frase em português. Se não houver voz pt-BR instalada, usa a voz
   padrão do System.Speech; o diagnóstico registra o fallback.

## Configurar o GSI 0.2

1. Feche o Dota antes de configurar.
2. No Coach, clique **Configurar GSI 0.2…** e selecione **dota 2 beta**.
   Encontre a pasta pela Steam → Biblioteca → Dota 2 → Propriedades →
   Arquivos instalados → Explorar. Pode estar em qualquer unidade.
3. Será criado:
   `game\dota\cfg\gamestate_integration\gamestate_integration_dota_ai_coach_alpha02.cfg`.
4. Steam → Dota 2 → Propriedades → Geral → Opções de inicialização:
   acrescente **-gamestateintegration**, preservando outras opções existentes.
5. Abra/reinicie o Dota. O novo receptor usa **127.0.0.1:32124** com token local.
   O 0.1 usava 32123: não copie o CFG antigo por cima do novo.
6. Não abra portas do roteador nem exponha o receptor à rede.

O botão só cria o CFG da versão 0.2; preserva o da versão 0.1. Caso não possa gravar
na pasta da Steam, copie manualmente o CFG gerado em `%LOCALAPPDATA%\DotaAICoach02`
para a pasta `gamestate_integration` acima e autorize a cópia pelo Explorador.

## Primeiro teste real

1. No Dota, escolha Jogar → Praticar com bots → **solo**, escolha uma dificuldade
   confortável e um Carry conhecido, como Juggernaut.
2. Ao entrar, confirme **GSI CONECTADO**, contador de pacotes subindo e Hero,
   Tempo, LH, GPM, XPM, Gold, itens e habilidades atualizando no app.
3. Deixe o minimapa experimental **DISABLED** no primeiro teste.
4. Siga **docs/TESTE_REAL.md** para provocar cada regra. Comece por farm.
5. Ao ouvir uma recomendação, use Boa/Ruim/Irrelevante ao lado da última ID.
6. Clique **Exportar diagnóstico + avaliações…** antes de fechar o aplicativo.
7. Feche e reabra pelo mesmo **Start-Bot-Test.cmd**: a avaliação deve permanecer
   no histórico. O campo “última” reinicia; o histórico é persistente.

Para uso com limiares normais, abra **Start-Coach.cmd**. O modo TEST é argumento de
inicialização, nunca fica salvo. NORMAL bloqueia a ativação de Vision.

## Arquivos e dados

- `coach02/`: regras, prioridade, TTS, visão, serviço, UI, medição e SQLite do 0.2.
- `coach/`: baseline 0.1 preservado, com transporte/normalização reutilizados.
  As regras antigas não são executadas pelo novo aplicativo.
- `tests/test_alpha.py`: testes originais intactos; `test_alpha02.py`: testes novos.
- `requirements*.txt`: dependências fixadas; `Run-Tests.cmd`: suite automatizada.
- `docs/TESTE_REAL.md`: roteiro simples por regra e checklist de aceitação.
- `docs/DECISIONS.md`: arquitetura, limites e segurança.
- `docs/VALIDATION.md` e `docs/test-results.txt`: resultados e pendências reais.
- `docs/CHANGES.md`: arquivos alterados e rollback.

Dados em `%LOCALAPPDATA%\DotaAICoach02`:
`settings02.json`, `coach02-test.sqlite3` (TEST), `coach02.sqlite3` (NORMAL),
`app.log` e quatro pequenos recortes PNG de calibração, se você os criar.
O banco contém snapshots de jogo, evidências, avaliações e eventos de voz.
O relatório exporta a execução atual; o histórico do banco conserva execuções anteriores.
Não envie o CFG ou settings02.json: eles contêm o token local. O diagnóstico omite-o.

## Se algo não funcionar

- Não abriu: execute Install.cmd novamente e envie o erro do console/app.log.
- Porta em uso: feche outra instância do 0.2. Não altere a porta só de um lado.
- Sem GSI: confira arquivo 0.2, biblioteca Steam correta, opção de inicialização e
  reinicie Dota. Menu principal não comprova dados de uma partida.
- Sem calls: Coach ON, partida sem pausa, limiares cumpridos; confira Diagnóstico /
  Regras. Eventos suprimidos aparecem na exportação com o motivo.
- Sem voz: Voz ON, volume, saída padrão e mixer do Windows; Testar voz. Exporte o
  diagnóstico. A voz real precisa ser validada no seu PC.
- Vision suspenso: Dota precisa estar em primeiro plano, sem pausa, herói vivo,
  GSI recente e ROI correto. Alt+Tab suspende a captura e reinicia o rastreamento.

Para rodar por terminal: `.venv\Scripts\python.exe run.py --test-mode`.
O modo `--headless` serve ao desenvolvimento e não mostra a interface.
