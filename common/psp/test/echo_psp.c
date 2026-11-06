/* Host build of PSP-side link logic over TCP: listens on 127.0.0.1:<port> (0 = random), prints
 * "PORT n", answers HELLO/PING automatically and echoes every frame of type >= 0xF1. Exits on BYE. */
#include <arpa/inet.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>
#include "../io_posix_tcp.h"

static uint8_t rx[1 << 20], tx[(1 << 20) + 64], chunk[65536];

int main(int argc, char **argv) {
    int port = argc > 1 ? atoi(argv[1]) : 47100, fd, s, one = 1;
    struct sockaddr_in a;
    socklen_t al = sizeof a;
    psp_link_t l;
    psp_link_frame_t f;
    /* listen manually so that port 0 works and we can print the chosen port */
    s = socket(AF_INET, SOCK_STREAM, 0);
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons((uint16_t)port);
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(s, (struct sockaddr *)&a, sizeof a) || listen(s, 1)) return 2;
    getsockname(s, (struct sockaddr *)&a, &al);
    printf("PORT %d\n", ntohs(a.sin_port));
    fflush(stdout);
    fd = accept(s, NULL, NULL);
    close(s);
    psp_link_init(&l, psp_tcp_io(&fd), rx, sizeof rx, tx, sizeof tx, chunk, sizeof chunk);
    l.name = "echo_psp";
    for (;;) {
        int r = psp_link_poll(&l, 1000000, &f);
        if (r < 0) return 3;
        if (r == 0) continue;
        if (f.type == PSP_LINK_T_BYE) break;
        if (f.type >= 0xF1) psp_link_send(&l, f.type, f.flags, f.payload, f.len);
    }
    close(fd);
    return 0;
}
