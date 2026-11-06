# HARDWARE_TEST — PSP control deck (feat/mac-controller), ≈15 min

**CFW assumption:** PSP E1000 on 6.60/6.61 with PRO-C, LME or ARK-4 (kernel PRXs loadable from a user EBOOT).
The exact CFW was unknown when this was written (2026-11-07). **Nothing below has run on a real PSP yet.**
Every "expected" line is a prediction. Write down what actually happens.

Only USB is used (the E1000 has no Wi-Fi). Data path: PSP app → `usbhostfs.prx` async channel 4 → USB →
`usbhostfs_pc` on the Mac → TCP `127.0.0.1:10004` → `psp_deck.py` → CGEvents.

## 0. USB smoke test first (≈5 min, once)

Run `docs/HARDWARE_TEST.md` from main, **section 2 (HOSTFS mode)** only. That uses the echo app with
`tools/usb_probe.py echo --spec hostfs`. If that fails, stop and use its troubleshooting table. The deck uses
exactly the same USB path, so the deck can't work while echo doesn't.

## 1. Build (Mac, 1 min)

```bash
cd ~/pet_projects/psp_e1000/.worktrees/mac-controller    # or a clone of branch feat/mac-controller
source tools/env.sh
make -C controller/psp clean && make -C controller/psp
ls -l controller/psp/{EBOOT.PBP,usbhostfs.prx,pspmaclink.prx}
.venv/bin/python -m pip install -r requirements.txt        # pyobjc for real events (main venv: already there)
python controller/mac/psp_deck.py --check-config           # validates controller/mac/deck.toml
```

`.venv` means `/Users/semyon/pet_projects/psp_e1000/.venv`. From the worktree, run
`/Users/semyon/pet_projects/psp_e1000/.venv/bin/python` (`tools/env.sh` only adds a `.venv` that is inside
the checkout).

## 2. Copy to the PSP (2 min)

On the PSP, open Settings → USB Connection and plug in the cable. Then:

```bash
mkdir -p "/Volumes/<PSP stick>/PSP/GAME/PSPDECK"
cp controller/psp/{EBOOT.PBP,usbhostfs.prx,pspmaclink.prx} "/Volumes/<PSP stick>/PSP/GAME/PSPDECK/"
diskutil eject "/Volumes/<PSP stick>"
```

Exit USB Connection mode on the PSP and leave the cable plugged in.

## 3. Start the Mac side (1 min)

```bash
# tab 1: USB <-> TCP bridge from the pspdev toolchain (needs Homebrew libusb, already installed)
~/pspdev/bin/usbhostfs_pc -v
# tab 2: first a dry run (logs events, needs no permissions)
cd ~/pet_projects/psp_e1000/.worktrees/mac-controller
/Users/semyon/pet_projects/psp_e1000/.venv/bin/python controller/mac/psp_deck.py --transport hostfs --dry-run --events-log - --no-moves
```

Expected tab 2: `waiting for hostfs …` lines until `usbhostfs_pc` is up, then `transport hostfs open`.

## 4. Start the PSP app (1 min)

PSP: Game → Memory Stick → **PSP Deck (Mac controller)**.

Expected on the PSP:
- top bar `io:usb-hostfs  USB connected`, then `MAC LINKED` in green within ~1 s
- the wheel shows the 6 labels from `deck.toml` (Mission Ctrl, Play/Pause, Screenshot, Next track, Cmd+Tab, Downloads)
- left panel: `rtt psp->mac->psp … ms`, `mac rtt … ms in 60 Hz`, `mac events … DRY-RUN`, and a `usb rx/tx` line

Expected in Mac tab 2: `connected to psp_deck; sending 6 wheel labels`, then JSON lines for each button.

If the top bar says `io:demo` with `USB failed XXXXXXXX: …`, write down the code. Then go to the
troubleshooting table below and the one in main's `docs/HARDWARE_TEST.md`.

## 5. Dry-run checks (2 min)

| Do on the PSP | Expected JSON in tab 2 |
|---|---|
| press/release **L**, **R** | `mouse_button left/right down true` then `false` |
| **✕**, **○**, **□**, D-pad | `key return / escape / space / up…` down+up; holding D-pad gives `"repeat": true` lines after 0.4 s |
| **START** | `media playpause` |
| hold **△** + nub | `scroll` lines (cursor does not move) |
| nub | (hidden by `--no-moves`) drop that flag to see `mouse_move dx/dy` |
| hold **SELECT**, push nub toward "Screenshot", release | `key cmd+shift+3` ×2; PSP bottom line: `OK Screenshot: dry-run: key` |

