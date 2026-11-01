/* rt.c - the two C runtime functions the compiler may call even in a freestanding build (there is no CRT). */
#include <stddef.h>

void *memset(void *d, int c, size_t n) { unsigned char *p = d; while (n--) *p++ = (unsigned char)c; return d; }
void *memcpy(void *d, const void *s, size_t n) { unsigned char *p = d; const unsigned char *q = s; while (n--) *p++ = *q++; return d; }

/* The MSVC-style toolchain wants this symbol whenever floating point is used and there is no CRT. */
int _fltused = 1;
