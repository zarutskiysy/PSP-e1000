# Overnight goal: PSP E1000 × Mac POCs

You are the orchestrator. I'm asleep for ~8 hours and can't answer anything: never block on me —
decide, log the decision in `docs/DECISIONS.md`, keep going. On every start or wake-up, first read
`docs/STATUS.md` (if it exists) and continue from it; don't relaunch subagents that are still running.

## Goal

By morning, the private repo https://github.com/zarutskiysy/PSP-e1000 (empty right now; this folder
`/Users/semyon/pet_projects/psp_e1000` becomes its checkout) has:

- `main`: toolchain setup, shared PSP⇄Mac link code, research docs.
- Three POC branches, each building from a clean clone, verified as far as possible without hardware
  (PPSSPP emulator + a fake-PSP mock on the Mac side), each with a `HARDWARE_TEST.md` I can run on the
  real PSP in ≤15 minutes.
- `docs/MORNING_REPORT.md`: what works, what's verified vs. not, feasibility verdicts with links,
  what I need to do, recommended next step.

POC over polish. Don't spend time on UI beauty.

## My setup

- PSP E1000 (Street), CFW, runs homebrew from the memory stick. Exact CFW unknown: assume
  6.60/6.61 + PRO/LME/ARK-4 and document the assumption. PSP Go!Cam camera (came with Invizimals).
- MacBook Air, Apple Silicon (arm64), macOS 26. Present: brew, gh, docker, git, python3.12.
  Missing: cmake, PSP toolchain, PPSSPP.
- You may download and install anything needed from official sources (brew, PyPI, GitHub releases of
  pspdev / PPSSPP, etc.). Never download commercial game ISOs, Sony firmware or BIOS — PPSSPP doesn't
  need them.

## Facts to verify before building (don't trust me)

1. E1000 has no Wi-Fi → USB (and the headphone jack) are the only links to the Mac.
2. The camera plugs into the same USB port → camera and Mac link probably can't run at the same time.
   If confirmed, camera ideas are standalone or need a side channel (e.g. data-over-sound like ggwave
   through the headphone jack). Low priority tonight.
3. A custom USB device on the PSP needs a kernel-mode PRX (`sceUsbbd*`). Reference implementations:
   pspdev/psplinkusb (usbhostfs + libusb host side), RemoteJoyLite. Also check whether any homebrew
   makes the PSP a class-compliant USB HID (then no Mac-side driver is needed).
4. PPSSPP can't emulate a USB link to the host → USB code is hardware-only. Everything else must be
   testable in the emulator or through a mock transport.

## Tracks (one branch each)

**A. `feat/mac-controller`** — PSP as a Mac control deck: analog nub → mouse, L/R → clicks,
D-pad/face buttons → keys, plus a radial "action wheel" on the PSP screen for macros (Mission Control,
play/pause, screenshot, run a shell command; defined in a config file). Mac side: Python daemon
posting CGEvents (I grant Accessibility in the morning; tests use a dry-run mode) — or the HID route if
research shows it's simpler.

