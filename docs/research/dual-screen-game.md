# Track C research: asymmetric dual-screen game (Mac + PSP E1000)

Scout report, 2026-11-07. Facts were checked against the GitHub API, PPSSPP source and web pages on this date. Anything marked **UNVERIFIED** could not be confirmed.

## Summary

1. **Verdict: doable tonight (emulator + mock only), and doable with hardware once the shared USB bulk PRX works.** The game needs under 2 KB/s, so bandwidth is not a risk. The only hardware-only part is the shared USB transport from `common/`.
2. **PSP graphics: SDL3.** It is in pspdev's `psp-libraries` group, so the macOS-arm64 pspdev release installs it. It is the stack the official pspdev docs use for their examples, and its built-in `SDL_RenderDebugText` gives an 8×8 console font without font files. The same C file also builds natively on the Mac, which gives a pixel-identical "fake PSP".
3. **Emulator automation: PPSSPP 1.20.4 (Homebrew cask `ppsspp-emulator`) with its WebSocket debugger.** It handles input (`input.buttons.press`, `input.analog.send`), screenshots (`gpu.buffer.screenshot`) and `memory.read`/`memory.write`. Those memory calls let a Mac bridge act as the "link" to the PSP mini-game inside PPSSPP. The `--debugger` command-line flag exists only in master after 1.20.4; the release enables it through the ini key `RemoteDebuggerOnStartup`.
4. **Camera: the Go!Cam mounts on the Mini-USB port, so the camera and the USB link to the Mac are mutually exclusive.** The E1000 has no mic, so a sound side channel could only run PSP → Mac at about 8–16 B/s (ggwave). Camera ideas are standalone only.
5. **Recommended game: "Blackwater Ping".** The Mac draws a submarine in a dark trench, and the PSP is its sonar scope plus hacking console. Game messages are 6 small types in the `0x40`–`0x5F` range on top of the shared framed protocol.

## Fact table

