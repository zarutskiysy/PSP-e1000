#include "io_posix_tcp.h"
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

static void tune(int fd) {
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
}

int psp_tcp_listen_accept(const char *host, int port) {
    struct sockaddr_in a;
    int one = 1, s, c;
    s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) return -1;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET;
    a.sin_port = htons((uint16_t)port);
    inet_pton(AF_INET, host, &a.sin_addr);
    if (bind(s, (struct sockaddr *)&a, sizeof(a)) < 0 || listen(s, 1) < 0) {
        close(s);
        return -2;
    }
    c = accept(s, NULL, NULL);
    close(s);
    if (c >= 0) tune(c);
    return c;
}

int psp_tcp_connect(const char *host, int port) {
    struct sockaddr_in a;
    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) return -1;
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET;
    a.sin_port = htons((uint16_t)port);
    inet_pton(AF_INET, host, &a.sin_addr);
    if (connect(s, (struct sockaddr *)&a, sizeof(a)) < 0) {
        close(s);
        return -2;
    }
    tune(s);
    return s;
}

static int tcp_write(void *ctx, const void *buf, int len) {
    int fd = *(int *)ctx, done = 0;
    while (done < len) {
        ssize_t w = send(fd, (const char *)buf + done, (size_t)(len - done), 0);
        if (w <= 0) return -1;
        done += (int)w;
    }
    return done;
}

static int tcp_read(void *ctx, void *buf, int len, int timeout_us) {
    int fd = *(int *)ctx;
    struct pollfd p;
    int r;
    ssize_t n;
    p.fd = fd;
    p.events = POLLIN;
    r = poll(&p, 1, timeout_us < 0 ? -1 : timeout_us / 1000);
    if (r < 0) return -1;
    if (r == 0) return 0;
    n = recv(fd, buf, (size_t)len, 0);
    if (n <= 0) return -1; /* 0 = peer closed */
    return (int)n;
}

psp_link_io_t psp_tcp_io(int *fd) {
    psp_link_io_t io;
    io.write = tcp_write;
    io.read = tcp_read;
    io.ctx = fd;
    return io;
}
