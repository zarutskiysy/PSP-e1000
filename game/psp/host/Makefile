# macOS host build of the PSP console (same C sources as the EBOOT).
#   make -C game/psp/host          -> run unit tests
#   make -C game/psp/host psp_host -> host console (TCP / demo / PPM screenshots)
CC ?= cc
CFLAGS ?= -std=c99 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined
COMMON = ../../../common/psp
SRC = ../console.c ../view.c ../gfx.c ../app.c ../demo_mac.c ../bot.c $(COMMON)/link.c $(COMMON)/io_pipe.c
HDR = $(wildcard ../*.h) ../../proto_game.h $(COMMON)/link.h ../../../common/protocol/psp_link.h

all: run

test_console.bin: test_console.c $(SRC) $(HDR)
	$(CC) $(CFLAGS) -o $@ test_console.c $(SRC) -lm

psp_host: host_main.c $(SRC) $(COMMON)/io_posix_tcp.c $(HDR)
	$(CC) -std=c99 -Wall -Wextra -Werror -O2 -o $@ host_main.c $(SRC) $(COMMON)/io_posix_tcp.c -lm

run: test_console.bin
	./test_console.bin

clean:
	rm -rf *.bin *.dSYM psp_host

.PHONY: all run clean
