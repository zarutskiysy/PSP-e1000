# Blackwater Ping — PSP console EBOOT.
#   source tools/env.sh && make -C game/psp        -> game/psp/EBOOT.PBP
# Output: EBOOT.PBP + usbhostfs.prx + pspmaclink.prx -> copy all three to ms0:/PSP/GAME/BLACKWATER/
# Transports: real USB (hardware), PPSSPP mailbox (emulator), in-process demo (fallback).
TARGET = blackwater
COMMON = ../../common/psp
OBJS = main.o app.o console.o view.o gfx.o demo_mac.o bot.o $(COMMON)/link.o $(COMMON)/io_pipe.o $(COMMON)/io_mailbox.o
CFLAGS = -O2 -G0 -Wall -std=gnu99
LIBS = -lpspctrl -lpspdisplay -lpspge -lm

# Real USB (usbhostfs mode) is ON by default; `make USB=0` builds an emulator/demo-only EBOOT.
EXTRA_TARGETS = EBOOT.PBP
USB ?= 1
ifeq ($(USB),1)
include $(COMMON)/usb/usb.mk
endif
PSP_EBOOT_TITLE = Blackwater Ping
BUILD_PRX = 1
PSPSDK = $(shell psp-config --pspsdk-path)
include $(PSPSDK)/lib/build.mak