| # | Claim | Verified? | Link |
|---|---|---|---|
| F1 | E1000 has no Wi-Fi or ad-hoc, has a mono speaker, and the microphone was removed | Yes (Wikipedia: "lacked support for Wi-Fi, ad-hoc features…"; "microphone [was] also removed") | https://en.wikipedia.org/wiki/PlayStation_Portable |
| F2 | E1000 has Hi-Speed USB (USB 2.0), a "Headset connector" and a monaural speaker | Yes (Sony spec sheet as reprinted) | https://www.xtremeps3.com/2011/08/24/sony-releases-psp-e1000-technical-specification |
| F3 | Go!Cam "mounts on top of the PSP via the Mini USB connection slot and a screw"; PSP-300 needs FW 2.82+, PSP-450x needs FW 6.00+ | Yes | https://en.wikipedia.org/wiki/Go!Cam |
| F4 | Go!Cam works on the **E1000** specifically | **UNVERIFIED.** No source confirms or denies it. A 2010 Sony statement says the camera was for pre-Go models only. Semyon owns both, so he can test physically. | https://www.gameinformer.com/b/news/archive/2010/07/07/psp-camera-no-go.aspx |
| F5 | Camera and Mac USB link cannot run at the same time | Yes (inferred from F3: one Mini-B port). The oasis-os research also says the PSP is always the USB *device*, and that Sony accessories take power from side pads beside the Mini-B port. | https://andrewaltimit.github.io/oasis-os/journal/05-psp-usb-research.html |
| F6 | pspsdk ships a camera API: `src/usb/pspusbcam.h` (`sceUsbCamSetupVideo`, `sceUsbCamStartVideo`, `sceUsbCamReadVideoFrameBlocking`, `sceUsbCamSetupStill`, …), `PSP_USBCAM_PID 0x282`, driver name `"USBCamDriver"` | Yes | https://github.com/pspdev/pspsdk/blob/master/src/usb/pspusbcam.h |
| F7 | A homebrew sample that actually uses the camera on real hardware | **UNVERIFIED / not found.** GitHub code search for `sceUsbCamSetupStill` finds only the SDK, emulators (PPSSPP, JPCSP) and libc bindings. | https://github.com/hrydgard/ppsspp/blob/master/Core/HLE/sceUsbCam.cpp |
| F8 | PPSSPP HLE-emulates `sceUsbCam`; on macOS it forwards to `System_CameraCommand("startVideo_WxH")` | Yes (source). Whether the macOS SDL build delivers webcam frames is **UNVERIFIED**. | https://github.com/hrydgard/ppsspp/blob/master/Core/HLE/sceUsbCam.cpp |
| F9 | Reported PSP USB bulk throughput with a custom `sceUsbbd` driver on ARK-4: ~28 MB/s / ~100 fps of 480×272 | Author's own claim, not reproduced (useful mainly for track B) | https://andrewaltimit.github.io/oasis-os/journal/05-psp-usb-research.html , https://github.com/AndrewAltimit/oasis-os |
| F10 | pspdev release `v20261101` ships `pspdev-macos-latest-arm64.tar.gz` | Yes (GitHub API) | https://github.com/pspdev/pspdev/releases/tag/v20261101 |
| F11 | The pspdev install runs `psp-pacman -S psp-libraries`; `sdl2`, `sdl3`, `raylib`, `oslib`, `ya2d` and `libintrafont` all declare `groups=('psp-libraries')`, so the prebuilt release should include them | Yes for the build script and PSPBUILDs. Presence inside the tarball is **UNVERIFIED** (check with `ls $PSPDEV/psp/lib/libSDL3*`). | https://github.com/pspdev/pspdev/blob/master/scripts/003-psp-packages.sh , https://github.com/pspdev/psp-packages |
| F12 | Official pspdev "basic programs" page: Hello world, GU shapes and sprites, input, audio, then SDL3, SDL3_mixer and SDL3_ttf examples, all built with `psp-cmake .. && make` | Yes | https://pspdev.github.io/basic_programs.html |
| F13 | Upstream SDL has PSP video and render backends (`src/video/psp`, `src/render/psp/SDL_render_psp.c`) | Yes | https://github.com/libsdl-org/SDL/tree/main/src/render/psp |
| F14 | `SDL_RenderDebugText` (8×8 built-in font) is available since SDL 3.2.0; pspdev ships SDL3 3.4.14 | Yes (header plus PSPBUILD). That it renders correctly on the PSP backend is **UNVERIFIED**. | https://github.com/libsdl-org/SDL/blob/main/include/SDL3/SDL_render.h , https://github.com/pspdev/psp-packages/blob/master/sdl3/PSPBUILD |
| F15 | PPSSPP latest release is v1.20.4 (2026-05-16). Its GitHub assets include `PPSSPPSDL-macOS-v1.20.4.zip`. | Yes | https://github.com/hrydgard/ppsspp/releases/tag/v1.20.4 |
| F16 | Homebrew cask **`ppsspp-emulator`** 1.20.4 (old name `ppsspp` is in `cask_renames.json`) installs `PPSSPPSDL.app` from `ppsspp.org/files/1_20_4/PPSSPP_macOS.dmg`. It has no arch restriction. | Yes. That the binary is universal or arm64 is **UNVERIFIED**; run `lipo -info` after install. | https://github.com/Homebrew/homebrew-cask/blob/HEAD/Casks/p/ppsspp-emulator.rb |
| F17 | WebSocket debugger: path `/debugger`, subprotocol `debugger.ppsspp.org`, JSON `{"event": ...}`. It shares a port with Remote ISO (`RemoteISOPort`, 0 = auto, logged as `Listening on port N`). | Yes (master docs, 2026-11-05) | https://github.com/hrydgard/ppsspp/blob/master/docs/WebSocketDebugger.md |
| F18 | Enabling the debugger: UI path Settings > Tools > Developer Tools > "Allow remote debugger", or ini `RemoteDebuggerOnStartup` (in `generalSettings`, v1.20.4) | Yes (v1.20.4 `Core/Config.cpp` lines ~298/304) | https://github.com/hrydgard/ppsspp/blob/v1.20.4/Core/Config.cpp |
| F19 | The `--debugger=PORT` command-line flag works for the **GUI app only in master** (`Core/CmdLine.cpp` does not exist at tag v1.20.4). **Headless** has `--debugger` in v1.20.4. | Yes (GitHub contents API at both refs) | https://github.com/hrydgard/ppsspp/blob/master/Core/CmdLine.cpp , https://github.com/hrydgard/ppsspp/blob/v1.20.4/headless/Headless.cpp |
| F20 | v1.20.4 events exist: `input.buttons.send/press`, `input.analog.send`, `gpu.buffer.screenshot`, `game.status`, `game.reset`, `version`, `memory.read/write(_u8/16/32)`. `game.state.*` and `memory.search` are master-only. | Yes | https://github.com/hrydgard/ppsspp/tree/v1.20.4/Core/Debugger/WebSocket |
| F21 | PPSSPPHeadless is not in the cask; build it with `cmake -DHEADLESS=ON`. v1.20.4 flags: `--root --log --graphics= --screenshot= --timeout= --max-mse= --debugger= --state= --compare`. `--screenshot-save`/`--screenshot-dir` are master-only. | Yes | https://github.com/hrydgard/ppsspp/blob/master/headless/README.md |
| F22 | Homebrew can trigger a headless screenshot with `sceIoDevctl("emulator:", 0x20 /*EMIT_SCREENSHOT*/, …)`, and detect PPSSPP with `EMULATOR_DEVCTL__GET_HAS_DISPLAY = 1` | Yes (source) | https://github.com/hrydgard/ppsspp/blob/master/Core/HLE/sceIo.cpp |
| F23 | ggwave: MIT, FSK, "8-16 bytes/sec", core is `ggwave.cpp` (~71 KB) + `fft.h`, and it runs on Arduino/ESP32/RP2040. PyPI `ggwave` 0.4.3 is sdist-only, so it needs a compiler. | Yes. That it compiles for PSP MIPS is **UNVERIFIED** (plausible: C++11, no deps). | https://github.com/ggerganov/ggwave , https://pypi.org/project/ggwave/ |
| F24 | libquiet: BSD-3, depends on liquid-dsp, last push 2021-05 | Yes. Bitrate not checked. | https://github.com/quiet/quiet |
| F25 | PS3 Formula One CE "PSP as rear-view mirror" was shown at E3 2006 but cut from the shipped game | Yes (multiple sources; GameSpot review notes it is missing) | https://en.wikipedia.org/wiki/Remote_Play |

