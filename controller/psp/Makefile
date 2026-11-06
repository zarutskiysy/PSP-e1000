# PSP control deck app.
#   source tools/env.sh && make -C controller/psp        -> EBOOT.PBP + usbhostfs.prx + pspmaclink.prx
#   make -C controller/psp USB=0                          -> emulator/demo-only EBOOT (usb_stub.c)
# Transport is chosen at runtime in deck_io.c: USB HOSTFS on hardware, PPSSPP mailbox in the
# emulator, built-in demo peer as fallback. Copy EBOOT.PBP + both PRXs to ms0:/PSP/GAME/PSPDECK/.
TARGET = psp_deck
COMMON = ../../common/psp
USB ?= 1
OBJS = main.o deck_io.o demo_peer.o $(COMMON)/link.o $(COMMON)/io_pipe.o $(COMMON)/io_mailbox.o
CFLAGS = -O2 -G0 -Wall -std=gnu99
LIBS = -lpspctrl -lpsprtc -lm
EXTRA_TARGETS = EBOOT.PBP
ifeq ($(USB),1)
include $(COMMON)/usb/usb.mk
else
OBJS += usb_stub.o
endif
PSP_EBOOT_TITLE = PSP Deck (Mac controller)
BUILD_PRX = 1
PSPSDK = $(shell psp-config --pspsdk-path)
include $(PSPSDK)/lib/build.mak
