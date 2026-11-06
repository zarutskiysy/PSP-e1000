# Include from a PSP app Makefile to add the real USB transport:
#
#   COMMON = <path to common/psp>
#   EXTRA_TARGETS = EBOOT.PBP
#   ifeq ($(USB),1)
#   include $(COMMON)/usb/usb.mk
#   endif
#   include $(PSPSDK)/lib/build.mak
#
# Adds -DWITH_USB, psp_usb_io.o and the PspMacLink syscall stubs, and builds usbhostfs.prx +
# pspmaclink.prx next to the EBOOT (copy all three to ms0:/PSP/GAME/<app>/).
.DEFAULT_GOAL := all
USB_DIR := $(COMMON)/usb
OBJS += $(USB_DIR)/psp_usb_io.o $(USB_DIR)/prx/PspMacLink.o
CFLAGS += -DWITH_USB
LIBS += -lpspkubridge
EXTRA_TARGETS += usbhostfs.prx pspmaclink.prx
EXTRA_CLEAN += usbhostfs.prx pspmaclink.prx

$(USB_DIR)/prx/PspMacLink.S:
	$(MAKE) -C $(USB_DIR)/prx PspMacLink.S

usbhostfs.prx: FORCE
	$(MAKE) -C $(COMMON)/usbhostfs
	cp $(COMMON)/usbhostfs/usbhostfs.prx $@

pspmaclink.prx: FORCE
	$(MAKE) -C $(USB_DIR)/prx
	cp $(USB_DIR)/prx/pspmaclink.prx $@

.PHONY: FORCE
FORCE:
