# source tools/env.sh && make -C examples/echo            (emulator-only build)
#                         make -C examples/echo USB=1     (adds the USB transport; needs common/psp/usb)
TARGET = echo
COMMON = ../../common/psp
OBJS = main.o $(COMMON)/link.o $(COMMON)/io_mailbox.o
CFLAGS = -O2 -G0 -Wall -std=gnu99
LIBS = -lpspctrl
ifeq ($(USB),1)
include $(COMMON)/usb/usb.mk
endif
EXTRA_TARGETS = EBOOT.PBP
PSP_EBOOT_TITLE = PSP E1000 x Mac Echo
BUILD_PRX = 1
PSPSDK = $(shell psp-config --pspsdk-path)
include $(PSPSDK)/lib/build.mak
