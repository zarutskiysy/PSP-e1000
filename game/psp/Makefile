# Blackwater Ping — PSP console EBOOT.
#   source tools/env.sh && make -C game/psp        -> game/psp/EBOOT.PBP
# Optional transports are compiled in automatically when their sources exist in common/:
#   common/psp/io_mailbox.c      -> PPSSPP mailbox io (tools/ppsspp_bridge.py)
#   common/psp/usb/psp_usb_io.c  -> real USB (usbhostfs mode)
TARGET = blackwater
COMMON = ../../common/psp
OBJS = main.o app.o console.o view.o gfx.o demo_mac.o bot.o $(COMMON)/link.o $(COMMON)/io_pipe.o
CFLAGS = -O2 -G0 -Wall -std=gnu99
LIBS = -lpspctrl -lpspdisplay -lpspge -lm

ifneq ($(wildcard $(COMMON)/io_mailbox.c),)
OBJS += $(COMMON)/io_mailbox.o
CFLAGS += -DBW_HAVE_MAILBOX
endif
ifneq ($(wildcard $(COMMON)/usb/psp_usb_io.c),)
OBJS += $(COMMON)/usb/psp_usb_io.o
CFLAGS += -DBW_HAVE_USB
LIBS += -lpspusb -lpspusbbus
endif

EXTRA_TARGETS = EBOOT.PBP
PSP_EBOOT_TITLE = Blackwater Ping
BUILD_PRX = 1
PSPSDK = $(shell psp-config --pspsdk-path)
include $(PSPSDK)/lib/build.mak
