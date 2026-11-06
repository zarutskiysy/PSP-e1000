# Host (macOS) build of the PSP decoder: unit tests + shared lib for tools/fake_psp_screen.py.
#   make -C screen/codec          -> runs the C tests, builds libscrcodec.dylib
CC ?= cc
CFLAGS_TEST ?= -std=c99 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined
CFLAGS_LIB ?= -std=c99 -Wall -Wextra -Werror -O2 -fPIC
SRC = scr_codec.c
DEPS = scr_codec.c scr_codec.h ../proto_screen.h
UNAME := $(shell uname)
LIBEXT := $(if $(filter Darwin,$(UNAME)),dylib,so)

all: test lib

test/test_codec.bin: test/test_codec.c $(DEPS)
	$(CC) $(CFLAGS_TEST) -o $@ test/test_codec.c $(SRC)

test: test/test_codec.bin
	./test/test_codec.bin

lib: libscrcodec.$(LIBEXT)

libscrcodec.$(LIBEXT): $(DEPS)
	$(CC) $(CFLAGS_LIB) -shared -o $@ $(SRC)

clean:
	rm -rf test/*.bin test/*.dSYM libscrcodec.*

.PHONY: all test lib clean
