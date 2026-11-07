# Hardware test: PSP as a Mac second screen (≈15 min)

**Assumption:** CFW 6.60/6.61 with PRO-C, LME or ARK-4 (can load kernel PRXs from a homebrew EBOOT). The exact CFW is unknown; nothing here has run on a real PSP yet, so every "expected" below is a prediction. PSP E1000 has no Wi-Fi: USB only, data-capable mini-USB cable, Go!Cam unplugged (same port).

Optional but recommended first: main's smoke test `docs/HARDWARE_TEST.md` (echo app, ~10 min). If it fails, this one will too; fix that first.

## 0. Build on the Mac (2 min)

```bash
cd ~/pet_projects/psp_e1000/.worktrees/second-screen      # or: git checkout feat/second-screen in any clone
PY=~/pet_projects/psp_e1000/.venv/bin/python               # the venv lives in the main checkout
$PY -m pip install -r requirements.txt                     # numpy, mss, pyobjc ScreenCaptureKit (pinned)
source tools/env.sh
make -C screen/psp clean && make -C screen/psp             # USB build by default
ls -l screen/psp/{EBOOT.PBP,pspmaclink.prx,usbhostfs.prx}
$PY -m pytest -q screen/tests                              # expect: 34 passed, 2 skipped
```

## 1. Copy to the memory stick (2 min)

PSP: Settings → USB Connection, plug in the cable. Then:

```bash
mkdir -p "/Volumes/<STICK>/PSP/GAME/pspscreen"
cp screen/psp/{EBOOT.PBP,pspmaclink.prx,usbhostfs.prx} "/Volumes/<STICK>/PSP/GAME/pspscreen/"
diskutil eject "/Volumes/<STICK>"
```

The result is `ms0:/PSP/GAME/pspscreen/EBOOT.PBP`, `pspmaclink.prx` and `usbhostfs.prx`. Do not copy `screen.cfg`: without it the app shows the menu. Exit USB Connection mode and leave the cable plugged in.

## 2. Start the app in MACLINK mode (1 min)

PSP: Game → Memory Stick → **PSP E1000 Second Screen** → press **○** (USB maclink).

Expected PSP text: `io: usb`, then a line `USB: connected, speed HIGH (480M), rx … tx …`. `waiting for host` should change to `connected` within a few seconds of plugging in.

Mac check: `$PY tools/usb_probe.py list` should show `054C:01CB speed=high (480 Mbit/s)`.

## 3. Throughput probe, Mac→PSP (2 min)

```bash
$PY screen/mac/psp_screen.py probe --transport usb --sizes 16,64,256 --mb 8
```

Expected: `USB speed code: 3`, then one line per transfer size and a Markdown table. Scout estimate: **8–16 MB/s**. The PSP shows `probe: … KB/s`.

Paste the table into `docs/MORNING_REPORT.md` and into the verdict in `screen/README.md`. The line `raw full-frame ceiling N fps` = MB/s ÷ 261,120 B.

## 4. Synthetic stream: colours, flow control, stats (2 min)

```bash
$PY screen/mac/psp_screen.py --transport usb --source test-pattern --fps 30 --duration 20
```

Expected on the PSP:
- Bars, left to right: white, yellow, cyan, green, magenta, **red**, **blue**, black.
- Three gradient strips: red, green, blue.
- An orange box moving right.
- The bottom line reads `~30fps … dec x.xms usb #N e0 c0`.

If red and blue are swapped, the pixel order is wrong; report it.

The Mac prints `[stats] sent 30 fps acked 30 fps … | PSP fps … dec … ms rtt … ms err 0` once per second.

## 5. Worst case: every tile changes (3 min)

```bash
$PY screen/mac/psp_screen.py --transport usb --source video-ish --fps 60 --lz4 off  --duration 15
$PY screen/mac/psp_screen.py --transport usb --source video-ish --fps 60 --lz4 auto --duration 15
$PY screen/mac/psp_screen.py --transport usb --source video-ish --fps 60 --lz4 auto --window 4 --duration 15
```

Write down `acked fps`, `MB/s` and PSP `dec` ms for each. Predictions (ESTIMATE): raw ~22–35 fps, LZ4 ~50 fps. Whichever is faster is the default to keep.

