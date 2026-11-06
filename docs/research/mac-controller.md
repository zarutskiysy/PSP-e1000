# Track A research: PSP E1000 as a Mac control deck

Scout report, 2026-11-07. Research only; no code was written or run on hardware.
Repo dates come from `gh api repos/...` (`pushed_at`) on 2026-11-07.

## Summary

- E1000 has no Wi-Fi. The mini-USB port (USB 2.0 Hi-Speed device) is the only data link; the headset jack is the only other wire.
- A custom USB device needs a kernel PRX that calls `sceUsbbd*`. The pspsdk ships an open header (`src/usb/pspusbbus.h`) and stubs (`-lpspusbbus_driver`).
- Prior art covers both routes. The vendor-bulk route is psplinkusb `usbhostfs.prx` (BSD-3) plus `usbhostfs_pc` (libusb; pspdev docs say macOS needs no extra setup). The HID route has three examples: FuSa GamePad (HID gamepad, GPL-3.0), hnaves `hidmouse` (HID mouse, no license) and muxira/PSPad (HID / DS4 / X360, Oct 2026, tested on PSP-3001 with CFW 6.61, no license).
- **Recommendation:** reuse the unmodified psplinkusb `usbhostfs.prx` and `usbhostfs_pc`. The PSP app writes our framed protocol into async channel 4. `usbhostfs_pc` exposes that channel on Mac TCP `localhost:10004`. A Python daemon reads it and posts CGEvents. This needs no new USB code on either side, and the mock is a plain TCP server on port 10004.
- **Feasibility verdict: doable tonight (emulator+mock only).** Everything except the physical USB hop can be built and verified tonight (PSP UI in PPSSPP; Mac daemon via mock + dry-run). The USB hop reuses proven components, so the hardware run should mostly be a smoke test. Its residual risk is CFW-specific (see Risks).

## Facts table

