# Morning report — PSP E1000 × Mac (overnight run 2026-11-07, 02:22–03:45 MSK)

**TL;DR.** All three POCs are built, tested and reviewed, **without hardware**. Each EBOOT builds from a clean clone
with one command and runs in PPSSPP. The *real* PSP code talks to the *real* Mac code end-to-end in the
emulator through a debugger bridge. The USB path compiles but has **never touched a PSP**. Your first 10 minutes:
[`docs/HARDWARE_TEST.md`](HARDWARE_TEST.md) (USB smoke test with the echo app). Then each branch's `HARDWARE_TEST.md`.

| Branch | Head | Verdict | Without hardware | Hardware test |
|---|---|---|---|---|
| `main` | latest | toolchain, link library, emulator bridge, USB PRX | C + Python tests, clean-clone build | `docs/HARDWARE_TEST.md` ≈10 min |
| `feat/mac-controller` | `9565212` | **doable with hardware**, low risk | 83 tests incl. PPSSPP e2e; deck UI + wheel in PPSSPP; daemon dry-run | `HARDWARE_TEST.md` ≈15 min |
| `feat/second-screen` | `a762968` | **doable with hardware**; expected ~20–25 fps raw, ~50 fps LZ4 full-screen (estimates) | 51 tests; pixel-exact in PPSSPP (replay + live); C decoder fuzzed (500k inputs, 0 ASan/UBSan reports) | `HARDWARE_TEST.md` ≈15 min |
| `feat/dual-screen-game` | `05dbb28` | **doable**, bandwidth trivial (< 2 KB/s) | 30 tests + PPSSPP full loop: ping → hack → bulkhead → win; PSP code fuzzed (300k frames, clean after fix) | `HARDWARE_TEST.md` ≈15 min |

No track was stopped: none hit a no-go. `main` = the commit that contains this file.

**How it was checked.** Each track: scout research → builder in its own worktree → I rebuilt from a clean clone
and ran all tests → the scout re-reviewed adversarially (clean clone, hostile frames, fuzzing, reading
HARDWARE_TEST.md as you would at 8 am) → fixes → round 2 with **no blocking issues** on all three. Review rounds
found and fixed real bugs: a daemon crash on short frames (A), an outdated USB PRX on a branch + a HOSTFS mode
that could not work (B), an out-of-bounds write / divide-by-zero in the PSP game from one hostile message (C),
and on `main` a parser stall on a bogus length and a bridge replay after an app restart.

## What you need to do (in order)

1. `cd ~/pet_projects/psp_e1000 && git pull && source tools/env.sh` (toolchain is at `~/pspdev`, venv at `.venv`).
2. **USB smoke test**, [`docs/HARDWARE_TEST.md`](HARDWARE_TEST.md): build `examples/echo`, copy 3 files to
   `ms0:/PSP/GAME/PSPE1000_ECHO/`, run it in HOSTFS (✕) and MACLINK (○) modes, paste the `RESULT …` lines below.
   This one test answers the three biggest unknowns: does your CFW load our kernel PRXs from a user EBOOT,
   does macOS libusb see the PSP, and what is the real MB/s.
3. Then whichever track you like: `cd .worktrees/<track> && git pull` (the branches are checked out there, so
   `git switch` in the main checkout would refuse), follow its `HARDWARE_TEST.md`.
   - controller: grant **Accessibility** to your terminal app when the daemon asks (first run without `--dry-run`).
   - second screen: grant **Screen Recording** for real capture (test patterns work without it).
4. Tell me the CFW (VSH menu / version string). Everything assumes 6.60/6.61 + PRO-C, LME or ARK-4.

## Measured on hardware (fill in)

| Test | Result |
|---|---|
| CFW / version | |
| `usb_probe.py list` (PID, speed) | |
| HOSTFS ping RTT (min/median/max) | |
| HOSTFS echo 3000 B MB/s | |
| MACLINK ping RTT | |
| MACLINK echo 65000 B MB/s | |
| `psp_screen.py probe` Mac→PSP MB/s 16/64/256 KiB | |

## Verified vs not

