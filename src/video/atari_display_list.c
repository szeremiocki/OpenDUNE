#include <assert.h>
#include <string.h>
#include "../../include/types.h"
#include "../os/endian.h"
#include "video.h"

bool g_videoDisplayListActive;
uint16 *g_videoDisplayListNext, *g_videoDisplayListLimit;
static uint16 s_storage[VIDEO_ATARI_DISPLAY_LIST_BYTES / 2];

bool Video_Atari_DisplayListPending(void)
{
	return g_videoDisplayListActive && g_videoDisplayListNext != s_storage;
}

void Video_Atari_DisplayListFlush(void)
{
	if (g_videoScrollPending) Video_Atari_FinishScroll();
	if (!Video_Atari_DisplayListPending()) return;
	*g_videoDisplayListNext = HTOBE16(0x4e75);
	g_videoDisplayListActive = false;
	Video_Atari_ExecuteDisplayList(s_storage);
	g_videoDisplayListNext = s_storage;
	g_videoDisplayListActive = true;
}

void Video_Atari_DisplayListBegin(void)
{
	assert(!g_videoDisplayListActive);
	if (!Video_Atari_ViewportBlitter()) return;
	g_videoDisplayListNext = s_storage;
	g_videoDisplayListLimit = s_storage + VIDEO_ATARI_DISPLAY_LIST_BYTES / 2 - 1;
	g_videoDisplayListActive = true;
}

void Video_Atari_DisplayListCheck(uint16 bytes)
{
	assert(bytes != 0 && !(bytes & 1) && bytes <= VIDEO_ATARI_DISPLAY_LIST_BYTES - 2);
	if (g_videoDisplayListActive &&
	    (uint32)(g_videoDisplayListLimit - g_videoDisplayListNext) * 2 < bytes)
		Video_Atari_DisplayListFlush();
}

void Video_Atari_QueueTileCursor(void)
{
	uint16 *out = g_videoDisplayListNext;
	uint32 address = HTOBE32((uint32)(size_t)g_videoTileCursorTail);

	assert(g_videoDisplayListActive && g_videoTileCursorTail != NULL);
	assert(g_videoDisplayListLimit - out >= 3);
	*out++ = HTOBE16(0x4eb9);
	/* Longword operands in the instruction stream are word-aligned. */
	memcpy(__builtin_assume_aligned(out, 2), &address, sizeof(address));
	g_videoDisplayListNext = out + 2;
}

void Video_Atari_DisplayListEnd(void)
{
	Video_Atari_DisplayListFlush();
	g_videoDisplayListActive = false;
}

void Video_Atari_DisplayListFree(void)
{
	Video_Atari_DisplayListEnd();
	g_videoDisplayListNext = g_videoDisplayListLimit = NULL;
}