## Prior art (design lessons)

| Name | URL | Year | Lesson for a sonar/console second screen |
|---|---|---|---|
| Wii U GamePad / Nintendo Land | https://en.wikipedia.org/wiki/Nintendo_Land , https://iwataasks.nintendo.com/interviews/wiiu/nintendo-land/0/0 | 2012 | Asymmetry works best when the handheld player *knows something the TV player doesn't* (Mario Chase, Luigi's Ghost Mansion). Iwata later admitted "asymmetric gameplay" was hard to explain, so make the information gap obvious in the first 10 seconds. |
| Keep Talking and Nobody Explodes (GDC talk "Designing Asymmetric Gameplay…") | https://gdcvault.com/play/1023113/Designing-Asymmetric-Gameplay-For-Keep | 2015/16 | The fun is the *communication*. Keep each side's information incomplete and use short readable codes; they found O vs 0 confusion in a font. Our PSP console must use unambiguous glyphs. |
| Iron Lung (sub with no window, map + coordinates only) | https://en.wikipedia.org/wiki/Iron_Lung_(video_game) | 2022 | Navigating blind with an indirect sensor builds tension. We use the *idea* of indirect sensing only. The art, setting and mechanics stay original (no photo-camera mechanic). |
| Artemis Spaceship Bridge Simulator / Spaceteam | https://en.wikipedia.org/wiki/Artemis:_Spaceship_Bridge_Simulator , https://en.wikipedia.org/wiki/Spaceteam | 2010s | Station-based roles: the helm sees space, the science station sees scans. That maps to Mac = helm and PSP = sonar/engineering. |
| GameCube–GBA link (Four Swords Adventures) | https://en.wikipedia.org/wiki/GameCube_%E2%80%93_Game_Boy_Advance_link_cable , https://en.wikipedia.org/wiki/The_Legend_of_Zelda:_Four_Swords_Adventures | 2003–04 | A handheld screen that is the *private* view (inside houses, caves) while the TV is shared. The PSP scope is the private instrument. |
| Dreamcast VMU | https://en.wikipedia.org/wiki/VMU | 1998 | The controller screen shows status at a glance, so there is no need to look down often. The PSP should be glanceable: big sweep, few glyphs. |
| DS Download Play | https://en.wikipedia.org/wiki/Nintendo_DS#Download_Play | 2004 | The client can be a thin program pushed from the host. Analogous: the PSP mini-game is a thin client and the Mac is authoritative. |
| PSP Remote Play / F1 CE rear-mirror (cut) | https://en.wikipedia.org/wiki/Remote_Play | 2006 | Streaming *video* to the PSP as a second screen was cut. Sending *game state* and rendering locally is the robust pattern, and it is ours. |
| oasis-os PSP USB research | https://github.com/AndrewAltimit/oasis-os (pushed 2026-10-31, Unlicense) | 2026 | Recent working `sceUsbbd` vendor-device driver on ARK-4 (Rust). It is a cross-check for the `common/` USB PRX. |
| xerpi psp-uvc-usb-video-class | https://github.com/xerpi/psp-uvc-usb-video-class (pushed 2020-10-04) | 2020 | The PSP as a class-compliant UVC device (screen → Mac). Relevant to tracks A/B more than C. |

