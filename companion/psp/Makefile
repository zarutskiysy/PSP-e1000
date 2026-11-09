# PSP AI Companion EBOOT.
#   export PATH=$HOME/pspdev/bin:$PATH && make -C companion/psp   -> EBOOT.PBP + usbhostfs.prx + pspmaclink.prx
#   make -C companion/psp USB=0                                   -> emulator-only EBOOT
# Install: copy EBOOT.PBP and both PRXs to ms0:/PSP/GAME/PSPCOMPANION/
TARGET = psp_companion
COMMON = ../../common/psp
USB ?= 1
OBJS = main.o app.o pet.o gfx.o ui.o $(COMMON)/link.o $(COMMON)/io_mailbox.o
CFLAGS = -O2 -G0 -Wall -std=gnu99
LIBS = -lpspctrl -lpspdisplay -lpspge -lpsppower -lm
EXTRA_TARGETS = EBOOT.PBP
ifeq ($(USB),1)
include $(COMMON)/usb/usb.mk
endif
PSP_EBOOT_TITLE = PSP AI Companion
BUILD_PRX = 1
PSPSDK = $(shell psp-config --pspsdk-path)
include $(PSPSDK)/lib/build.mak
