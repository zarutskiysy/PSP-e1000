/* pspmaclink.prx syscall API (kernel module, see main.c). Called through psp_usb_io.c. */
#ifndef PSPMACLINK_H
#define PSPMACLINK_H
#ifdef __cplusplus
extern "C" {
#endif
#define PML_MODE_HOSTFS 1  /* start psplink's USBHostFSDriver (usbhostfs.prx must be loaded), async channel 4 */
#define PML_MODE_MACLINK 2 /* start our own vendor bulk driver "PspMacLinkDriver" */
#define PML_DRIVER_NAME "PspMacLinkDriver"
#define PML_PID_MACLINK 0x1CB
#define PML_PID_HOSTFS 0x1C9
/* returns 0 or a negative sce error */
int pmlStart(int mode);
int pmlStop(void);
/* 0 off, 1 waiting for host, 2 connected */
int pmlState(void);
/* blocking write of len bytes, returns len or <0 */
int pmlWrite(const void *data, int len);
/* waits up to timeout_us (<0 forever) for data, returns bytes (>0), 0 timeout, <0 error */
int pmlRead(void *data, int len, int timeout_us);
/* debug counters: out[0]=attach speed (1 full, 2 hi), [1]=rx bytes, [2]=tx bytes, [3]=last error; returns 4 */
int pmlInfo(int *out, int n);
#ifdef __cplusplus
}
#endif
#endif