## PSP 2D graphics library table

| Name | URL | Last activity | Use for us | License |
|---|---|---|---|---|
| **SDL3 (recommended)** | https://github.com/libsdl-org/SDL , PSPBUILD https://github.com/pspdev/psp-packages/tree/master/sdl3 | upstream 2026-11-06; pspdev pkg 3.4.14 | Lines, filled rects, `SDL_RenderGeometry` for the sweep wedge, `SDL_RenderDebugText` for the console. The same code builds with brew SDL3 on the Mac. Official pspdev examples use it. | Zlib |
| SDL2 | https://github.com/pspdev/psp-packages/tree/master/sdl2 | pkg 2.32.10, PSPBUILD touched 2026-06-11 | Fallback if SDL3 misbehaves. Needs SDL2_ttf or an embedded bitmap font for text. | Zlib |
| raylib (raylib4Consoles port) | https://github.com/pspdev/psp-packages/tree/master/raylib → https://github.com/raylib4Consoles/raylib (2026-04-23); samples https://github.com/raylib4Consoles/raylib4Psp ; template https://github.com/BrownNPC/psp-raylib-template (2026-03-12) | pkg `5.6dev`, PSPBUILD 2026-06-24 | Nicest API (`DrawCircleSector`, default font) and also desktop-portable. It is a "dev" port on top of pspgl, which carries more risk. Second choice. | Zlib |
| OSLib (dogo modfix) | https://github.com/dogo/oslib | 2026-11-06 (active) | Classic 2D lib with fonts. GPL-2.0 is fine for a private POC but it does not build on the Mac. | GPL-2.0-only |
| gLib2D | https://github.com/libcg/gLib2D | 2015-07-13 | Tiny, GU-based. Not in psp-packages, so it must be vendored. | LGPL-3.0 |
| ya2d | https://github.com/xerpi/ya2d | 2026-05-12 (pkg) | Small 2D lib. Little documentation. | LGPL-2.1 |
| Raw sceGu / framebuffer + `pspDebugScreenPrintf` | https://github.com/pspdev/pspsdk/tree/master/src/samples/gu (samples: `lines`, `sprite`, `text`, `blit`…) | pspsdk 2026-11-05 | Zero deps. Debug-screen text over a software-drawn scope is the fastest path if SDL3 breaks. It does not build on the Mac. | BSD-style (pspsdk) |
| libintrafont | https://github.com/pspdev/libintrafont | 2025-10-16 | Uses the PSP firmware fonts. Firmware fonts are absent in PPSSPP without flash0 (**UNVERIFIED** for HLE fallback), so avoid it. | CC-BY-SA-3.0 |

**Recommendation:** use SDL3 at 480×272 with one `SDL_Renderer`. Draw the scope as a circle (line segments), the sweep as a fading triangle fan (`SDL_RenderGeometry`), contacts as small rects, and console text with `SDL_RenderDebugText`. Build the same `psp_game/` sources twice: `psp-cmake` for EBOOT.PBP, and plain `cmake` against brew `sdl3` as a native `fake_psp_game` on the Mac. Swap only the transport, using TCP mock on the Mac. If SDL3 fails on the PSP backend, fall back to raw framebuffer drawing plus `pspDebugScreen`, keeping the game logic in a portable C file.

