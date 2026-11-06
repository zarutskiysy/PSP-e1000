# One command (from the repo root):  source tools/env.sh && make -C screen/psp
#   -> screen/psp/EBOOT.PBP + pspmaclink.prx + usbhostfs.prx (copy all three to ms0:/PSP/GAME/pspscreen/)
# USB=0 builds an emulator-only EBOOT (mailbox + replay ios). The USB build also runs in PPSSPP.
TARGET = pspscreen
COMMON = ../../common/psp
USB ?= 1
OBJS = main.o ../codec/scr_codec.o $(COMMON)/link.o $(COMMON)/io_mailbox.o
CFLAGS = -O2 -G0 -Wall -std=gnu99
LIBS = -lpspctrl -lpsppower
EXTRA_TARGETS = EBOOT.PBP
ifeq ($(USB),1)
include $(COMMON)/usb/usb.mk
endif
PSP_EBOOT_TITLE = PSP E1000 Second Screen
BUILD_PRX = 1
PSPSDK = $(shell psp-config --pspsdk-path)
include $(PSPSDK)/lib/build.mak
