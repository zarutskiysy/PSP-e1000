# Blackwater Ping on a real PSP E1000 (≈15 min)

**Assumed:** PSP E1000 with CFW 6.60/6.61 and PRO-C, LME or ARK-4 enabled (the launcher was run after
the last reboot). No Wi-Fi is needed. The connection is a USB data cable (Mini-B) to the MacBook.
**Not yet run on hardware.** Every "expected" below is a prediction. The game was verified only against
mocks and in PPSSPP 1.20.4.

**Do main's `docs/HARDWARE_TEST.md` step 2 (echo app, HOSTFS mode) first** if you have not. It proves
the cable, kernel-module loading and `usbhostfs_pc` with the smallest app. This game uses the same HOSTFS
path and the same two PRX files.

## 1. Build (Mac, 1 min)

```bash
cd ~/pet_projects/psp_e1000 && git checkout feat/dual-screen-game   # or use the worktree
source tools/env.sh
make -C game/psp clean && make -C game/psp
ls -l game/psp/EBOOT.PBP game/psp/usbhostfs.prx game/psp/pspmaclink.prx   # all three must exist
.venv/bin/pip install -r requirements.txt                                 # pygame-ce==2.5.8
```

## 2. Copy to the PSP (3 min)

On the PSP, open Settings → USB Connection, then plug in the cable:

```bash
mkdir -p "/Volumes/<PSP stick>/PSP/GAME/BLACKWATER"
cp game/psp/EBOOT.PBP game/psp/usbhostfs.prx game/psp/pspmaclink.prx "/Volumes/<PSP stick>/PSP/GAME/BLACKWATER/"
diskutil eject "/Volumes/<PSP stick>"
```

Exit USB Connection mode on the PSP. **Leave the cable plugged in.**

Files on the stick: `ms0:/PSP/GAME/BLACKWATER/{EBOOT.PBP, usbhostfs.prx, pspmaclink.prx}`.

## 3. Run (5 min)

1. **Mac, tab 1:** `~/pspdev/bin/usbhostfs_pc -v` and keep it running.
2. **PSP:** Game → Memory Stick → **Blackwater Ping**.
   Expected: on the left, a green sonar circle with a rotating sweep. On the right: `BLACKWATER PING  NO LINK USB`,
   and the log line `USB HOSTFS UP: RUN USBHOSTFS_PC`. Tab 1 should print a "connected" line.
   (If the log says `USB FAILED - DEMO MODE:` plus an error, see the table below. The app still runs
   against a built-in scripted demo, so you can try the controls anyway.)
3. **Mac, tab 2:**
   ```bash
   cd ~/pet_projects/psp_e1000
   .venv/bin/python game/mac/blackwater.py --transport hostfs --summary /tmp/bw_hw.json
   ```
   Expected within about 2 s:
   - the Mac title screen says `PSP linked: blackwater_psp`;
   - the PSP header turns green: `LINK USB`, and the log shows `LINK UP`.
4. **PSP: press START.** Expected: the Mac shows the dark shaft with the sub and its lamp, and the PSP shows
   HULL/BATT/NOISE bars and `DIVE! CO-OP`.
5. **Play one loop:**
   - Click the Mac window and steer down with the arrows. The PSP nub also steers (solo mode).
   - On the PSP press **✕**. Mines (yellow ×), the creature (red dot), the bulkhead (blue bar) and the
     exit (green square) appear on the scope. The Mac log shows `PSP: ACTIVE PING (LOUD)` and the Mac HUD
     shows `RTT n ms`.
   - Press **△**. A buoy (diamond) appears on the Mac map at that mine.
   - Drive into the striped bulkhead (depth 800). The PSP switches to **GATE 1 PHASE LOCK**. Match the
     yellow bars to the blue ones (←→ slot, ↑↓ value) and press **✕**. Expected: `LOCK OPEN` on the PSP,
     and on the Mac the bulkhead becomes dashed and you can pass it.
   - Do the same at depth 1600, then reach the green beacon at the bottom. Both screens should show
     **SURFACED**. (Losing is fine too. Both screens show LOST.)
   - One-person shortcut: add `--bot --easy` to the Mac command. The Mac then steers itself, and you only
     ping and crack the locks on the PSP.
6. Close the Mac window (ESC). It prints a JSON line, which is also saved to `/tmp/bw_hw.json`. HOME → exit
   on the PSP. Ctrl-C tab 1.

## 4. What to report

Paste `/tmp/bw_hw.json` into `docs/MORNING_REPORT.md`. The useful fields are:
- `rtt_ms.median` / `rtt_ms.max`: PING→PONG over USB HOSTFS. The emulator gave about 205 ms and local TCP about 0.4 ms.
  Prediction for USB: a few ms (unmeasured).
- `tx_Bps` / `rx_Bps`: link bandwidth used. Expected about 200–330 B/s Mac→PSP and about 20–40 B/s PSP→Mac,
  or up to about 350 B/s PSP→Mac while the nub is held.
- `outcome`, `stats.hacks_ok`, `gates_open`: was the loop completed?
- Also note whether the HUD RTT stays steady and whether any input felt laggy.

## Troubleshooting

| Symptom | Likely cause | Try |
|---|---|---|
| PSP log `USB FAILED - DEMO MODE:` with `load …usbhostfs.prx: 8002013C` (or similar) | CFW not active, or it blocks kernel modules from a user EBOOT | Re-run the PRO/LME/ARK launcher after a reboot. Main's HARDWARE_TEST table covers more codes. |
| `load … 80020148` / `8002014C` | bad copy or wrong file | Re-copy all three files. Sizes must match `ls -l game/psp/*.prx`. |
| `pmlStart…` / `80243…` error | USB bus busy (USB Connection mode still on, a USB plugin, the Go!Cam) | Exit USB mode, disable USB plugins in the CFW menu, unplug the camera, reboot. |
| PSP says `LINK USB` never, and the Mac says `PSP SILENT (hostfs)` | usbhostfs_pc is up but the PSP is not attached, or the HELLO was lost | Check that tab 1 printed "connected". Restart the PSP app; the Mac re-sends HELLO every 1 s. Try `usbhostfs_pc -p 0x1c9 -vv`. |
| Mac `waiting for PSP on hostfs: … refused` | usbhostfs_pc not running | Start tab 1 first. Port 10004 = channel 4. |
| Link up, but the PSP scope never updates | Mac→PSP data lost: usbhostfs keeps only a 4 KiB Mac→PSP ring and drops overflow | Run the Mac with `--state-hz 5`. Report `rx_frames` / `tx_frames` from the summary. |
| Lock never opens on the Mac after ✕ | HACK_RESULT lost, or a mismatch (wrong bars: the log says `MISMATCH: -3 S`) | Make sure all bars are green, then press ✕. The Mac re-requests the lock 25 s after an unanswered HACK_REQ. |
| Mac keys do nothing | the pygame window is not focused | Click the window. |
| PSP freezes | kernel-side problem (HOSTFS mode does not use our own USB driver, only psplink's usbhostfs) | Hold POWER for 10 s. Note what was on the screen. |
| Want to check the PSP app without USB | — | Hold **SELECT** while it starts. This forces `LINK DEMO` (a built-in scripted Mac). |