## Recommended game: "Blackwater Ping" (original concept)

**Fiction:** a salvage submersible in a flooded mine shaft (original setting). The Mac shows a top-down cross-section that is almost fully black. The only visible area is a 40 px lamp radius around the sub. The PSP is the sub's instrument panel.

- **Mac (pygame-ce), authoritative simulation at 30 Hz:** the sub has inertia. The world holds rock walls, drifting mines, a slow "listener" creature that homes on the *last active ping position*, sealed bulkheads (gates) and an exit beacon. The Mac renders only what the lamp reveals, plus any MARK buoys the PSP player placed. Lose when hull reaches 0. Win when the sub reaches the exit.
- **PSP, sonar + console:** a round scope (left 272×272) with a rotating sweep.
  - **Active ping (×):** returns contacts with range and bearing. It raises `noise`, and the creature hears it.
  - **Passive listen (□):** shows only moving things as bearing lines without range. It is safe but vague.
  - **Mark a contact (△):** places a buoy on the Mac map.
  - **Hack console (right 208 px, text):** when the sub touches a gate, the Mac sends HACK_REQ. The PSP runs a seeded mini-puzzle, for example: match a 4-symbol frequency code using the D-pad, or a timed sequence of digits shown as a waveform. The PSP returns HACK_RESULT before the timer runs out.
- **Why two screens matter:** the Mac player can see the walls nearby but not the threats; the PSP sees threats but not walls. The noise trade-off (ping = information vs. attracting the creature) makes each ping a decision. It works in two modes:
  - **Co-op:** Mac keyboard pilots, PSP is sonar.
  - **Solo, Wii U "GamePad" style:** the PSP analog nub pilots via PILOT_INPUT, the Mac is the "TV", and the player glances between screens. Solo mode also reuses track A's input path.

### Message list (game types live in 0x40–0x5F; the header comes from `common/`: magic, type, seq, len, payload, crc16)

Little-endian fixed-size payloads. Angles are `u16` (0..65535 = 0..360°). Distances are `u16` in world units (1 unit = 1 Mac px at 1×).

| Type | Dir | Name | Payload | Rate |
|---|---|---|---|---|
| 0x40 | Mac→PSP | GAME_START | `level u8, mode u8 (0 coop,1 solo), seed u32` (6 B) | once / level |
| 0x41 | Mac→PSP | SUB_STATE | `tick u16, x i16, y i16, heading u16, speed i8, hull u8, battery u8, noise u8, flags u8` (13 B) | 10 Hz |
| 0x42 | Mac→PSP | ECHO | `ping_id u8, n u8, n × {bearing u16, range u16, kind u8 (0 rock,1 mine,2 creature,3 gate,4 exit,5 unknown), strength u8}` (2+6n B, n ≤ 32 → ≤ 194 B) | per ping (≤ 1/s) |
| 0x43 | Mac→PSP | HACK_REQ | `gate_id u8, puzzle u8, difficulty u8, seed u32, time_limit_ds u16` (9 B) | on gate contact |
| 0x44 | Mac→PSP | EVENT | `code u8 (1 DAMAGE,2 CREATURE_NEAR,3 GATE_OPEN,4 WIN,5 LOSE,6 BATTERY_LOW), arg u16` (3 B) | on event |
| 0x50 | PSP→Mac | PING_CMD | `ping_id u8, mode u8 (0 passive,1 wide,2 narrow), bearing u16, width u16` (6 B) | on button |
| 0x51 | PSP→Mac | HACK_RESULT | `gate_id u8, ok u8, elapsed_ds u16` (4 B) | once per HACK_REQ |
| 0x52 | PSP→Mac | MARK | `bearing u16, range u16, tag u8` (5 B) | on button |
| 0x53 | PSP→Mac | PILOT_INPUT | `ax i8, ay i8, buttons u16` (4 B) | 30 Hz in solo mode, else off |