**Verified tonight (on this Mac):**
- Toolchain: pspdev `v20261101` macOS-arm64 prebuilt (psp-gcc 15.2.0), PPSSPP 1.20.4 (Homebrew cask `ppsspp-emulator`).
- `main`: protocol C header ⇄ Python mirror byte-identical (golden vectors); C link logic under ASan/UBSan; mock e2e;
  emulator e2e (echo EBOOT in PPSSPP ⇄ Python `Link`): ~200 ms RTT, ~280 KiB/s each way through the bridge.
- `usbhostfs_pc` from the toolchain runs on this Mac and listens on 127.0.0.1:10000–10007 ("waiting for device").
- Every branch: clean clone → one `make` → `EBOOT.PBP` + `usbhostfs.prx` + `pspmaclink.prx`; all tests pass;
  adversarial review by the track's scout until no blocking issues; all commits authored by you, no AI attribution.
- Screenshots of the PSP apps in PPSSPP: `docs/img/` on each branch.

**Not verified (needs the PSP):**
- Loading our kernel PRXs from a user-mode EBOOT on your CFW (`sceKernelLoadModule`, with `kuKernelLoadModule` fallback).
- `pspmaclink.prx` (our own `sceUsbbd` bulk driver, MACLINK mode) — written from psplinkusb's usbhostfs pattern,
  self-reviewed twice (2 bugs fixed: state race, channel-registration order), but never executed. HOSTFS mode
  reuses psplink's proven usbhostfs; only our small starter code is new.
- Real throughput / latency, real CGEvent posting, media keys on macOS 26, ScreenCaptureKit speed, PSP-side fps.
- PPSSPP emulator numbers are **bridge-limited** (debugger requests are served once per frame); never read them as hardware numbers.

## Track verdicts with evidence

### A. Mac control deck — `feat/mac-controller`
- Nub → mouse (deadzone + acceleration, PSP timestamps), L/R → clicks/drag, buttons → keys with repeat, △+nub scroll,
  START play/pause; hold SELECT → radial wheel, labels from `controller/mac/deck.toml`, actions: keys, media keys,
  Mission Control, open app, shell (Screenshot = `screencapture -x`).