| # | Claim | Verified? | Source |
|---|---|---|---|
| 1 | PSP-E1000 has no Wi-Fi; mono speaker | Yes (multiple press reports of Sony's spec sheet) | [Softpedia: "Cheaper PSP E-1000 Doesn't Have Wi-Fi or Stereo Sound"](https://news.softpedia.com/news/Cheaper-PSP-E-1000-Doesn-t-Have-Wi-Fi-or-Stereo-Sound-Full-Specs-Revealed-217787.shtml), [Siliconera specs](https://siliconera.com/new-european-100-psp-e-1000-specs-detailed), [iFixit E1000](https://www.ifixit.com/Device/PSP_E1000). TheSixthAxis spec page was blocked by a bot check, not read |
| 2 | E1000 ports: DC IN 5V, Hi-Speed USB (USB 2.0 compliant), headset connector | Partly (search snippet of the Sony spec list; page not fetched) | [TheSixthAxis](https://www.thesixthaxis.com/2011/08/22/tech-specs-released-for-psp-e1000/) (UNVERIFIED by direct read) |
| 3 | The PSP is USB *device*-only (cannot be a host), so any PC link means emulating a device in software | Yes (consistent with all code below; Habr article cited by search) | [habr.com/post/213513](https://habr.com/post/213513) (not read directly) |
| 4 | Custom USB device = kernel PRX using `sceUsbbdRegister`, `sceUsbbdReqSend/Recv`, then `sceUsbStart(bus)`, `sceUsbStart(driver)`, `sceUsbActivate(pid)` | Yes (read source) | [psplinkusb usbhostfs/main.c](https://github.com/pspdev/psplinkusb/blob/master/usbhostfs/main.c) (`PSP_MODULE_INFO(..., PSP_MODULE_KERNEL, ...)` l.26, `sceUsbbdRegister` l.1299); [psplink/util.c `init_usbhost`](https://github.com/pspdev/psplinkusb/blob/master/psplink/util.c) l.~413-455 |
| 5 | Open pspsdk header exists: `src/usb/pspusbbus.h` with `sceUsbbdRegister/Unregister/ClearFIFO/Stall/ReqSend/ReqRecv/ReqCancel/ReqCancelAll`; stubs in `sceUsbBus_driver.S` (link `-lpspusbbus_driver`) | Yes | [pspsdk/src/usb/pspusbbus.h](https://github.com/pspdev/pspsdk/blob/master/src/usb/pspusbbus.h) (last changed 2020-05-07), [sceUsbBus_driver.S](https://github.com/pspdev/pspsdk/blob/master/src/usb/sceUsbBus_driver.S) |
| 6 | psplinkusb uses VID 0x054C / PID 0x01C9 | Yes | [usbhostfs/usbhostfs.h](https://github.com/pspdev/psplinkusb/blob/master/usbhostfs/usbhostfs.h) (`HOSTFSDRIVER_PID 0x1C9`, `SONY_VID 0x54C`), [usbhostfs_pc/50-psplink.rules](https://github.com/pspdev/psplinkusb/blob/master/usbhostfs_pc/50-psplink.rules) |
| 7 | usbhostfs interface is vendor class 0xFF/0xFF; 3 endpoints (EP1 IN bulk 0x81, EP2 OUT bulk, EP3 async); 512 B max packet at HS, 64 B at FS | Yes (read descriptors l.60-235) | [usbhostfs/main.c](https://github.com/pspdev/psplinkusb/blob/master/usbhostfs/main.c) |
| 8 | The PSP bus forces VID 054C regardless of the descriptor; the PID is whatever is passed to `sceUsbActivate()` | Yes (empirical, PSPad field log: "Actual USB VID is now confirmed 054C, not the template's 045E") | [PSPad docs/USB_NOTES.md](https://github.com/muxira/PSPad/blob/main/docs/USB_NOTES.md) |
| 9 | `usbhostfs.prx` exports async-channel API to **user mode** (`USBHostFS`, flags 0x4001): `usbAsyncRegister/Read/ReadWithTimeout/Write/Flush`, `usbWaitForConnect`, `usbWriteBulkData`; user stub lib `libusbhostfs` | Yes | [usbhostfs/exports.exp](https://github.com/pspdev/psplinkusb/blob/master/usbhostfs/exports.exp), [libusbhostfs/USBHostFS.S](https://github.com/pspdev/psplinkusb/blob/master/libusbhostfs/USBHostFS.S) |
| 10 | Channels 0-3 are reserved by psplink; `ASYNC_USER = 4`; `MAX_ASYNC_CHANNELS = 8` | Yes | [usbhostfs/usbasync.h](https://github.com/pspdev/psplinkusb/blob/master/usbhostfs/usbasync.h) |
| 11 | `usbhostfs_pc` exposes async channel *i* as a TCP server on `BASE_PORT + i` (default base 10000, `-b` to change), so channel 4 is `localhost:10004` | Yes (`make_socket(g_baseport + i)` l.3180) | [usbhostfs_pc/main.c](https://github.com/pspdev/psplinkusb/blob/master/usbhostfs_pc/main.c) |
| 12 | RemoteJoy (in psplinkusb) uses exactly this pattern: kernel PRX does `sceUsbStart(bus)` → `sceUsbStart("USBHostFSDriver")` → `sceUsbActivate(0x1C9)` → `usbAsyncRegister(ASYNC_USER)`, and its PC client talks over the TCP port | Yes | [tools/remotejoy/main.c](https://github.com/pspdev/psplinkusb/blob/master/tools/remotejoy/main.c) l.530-582 |
| 13 | RemoteJoy direction is **PC→PSP input** (a PC joypad drives the PSP, by hooking `sceCtrl*`), plus PSP→PC screen. It is not a PSP→PC controller | Yes (README) | [tools/remotejoy/README](https://github.com/pspdev/psplinkusb/blob/master/tools/remotejoy/README) |
| 14 | pspdev's toolchain build installs `usbhostfs_pc` (and `pspsh`) on every non-Windows host, macOS included | Yes (build script) | [pspdev/pspdev scripts/004-psplinkusb-extra.sh](https://github.com/pspdev/pspdev/blob/master/scripts/004-psplinkusb-extra.sh). Whether the prebuilt `pspdev-macos-latest-arm64.tar.gz` (release v20261101) bundles a runnable `usbhostfs_pc` and links libusb dynamically: UNVERIFIED (not downloaded) |
| 15 | "MacOS should not require any additional setup" for PSPLINK, i.e. no kext/driver for the vendor-class device | Yes (official docs). Consistent with libusb behaviour: macOS has no kernel driver for class 0xFF, so `libusb_claim_interface` works unprivileged | [pspdev.github.io/debugging.html](https://pspdev.github.io/debugging.html). libusb background: [libusb#906](https://github.com/libusb/libusb/issues/906) (detach is only needed when a kext owns the interface) |
| 16 | psplink.zip release (prebuilt PSP side incl. `usbhostfs.prx`) latest v3.2.1 (2025-07-06); repo active (last push 2026-11-03, async-receive lifecycle fixes) | Yes | [psplinkusb releases](https://github.com/pspdev/psplinkusb/releases) |
| 17 | Kernel PRX can be loaded from a **user-mode** EBOOT on CFW 6.61: PSPad's EBOOT is `PSP_MODULE_INFO("PSPad", 0, ...)` and calls `sceKernelLoadModule` + `sceKernelStartModule` on its `PSP_MODULE_KERNEL` PRX. FuSa does the same with `pspSdkLoadStartModule(..., PSP_MEMORY_PARTITION_KERNEL)` | Yes (code read). PSPad claims it is hardware-tested on PSP-3001 / CFW 6.61; not tested on E1000 or LME/ARK-4 | [PSPad src/eboot/runtime_loader.c](https://github.com/muxira/PSPad/blob/main/src/eboot/runtime_loader.c), [FuSa src/app/main.c](https://github.com/andy-man/psp-fusa-gamepad/blob/main/src/app/main.c) l.176 |
| 18 | PRO CFW: "Run your own unsigned applications, both user and kernel mode"; ships an extended KUBridge. ARK-4: "compatible with legacy 1.50 software" (LEDA) | Yes (READMEs) | [procfw mirror README](https://github.com/jomkingal/procfw), [ARK-4 README](https://github.com/PSP-Archive/ARK-4), [GameBrew PRO](https://www.gamebrew.org/wiki/PRO_Firmware_PSP) |
| 19 | A kernel-mode *main EBOOT* (`PSP_MODULE_INFO` flag 0x1000, like pspsdk's `samples/usb/storage`) is the 1.50-kernel style and is not the normal path on 6.xx; use a user EBOOT plus a separate kernel PRX | Partly: the sample uses 0x1000 (read); "not supported on 6.xx without LEDA" is community knowledge | [pspsdk samples/usb/storage/main.c](https://github.com/pspdev/pspsdk/blob/master/src/samples/usb/storage/main.c) l.32. 6.xx restriction: UNVERIFIED by a primary source |
| 20 | Class-compliant HID from a PSP exists and works without host drivers (gamepad, mouse, keyboard) | Yes (source read for FuSa, hidmouse, PSPad; Keyse only from wiki) | see Prior art |
| 21 | PPSSPP HLE implements `sceUsbStart/Stop/GetState/Activate` but **not** `sceUsbbd*` | Yes (grep of `Core/HLE/sceUsb.cpp`; no `sceUsbbdRegister` in repo) | [ppsspp Core/HLE/sceUsb.cpp](https://github.com/hrydgard/ppsspp/blob/master/Core/HLE/sceUsb.cpp) |
| 22 | CGEvent APIs: `CGEventCreateMouseEvent`, `CGEventCreateKeyboardEvent`, `CGEventCreateScrollWheelEvent2`, `CGEventPost`; `CGPreflightPostEventAccess()` / `CGRequestPostEventAccess()` (macOS 10.15+) | Yes (local macOS SDK headers `CoreGraphics/CGEvent.h` l.107, 405, 408) | [Apple CGEvent docs](https://developer.apple.com/documentation/coregraphics/cgevent) (URL not fetched) |
| 23 | Posting synthetic events needs the Accessibility (TCC) grant. A script run from Terminal inherits **Terminal's** grant; `AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})` shows the prompt | Yes (community docs, consistent with Apple behaviour) | [docs.rs autoitx permissions.rs](https://docs.rs/crate/autoitx/latest/source/src/backend/macos/permissions.rs). Apple primary doc not fetched (UNVERIFIED link: [AXIsProcessTrustedWithOptions](https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions)) |
| 24 | Media play/pause: `NSEvent.otherEventWithType_...(NSSystemDefined=14, flags 0xa00/0xb00, subtype=8, data1=(NX_KEYTYPE_PLAY<<16)|((0xa if down else 0xb)<<8), data2=-1)`, then `CGEventPost(0, ev.CGEvent())`. `NX_KEYTYPE_PLAY=16`, `NX_SUBTYPE_AUX_CONTROL_BUTTONS=8` | Yes (gist read; constants checked in local SDK `IOKit/hidsystem/ev_keymap.h` l.74 and `IOLLEvent.h` l.186) | [gist fredrikw/4078034](https://gist.github.com/fredrikw/4078034), [SO 11045814](https://stackoverflow.com/questions/11045814/emulate-media-key-press-on-mac) |
| 25 | Key codes: `kVK_ANSI_3=0x14`, `kVK_UpArrow=0x7E`, `kVK_DownArrow=0x7D`, `kVK_LeftArrow=0x7B`, `kVK_RightArrow=0x7C`, `kVK_Return=0x24`, `kVK_Space=0x31`, `kVK_Escape=0x35` | Yes (local SDK `HIToolbox/Events.h`) | local SDK |
| 26 | Mission Control can be launched with `open -a "Mission Control"` (the app exists at `/System/Applications/Mission Control.app` on this Mac); default hotkey is Ctrl+Up | App presence verified locally; the `open -a` behaviour and the Ctrl+Up default are UNVERIFIED (well-known, not tested) | local filesystem |
| 27 | Screenshot: `/usr/sbin/screencapture` exists on this Mac. Synthesising Cmd+Shift+3 (keycode 0x14 with Cmd+Shift flags) also works in principle | CLI presence verified locally; key-combo route UNVERIFIED | local filesystem |
| 28 | Measured PSP HID report rate: ~124-125 completed reports/s (≈8 ms) with a 4 ms endpoint interval; 1 ms service wakeups did not raise it. `sceCtrl` sampling reached 179 Hz with sampling cycle 5555 µs | Yes (field log, PSP-3001 / CFW 6.61, Windows host) | [PSPad docs/USB_NOTES.md](https://github.com/muxira/PSPad/blob/main/docs/USB_NOTES.md) |

## Prior art

| Name | URL | Last activity | What it is / what to reuse | License |
|---|---|---|---|---|
| psplinkusb (`usbhostfs.prx`, `usbhostfs_pc`, RemoteJoy) | https://github.com/pspdev/psplinkusb | pushed 2026-11-03; release v3.2.1 2025-07-06 | **Primary reuse.** Vendor-class bulk USB driver plus async channels; Mac host bridge to TCP. Reuse `usbhostfs.prx` unmodified, `libusbhostfs` stubs, the RemoteJoy start sequence, and `usbhostfs_pc` as is | BSD-3-Clause |
| pspsdk | https://github.com/pspdev/pspsdk | pushed 2026-11-05 | `pspusbbus.h`, `pspusb.h`, `-lpspusbbus_driver`, `-lpspusb` | BSD-style (GitHub: NOASSERTION) |
| FuSa GamePad (Andy_maN; USB research by hnaves) | https://github.com/andy-man/psp-fusa-gamepad ; [GameBrew](https://www.gamebrew.org/wiki/FuSa_GamePad_PSP) | v0.3 2010-01-03; repo upload 2025-01-08 | HID gamepad (4 axes, POV, 12 buttons), PID 0x01CB, single-file PRX `src/prx/usbhid.c` + descriptors `usbhid.h`; user EBOOT loads it with `pspSdkLoadStartModule`. Claims Windows/macOS/Linux/PS3 without drivers; CFW 3.80+ (not stated for 6.6x). Best minimal HID template | GPL-3.0 (copying makes our PSP code GPL) |
| hidmouse (hnaves, mirrored by esxgx) | https://github.com/esxgx/hidmouse | 2012-06-19 | HID **mouse** PRX (3 buttons + X/Y/wheel, PID 0x7D): `prx/hidmouse.c` has a ready mouse report descriptor and the update loop (nub → relative X/Y, D-pad → wheel) | None stated (all rights reserved; reference only) |
| pspusb (hnaves "PSP Open Edition USB driver") | https://github.com/esxgx/pspusb | 2012-06-19 | Older reverse-engineered `sceUsbbd` header/driver | None stated |
| PSPad (muxira) | https://github.com/muxira/PSPad | created and pushed 2026-10-15; v1.0.0 2026-10-15 | Modern HID / DS4 / X360 controller, **hardware-tested on PSP-3001 / CFW 6.61**, CI build, host unit tests with `tests/psp_stubs`. Most valuable for *gotchas* (`docs/USB_NOTES.md`: EP0 handling, endpoint-table terminators, 125 Hz measurement, VID override) and for the user-EBOOT → kernel-PRX loader pattern (`src/eboot/runtime_loader.c`) | **No license** ("publishing source alone does not grant an open-source license"). Read, do not copy |
| Keyse (kgsws) | [GameBrew](https://gamebrew.org/wiki/Keyse_PSP) | 2011-02-24 | PSP as USB **HID keyboard + mouse**, with game/realtime/macro modes. Closest functional match to track A's HID variant. Source only inside a zip on GameBrew (not downloaded, not inspected) | GPL (per GameBrew; UNVERIFIED) |
| remotejoy-minus (SourceK78) | https://github.com/SourceK78/remotejoy-minus | pushed 2026-11-03 | Standalone USB PRX derived from RemoteJoy/RemoteJoyLite (PC/RP2040 → PSP input). Modern reference for a standalone `sceUsbbd` PRX on current CFW | BSD-3-Clause |
| RemoteJoyLite (Kethen/TyRaNiD lineage) | [GameBrew](https://gamebrew.org/wiki/Remote_Joy_Lite_PSP), [ConsoleMods](https://consolemods.org/wiki/PSP:RemoteJoyLite_Streaming_Plugin) | n/a | PSP screen → Windows PC, PC input → PSP. Plugin blocks USB file transfer while enabled. No official GitHub repo found | "Mixed" (GameBrew) |
| psp-uvc-usb-video-class (xerpi) | https://github.com/xerpi/psp-uvc-usb-video-class | 2020-10-04 | Class-compliant UVC device from PSP: proof that standard classes work through `sceUsbbd`; relevant to track B | None stated |
| capusbpsp (173210) | https://github.com/173210/capusbpsp | 2015-03-11 | Hooks to capture PSP USB traffic; debugging aid | GPL-3.0 |
| VitaPad (Rinnegatamante) | https://github.com/Rinnegatamante/VitaPad | 2023-07-26, archived | Vita → PC over Wi-Fi with a PC client (vJoy/ViGEm). Design reference for "handheld runs a server, PC daemon injects input" | None stated |
| VitaOxiPad | https://github.com/DvaMishkiLapa/VitaOxiPad | 2026-02-03 | Successor to VitaPad (Rust PC client); good protocol design reference (Wi-Fi) | NOASSERTION |
| vitastick (xerpi) | https://github.com/xerpi/vitastick | 2022-06-16 | Vita as a USB HID gamepad via a kernel plugin: the Vita analogue of the HID route | None stated |
| Springo77/vitapad | https://github.com/Springo77/vitapad | 2026-02-20 | Vita USB gamepad plugin with touchpads | None stated |
| InputRedirectionClient-Qt (TuxSH) | https://github.com/TuxSH/InputRedirectionClient-Qt | 2020-04-22 | **PC → 3DS** direction (opposite of ours); reference only for packet format/rate | MIT |
| ds4vita (xerpi) | https://github.com/xerpi/ds4vita | 2021-05-15 | DS4 → Vita (opposite direction); not relevant beyond naming | None stated |
| WiFiController / "PSP controls your PC" (2006) | [Engadget 2006](https://www.engadget.com/2006-08-06-psp-controls-your-pc-then-the-world.html) | 2006 | Wi-Fi + PPJoy, FW 1.50, Windows; historical only (E1000 has no Wi-Fi) | UNVERIFIED |

"PSPad" turned out to be the 2026 USB HID project above, not a Wi-Fi app. I found no PSP→Mac CGEvent project.

## Recommended approach

### Architecture (primary: vendor bulk via psplink's usbhostfs)

```
PSP: EBOOT (user mode)                               Mac
 ├─ loads usbhostfs.prx (kernel, from psplink.zip,   usbhostfs_pc (from pspdev toolchain)
 │   BSD, unmodified)                                  └─ libusb claims 054C:01C9 iface 0
 ├─ sceUsbStart("USBBusDriver"),                       └─ async ch.4  ⇄  TCP localhost:10004
 │   sceUsbStart("USBHostFSDriver"),                                       ⇅
 │   sceUsbActivate(0x1C9)                           psp_deck daemon (Python 3.12)
 ├─ usbAsyncRegister(4, &endp)                         ├─ transport: TCP client :10004
 ├─ 60-180 Hz: sceCtrlPeekBufferPositive →             │   (mock: fake_psp.py = TCP server :10004)
 │   common/ frame {buttons, Lx, Ly, wheel_action}     ├─ decode common/ frames
 │   → usbAsyncWrite(4, buf, len)                      ├─ mapper: nub→Δmouse (deadzone, accel curve),
 └─ action wheel UI (pspgu / debug screen), reads      │   L/R→clicks, D-pad/face→keys, wheel id→macro
     wheel.cfg from ms0:, sends ACTION(id)             └─ backends: CGEvent (real) | dry-run (log JSON)
```

Why this one:
1. **Zero new USB code.** PSP side: `usbhostfs.prx` is used unmodified (prebuilt in `psplink.zip` or built by pspdev). Mac side: `usbhostfs_pc` already does libusb and exposes channels as TCP. Our code only does `usbAsyncWrite` on the PSP and `socket.connect(("127.0.0.1", 10004))` on the Mac.
2. **The mock is trivially faithful.** `tools/fake_psp.py` listens on TCP 10004 and emits the same frames. The daemon cannot tell the difference, so the mock exercises the same code path end to end.
3. **Hardware smoke test is free.** In the morning, run stock PSPLINK plus `usbhostfs_pc` first. If `pspsh` connects, the USB link, the cable, macOS libusb and CFW kernel loading are all proven before our app is involved.
4. Shell-command macros and the config-defined wheel need a Mac process anyway. The HID route alone cannot run `open -a ...` or arbitrary commands.

Note for the orchestrator: if `common/` keeps a direct pyusb transport for tracks B/C, it must speak the usbhostfs wire protocol, or B/C will need their own PRX. That protocol is `HOSTFS_MAGIC`/`ASYNC_MAGIC` headers, a HELLO reply on EP2, and async data on EP3 (see `usbhostfs_pc/main.c`). For track A, the TCP bridge is simpler and lower risk.

### Exactly what to reuse

PSP side:
- `pspdev/psplinkusb` release `psplink.zip` → copy `usbhostfs.prx` next to our `EBOOT.PBP`. Alternatively build `usbhostfs/` (Makefile: `USE_KERNEL_LIBS=1`, `LIBS=-lpspusbbus_driver`, `build_prx.mak`).
- `usbhostfs/usbasync.h` (struct `AsyncEndpoint`, `ASYNC_USER`, prototypes) and `usbhostfs/usbhostfs.h` (`HOSTFSDRIVER_NAME "USBHostFSDriver"`, `HOSTFSDRIVER_PID 0x1C9`). These are BSD, so the headers can be vendored.
- Link the user stubs from `libusbhostfs/USBHostFS.S` (library `USBHostFS`, flags 0x4001), or vendor that `.S` file.
- Start sequence copied from `tools/remotejoy/main.c` l.530-556 (`sceUsbStart(PSP_USBBUS_DRIVERNAME)`, `sceUsbStart(HOSTFSDRIVER_NAME)`, `sceUsbActivate(HOSTFSDRIVER_PID)`, `usbAsyncRegister(ASYNC_USER, &g_endp)`). Write path: `usbAsyncWrite(ASYNC_USER, ...)` (l.519).
- Loader: user-mode EBOOT (`PSP_MODULE_INFO(name, 0, 1, 1)`) → `pspSdkLoadStartModule("usbhostfs.prx", PSP_MEMORY_PARTITION_KERNEL)` (FuSa `src/app/main.c` l.176 pattern). If that fails, fall back to `sceKernelLoadModule` + `sceKernelStartModule` (PSPad pattern) and log the error code to `ms0:/PSP/GAME/<app>/log.txt`.
- Input: `sceCtrlSetSamplingCycle(0)`, `sceCtrlSetSamplingMode(PSP_CTRL_MODE_ANALOG)`, `sceCtrlPeekBufferPositive`. Lx/Ly are 0..255 with center ~128; apply a deadzone of ~±20 on the Mac side, not the PSP side.
- The emulator path must not call into the PRX. PPSSPP has no `sceUsbbd` HLE. Use a compile flag or "PRX load failed → offline UI mode", so the action wheel still runs in PPSSPP.

Mac side (Python 3.12, `pyobjc-framework-Quartz` + `pyobjc-framework-Cocoa`; neither is installed now):
- Mouse move: get the current position with `Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))`, add the delta, clamp to `CGDisplayBounds(CGMainDisplayID())` (or the union of displays), then `CGEventCreateMouseEvent(None, kCGEventMouseMoved, pt, kCGMouseButtonLeft)` → `CGEventPost(kCGHIDEventTap, ev)`. **While a button is held, post `kCGEventLeftMouseDragged`, not MouseMoved**, otherwise drags don't work.
- Clicks: `kCGEventLeftMouseDown/Up` (L), `kCGEventRightMouseDown/Up` (R). For a double click, set `CGEventSetIntegerValueField(ev, kCGMouseEventClickState, 2)`.
- Scroll (e.g. nub + held button): `CGEventCreateScrollWheelEvent2(None, kCGScrollEventUnitLine, 1, dy)` (some pyobjc versions only expose `CGEventCreateScrollWheelEvent`).
- Keys: `CGEventCreateKeyboardEvent(None, keycode, True/False)`, plus `CGEventSetFlags(ev, kCGEventFlagMaskCommand | kCGEventFlagMaskShift)` for combos. Keycodes are in fact #25.
- Play/pause: the gist recipe in fact #24. Import `NSEvent` from `AppKit` rather than `Quartz.NSEvent`.
- Mission Control: `subprocess.run(["open", "-a", "Mission Control"])`, with Ctrl+Up (`0x7E` + `kCGEventFlagMaskControl`) as fallback. Screenshot: `screencapture -x ~/Desktop/psp-<ts>.png` (more reliable than synthesising Cmd+Shift+3). Shell commands: `subprocess.Popen(cmd, shell=True)` from the config; log every execution.
- Permission: at startup, check `Quartz.CGPreflightPostEventAccess()`. If it returns False, call `CGRequestPostEventAccess()` (or `AXIsProcessTrustedWithOptions` with prompt), print "grant Accessibility to <Terminal app>", then continue in dry-run. Dry-run backend = the same mapper, but events are appended as JSON lines so they can be asserted in tests.
- Config: one TOML/JSON file shared by both sides. It defines the wheel slots (label, action type `key|combo|media|app|shell|mission_control|screenshot`, args). The PSP gets only labels + ids (copied to `ms0:` or sent over the link at connect); the Mac owns the actions.

### Optional variant / phase 2: class-compliant HID (no Mac daemon for basic input)

If a no-install mode is wanted later, write a separate kernel PRX in the FuSa/hidmouse structure. Use **one HID interface with report IDs**: 1 = keyboard (boot-keyboard style), 2 = mouse (buttons + rel X/Y/wheel), 3 = Consumer Control (usage page 0x0C: Play/Pause 0xCD, volume). That gives mouse, keys and media with zero Mac software. Wheel macros like Screenshot and Mission Control (Ctrl+Up) become key chords; shell commands still need Mac software. Option: map them to F13-F19 and bind those in macOS Shortcuts.

Reuse: the descriptor/driver layout from FuSa `src/prx/usbhid.h` + `usbhid.c` (GPL-3.0, so a PRX derived from it is GPL), or write it fresh using `pspusbbus.h` (BSD). The mouse report descriptor is in hidmouse `prx/hidmouse.c` l.18-46 (no license, so retype it from the USB HID spec rather than copy). Note: an HID *gamepad* (FuSa/PSPad) does not move the macOS cursor by itself; only mouse/keyboard usages do.

## Latency estimate

No published end-to-end PSP→PC latency measurement was found. The only measured rate is PSPad's 124-125 completed HID reports/s (fact #28).

**ESTIMATE** for the bulk route: PSP pad sampling 0-16.7 ms (vblank-synced) or ≤5.6 ms with a 5555 µs sampling cycle, plus PSP send loop period (~4-8 ms), plus USB HS bulk transfer (<1 ms for <64 B), plus the `usbhostfs_pc` thread and TCP loopback (<1 ms), plus Python decode and `CGEventPost` (<1 ms). That totals **~10-25 ms typical, ≤~30 ms worst case**. This is fine for a cursor and macro deck, not for competitive gaming. To be measured in the morning with a PSP-side timestamp echoed back (ping over channel 4).

## Risks / gotchas

1. **CFW variance.** Kernel-PRX loading from a user EBOOT is proven on CFW 6.61 (PSPad) and old M33 (FuSa). Untested on the user's unknown CFW and E1000 (E1000 = 6.60/6.61 only, so PRO-C/LME/ARK-4). Mitigation: step 0 of HARDWARE_TEST is "run stock PSPLINK". Log every `sceKernelLoadModule`/`sceUsbStart` return code to a file.
2. **Kernel-mode main EBOOT (flag 0x1000) won't work on 6.xx** without ARK-4's legacy/LEDA path. Always use a user EBOOT plus a separate `PSP_MODULE_KERNEL` PRX. Do not copy the pspsdk `usb/storage` sample's 0x1000.
3. **USB ownership conflicts.** The XMB "USB Connection" mode, RemoteJoyLite or other USB plugins in `seplugins` (RemoteJoyLite "blocks USB file transfer"), and the Go!Cam all use the same port and bus. Only one bus driver can be active; tell the user to disable USB plugins.
4. **User-mode buffers into `usbAsyncWrite`.** It is exported to user mode (0x4001), but psplink mostly calls it from kernel modules. If writes from user space misbehave (k1/address checks), fallback: a tiny kernel PRX (~50 lines, BSD) that wraps `usbAsyncWrite` with `pspSdkSetK1(0)`. UNVERIFIED either way.
5. **`usbhostfs_pc` single-client TCP.** Each channel accepts one client. The daemon must reconnect on drop and must tolerate `usbhostfs_pc` restarts. psplink's async lifecycle had fixes merged 2026-10-29 / 11-03, so build from current master.
6. **PPSSPP.** It has no `sceUsbbd`; loading `usbhostfs.prx` in the emulator may log unresolved imports or crash. Skip the load in emulator builds.
7. **macOS TCC.** The Accessibility grant goes to the *terminal app* running Python. Re-signed or venv Python binaries can trigger re-prompts. Without the grant, `CGEventPost` silently does nothing, hence the preflight check and dry-run fallback. Media-key events: the SO thread notes a cosmetic Dock glitch on Big Sur.
8. **Mouse feel.** A raw nub is noisy (8-bit, center drift). Use a deadzone, an exponential acceleration curve and sub-pixel accumulation on the Mac side, and post at a steady rate (e.g. on every frame), not only on change.
9. **HID-route specific** (if pursued): macOS may show the Keyboard Setup Assistant the first time a new HID keyboard appears (known macOS behaviour, UNVERIFIED here). The PSP forces VID 054C. EP0 class requests (GET_DESCRIPTOR report, SET_IDLE, SET_REPORT for keyboard LEDs) must be answered or stalled correctly; PSPad's USB_NOTES documents several hangs from this. PSPad also hit `sceUsbStart(driver) → 0x80243002` from missing endpoint/interface table terminators.
10. **E1000 charging over USB / power draw.** UNVERIFIED; keep the AC adapter plugged in for long sessions.

## Backup ideas (if track A stalls)

1. **PSP as MIDI beat pad.** Same transport: PSP sends pad/nub events on channel 4, and a Mac daemon maps them to MIDI notes/CC on the IAC Driver bus (`mido` + `python-rtmidi`, IAC enabled in Audio MIDI Setup) for GarageBand/Logic. Nub = pitch bend/mod wheel, face buttons = drum pads, the action wheel picks kits. Fully mockable; zero extra PSP USB work.
2. **PSP as status/now-playing/Pomodoro display.** Reverse direction on the same channel: the Mac pushes small text/JSON frames (now playing via `osascript`/MediaRemote, CPU/RAM/battery via `psutil`, Pomodoro timer), and the PSP renders them, with buttons sending back play/pause/next. Low bandwidth, so no throughput risk (unlike track B).
3. **Stream Deck clone.** The action wheel alone, a grid of 9-16 configurable macro tiles with icons on the PSP screen. It is the controller track minus mouse movement and the most useful day-to-day. It reuses everything above and is easiest to make reliable.
