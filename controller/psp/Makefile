# PSP control deck app.  Build: source tools/env.sh && make -C controller/psp   -> controller/psp/EBOOT.PBP
#
# Transport sources are picked automatically:
#   common/psp/usb/*.c present  -> real USB io (HOSTFS mode); else usb_stub.c (USB reports "not built")
#   common/psp/io_mailbox.c     -> PPSSPP mailbox io (-DDECK_HAVE_MAILBOX); else built-in demo peer
TARGET = psp_deck
COMMON = ../../common/psp

USB_SRCS := $(wildcard $(COMMON)/usb/*.c)
ifeq ($(strip $(USB_SRCS)),)
USB_OBJS = usb_stub.o
else
USB_OBJS = $(USB_SRCS:.c=.o)
endif

ifneq ($(wildcard $(COMMON)/io_mailbox.c),)
MAILBOX_OBJS = $(COMMON)/io_mailbox.o deck_mailbox.o
MAILBOX_FLAGS = -DDECK_HAVE_MAILBOX
endif

OBJS = main.o deck_io.o demo_peer.o $(COMMON)/link.o $(COMMON)/io_pipe.o $(USB_OBJS) $(MAILBOX_OBJS)
CFLAGS = -O2 -G0 -Wall -std=gnu99 $(MAILBOX_FLAGS) $(USB_CFLAGS)
LIBS = $(USB_LIBS) -lpspctrl -lpsprtc -lm
EXTRA_TARGETS = EBOOT.PBP
PSP_EBOOT_TITLE = PSP Deck (Mac controller)
BUILD_PRX = 1
PSPSDK = $(shell psp-config --pspsdk-path)
include $(PSPSDK)/lib/build.mak

.PHONY: info
info:
	@echo "USB objects:     $(USB_OBJS)"
	@echo "mailbox objects: $(MAILBOX_OBJS)"
