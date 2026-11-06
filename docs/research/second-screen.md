# Track B: PSP E1000 as a Mac second screen over USB (research)

Scout report, 2026-11-07. Research only, no code. Facts link to sources. **UNVERIFIED** marks anything I could not confirm from a primary source. **ESTIMATE** marks my own engineering numbers.

## Summary

1. **The PSP's USB device port is USB 2.0 High-Speed** (512-byte bulk endpoints). Every modern PSP USB driver declares Hi-Speed descriptors: psp-uvc, psplinkusb usbhostfs, psp-cast and oasis-os. The best measured bulk number is **261 KB per frame in 16.1 ms ≈ 16 MB/s**, PSP→host ([psp-uvc #11](https://github.com/xerpi/psp-uvc-usb-video-class/issues/11)). One project claims **28 MB/s host→PSP for raw RGB565 frames at about 100 fps** ([oasis-os journal](https://andrewaltimit.github.io/oasis-os/journal/05-psp-usb-research.html)), but no one else has reproduced it.
2. Raw RGB565 at 480×272 is 261,120 B/frame, so the link alone gives **30 fps at 8 MB/s** (my conservative figure), **60 fps at 16 MB/s** (measured class), and stays at the 60 Hz vblank cap at 28 MB/s. With dirty-tile delta, typical desktop content needs only a small fraction of that.
3. A direct precedent exists for exactly this direction (host→PSP display). **PSPdisp** (JJS, BSD, v0.6.1) claims "60 fps reachable with all compression quality settings" over USB. Its 2026 Linux port **pspdisp-linux** reports **"around 57 to 60 fps"** on real hardware, using JPEG frames decoded by the PSP's hardware `sceJpegDecodeMJpeg`.
4. **The Mac side is fine.** `CGWindowListCreateImage`, the call `mss` uses, is still exported on this Mac (macOS 26.6, checked locally), but Apple deprecated it and removed it from the macOS 15 SDK. ScreenCaptureKit through `pyobjc-framework-ScreenCaptureKit` 13.0 is the supported path. libusb can claim a vendor-class interface on Apple Silicon without a kext: [remotejoy-audio](https://github.com/00xJS/remotejoy-audio) does it today, and psplinkusb's host tools build on `macos-latest arm64` in CI. Homebrew `libusb`, `lz4` and `turbojpeg` are already installed in `/opt/homebrew/lib`.
5. **The risks are on the PSP side.** A kernel PRX using `sceUsbbd*` can hang the console, and NID or ARK-4 quirks are possible. PPSSPP does not emulate `sceUsbbd*` at all, so the USB path cannot be tested in an emulator.

### Feasibility verdict: **doable with hardware**. Tonight without the PSP plugged in: **emulator + mock only**.

- **Evidence:** at least four independent working projects stream 480×272 frames over PSP USB at 20–60 fps: psp-uvc, psp-cast (tested on an **E-1000**), RemoteJoyLite/remotejoy-audio (on Apple Silicon), and PSPdisp/pspdisp-linux. Two of them go host→PSP.
- **Tonight:** PPSSPP implements `sceJpegDecodeMJpeg` ([sceJpeg.cpp](https://github.com/hrydgard/ppsspp/blob/master/Core/HLE/sceJpeg.cpp)) but has no `sceUsbbd*` (code search of hrydgard/ppsspp found none). That means the PSP blit/decode path can run in PPSSPP fed from a file or mock, and the Mac capture → encode → frame-format path can run against a loopback mock. The USB link itself needs the real PSP.

### Expected fps (calculation)

| Mode | Bytes/frame | at 8 MB/s (conservative) | at 16 MB/s (measured class) | at 28 MB/s (oasis claim) |
|---|---|---|---|---|
| Raw RGB565 full frame | 261,120 | **30.6 fps** | 61 → **60** (vblank cap) | 107 → 60 |
| 8-bit palette full frame | 130,560 | 61 → 60 | 60 | 60 |
| RGB565 dirty tiles, 10% of screen changed (ESTIMATE) | ~26 KB | 60 | 60 | 60 |
| JPEG q≈75–85 (ESTIMATE ~20–50 KB) | ~20–50 KB | 60 | 60 | 60 (decode-bound; pspdisp-linux reports 57–60) |

**Planning number:** expect **25–30 fps worst case with raw RGB565 and synchronous pyusb**, and **50–60 fps** with dirty tiles or JPEG. Both clear the ≥10 fps "useful" bar.

The real bottleneck is more likely Python-side capture/convert latency or PSP-side cache/copy handling than the USB link. Measure link throughput first (see the pipeline below).

---

## 1. Throughput evidence

Direction matters. **IN** means PSP→host. **OUT** means host→PSP, which is our direction.

| Source | Link | Number | Measured / claimed | Notes |
|---|---|---|---|---|
| psp-uvc (xerpi), issue #11 | https://github.com/xerpi/psp-uvc-usb-video-class/issues/11 | "16.1ms to send the frame through USB" for 480×272 YUY2 (261,120 B + 2 B header) → **≈16.2 MB/s IN**. Also "32.9ms to perform CSC" on CPU, so ~20 fps total | **Measured** (author's on-device timing; the `LOG("CSC: %dus, USB send: %dus")` call is in `src/main.c`) | One 261 KB `sceUsbbdReqSend`. Descriptors: Hi-Speed bulk `wMaxPacketSize 0x200` with a Full-Speed 64 B fallback (`include/usb_descriptors.h`). README: "480x272 YUY2 @ 30 FPS and 60 FPS (WIP)" |
| psp-uvc, issue #5 | https://github.com/xerpi/psp-uvc-usb-video-class/issues/5 | "framerate drops down to 18-20 fps on PSP GO 6.61 CFW PRO" | Measured by a user | Matches the CPU-conversion bound, not the USB bound |
| psp-cast (Lucaspcaldeira, MIT, 2026-10) | https://github.com/Lucaspcaldeira/psp-cast | "30 fps são ~7,8 MB/s e 60 fps ~15,7 MB/s, perto do limite prático do USB do PSP (~16 MB/s)". Has a 60 fps full-frame 16-bit mode and "sempre 32 bits (cores exatas, ~20 fps)" (≈10.4 MB/s) | **Claimed** (README); F3 overlay shows live MB/s | **Tested on a "PSP E-1000 'Street' com PRO/LME"**. IN direction. Host is Python + **pyusb** (`pc/pspcast.py`), PSP side TX in 64 KB chunks (`psp/usbdrv.c`) |
| oasis-os journal #05 | https://andrewaltimit.github.io/oasis-os/journal/05-psp-usb-research.html | "the driver sustained **~100 FPS / 28 MB/s**" | Claimed as measured; **UNVERIFIED**, small project (6★) | **OUT direction** (host→PSP), raw RGB565 stride-padded 512×272×2 = 278,528 B/frame, 16 KB chunks (`crates/oasis-usb-client-psp/src/framebuffer.rs`, `transfer.rs`). 28e6 / 278,528 ≈ 100 fps, so the arithmetic is self-consistent |
| PSPdisp v0.4 changelog | https://jjs.at/software/pspdisp.html, https://gamebrew.org/wiki/PSPdisp | "Increased USB transfer speeds, 60 fps reachable with all compression quality settings" | Claimed | OUT direction. Quality modes are JPEG levels plus "Uncompressed" (BMP). Unclear whether the 60 fps claim includes Uncompressed |
| pspdisp-linux (2026) | https://github.com/ImNoammm/pspdisp-linux | "Around 57 to 60 fps, since the PSP is vblank-locked at 60" | Claimed, "works on real hardware" (PSP Slim) | OUT direction, baseline JPEG over usbhostfs async channel, HW `sceJpegDecodeMJpeg` |
| remotejoy-audio (2026) | https://github.com/00xJS/remotejoy-audio | Sample log line `[rate] video=58.0fps` | Example output in README, not a benchmark | IN direction, **macOS Apple Silicon + libusb**, RemoteJoyLite plugin on 6.61 PRO-C |
| RemoteJoyLite | https://github.com/PSP-Archive/RemoteJoyLite, https://gamebrew.org/wiki/Remote_Joy_Lite_PSP | No fps number found; F1 shows live FPS | **UNVERIFIED** | IN direction |
| psplinkusb usbhostfs | https://github.com/pspdev/psplinkusb | No published MB/s. `HOSTFS_MAX_BLOCK (64*1024)`, `HOSTFS_BULK_MAXWRITE (1024*1024)`, HS bulk 512 B (`usbhostfs/main.c`, `usbhostfs.h`) | **UNVERIFIED** (no number) | PSPdisp and pspdisp-linux run their video over usbhostfs's async channel, so it can clearly sustain 60 fps of JPEG |
| PSP USB mass storage | Fedora list 2009 thread ([link](https://listman.redhat.com/archives/fedora-list/2009-February/331968.html), seen via search snippet; page fetch failed on DNS) | "PSP is able to maintain a speed of around **6.5 MBps**" | Anecdotal | Memory Stick-bound (MS Pro Duo is ~20 MB/s nominal, [psdevwiki](https://psdevwiki.com/psp/Memory_Card)), not representative of raw bulk |
| PyUSB on a generic HS device (not PSP) | https://renesas-wiki.atlassian.net/wiki/spaces/REN/pages/98304002 | PyUSB best **OUT 201 Mbps (≈25 MB/s)**, 1,000,000 B transfer, 16 KB buffer, DMA firmware | Measured (Windows + WinUSB) | Shows PyUSB is **not** the bottleneck at ≥16 KB transfers. The device firmware is |

**Is the E1000 High-Speed?** Yes. psp-cast's README says it was tested on an E-1000 and claims ~15.7 MB/s at 60 fps, which is impossible at Full Speed (12 Mbit/s ≈ 1.2 MB/s max). No E1000-specific primary spec sheet was found, so the E1000 point rests on psp-cast's claim. **The first hardware test should log `dev.speed` in pyusb** (oasis-os `test_echo.py` shows how) and confirm `3 = High`.

## 2. Codec / decode cost on the PSP (Allegrex 333 MHz)

- **Raw RGB565.** PSP 16-bit 565 puts **R in the low 5 bits** (psp-uvc `r5g6b5_to_yuy2`: `p0_r = p0 & 0x1F`). The host must pack `(B<<11)|(G<<5)|R`. Display it natively with `PSP_DISPLAY_PIXEL_FORMAT_565`, framebuffer stride 512 px. Cost is a cache invalidate plus a ~261 KB copy into VRAM, or receive straight into a VRAM-sized buffer as oasis-os does. A few ms (ESTIMATE).
- **8-bit palette.** Halves bandwidth but needs a CLUT pass on the PSP. Use the GU with a `GU_PSM_T8` texture and a CLUT so the GE does the lookup for free. Not needed if RGB565 already reaches 60 fps.
- **LZ4.** Available as a pspdev package ([psp-packages/lz4](https://github.com/pspdev/psp-packages/tree/master/lz4); also `minilzo`, `miniz`, `zlib`). **No published LZ4 benchmark exists for Allegrex or 32-bit MIPS (UNVERIFIED).** My ESTIMATE is 50–150 MB/s decode on the 333 MHz core with 16 KB caches, so 261 KB decodes in about 2–5 ms. That is affordable, but it only pays off if the link really is the bottleneck. The kernel also has `sceKernelDeflateDecompress` / `sceKernelGzipDecompress` ([psputilsforkernel.h](https://github.com/pspdev/pspsdk/blob/master/src/kernel/psputilsforkernel.h)).
- **Hardware JPEG:** **`sceJpegDecodeMJpeg` exists in pspsdk.** [`src/mpeg/pspjpeg.h`](https://github.com/pspdev/pspsdk/blob/master/src/mpeg/pspjpeg.h) declares `sceJpegInitMJpeg`, `sceJpegCreateMJpeg(w,h)`, `int sceJpegDecodeMJpeg(u8 *jpegbuf, SceSize size, u8 *rgba, u32 unk)` and `sceJpegDecodeMJpegYCbCr`. Load it with `sceUtilityLoadModule(PSP_MODULE_AV_AVCODEC)`. Output is RGBA8888 (480×272×4 = 522 KB buffer). Working usage is in [pspdisp-linux `psp/source-min/jpeg.c`](https://github.com/ImNoammm/pspdisp-linux/blob/main/psp/source-min/jpeg.c), and original PSPdisp falls back to libjpeg when sceJpeg is unavailable (`psp/source/compress.c`).
  - No ms-per-frame figure is published (UNVERIFIED). pspdisp-linux's 57–60 fps end-to-end implies decode under ~16 ms per frame. PPSSPP emulates it.
  - Downside: JPEG blurs small text. For terminal or dashboard content, lossless RGB565 is better.

## 3. PSPdisp and related projects

**PSPdisp** by Jochen Schleu (JJS):
- Homepage: https://jjs.at/software/pspdisp.html. Source mirror: https://github.com/PSP-Archive/PSPdisp (Pascal/Delphi host app, Windows display mirror driver, PSP homebrew).
- BSD license; "Full source code is included" in the download. v0.6.1, GameBrew lists the last update as 2016-01-01.
- How it works: a Windows display driver creates a virtual monitor (modes from 480×272 up to 1920×1080, plus rotated variants). The Delphi app captures, compresses and sends frames over USB (libusb or WinUSB) or WLAN.
- The PSP app decodes JPEG (hardware sceJpeg, libjpeg fallback), PNG or BMP ("Uncompressed"), then draws with the GU (`psp/source/compress.c`).
- USB transport is **psplinkusb's usbhostfs.prx async channel** (`ASYNC_MAGIC 0x782F0813`), loaded by the PSP app. It is not a custom `sceUsbbd` driver.
- "CPU load reduction (down to 0 % without screen changes)" via change detection.
- Extended-display mode works only up to Windows 7.

**Prior art**

| Name | URL | Last activity (`gh api` pushed_at) | What to reuse | License |
|---|---|---|---|---|
| PSPdisp (source mirror) | https://github.com/PSP-Archive/PSPdisp | 2020-12-28 (upstream v0.6.1, ~2016) | PSP app (JPEG/PNG/BMP decode + GU draw), wire protocol, usbhostfs async usage | BSD (license.txt) |
| **pspdisp-linux** | https://github.com/ImNoammm/pspdisp-linux | 2026-10-01 | **Best template.** C Linux host: libusb bulk to VID 054C PID 0x1C9, EP OUT 0x02, usbhostfs handshake (`linux-host/transport_usb.c`), JPEG encode + FNV hash skip of unchanged frames (`frame.c`). Minimal PSP app `psp/source-min` (USB-only, HW MJPEG). The PSP side is unchanged across hosts, so **a macOS host is just a new capture backend** | BSD (Schleu copyright) |
| PSPdisp-improved | https://github.com/tojikoumori/PSPdisp-improved | 2026-10-18 | Tearing fix, colour controls (WIP) | none stated |
| psp-uvc-usb-video-class | https://github.com/xerpi/psp-uvc-usb-video-class | 2020-10-04 | Clean minimal `sceUsbbd*` kernel PRX: HS/FS descriptors, `sceUsbbdRegister`, `sceUsbbdReqSend` with event-flag completion, `sceDmacplusLcdcGetBaseAddr` | none stated |
| psp-cast | https://github.com/Lucaspcaldeira/psp-cast | 2026-10-20 | Kernel PRX `psp/usbdrv.c` (3 bulk EPs, 64 KB TX chunks, RX re-arm loop), 16-byte "PCST" protocol header (`common/pcast_protocol.h`), **pyusb host** (`pc/pspcast.py`). **Tested on E-1000 PRO/LME**, claims ARK-4 "deve funcionar". VID/PID 054C:01DC | MIT |
| oasis-os (thin client) | https://github.com/AndrewAltimit/oasis-os | 2026-10-31 | **Same direction as us**: host→PSP RGB565 in 16 KB FRAME_CHUNKs into double-buffered VRAM (`crates/oasis-usb-client-psp/src/{framebuffer,transfer,usbd}.rs`, Rust). Host in Rust (`crates/oasis-usb-host`), pyusb test script `test_echo.py`. VID/PID 054C:1337 | Unlicense |
| RemoteJoyLite | https://github.com/PSP-Archive/RemoteJoyLite | 2021-02-16 | PSP→PC framebuffer plugin; display hook technique | none stated |
| remotejoy-audio | https://github.com/00xJS/remotejoy-audio | 2026-09-11 | **Proof that macOS arm64 + libusb claims a PSP vendor interface with no driver**. Notes on 6.61 PRO-C kernel stubs and clean `module_reboot_before` | none stated |
| libretro-remotejoy | https://github.com/libretro/libretro-remotejoy | 2026-09-05 | libusb RemoteJoy client | GPL-2.0 |
| psplinkusb | https://github.com/pspdev/psplinkusb | 2026-11-03 | `usbhostfs` PRX (HS bulk, async channels) + `usbhostfs_pc` (CI builds on `macos-latest` arm64, per `.github/workflows/host_tools.yml`) | BSD-3-Clause |
| DeskPad | https://github.com/Stengo/DeskPad | 2026-02-28 | `CGVirtualDisplay` private API header ([CGVirtualDisplayPrivate.h](https://github.com/Stengo/DeskPad/blob/main/DeskPad/CGVirtualDisplayPrivate.h)), creation code in [ScreenViewController.swift](https://github.com/Stengo/DeskPad/blob/main/DeskPad/Frontend/Screen/ScreenViewController.swift) | MIT |

No macOS port of PSPdisp exists. The closest Mac work is remotejoy-audio, which runs PSP→Mac.

## 4. Mac capture

- **ScreenCaptureKit (`SCStream`)** is the supported API.
  - `pyobjc-framework-ScreenCaptureKit` 13.0 is on PyPI (requires Python ≥ 3.11, not installed here).
  - Set `SCStreamConfiguration.width=480, height=272`, `pixelFormat=kCVPixelFormatType_32BGRA`, `minimumFrameInterval=1/30`, and `sourceRect` for a region. SCK then scales on the GPU and delivers only on change, since SCStream skips idle frames.
  - Frames arrive as IOSurface-backed `CVPixelBuffer`s ([Apple sample](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos)).
  - **No pyobjc SCStream sample was found (UNVERIFIED path).** Implementing the `SCStreamOutput` protocol from Python works in principle, as in the Zed and Rust examples. The fallback is a ~100-line Swift helper that writes frames to stdout or a shared memory region.
  - Requires the **Screen Recording** TCC permission for the host binary (Terminal/iTerm/python).
- **`CGWindowListCreateImage` / `CGDisplayCreateImage`** were removed from the macOS 15 SDK ("obsoleted in macOS 15.0 – Please use ScreenCaptureKit", [MacPorts #71136](https://trac.macports.org/ticket/71136), [wx-dev](https://groups.google.com/g/wx-dev/c/iReuuqxtGyk)). They remain **exported at runtime**: I verified via ctypes on this Mac (macOS 26.6, build 25G72) that `CGWindowListCreateImage`, `CGDisplayCreateImage`, `CGDisplayStreamCreate` and `CGPreflightScreenCaptureAccess` all resolve.
- **`mss`** (10.2.0) calls `CGWindowListCreateImage` through ctypes (`src/mss/darwin.py`), so the SDK removal does not affect it. A ScreenCaptureKit backend is still an open request ([python-mss #451](https://github.com/BoboTiG/python-mss/issues/451)).
  - Whether `mss` returns real pixels on macOS 26 and at what fps is **UNVERIFIED**. It is a one-shot grab at full Retina resolution followed by downscaling, so it is slow (ESTIMATE 10–30 ms per grab).
  - It is OK for a quick prototype. Use SCK for the real pipeline.
- **CGVirtualDisplay** is the private API DeskPad uses (`CGVirtualDisplayDescriptor`, `CGVirtualDisplaySettings`, `CGVirtualDisplayMode(width:height:refreshRate:)`).
  - DeskPad only defines modes ≥1280×720 and captures with the (also deprecated) `CGDisplayStream`.
  - **Whether macOS accepts a 480×272 mode is UNVERIFIED.** [go-macos/virtualdisplay](https://pkg.go.dev/github.com/go-macos/virtualdisplay) reports 640×480 working and warns that macOS restores the last mode per display identity.
  - Even if 480×272 works, the menu bar eats a big share of a 272-px display. Recommend a 960×544 HiDPI mode (480×272 points), or simply mirroring a 480×272 region or one dedicated window. Treat the virtual display as stretch scope.

## 5. Mac USB host

- **libusb 1.0 on macOS arm64 can claim a vendor-specific (class 0xFF) interface with no kext/dext.** Evidence: remotejoy-audio ("No driver is needed — macOS lets a userspace process claim the PSP's vendor-specific USB interface directly"), and psplinkusb `usbhostfs_pc` builds on macOS arm64 CI.
  - No `sudo` is needed on macOS (unlike Linux udev).
  - Homebrew `libusb-1.0.0.dylib` is present. `pyusb` 1.3.1 is not installed yet.
  - Our PRX should expose only class 0xFF interfaces. The caveat is that if the device ever presents a class macOS binds a driver to (MSC, UVC), libusb gets `kIOReturnExclusiveAccess`.
- **pyusb overhead:** negligible at large transfers. Renesas measured PyUSB at ≈25 MB/s OUT with 16 KB+ buffers, faster than LibUsbDotNet. psp-cast's pyusb host claims ~15.7 MB/s.
- **Recommendation:** write one whole frame, or ≥64 KB packets, per `dev.write(0x02, buf, timeout)`. libusb splits them into 512 B HS packets in hardware/IOKit. Avoid transfers <16 KB.
  - The PSP side should keep a `sceUsbbdReqRecv` queued at all times. Use 64 KB receive buffers, 64-byte aligned, and call `sceKernelDcacheInvalidateRange` after completion.
  - To reach >16 MB/s, pipeline with 2 receive buffers on the PSP and a writer thread on the Mac (python-libusb1 async if needed).

## 6. Verdict

**Useful, not marginal.** Even the conservative raw path gives ~30 fps at 480×272, and the measured-class link gives 60 fps. Prior art reaches 57–60 fps in the same host→PSP direction.

The practical limit is **legibility**, not fps. 480×272 on a 4.3" panel suits a terminal tail, a dashboard, a clock or a music widget, not a scaled-down desktop.

The degraded mode is still worth building as backup #1 (see below).

## Recommended pipeline

1. **Capture (Mac, Python):**
   - ScreenCaptureKit `SCStream` on a 480×272 `sourceRect` (1:1 pixels, crisp text), or on a window via `SCContentFilter(desktopIndependentWindow:)` scaled to 480×272.
   - BGRA, `minimumFrameInterval` 1/30 (raise to 1/60 later), `showsCursor` optional.
   - Prototype fallback: `mss.grab(region)` + numpy downscale.
2. **Encode (Mac, numpy):**
   - BGRA → **PSP BGR565** `((B>>3)<<11)|((G>>2)<<5)|(R>>3)` as `<u2`.
   - Split into **16×16 tiles** (30×17 = 510 tiles) and compare with the previous frame (numpy `!=` per tile). Send only dirty tiles.
   - If the dirty area exceeds ~60% of the frame, send a full frame instead. A keyframe every N s guards against desync.
   - Optional **LZ4 block** compression per message (Homebrew `liblz4` present; Python `lz4` package). Enable only if measurements show the link is the bottleneck.
3. **Frame format (wire), little-endian:**
   - 16-byte header: `magic 'PSPF' u32 | type u16 (FULL=1, TILES=2, PING=3) | flags u16 (bit0 = LZ4) | seq u32 | payload_len u32`.
   - FULL payload: 480×272×2 rows, stride 480.
   - TILES payload: `count u16`, then `[tx u8, ty u8, 512 B pixels]`.
   - Pad each transfer to a multiple of 512 B, or end it with a short packet, so the PSP's `ReqRecv` completes.
   - The PSP replies on EP IN with `ack seq + buttons` for flow control: one frame in flight, two at most.
4. **PSP receive and decode (kernel PRX + user app):**
   - Kernel PRX based on psp-cast `usbdrv.c` or psp-uvc `main.c`: `sceUsbbdRegister`, HS descriptors (bulk 0x81 IN / 0x02 OUT, 512 B, class 0xFF), VID 054C with **our own PID** (not 0x1C9 psplink or 0x1DC psp-cast). Continuous `sceUsbbdReqRecv` into 2×64 KB buffers.
   - The user app (EBOOT) loads the PRX, reassembles messages, and optionally LZ4-decodes (psp-packages `lz4`).
5. **Blit:**
   - FULL: copy rows 480 → stride 512 into the back buffer in VRAM (`0x44000000` uncached mirror), with `sceDmacMemcpy` or a plain loop.
   - TILES: per-tile 16-row copy.
   - Then `sceDisplayWaitVblankStart()` + `sceDisplaySetFrameBuf(back, 512, PSP_DISPLAY_PIXEL_FORMAT_565, PSP_DISPLAY_SETBUF_NEXTFRAME)`, then swap buffers. The GU (`sceGuCopyImage`) is optional.
   - Call `scePowerTick` to stop auto-sleep and dimming.
6. **Measure first (hardware night 1):**
   - Echo/throughput test: Mac writes 8 MB in 256 KB chunks while the PSP counts bytes and reports µs.
   - Log `dev.speed` and the OUT MB/s for 16 KB / 64 KB / 256 KB transfer sizes. That number picks raw vs tiles vs LZ4.

**Codec choice:** **raw BGR565 + 16×16 dirty tiles**. LZ4 is a switchable flag. JPEG via `sceJpegDecodeMJpeg` is the fallback for video-like content.

Rationale: it is lossless (text stays readable), needs zero PSP decode CPU, is trivially debuggable, and fits the link even uncompressed.

## Risks / gotchas

- **Kernel PRX hangs:** a bug in kernel mode freezes the PSP. Recovery: battery pull, or hold R at boot for the recovery menu. Plugins can be disabled there. Export `module_reboot_before` (see remotejoy-audio).
- **NIDs / CFW differences:** oasis-os claims "the standard PSPSDK NIDs are wrong for 6.61 firmware" and that ARK-4 needs direct address calls. **UNVERIFIED and contradicted** for PRO: psp-uvc, psp-cast and remotejoy-audio all use standard `sceUsbBus_driver` stubs on 6.61 PRO/LME. ARK-4 is untested by psp-cast. **Prefer PRO/LME for the first test.** remotejoy-audio also warns not to statically link PRO's `libpspsystemctrl_kernel`.
- **Only one USB device personality at a time:** our driver vs XMB "USB mode", psplink/usbhostfs, RemoteJoyLite, psp-uvc. Disable the others in `seplugins`. psp-cast handles XMB USB mode by releasing and re-binding.
- **Emulator gap:** PPSSPP has no `sceUsbbd*`, so the USB path cannot be emulated. Its kernel-PRX support is also limited. Test the receive-and-blit code in PPSSPP by feeding frames from `host0:`/ms0 files.
- **Cache coherency / alignment:** receive buffers must be 64-byte aligned. Call `sceKernelDcacheInvalidateRange` before reading and `WritebackInvalidate` before sending. oasis-os also notes a BSS-layout sensitivity: calling `init()` before USB "breaks recv (root cause unknown)".
- **USB transfer termination:** if `payload_len` is an exact multiple of 512, the host must send a ZLP, or the PSP must request exactly `payload_len`. Otherwise `ReqRecv` waits forever.
- **Pixel order:** the PSP 565 format is R in the low bits (BGR565 from the host's view). Getting this wrong gives blue/red swapped.
- **macOS permissions:** Screen Recording TCC prompt for the Python/terminal binary. macOS 15+ periodically re-asks for screen-capture consent (frequency **UNVERIFIED**). The private `CGVirtualDisplay` API may break on any macOS update.
- **CGWindowListCreateImage future:** present at runtime on 26.6, but deprecated and gone from the SDK. Don't build the final path on it.
- **Physical:** needs a data-capable mini-USB cable. The PSP screen and battery stay on (the E1000 has no Wi-Fi, so USB is the only link). Keep `scePowerTick`.
- **Legibility:** 480×272 is small. Mirroring a downscaled 1440p desktop is unreadable. Design the content for the panel.

## Backup ideas

1. **Dashboard mode (data, not pixels).** The Mac sends compact structs or JSON (clock, CPU/RAM, now-playing, notifications, a log tail, build status) at 1–10 Hz. The PSP renders them with intraFont + GU. Bandwidth is tiny, text is perfectly crisp, there is no Screen Recording permission, and it uses the same USB transport. **Ship this if raw pixels misbehave.**
2. **Reuse PSPdisp's PSP side and write only a macOS host.** pspdisp-linux keeps PSPdisp's wire protocol unchanged and talks plain libusb (VID 054C, PID 0x1C9, usbhostfs async handshake magic `0x782F0812`, JPEG frames). A Python/pyusb + ScreenCaptureKit + turbojpeg host could drive the unmodified `psp/source-min` EBOOT. No custom kernel driver needed (it uses psplinkusb's usbhostfs.prx), and there is precedent for 57–60 fps. This is probably the **fastest route to pixels on real hardware**.
3. **Zero-driver file mode:** run psplinkusb `usbhostfs_pc` on the Mac (builds on arm64). The Mac writes `frame.bin`, and the PSP app polls `host0:/frame.bin` with ordinary `sceIoRead`. Throughput is lower (64 KB blocks + file-IO round trips, UNVERIFIED rate), but it is fine for a dashboard at a few fps and easy to debug.
