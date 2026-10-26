/** @file src/os/common.h Compiler-independent common statements. */

#ifndef OS_COMMON_H
#define OS_COMMON_H

/**
 * Compute length of an array.
 * @param address of the array.
 * @return Number of elements of the array.
 */
#define lengthof(array) (sizeof(array) / sizeof((array)[0]))

#ifdef TOS
#include <stddef.h>
#include <string.h>

/**
 * Compare two 2-byte aligned blocks of even size for equality; the m68k libc memcmp() is a slow byte loop.
 * @return True if the blocks are identical.
 */
static inline int Memory_Equal16(const void *a, const void *b, size_t bytes)
{
	typedef unsigned long __attribute__((may_alias)) Long;
	typedef unsigned short __attribute__((may_alias)) Word;
	const Long *la = (const Long *)a, *lb = (const Long *)b;
	size_t longs = bytes >> 2;

	while (longs-- != 0) {
		if (*la++ != *lb++) return 0;
	}
	if ((bytes & 2) != 0 && *(const Word *)la != *(const Word *)lb) return 0;
	return 1;
}
#else
#include <string.h>
#define Memory_Equal16(a, b, bytes) (memcmp((a), (b), (bytes)) == 0)
#endif

#endif /* OS_COMMON_H */
