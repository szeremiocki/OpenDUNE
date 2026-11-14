#ifndef VIDEO_ATARI_SIDEBAR_H
#define VIDEO_ATARI_SIDEBAR_H

#include <stddef.h>
#include "types.h"

typedef struct VideoAtariSidebarBlit {
	uint16 words[192];
} VideoAtariSidebarBlit;

/* Immutable source pixels and opacity use four interleaved words per group.
 * NULL opacity selects an opaque copy, with endmasks for shifted/clipped edges. */
extern size_t Video_Atari_CompileSidebarBlit(VideoAtariSidebarBlit *code,
    const uint16 *pixels, const uint16 *masks, uint16 sourceWidth,
    uint16 width, uint16 height, uint16 phase);
extern void Video_Atari_QueueSidebarBlit(const uint16 *code, uint16 *dst);
/* dst is the first 16-pixel group containing the fixed 24x7 health-bar interior. */
extern void Video_Atari_QueueSidebarHealth(uint16 *dst, uint16 width, uint8 foreground, uint8 background);
/* Parameters live inside the list and must be filled before submitting the next command. */
extern void *Video_Atari_QueueSidebarCPU(void (*code)(const void *), size_t bytes);

#endif
