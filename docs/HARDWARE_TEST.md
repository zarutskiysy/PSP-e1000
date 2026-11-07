# Hardware smoke test: USB link (≈10 min) — do this FIRST, before any track

Proves cable + CFW kernel-module loading + both USB modes, with the smallest possible app.
Assumed CFW: 6.60/6.61 with PRO-C, LME or ARK-4 (exact CFW unknown on 2026-11-07). Nothing here was
run on a real PSP yet: every result below is a prediction to check.

## 0. Build (Mac)

```bash
cd ~/pet_projects/psp_e1000 && source tools/env.sh
make -C examples/echo clean && make -C examples/echo USB=1
ls examples/echo/{EBOOT.PBP,usbhostfs.prx,pspmaclink.prx}
```

## 1. Copy to the PSP

PSP: Settings → USB Connection (or the CFW VSH menu "USB device: Memory Stick"), plug the cable, then:

```bash
mkdir -p /Volumes/<PSP stick>/PSP/GAME/PSPE1000_ECHO
cp examples/echo/{EBOOT.PBP,usbhostfs.prx,pspmaclink.prx} /Volumes/<PSP stick>/PSP/GAME/PSPE1000_ECHO/
diskutil eject /Volumes/<PSP stick>
```

Leave the cable plugged in. Exit USB mode on the PSP.

## 2. HOSTFS mode (psplink's usbhostfs, Mac tool `usbhostfs_pc`)

1. Mac, tab 1: `~/pspdev/bin/usbhostfs_pc -v` (keep running).
2. PSP: Game → Memory Stick → "PSP E1000 x Mac Echo" → press **✕** (HOSTFS).
   Expected PSP screen: `usb: ok`, `usb state: 2`. Expected tab 1: a "Connected to device" line.
3. Mac, tab 2: `.venv/bin/python tools/usb_probe.py echo --spec hostfs`
   Expected: `peer: 'echo' role=1`, then `RESULT hostfs ping rtt ms …` and echo MB/s lines. Paste them into
   `docs/MORNING_REPORT.md` (section "Measured on hardware").
4. HOME → exit the app. Stop usbhostfs_pc (Ctrl-C).

## 3. MACLINK mode (our own bulk driver, pyusb)

1. Start the app again, press **○** (MACLINK).
2. Mac: `.venv/bin/python tools/usb_probe.py list` → expected `054C:01CB  speed=high (480 Mbit/s)  pspmaclink`.
3. Mac: `.venv/bin/python tools/usb_probe.py echo --spec usb` → RTT + MB/s lines; the 65000 B line is the
   number the second-screen track needs (scout estimate 8–16 MB/s, `docs/research/second-screen.md`).

## If it fails

| Symptom | Likely cause | Try |
|---|---|---|
| PSP: `usb: load ms0:/…/usbhostfs.prx: 8002013C` or similar | CFW blocks kernel modules from a user EBOOT | Use ARK-4/PRO "recovery → plugins/advanced"? Check that the CFW is enabled (not OFW after reboot: re-run the PRO/ARK launcher). Note the code. |
| `load … 80020148` / `8002014C` | PRX built for wrong FW / bad file copy | Re-copy the three files; check sizes match `ls -l examples/echo/*.prx`. |
| `pmlStart(…): 80243…` | USB bus already used (USB mode on, RemoteJoyLite/psplink plugin active, camera plugged) | Exit USB Connection mode, disable USB plugins in the CFW menu, reboot PSP. |
| PSP shows state 1 forever | Charge-only cable, or Mac didn't enumerate | Another cable/port; `system_profiler SPUSBDataType | grep -A5 -i sony`. |
| `usb_probe list` shows nothing but PSP says state 2 | libusb not found | `brew install libusb`; check `/opt/homebrew/lib/libusb-1.0.dylib`. |
| `usb_probe echo --spec usb` times out after HELLO | ZLP / endpoint issue in pspmaclink | Run `--sizes 100` only; report the PSP screen counters (rx/tx bytes, last err). |
| hostfs: `usbhostfs_pc` never says connected | PID mismatch | `usbhostfs_pc -p 0x1c9 -vv`. |
| PSP freezes | kernel bug in pspmaclink.prx | Hold POWER 10 s. Report which mode and what you did; HOSTFS mode does not use our own bulk driver (pspmaclink only starts usbhostfs and forwards its channel 4). |
