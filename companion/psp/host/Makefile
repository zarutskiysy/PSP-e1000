# Host (macOS) builds of the PSP logic and renderer, with ASan/UBSan.
#   make -C companion/psp/host         -> test_app, render, vectors
#   make -C companion/psp/host check   -> runs test_app
CC = clang
CFLAGS = -std=gnu99 -g -O1 -Wall -Wextra -Wno-unused-parameter -fsanitize=address,undefined -fno-omit-frame-pointer
SRC = ../app.c ../pet.c ../gfx.c ../ui.c
BIN = test_app render vectors

all: $(BIN)

test_app: test_app.c $(SRC)
	$(CC) $(CFLAGS) -o $@ test_app.c $(SRC) -lm

render: render.c $(SRC)
	$(CC) $(CFLAGS) -o $@ render.c $(SRC) -lm

vectors: vectors.c $(SRC)
	$(CC) $(CFLAGS) -o $@ vectors.c $(SRC) -lm

check: test_app
	./test_app

clean:
	rm -rf $(BIN) *.dSYM

.PHONY: all check clean