- Transport: USB **HOSTFS** (psplink `usbhostfs.prx` async channel 4 ⇄ `usbhostfs_pc` ⇄ TCP 10004), the RemoteJoy
  pattern ([psplinkusb tools/remotejoy](https://github.com/pspdev/psplinkusb/blob/master/tools/remotejoy/main.c)).
- Numbers: 60 Hz reports by design; latency **estimate** 10–25 ms (vblank ≤16.7 ms + USB + TCP + Python). Comparable
  measured prior art: PSPad HID 124–125 reports/s on a PSP-3001 ([muxira/PSPad](https://github.com/muxira/PSPad)).
- Future option (documented, not built): make the PSP a class-compliant USB HID (FuSa GamePad, hnaves hidmouse, PSPad
  prove it works) — then no Mac daemon is needed for basic input.

### B. Second screen — `feat/second-screen`
- Mac: capture (ScreenCaptureKit, `mss` fallback) or synthetic sources → RGB565 (PSP order) 16×16 dirty tiles,
  optional LZ4 → ≤64 KiB chunks, ACK window; reconnects. PSP: decode + blit, on-screen fps/MB/s/dec ms.
- USB **MACLINK** (own bulk driver, pyusb) for bandwidth; HOSTFS works too but only as slow stop-and-wait
  (usbhostfs drops Mac→PSP data beyond a 4 KiB ring — found tonight, `common/psp/usbhostfs/main.c` `fill_async`).
- Throughput prior art: PSP USB 2.0 HS; psp-uvc measured ~16 MB/s PSP→host
  ([issue #11](https://github.com/xerpi/psp-uvc-usb-video-class/issues/11)); pspdisp-linux reports 57–60 fps host→PSP (JPEG).
- Codec measured on this Mac: test pattern 1.1 KiB/frame, scrolling text 31 KiB/frame LZ4 (256 KiB raw), encode < 1 ms.
- **Expected fps (estimate):** full-screen raw ~22 @8 MB/s / ~35 @16 MB/s; full-screen LZ4 ~50; typical UI = Mac
  capture rate (30 fps default). Legibility of a 4.3" 480×272 panel limits usefulness more than fps.

### C. Dual-screen game — `feat/dual-screen-game` ("Blackwater Ping", original)
- Mac (pygame-ce): dark flooded shaft, only the lamp shows rock. PSP: sonar scope + phase-lock hacking console.
  Each screen knows what the other doesn't. ✕ ping (loud, attracts the creature), □ listen, △ buoy, nub steers (solo).
- Bandwidth < 2 KB/s, 10 Hz state, every Mac→PSP burst < 200 B (well inside the HOSTFS 4 KiB limit).
- Played end-to-end in PPSSPP at ~200 ms RTT and still playable; USB latency to be measured by its HARDWARE_TEST.
- Worth one manual check on hardware: exit and relaunch the PSP app mid-dive (the emulator could only simulate an
  app restart, because PPSSPP 1.20.4 deadlocks on `game.reset` with the debugger attached).

## Facts checked (the four in the brief)

1. **E1000 has no Wi-Fi** — confirmed ([Wikipedia](https://en.wikipedia.org/wiki/PlayStation_Portable),
   [Softpedia spec report](https://news.softpedia.com/news/Cheaper-PSP-E-1000-Doesn-t-Have-Wi-Fi-or-Stereo-Sound-Full-Specs-Revealed-217787.shtml)).
   USB 2.0 Hi-Speed device port + headset jack are the only wires. It also has **no microphone**, so a sound side
   channel could only go PSP→Mac.
2. **Camera on the same port** — confirmed: the Go!Cam mounts on the Mini-USB slot ([Wikipedia: Go!Cam](https://en.wikipedia.org/wiki/Go!Cam)),
   so camera and Mac link are mutually exclusive. Whether the Go!Cam works on an E1000 at all is **UNVERIFIED** —
   please just try it. Audio side channel (ggwave) ≈ 8–16 B/s: scores/codes only. Camera ideas = standalone.
3. **Custom USB device = kernel PRX with `sceUsbbd*`** — confirmed (open header `pspusbbus.h` in pspsdk; psplinkusb
   usbhostfs is the reference). **HID homebrew exists**: FuSa GamePad (GPL-3.0), hnaves hidmouse, muxira/PSPad (Oct 2026).
4. **PPSSPP can't emulate USB to the host** — confirmed (no `sceUsbbd*` in PPSSPP). Workaround built tonight: mailbox
   rings in PSP RAM + `tools/ppsspp_bridge.py` over PPSSPP's WebSocket debugger, so the same PSP binary is tested
   against the Mac code. Research with all links: `docs/research/*.md`.

## Recommended next step

Run the 10-minute smoke test. Then:
- If **both modes work** → the controller deck is the quickest real win (HOSTFS, ~15 min to a working deck), then
  measure MACLINK MB/s for the screen.
- If **PRX loading fails** on your CFW → that is the one real blocker for all tracks; send me the error code from the
  echo screen (troubleshooting table in `docs/HARDWARE_TEST.md`). Fallback: run psplink's own EBOOT + `usbhostfs_pc`
  to separate "CFW blocks kernel modules" from "our PRX is wrong".
- If **MACLINK fails but HOSTFS works** → controller and game are unaffected; I fix `pspmaclink.prx` with your screen
  counters (rx/tx bytes, last error).

Against the 3-year bet (ML × physical systems × hardware/security): this is a fun side quest, not a new direction.
The one transferable piece is the PSP-side USB kernel driver + measurement harness — a small embedded/USB skill,
not a reason to open a new track.

## Where things are

- Decisions: `docs/DECISIONS.md` (main) + `docs/DECISIONS-<track>.md` on each branch. Orchestrator log: `docs/STATUS.md`.
- Setup from scratch: `docs/SETUP.md`. Architecture diagram: `README.md`.
- Worktrees (local only): `.worktrees/{mac-controller,second-screen,dual-screen-game}`.
- Installed tonight outside the repo: Homebrew `libusb` 1.0.30 (02:25) and cask `ppsspp-emulator` 1.20.4 (02:32); the
  pspdev toolchain in `~/pspdev` (download kept in `~/pspdev_dl`, safe to delete). A `brew install cmake` that started
  upgrading unrelated formulae was killed before it changed anything (no other kegs touched; cmake comes from PyPI).
  Python deps in `.venv`. PPSSPP sandbox configs in `.ppsspp_home/` (your own `~/.config/ppsspp` got a default config
  from one early un-sandboxed launch). A background `caffeinate` kept the Mac awake.
