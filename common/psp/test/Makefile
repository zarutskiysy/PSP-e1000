# Host (macOS) unit tests for the PSP-side C code.  Usage: make -C common/psp/test
CC ?= cc
CFLAGS ?= -std=c99 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined
SRC = ../link.c ../io_pipe.c ../io_mailbox.c

all: run

test_link.bin: test_link.c $(SRC) ../link.h ../io_pipe.h ../io_mailbox.h ../../protocol/psp_link.h
	$(CC) $(CFLAGS) -o $@ test_link.c $(SRC)

run: test_link.bin
	./test_link.bin

golden: test_link.bin
	./test_link.bin --golden

clean:
	rm -rf *.bin *.dSYM

.PHONY: all run golden clean

echo_psp.bin: echo_psp.c ../link.c ../io_posix_tcp.c ../link.h ../io_posix_tcp.h ../../protocol/psp_link.h
	$(CC) $(CFLAGS) -o $@ echo_psp.c ../link.c ../io_posix_tcp.c