Peak bandwidth is about 30×(hdr+4) + 10×(hdr+13) + one ECHO, which is under 1.5 KB/s with an 8–10 B header. Latency target: under 50 ms one way (unmeasured; USB bulk round trips should be far below this, while the PPSSPP WebSocket bridge adds ms-level JSON overhead). Heartbeat and hello come from `common/` if it defines them; otherwise add `0x5F HEARTBEAT {tick u16}` at 1 Hz both ways. Mac-side rules: ECHO contents are computed by the Mac (it owns the world), the PSP never sends positions, and PING_CMD with the same `ping_id` is idempotent so retransmits are safe.

### Two other concepts (not chosen)

- **"Cold Relay" (heist):** the Mac shows a top-down stealth infiltration. The PSP is the intrusion deck: a node graph of cameras and doors, and the PSP player loops cameras and opens doors while a trace meter fills. Mac→PSP: `ROOM {id}`, `ALERT {level}`, `NODE_STATE[]`. PSP→Mac: `NODE_CMD {id, action}`, `TRACE {pct}`. Fun comes from timing the door against the guard. Not chosen: the graph UI needs more PSP screen work and the level design is heavier.
- **"Burn Plan" (orbital tug):** the Mac shows 2D orbital physics, a tug docking with debris. The PSP is the flight computer: the player programs a burn sequence (direction, duration) with buttons, and the PSP draws the predicted trajectory from state sent by the Mac. Mac→PSP: `ORBIT_STATE {r, v, t}` at 5 Hz. PSP→Mac: `BURN_PLAN {n × (t, angle, dur)}`, `EXECUTE`. Fun comes from planning on the handheld and watching it play out on the big screen. Not chosen: it needs orbital prediction code on the PSP, which carries more math risk tonight.

## PPSSPP automation recipe (for the Builder)