## 6. Real events + Accessibility (3 min)

Ctrl+C in tab 2, then:

```bash
/Users/semyon/pet_projects/psp_e1000/.venv/bin/python controller/mac/psp_deck.py --transport hostfs
```

The first time, macOS asks for Accessibility for the terminal app (Terminal/iTerm/Cursor), and the daemon
prints how to grant it. Open System Settings → Privacy & Security → Accessibility and enable that app.
If the app isn't listed, add it with "+". The daemon polls every 2 s and continues once access is granted.
If it never continues, quit and reopen the terminal app and start the daemon again. Whether a restart is
needed is UNVERIFIED.

Expected:
- the nub moves the cursor (slow near the centre, fast at full tilt); **L** clicks, and holding **L** while moving drags a window
- **SELECT** wheel → Mission Control opens; Play/Pause toggles Music; Screenshot puts a PNG on the Desktop
- the PSP shows `LIVE` (not `no-AX!`)

## 7. Latency / rate measurement (2 min)

Leave the app idle for 30 s. The daemon prints this line every 5 s:

```
[psp_deck] input 60.0 Hz | rtt median X ms p95 Y ms | events N | fires M
```

Then Ctrl+C. The final `summary:` line has median/p95 over all pings. For a JSON copy, add
`--summary /tmp/deck.json` to the command line.

Record for `docs/MORNING_REPORT.md`:
- **report rate** = `input … Hz`. Expected ≈ 60 (one INPUT_STATE per vblank)
- **Mac→PSP→Mac RTT** = rtt median/p95. It includes `usbhostfs_pc` and both USB directions
- **PSP→Mac→PSP RTT** from the PSP screen line `rtt psp->mac->psp`
- one-way input latency ≈ RTT/2 + up to 16.7 ms of pad sampling (vblank loop) + about 0.1 ms on the Mac (measured, see README)

Optional: hold a key repeat and watch for missing JSON lines. Optional: watch for CRC errors (rx/err counters on the PSP).

## Troubleshooting (deck-specific; USB-level problems: main `docs/HARDWARE_TEST.md`)

| Symptom | Likely cause | Try |
|---|---|---|
| PSP top bar `io:demo`, note `USB failed 8002…: load …usbhostfs.prx` | PRXs not next to EBOOT, or CFW not active | Re-copy all three files into the same folder. Re-run the CFW launcher (PRO/ARK fast-recovery) and start the app again. |
| `io:usb-hostfs USB waiting for host` forever | `usbhostfs_pc` not running / not seeing the PSP | Restart `usbhostfs_pc -v`, replug cable; `usbhostfs_pc -p 0x1c9 -vv`; check cable is data-capable (step 0 passed?) |
| `USB connected` but `NO MAC` | daemon not connected to 10004 | Tab 2 must say `transport hostfs open`. Is only one client on 10004? Close other tools that use port 10004 (`pspsh` does not, `usb_probe` does) |
| `MAC LINKED` but no JSON lines when pressing | daemon stuck / wrong transport | Ctrl+C and restart the daemon; the PSP re-handshakes automatically |
| Real mode: daemon logs events but the cursor doesn't move | Accessibility not granted to *this* terminal app | Step 6. The PSP shows `no-AX!`. Remove the app from the Accessibility list and add it again. |
| Cursor drifts at rest | nub not centred on this unit | raise `[mouse] deadzone` in `controller/mac/deck.toml` (0.15 → 0.25) |
| Cursor too slow/fast | taste | `max_speed`, `exponent` in `deck.toml` |
| Wheel fires the wrong slice | labels/slice order | slice 0 is 12 o'clock and slices go clockwise in `[[wheel]]` order |
| Media key does nothing | no player running / macOS routes it elsewhere | open Music first; the NSEvent recipe is from a 2012 gist (research fact #24) and isn't tested on macOS 26 |
| Mission Control slice: `error: …` on PSP | `open -a "Mission Control"` failed | change the slice to `action = "key:ctrl+up"` |
| PSP freezes | kernel PRX bug | hold POWER 10 s; note what you did; report it |

## Future option, not built tonight: PSP as a class-compliant USB HID

A kernel PRX could make the PSP enumerate as a HID keyboard+mouse+consumer-control device instead.
Prior art is FuSa GamePad, hnaves hidmouse and muxira/PSPad. macOS would then need no daemon and no
Accessibility grant for basic input. Shell macros would still need Mac software. See
`docs/research/mac-controller.md` → "Optional variant / phase 2". Tradeoffs and risks (EP0 class
requests, licence of the prior art) are listed there.