**B. `feat/second-screen`** — PSP as a tiny second display: Mac captures a 480×272 region/window (or a
virtual display, cf. DeskPad's CGVirtualDisplay), encodes it (RGB565 / palette + delta/RLE/LZ4),
streams over USB bulk; PSP blits to the framebuffer. Precedent: PSPDisp (Windows). Before building,
get real PSP USB throughput numbers from prior art and state the achievable fps.

**C. `feat/dual-screen-game`** — an original asymmetric game: main game on the Mac (pygame-ce is
fine), mini-game / console on the PSP, Wii U / DS style (e.g. the Mac shows a submarine in the dark,
the PSP is its sonar + hacking console). One playable loop end-to-end: fake-PSP on the Mac, and the PSP
mini-game running in PPSSPP. Original concept and assets only.

If a track turns out hardly doable (e.g. throughput makes the second screen useless, kernel USB
impossible on CFW), write the verdict with evidence, stop it, and replace it with the best idea from
the scouts' backlog. Seeds: PSP as a MIDI beat pad for GarageBand/Logic via an IAC virtual-MIDI
bridge; PSP as a now-playing / system-stats / Pomodoro display; camera-based standalone AR toy.

## Phase 0 — you, right away

- Call the keep-awake host tool if available, and run `caffeinate -dims -t 32400` in the background.
- Launch the 3 Scouts (below) first, so they research while you set up.
- `git init` here, add `origin`, main skeleton: README, `.gitignore` (toolchain, build outputs,
  `.venv`, `.worktrees/`, big binaries), `docs/STATUS.md`, `docs/DECISIONS.md`. Commit this file as is.
- Install the PSP toolchain (pspdev/pspdev prebuilt macOS-arm64 release; the docker pspdev image is the
  fallback) and PPSSPP. Build a hello-world `EBOOT.PBP` and prove it runs in PPSSPP with a saved
  screenshot in `docs/img/`. Find a scriptable way to drive the emulator (PPSSPP WebSocket remote
  debugger for input + screenshots, or PPSSPPHeadless built from source) — builders will need it.
- Shared code in `common/` on main:
  - a tiny framed protocol (magic, type, seq, len, payload, crc16) as one C header + a Python mirror;
  - Mac-side transport interface with two implementations: libusb (pyusb) and a mock (TCP/stdio);
  - `tools/fake_psp.py` that emulates the PSP end;
  - PSP-side protocol logic in plain C that also compiles on macOS for unit tests;
  - PSP-side USB bulk driver (kernel PRX, following psplinkusb's usbhostfs pattern). It must compile
    even though it can't be tested tonight; it may land after the builders start.
- Python 3.12 venv in `.venv`, deps pinned in `requirements.txt`.
- Push main. Builders may start as soon as the protocol header + mock transport are on main.

## Subagents: max 6 at once, 2 per track

Per track: one Scout and one Builder. Every brief must be self-contained (they don't see this chat):
track goal, done criteria, constraints, file locations, the rules below.

1. **Scout** (starts immediately, ≤45 min): find similar repos/projects (GitHub, wololo,
   PSP homebrew archives and forums) with working links and last-activity dates; a feasibility verdict
   (doable tonight / doable with hardware / not doable) with evidence; recommended approach and what to
   reuse; 2–3 backup ideas. Writes `docs/research/<track>.md` (no commits — you commit it on main).
   Mark anything unverified.
2. **Builder** (after its Scout and the main skeleton): works in its own git worktree
   (`git worktree add .worktrees/<track> -b feat/<track>`), never in the main checkout. Never edits
   `common/` — asks you; you change main, it rebases. Builds the PSP and Mac sides, tests,
   `HARDWARE_TEST.md`; commits often, pushes its branch.
3. Then reuse the Scout (SendMessage) as an **adversarial reviewer**: clean rebuild from scratch, run all
   tests, try to break it, check that `HARDWARE_TEST.md` steps are exact. The Builder fixes. At least
   one review round; stop when the reviewer has no blocking issues.

## Done criteria per track

- PSP: `EBOOT.PBP` builds from a clean clone with one command; runs in PPSSPP (screenshot in the
  branch's `docs/img/`); the USB path compiles.
- Mac: runs end-to-end against `fake_psp`; automated tests pass; the real-USB path is implemented and
  documented.
- `HARDWARE_TEST.md`: copy steps, run steps, expected result, what to do if it fails.
- Verdict plus measured or estimated numbers (latency, fps, bandwidth) where relevant.

## Rules

- Facts with links. Never invent repo names, numbers or APIs; mark what you couldn't verify.
- Git: commits use my existing git config. No `Co-Authored-By`, no "Generated with", no AI
  attribution anywhere. Never force-push, never rewrite main's history. No PRs — branches are enough.
- Stay inside this folder (worktrees live in `.worktrees/`) and the toolchain install dirs.
- You can't grant macOS permissions (Accessibility, Screen Recording): request them at runtime,
  test with dry-run / mock.
- Update `docs/STATUS.md` after every milestone (done / running / next) — it's your memory if the
  context gets compacted.
- When a subagent reports done, verify it yourself (build + tests) before marking it done.

## Stop when

All tracks meet the done criteria (or have a written no-go verdict and their replacement idea is done),
main and all branches are pushed, and `docs/MORNING_REPORT.md` is written — or 8 hours have passed.
Then stop the loop.