## 6. Real screen capture (3 min, needs a permission)

```bash
$PY screen/mac/psp_screen.py --transport usb --source screen:0,0 --fps 30            # top-left 480x272 points
```

The first run prints that Screen Recording is missing and macOS shows a prompt. To grant it:
1. Open **System Settings → Privacy & Security → Screen & System Audio Recording**.
2. Enable your terminal app (Terminal / iTerm / Cursor).
3. **Quit and reopen the terminal**, then re-run the command above.

Expected: the top-left corner of the Mac screen mirrored on the PSP, ~30 fps when it changes.

Variants:
- `--source screen:0,0,960,544` scales a larger region down to the PSP.
- `--source window:Terminal` captures one window.
- `--capture mss` tries the fallback backend.

## 7. Fallback: HOSTFS mode (only if MACLINK fails, 3 min)

1. Mac, tab 1: `~/pspdev/bin/usbhostfs_pc -v` (keep it running).
2. PSP: start the app, press **✕** (USB hostfs).
3. Mac, tab 2: `$PY screen/mac/psp_screen.py --transport hostfs --source test-pattern --fps 30 --duration 20`, then `$PY screen/mac/psp_screen.py probe --transport hostfs --mb 4`.

## Results to record

| item | value |
|---|---|
| CFW (PRO-C / LME / ARK-4, version) | |
| `probe` MB/s at 16 / 64 / 256 KiB (Mac wall, PSP-timed) | |
| test-pattern: acked fps, PSP dec ms | |
| video-ish raw / lz4 / lz4+window 4: fps, MB/s, dec ms | |
| real capture: fps, looks right? | |

## Troubleshooting

| Symptom | Likely cause | Try |
|---|---|---|
| PSP: `ERROR: psp_usb_start: 8002013C …` | CFW does not let the EBOOT load kernel PRXs, or a PRX file is missing | Check all three files are in `PSP/GAME/pspscreen/`. Re-run the CFW launcher (PRO/ARK is gone after a full reboot). See main's `docs/HARDWARE_TEST.md` table. |
| PSP: `ERROR: … 80020148 / 8002014C` | bad copy / wrong-firmware PRX | Re-copy; compare sizes with `ls -l screen/psp/*.prx`. |
| PSP stays `waiting for host` | charge-only cable, USB Connection mode still on, USB plugin (RemoteJoyLite/psplink) active, camera attached | Another cable or port; exit USB mode; disable USB plugins in the CFW menu; `system_profiler SPUSBDataType \| grep -A5 -i sony`. |
| speed shows `FULL (12M!)` | hub or cable negotiated Full-Speed (≤1.2 MB/s) | Plug directly into the Mac (USB-C adapter is fine), another cable. |
| Mac: `PSP not found on USB (VID 054c PID 01cb)` | app not in MACLINK mode, or libusb missing | Press ○ in the menu; `brew install libusb`. |
| Mac: `TimeoutError: no HELLO_ACK` | link up but frames not getting through | Run main's `tools/usb_probe.py echo --spec usb --sizes 100`; note the PSP counters (rx/tx bytes, last err). |
| Mac: `[warn] no ACK for 3.0s` repeating | PSP stalled or frames corrupted (`c` counter > 0 on the PSP line) | Lower `--window 1`, try `--lz4 off`; report `e`/`c` counters. |
| Picture OK but red and blue swapped | pixel order | Report it (encoder packs `B<<11\|G<<5\|R`, the PSP 565 order). |
| Garbage tiles that heal after ≤5 s | lost chunks, keyframe recovery working | Report the `c` (CRC/oversize) counter. |
| `Screen Recording permission not granted` after enabling it | terminal not restarted, or a different app hosts the shell | Quit and reopen the terminal; enable the app that actually runs Python (e.g. Cursor). |
| `ScreenCaptureKit did not answer` / black frames | SCK path unverified tonight | `--capture mss`. |
| PSP freezes | kernel-mode bug in pspmaclink.prx | Hold POWER 10 s. Try HOSTFS mode (step 7), which uses psplink's driver instead. |
| PSP dims / sleeps | — | The app calls `scePowerTick` every second; report it if it still sleeps. |
