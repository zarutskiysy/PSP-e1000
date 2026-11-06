# pspmaclink.prx (kernel module). Build: source tools/env.sh && make -C common/psp/usb/prx
# Also produces PspMacLink.S, the user-mode syscall stubs linked into EBOOTs (see ../usb.mk).
TARGET = pspmaclink
OBJS = main.o USBHostFS_driver.o exports.o
USE_KERNEL_LIBS = 1
INCDIR =
CFLAGS = -Os -G0 -Wall -fno-builtin-printf
ASFLAGS = $(CFLAGS)
LIBDIR =
LIBS = -lpspusbbus_driver -lpspusb_driver
EXTRA_CLEAN = USBHostFS_driver.S PspMacLink.S

PSPSDK = $(shell psp-config --pspsdk-path)
include $(PSPSDK)/lib/build_prx.mak

# kernel import stubs for usbhostfs.prx's USBHostFS_driver library (generated from the vendored exports)
USBHostFS_driver.S: ../../usbhostfs/exports.exp
	cd $(dir $<) && psp-build-exports -s exports.exp && mv USBHostFS_driver.S $(CURDIR)/ && rm -f USBHostFS.S

PspMacLink.S: exports.exp
	psp-build-exports -s exports.exp

all: PspMacLink.S
