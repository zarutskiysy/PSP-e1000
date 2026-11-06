# Build: source tools/env.sh && make -C screen/psp   -> screen/psp/EBOOT.PBP
# Optional ios are compiled in automatically once their sources exist in common/psp (from main):
#   common/psp/usb/usb_io.c   -> USB maclink/hostfs (SCR_HAVE_USB)
#   common/psp/io_mailbox.c   -> PPSSPP mailbox     (SCR_HAVE_MAILBOX)
TARGET = pspscreen
COMMON = ../../common/psp
OBJS = main.o ../codec/scr_codec.o $(COMMON)/link.o
CFLAGS = -O2 -G0 -Wall -std=gnu99
LIBS = -lpspctrl -lpsppower
ifneq ($(wildcard $(COMMON)/usb/usb_io.c),)
OBJS += $(COMMON)/usb/usb_io.o
CFLAGS += -DSCR_HAVE_USB
LIBS += -lpspusb -lpspusbbus -lpspkubridge
endif
ifneq ($(wildcard $(COMMON)/io_mailbox.c),)
OBJS += $(COMMON)/io_mailbox.o
CFLAGS += -DSCR_HAVE_MAILBOX
endif
EXTRA_TARGETS = EBOOT.PBP
PSP_EBOOT_TITLE = PSP E1000 Second Screen
BUILD_PRX = 1
PSPSDK = $(shell psp-config --pspsdk-path)
include $(PSPSDK)/lib/build.mak
