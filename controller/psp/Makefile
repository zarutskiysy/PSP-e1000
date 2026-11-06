# PSP control deck app.  Build: source tools/env.sh && make -C controller/psp   -> controller/psp/EBOOT.PBP
#
# Transports (chosen at runtime in deck_io.c): USB HOSTFS on hardware, PPSSPP mailbox in the
# emulator, built-in demo peer as fallback. The USB io comes from common/psp/usb/usb.mk when it
# exists on main; until then usb_stub.c is linked and the app reports "USB io not built in".
TARGET = psp_deck
COMMON = ../../common/psp
OBJS = main.o deck_io.o demo_peer.o $(COMMON)/link.o $(COMMON)/io_pipe.o $(COMMON)/io_mailbox.o
CFLAGS = -O2 -G0 -Wall -std=gnu99
LIBS = -lpspctrl -lpsprtc -lm
ifneq ($(wildcard $(COMMON)/usb/usb.mk),)
include $(COMMON)/usb/usb.mk
else
OBJS += usb_stub.o
endif
EXTRA_TARGETS = EBOOT.PBP
PSP_EBOOT_TITLE = PSP Deck (Mac controller)
BUILD_PRX = 1
PSPSDK = $(shell psp-config --pspsdk-path)
include $(PSPSDK)/lib/build.mak
