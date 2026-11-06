# STATUS (orchestrator memory)

Start: 2026-11-07 02:22 MSK. Hard stop: ~10:20 MSK.

## Done
- Scouts A/B/C finished 02:33–02:35 → docs/research/{mac-controller,second-screen,dual-screen-game}.md (committed on main)
- main: skeleton, common/ protocol (C+Py, golden-tested), pspmac transports (mock/hostfs/usb/tcp), fake_psp, hello EBOOT, venv, pushed
- Toolchain ~/pspdev (v20261101), PPSSPP 1.20.4 (/Applications/PPSSPPSDL.app), cmake via venv
- PPSSPP: sandbox HOME = .ppsspp_home (gitignored? -> add), debugger port 45677 confirmed listening
- Builders A/B/C launched ~02:52 in .worktrees/<track> (agent ids in conversation; reviewers = scouts A/B/C via SendMessage)

## Running
- Builder A (feat/mac-controller), Builder B (feat/second-screen), Builder C (feat/dual-screen-game)
- caffeinate (bg)

## Next (orchestrator, on main)
1. tools/ppsspp.py (launch sandboxed, screenshot, input) + hello screenshot docs/img/
2. common/psp/io_mailbox.{h,c} + tools/ppsspp_bridge.py (emulator <-> TCP 47100) — promised to builders "within ~1 hour" (~03:50)
3. common/psp/usb: pspmaclink.prx (MACLINK own driver + HOSTFS starter), vendored usbhostfs (BSD), psp_usb_io.c
4. notify builders (SendMessage) when 2 and 3 land
5. reviews by scouts, MORNING_REPORT
