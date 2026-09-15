/** @file src/gfx.h Graphics definitions. */

#ifndef GFX_H
#define GFX_H

extern uint8 g_paletteActive[256 * 3];
extern uint8 *g_palette1;
extern uint8 *g_palette2;
extern uint8 *g_paletteMapping1;
extern uint8 *g_paletteMapping2;

enum {
	SCREEN_WIDTH  = 320, /*!< Width of the screen in pixels. */
	SCREEN_HEIGHT = 200  /*!< Height of the screen in pixels. */
};

typedef enum Screen {
	SCREEN_0 = 0,
	SCREEN_1 = 1,
	SCREEN_2 = 2,
	SCREEN_3 = 3,
	SCREEN_ACTIVE = -1
} Screen;

extern void GFX_Init(void);
extern void GFX_Uninit(void);
extern Screen GFX_Screen_SetActive(Screen screenID);
extern bool GFX_Screen_IsActive(Screen screenID);
extern uint16 GFX_Screen_GetSize_ByIndex(Screen screenID);
extern void *GFX_Screen_Get_ByIndex(Screen screenID);

#define GFX_Screen_GetActive() GFX_Screen_Get_ByIndex(SCREEN_ACTIVE)

extern void GFX_DrawTile(uint16 spriteID, uint16 x, uint16 y, uint8 houseID);
extern void GFX_Init_TilesInfo(uint16 widthSize, uint16 heightSize);
extern void GFX_InvalidateTileLut(void);
extern void GFX_PutPixel(uint16 x, uint16 y, uint8 colour);
extern void GFX_Screen_Copy2(int16 xSrc, int16 ySrc, int16 xDst, int16 yDst, int16 width, int16 height, Screen screenSrc, Screen screenDst, bool skipNull);
extern void GFX_Screen_Copy(int16 xSrc, int16 ySrc, int16 xDst, int16 yDst, int16 width, int16 height, Screen screenSrc, Screen screenDst);
extern void GFX_ClearScreen(Screen screenID);
extern void GFX_ClearBlock(Screen index);
extern void GFX_SetPalette(uint8 *palette);
extern uint8 GFX_GetPixel(uint16 x, uint16 y);
extern uint16 GFX_GetSize(int16 width, int16 height);
extern void GFX_CopyFromBuffer(int16 left, int16 top, uint16 width, uint16 height, uint8 *buffer);
extern void GFX_CopyToBuffer(int16 left, int16 top, uint16 width, uint16 height, uint8 *buffer);

#define GFX_STORE_DIRTY_AREA
#if defined(TOS)
#define GFX_STORE_DIRTY_AREA_BLOCKS
#endif

struct dirty_area { uint16 left; uint16 top; uint16 right; uint16 bottom; };
#ifdef GFX_STORE_DIRTY_AREA
extern void GFX_Screen_SetDirty(Screen screenID, uint16 left, uint16 top, uint16 right, uint16 bottom);
extern void GFX_Screen_SetClean(Screen screenID);
extern bool GFX_Screen_IsDirty(Screen screenID);
extern struct dirty_area * GFX_Screen_GetDirtyArea(Screen screenID);
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
extern uint32 g_dirty_blocks[200];
#endif

/* Attribute dirty pixels to their producer, to size the "render terrain
 * directly in planar" idea: only 16px-aligned opaque block writes can skip
 * the chunky+c2p path, masked/unaligned sprite work cannot. */
/* DISABLED BY DEFAULT: see the note on VIDEO_C2P_STATS in video_atari.c.
 * These counters are reported through unbuffered Warning() writes from
 * inside the video tick, which perturbs exactly what it measures. Build
 * with -DGFX_DIRTY_SOURCE_STATS_ENABLE to collect them. */
#if defined(TOS) && defined(GFX_STORE_DIRTY_AREA_BLOCKS) && defined(GFX_DIRTY_SOURCE_STATS_ENABLE)
#define GFX_DIRTY_SOURCE_STATS
#endif
#ifdef GFX_DIRTY_SOURCE_STATS
enum DirtySource {
	DIRTY_SRC_VIEWPORT = 0,	/* GUI_Screen_Copy from the viewport tile rows */
	DIRTY_SRC_SCREENCOPY,	/* other GFX_Screen_Copy / GUI_Screen_Copy */
	DIRTY_SRC_SPRITE,	/* GUI_DrawSprite (mouse cursor, units, icons) */
	DIRTY_SRC_MOUSERESTORE,	/* GFX_CopyFromBuffer: cursor background restore */
	DIRTY_SRC_WSA,		/* WSA animation frames */
	DIRTY_SRC_TEXT,		/* font glyph blits */
	DIRTY_SRC_RECT,		/* filled rectangles / lines */
	DIRTY_SRC_FULL,		/* whole-screen invalidations */
	DIRTY_SRC_OTHER,
	DIRTY_SRC_COUNT
};
extern void GFX_Screen_SetDirtySource(int source);
extern void GFX_DirtyStats_Report(void);
#else
#define GFX_Screen_SetDirtySource(source)
#define GFX_DirtyStats_Report()
#endif
#else
#define GFX_Screen_SetDirty(screenID, left, top, right, bottom)
#define GFX_Screen_SetDirtySource(source)
#define GFX_DirtyStats_Report()
#define GFX_Screen_SetClean(screenID)
#define GFX_Screen_IsDirty(screenID) true
#define GFX_Screen_GetDirtyArea(screenID) NULL
#endif /* GFX_STORE_DIRTY_AREA */

#endif /* GFX_H */
