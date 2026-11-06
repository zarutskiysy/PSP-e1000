/* io_posix_tcp.h — POSIX TCP transport for host (macOS/Linux) builds of PSP-side logic.
 * Lets the exact PSP C code talk to the Mac daemon through the mock TCP transport. */
#ifndef PSP_IO_POSIX_TCP_H
#define PSP_IO_POSIX_TCP_H
#include "link.h"
/* Listens on host:port and accepts one client (the Mac side connects, as with USB). Returns fd or <0. */
int psp_tcp_listen_accept(const char *host, int port);
/* Connects to host:port. Returns fd or <0. */
int psp_tcp_connect(const char *host, int port);
/* ctx must point to an int holding the fd and stay alive while the io is used. */
psp_link_io_t psp_tcp_io(int *fd);
#endif
