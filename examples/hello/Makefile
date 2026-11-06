# Build: source tools/env.sh && make -C examples/hello   -> EBOOT.PBP
TARGET = hello
COMMON = ../../common/psp
OBJS = main.o $(COMMON)/link.o $(COMMON)/io_pipe.o
CFLAGS = -O2 -G0 -Wall -std=gnu99
LIBS = -lpspctrl -lpsprtc
EXTRA_TARGETS = EBOOT.PBP
PSP_EBOOT_TITLE = PSP E1000 x Mac Hello
BUILD_PRX = 1
PSPSDK = $(shell psp-config --pspsdk-path)
include $(PSPSDK)/lib/build.mak
