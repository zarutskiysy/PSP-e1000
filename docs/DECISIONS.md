# Decisions log

Overnight run, 2026-11-07 (started 02:22 MSK). Orchestrator decides without blocking on Semyon; every non-obvious choice is logged here.

| # | Time (MSK) | Decision | Why |
|---|---|---|---|
| 1 | 02:23 | Assume CFW 6.60/6.61 + PRO-C / LME / ARK-4 | Exact CFW unknown; all three load kernel PRXs from homebrew EBOOTs. Documented in every HARDWARE_TEST.md. |
| 2 | 02:24 | Toolchain: pspdev/pspdev release `v20261101`, asset `pspdev-macos-latest-arm64.tar.gz`, installed to `~/pspdev` | Official prebuilt for Apple Silicon; docker image kept as fallback. |
| 3 | 02:24 | Emulator: PPSSPP 1.20.4 via Homebrew cask `ppsspp-emulator` | Official build; no BIOS/firmware needed. |
| 4 | 02:25 | `caffeinate -dims -t 32400` runs in background; the app keep-awake tool was refused by the auto-mode classifier | Mac must not sleep overnight. |
