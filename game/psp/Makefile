# Blackwater Ping — PSP console EBOOT.
#   source tools/env.sh && make -C game/psp        -> game/psp/EBOOT.PBP
# Transports: PPSSPP mailbox (always), in-process demo (always), real USB (compiled in automatically
# once common/psp/usb/psp_usb_io.c exists on main).
TARGET = blackwater
COMMON = ../../common/psp
OBJS = main.o app.o console.o view.o gfx.o demo_mac.o bot.o $(COMMON)/link.o $(COMMON)/io_pipe.o $(COMMON)/io_mailbox.o
CFLAGS = -O2 -G0 -Wall -std=gnu99
LIBS = -lpspctrl -lpspdisplay -lpspge -lm

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
