# STATUS (orchestrator memory)

Start: 2026-11-07 02:22 MSK. Hard stop: ~10:20 MSK.

## Done (main, pushed, head 05b0005)
- Scouts A/B/C → docs/research/*.md
- common/: protocol (C header + Py mirror, golden-tested), link.c, io_pipe, io_posix_tcp, io_mailbox (emulator),
  usb/ (pspmaclink.prx own bulk driver + HOSTFS starter, psp_usb_io.c, usb.mk), usbhostfs vendored (BSD, bae0ac4)
- tools/: env.sh, fake_psp.py (echoes >=0xF1), ppsspp.py (launch/shot/input/memory), ppsspp_bridge.py, usb_probe.py
- examples/hello, examples/echo (USB=1 build verified, runs in PPSSPP), screenshots docs/img/
- docs: SETUP.md, HARDWARE_TEST.md (USB smoke test), DECISIONS.md (#1–10)
- Clean-clone build of main verified (hello, echo USB=1, C tests, pytest 8/8; one flaky emulator-fixture error once)
- Builders notified: ppsspp.py (ports A45671 B45672 C45673), mailbox+bridge (TCP A47101 B47102 C47103), USB

## Running
- Builder A feat/mac-controller (agent a8d60fe3f327a7959), B feat/second-screen (a856797967da202a7),
  C feat/dual-screen-game (ad64c13e2754b2810). First versions due ~05:30.
- Scouts (reviewers later via SendMessage): A af8362116ea1960f5, B a54fbefada454fcb1, C af3b7d072c18b0947
- caffeinate (bg)

## Track progress (03:17)
- A mac-controller: DONE at 878abe2 (review 2: no blocking; 82 tests incl. PPSSPP e2e; orchestrator clean-clone verified).
- B second-screen: fixes at af66cb8 (orchestrator verified: merged main, 47 pass); review 2 running.
- C dual-screen-game: builder v1 700c02d verified (build, host tests, 22 pass); review 1 by scout C running.
- main 6accb53: parser resync on bogus length (from review A).

## Next
- When a builder reports: verify (clean clone of branch, build, tests), then SendMessage its scout to review
- MORNING_REPORT.md at the end; README update
