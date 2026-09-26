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
extern void GFX_Init_DecodedTiles(uint32 tilesDataLength);
extern void GFX_FreeDecodedTiles(void);

/* One-shot measurement of the tile count and the RAM cost of pre-decoding
 * tiles to byte-per-pixel. The tile data lives in the game's PAK files, so
 * this can only be measured on the target. Results go to error.log.
 * Build with -DGFX_TILE_SIZE_STATS_ENABLE. */
#if defined(GFX_TILE_SIZE_STATS_ENABLE)
#define GFX_TILE_SIZE_STATS
extern void GFX_Report_TilesInfo(uint32 tilesDataLength);
#endif
extern void GFX_InvalidateTileLut(void);
extern void GFX_PutPixel(uint16 x, uint16 y, uint8 colour);
extern void GFX_Screen_Copy2(int16 xSrc, int16 ySrc, int16 xDst, int16 yDst, int16 width, int16 height, Screen screenSrc, Screen screenDst, bool skipNull);
extern void GFX_Screen_Copy(int16 xSrc, int16 ySrc, int16 xDst, int16 yDst, int16 width, int16 height, Screen screenSrc, Screen screenDst);
extern void GFX_Screen_CopyOverlap(int16 xSrc, int16 ySrc, int16 xDst, int16 yDst, int16 width, int16 height, Screen screen);
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
extern void GFX_Screen_SetDirty_(uint16 left, uint16 top, uint16 right, uint16 bottom);
/**
 * Temporarily ignore every dirty mark. Used by the Atari direct-to-planar
 * mouse cursor, which renders the sprite into SCREEN_0 only to read the
 * pixels back and immediately undoes the change.
 */
extern void GFX_Screen_SetDirtySuppress(bool suppress);

/* ENHANCEMENT -- Only SCREEN_0 is ever tracked, but an m68000 profile
 * showed 23145 calls of which just 1552 (6.7%) passed that test: the other
 * 93.3% pushed five arguments, JSR'd, tested the screen ID and returned.
 * That dead call overhead cost ~0.55% of all cycles, over half of it in the
 * callers' argument pushes.
 *
 * Hoisting the test into a macro lets the compiler discard the whole call
 * -- arguments included -- when the target is not the visible screen.
 * s_screenActiveID is exposed as g_screenActiveID for this.
 *
 * Measured: calls 23145 -> 1407 (every remaining call does real work), and
 * GUI_DrawSprite's per-call setup 167 instructions/2165 cycles -> 110/1481,
 * i.e. -31.6%. The per-scanline g_dirty_blocks loop is untouched at 48.1
 * cycles/iteration before and after, as are the sprite pixel loops. */
extern Screen g_screenActiveID;
#define GFX_Screen_SetDirty(screenID, left, top, right, bottom) \
	do { \
		Screen screenID_ = (screenID); \
		if (screenID_ == SCREEN_ACTIVE) screenID_ = g_screenActiveID; \
		if (screenID_ == SCREEN_0) { \
			GFX_Screen_SetDirty_((left), (top), (right), (bottom)); \
		} \
	} while (0)
extern void GFX_Screen_SetClean(Screen screenID);
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
extern void GFX_Screen_ClearDirtyRect(uint16 left, uint16 top, uint16 right, uint16 bottom);
#else
#define GFX_Screen_ClearDirtyRect(left, top, right, bottom)
#endif
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
/*#define GFX_DIRTY_SOURCE_STATS_ENABLE 1*/
#if defined(TOS) && defined(GFX_STORE_DIRTY_AREA_BLOCKS) && defined(GFX_DIRTY_SOURCE_STATS_ENABLE)
#define GFX_DIRTY_SOURCE_STATS
#endif

/* Logs every GFX_SetPalette() call (which palette range changed, and
 * whether the call was a no-op) plus every fast-path decision in
 * Video_Atari_TryPaletteFadeUniform(), including the uniform-value
 * detection result and the current hardware register state. Off by
 * default -- like the other *_STATS flags here, it writes through
 * unbuffered Warning() and is only meant for tracing palette/fade
 * behaviour. This is what identified the "intro cutscene stays black"
 * bug (hardware registers left at black while a non-uniform fade took
 * the software-only fallback path), and what measured the pair-LUT
 * rebuild counts that motivated the uniform fast path, so it is kept
 * for the next time fade behaviour needs investigating. */
/* #define PALETTE_FADE_DEBUG 1 */
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