1. **Install:** `brew install --cask ppsspp-emulator` gives `/Applications/PPSSPPSDL.app` v1.20.4. Check the architecture with `lipo -info /Applications/PPSSPPSDL.app/Contents/MacOS/*`. The executable name inside is **UNVERIFIED**; expect `PPSSPPSDL`. On first launch Gatekeeper may need approval or `xattr -dr com.apple.quarantine` (only if the user approves).
2. **Enable the debugger (v1.20.4 release):** edit the ini under `~/.config/ppsspp/` (the cask's `zap` path). The likely file is `~/.config/ppsspp/PSP/SYSTEM/ppsspp.ini` (**UNVERIFIED** subpath; run PPSSPP once and `find ~/.config/ppsspp -name ppsspp.ini`). In `[General]`, set `RemoteDebuggerOnStartup = True` and `RemoteISOPort = 0` (auto). Alternatively, use a fixed port and accept the fallback behaviour. Read the bound port from the log line `Listening on port N`, or from the OSD message. With a master/nightly build, simply pass `--debugger=0`.
3. **Boot:** run `"/Applications/PPSSPPSDL.app/Contents/MacOS/PPSSPPSDL" path/to/EBOOT.PBP`. Passing the file as argv is how PPSSPP's own launch works, but this path is **UNVERIFIED** on macOS. For a fixed mailbox address, a static `.elf` (`BUILD_PRX=0`) also boots and gives fixed symbol addresses.
4. **Client (Python, `websockets` or `websocket-client`):** connect to `ws://127.0.0.1:PORT/debugger` with subprotocol `debugger.ppsspp.org`. Send `{"event":"version","name":"blackwater-bridge","version":"0.1"}` first. Then use:
   - `{"event":"game.status"}` and wait until `game != null`;
   - `{"event":"input.buttons.press","button":"cross","duration":2}`;
   - `{"event":"input.analog.send","x":0.5,"y":0.0}`;
   - `{"event":"gpu.buffer.screenshot","type":"uri"}`, which returns a `data:image/png;base64,…` URI to save under `docs/img/`.

   Add `"ticket"` to correlate responses. Reference client: `scripts/websocket-test.py` and `Tools/wsdbg/` in the PPSSPP repo.
5. **Emulator "link" transport, no USB (PPSSPP cannot emulate the USB device):** the PSP game allocates a mailbox struct `{magic 'BWMB', rx_head, rx_tail, tx_head, tx_tail, rx[2048], tx[2048]}` as a global.
   - The bridge finds its address in one of three ways: (a) `psp-nm` on a static ELF build; (b) the game writes the pointer into scratchpad `0x00010000` (**UNVERIFIED** that `memory.read_u32` accepts scratchpad addresses); or (c) the game prints `MBOX@0x…` and the bridge reads it from the log.
   - The bridge then polls `memory.read` at 60 Hz and writes frames with `memory.write` (base64). It relays to the Mac game over the same TCP mock transport that `tools/fake_psp.py` uses, so the Mac game cannot tell the difference.
   - The PSP side detects the emulator with `sceIoDevctl("emulator:", 1, …) >= 0` and picks the mailbox transport. On hardware it picks the USB PRX.
   - Fallback if the memory API is awkward: a file mailbox on `ms0:/PSP/GAME/…/link_in.bin` polled at 10 Hz (cruder, but needs no debugger).
6. **Headless (optional, CI):** `cmake -DHEADLESS=ON -B build-headless && cmake --build build-headless` from a PPSSPP source checkout (needs cmake, which is not installed yet). Then run `PPSSPPHeadless --graphics=software --timeout=10 --screenshot=ref.png EBOOT.elf`. In v1.20.4, `--screenshot` *compares*; `--screenshot-save` needs master. The program calls `sceIoDevctl("emulator:", 0x20, …)` at the moment it wants captured. Treat this as nice-to-have; the GUI app plus WebSocket path is enough for tonight.

## Side channel through the headphone jack (low priority)

The E1000 has no microphone (F1), so audio runs PSP→Mac only: the PSP speaker or headphones, picked up by the Mac mic. ggwave runs at 8–16 B/s (F23), enough for one hack code per second, but not for STATE. The PSP side does not need ggwave: it can synthesize the FSK tones directly (the README documents the tone plan: F0 = 1875 Hz, dF = 46.875 Hz, 6 tones per 3 bytes). The Mac decodes with the ggwave library built from source (PyPI is sdist-only). libquiet is faster but depends on liquid-dsp and has been inactive since 2021. Use: the camera AR toy sends its score to the Mac (backup idea 1).

## Risks

1. **SDL3 PSP render or debug text has gaps** (F14 unverified). Mitigation: a one-hour spike first. Fallback to SDL2, then raw framebuffer plus `pspDebugScreen`.
2. **The PPSSPP 1.20.4 GUI has no `--debugger` flag** (F19). The ini key must be set before launch, the ini path is unverified, and the port is auto-picked. Mitigation: set `RemoteISOPort` to a fixed value, or parse the log; a nightly build from the GitHub CI link on ppsspp.org also works.
3. **Mailbox discovery in emulator memory** (PRX relocation). Mitigation: static ELF build for emulator tests, or printed address.
4. **The real USB link depends on `common/`'s kernel PRX**, which is untestable tonight. The game is transport-agnostic, so this stays a hardware-only risk, documented in `HARDWARE_TEST.md`.
5. **pspdev tarball contents** (F11): if SDL3 is missing, `psp-pacman -S sdl3` or the docker image `pspdev/pspdev`.
6. **Solo ergonomics:** looking between two screens can feel bad. Keep the PSP glanceable and send `EVENT` alerts as sound or flash on the PSP.
7. **Camera on E1000 unknown** (F4). This only affects the backup ideas.

## Backup ideas

1. **Camera AR toy (standalone, no Mac link):** "Lantern Moths". The Go!Cam feed (`sceUsbCamReadVideoFrameBlocking`) is shown with original sprite moths drawn to bright regions (brightness centroid). Optionally send the score to the Mac by ggwave. Needs F4 confirmed on hardware. PPSSPP camera input on macOS is unverified (F8).
2. **PSP as MIDI beat pad:** face buttons and D-pad are 8 pads and the L/R triggers switch banks. Frames go to the Mac, where a Python bridge (`mido` + `python-rtmidi`) sends them to the IAC Driver, then GarageBand or Logic. Tiny bandwidth; reuses track A's input path.
3. **PSP Pomodoro / system-stats display:** the Mac sends `STATS {cpu%, mem%, battery, now-playing title}` at 1 Hz, and the PSP renders a clock, bars and a 25-minute timer with SDL3 debug text. This is the lowest-risk fallback and reuses everything above.
