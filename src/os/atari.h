#ifndef OS_ATARI_H
#define OS_ATARI_H

#include <mint/osbind.h>
#include "types.h"

#ifndef ATARI_SUPERVISOR_RESIDENT
#define ATARI_SUPERVISOR_RESIDENT 0
#endif

#if ATARI_SUPERVISOR_RESIDENT
extern bool g_atariSupervisorResident;

#define Atari_SupervisorExec(callback) do { \
	if (g_atariSupervisorResident) (callback)(); \
	else (void)Supexec(callback); \
} while (0)
#define Atari_SupervisorRead(callback) \
	(g_atariSupervisorResident ? (callback)() : Supexec(callback))
#else
#define Atari_SupervisorExec(callback) ((void)Supexec(callback))
#define Atari_SupervisorRead(callback) Supexec(callback)
#endif

#endif
