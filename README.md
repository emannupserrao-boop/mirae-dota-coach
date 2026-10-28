# MIRAE — Dota 2 AI Coach (Alpha 0.2)

**A local, voice-based coach for Dota 2 that reads the live game state and tells you what matters right now.**

MIRAE listens to Dota 2's official **Game State Integration (GSI)** feed, evaluates coaching rules on each snapshot, prioritizes the most important recommendation and speaks it in Portuguese. A larger evidence-based decision engine is being built and tested offline, ready to replace the rule engine in the live service. Everything runs on the player's PC: no paid API, no external server, no memory reading and no gameplay automation.

> Built by Emannuel Serrão. User-facing docs are in Portuguese ([README.pt-BR.md](README.pt-BR.md)).

## Architecture

**Live service (Alpha 0.2, running today)**

```
GSI (HTTP, 127.0.0.1 + local token) → normalization → rule engine
  → priority & cooldowns → text-to-speech (System.Speech)
  → SQLite (snapshots, evidence, player ratings, voice events)
```

**Offline decision engine (exercised by the test suite, not yet wired to the live service)**

```
observation & event foundation → context builders (farm, threat, objectives, temporal evidence)
  → option generation → safety / feasibility / risk evaluation
  → decision arbiter (pairwise trade-offs, selection hysteresis)
```

## Engineering highlights

- **Evidence-first decisions.** In the decision engine, each recommendation carries the evidence that produced it (threat state, option safety, outcome evidence), so a wrong call can be traced and rated (*Good / Bad / Irrelevant*) from the UI.
- **Versioned design specs.** The root `*_V01.md` / `*_V02.md` documents are the design contracts for each stage of the decision engine (context builder, risk evaluation, option safety, decision arbiter, selection hysteresis, live-runtime shadow mode…).
- **Large automated test suite** — 40+ test modules with thousands of unit tests (`Run-Tests.cmd`), plus a manual real-game checklist (`docs/TESTE_REAL.md`).
- **Safe by design:** the GSI receiver only listens on localhost with a per-install token; TEST and NORMAL modes are separated; the experimental minimap vision is off by default.

## Stack

Python 3.12/3.13 · Tkinter UI · SQLite · Windows System.Speech (TTS) · Dota 2 GSI · unittest

## Run

```bat
Install.cmd          :: creates .venv with pinned dependencies
Start-Bot-Test.cmd   :: TEST mode (lower thresholds, for bot matches)
Start-Coach.cmd      :: normal mode
Run-Tests.cmd        :: automated test suite
```

Then use **Configurar GSI 0.2…** in the app to install the GSI config into your Dota 2 folder and add `-gamestateintegration` to the launch options.

## Status

Alpha. The offline core and the decision pipeline are tested; real-match validation is ongoing.

*Dota 2 is a trademark of Valve Corporation. This is an independent fan project, not affiliated with Valve.*

## License

Source available for reading and evaluation. All rights reserved.
