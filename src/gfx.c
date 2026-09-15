/** @file src/gfx.c Graphics routines. */

#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"

#include "gfx.h"

#include "gui/widget.h"
#include "house.h"
#include "opendune.h"
#include "sprites.h"
#include "video/video.h"
#include "os/error.h"

uint8 g_paletteActive[256 * 3];
uint8 *g_palette1 = NULL;
uint8 *g_palette2 = NULL;
uint8 *g_paletteMapping1 = NULL;
uint8 *g_paletteMapping2 = NULL;

static uint16 s_tileSpacing  = 0;	/* bytes to skip between each line. == SCREEN_WIDTH - 2*s_tileWidth */
static uint16 s_tileHeight   = 0;	/* "icon" sprites height (lines) */
static uint16 s_tileWidth    = 0;	/* "icon" sprites width in bytes. each bytes contains 2 pixels. 4 MSB = left, 4 LSB = right */
static uint8  s_tileMode     = 0;
static uint8  s_tileByteSize = 0;	/* size in byte of one sprite pixel data = s_tileHeight * s_tileWidth / 2 */

/* ENHANCEMENT -- Tiles pre-decoded to one byte per pixel at load time.
 *
 * g_tilesPixels packs two pixels per byte, so GFX_DrawTile had to split each
 * byte and map both nibbles through the tile's palette on every draw. That
 * expansion is a pure function of the tile data and its palette, so it is
 * hoisted to load time: tiles are decoded once into 8-bit chunky pixels and
 * the inner loop becomes a block copy.
 *
 * This is possible because g_iconRPAL entries are not RGB palettes but 16
 * bytes of 8-bit indices into the main 256-colour palette; the drawn pixel
 * is an ordinary main-palette index either way.
 *
 * Measured on ICON.ICN: 389 tiles of 16x16, 128 bytes packed -> 256 decoded,
 * so the cache costs 97 KB (49 KB more than the packed data it supplements)
 * against 979 KB free. If the allocation fails the old nibble-LUT path is
 * used unchanged, so this degrades gracefully.
 *
 * House recolouring (the 0x9x band, ~1.5% of calls) synthesises a palette
 * per call and cannot be pre-decoded; those calls keep the old path.
 *
 * Measured on m68000, at a comparable workload (viewport tiles 11838 ->
 * 11665): GFX_DrawTile 6.706% -> 2.853% of runtime, 12818 -> 5932 cycles
 * per call (-53.7%). The opaque inner loop went from 80.09 cycles per
 * source byte to 8.71, and the transparent one from 98.18 per byte to
 * 45.02 per pixel. */
static uint8 *s_tilesDecoded = NULL;	/* tileCount * (s_tileByteSize * 2) bytes, or NULL */
static uint8 *s_tileHasTransparency = NULL;	/* one flag per tile */
static uint16 s_tileCount = 0;

/* ENHANCEMENT -- Nibble-expansion lookup tables for GFX_DrawTile.
 *
 * Each source byte holds two pixels (4 MSB = left, 4 LSB = right), so the
 * inner loop has to split it and index the 16-entry palette twice. On 68000
 * GCC did that with LSR.L #4 plus AND.L #$0F - both long-sized operations on
 * nibble data - which cost 0.69% of total runtime *each*, measured.
 *
 * Expanding the palette into two 256-entry tables indexed by the whole byte
 * removes the shift and the mask outright: one byte index serves both
 * lookups, so the loop becomes MOVE.B (A1)+,D0 / two table-indexed stores /
 * CMP / BNE, taking the opaque loop from 116.1 to 76 cycles per source byte.
 *
 * Both tables are pure replication, so a build is 128 longword stores
 * (~4,000 cycles) rather than the 512 byte load/store pairs (~19,600) a
 * naive build would cost:
 *
 *   lo[b] = palette[b & 0x0F]  ->  the 16 palette bytes repeated 16 times
 *   hi[b] = palette[b >> 4]    ->  each palette byte replicated 16 times
 *
 * One call saves ~5,100 cycles, more than a build costs, so this is
 * profitable even if every single call has to rebuild. That is what removes
 * the need for any cache policy: there is no hit rate below which this
 * turns into a loss, so slots can be handed out first-come and never
 * reclaimed.
 *
 * Measured with TILE_LUT_STATS: ICON.ICN holds 166 palettes, but a real
 * playthrough touched only 10 distinct ones (plus 4 house-recoloured, 1.5%
 * of calls). Slots are therefore assigned lazily via a 256-entry index map
 * rather than reserving all 166 (which would cost 83 KB to hold 10 live
 * tables). A palette is built at most once, so lookups are a single array
 * read and a compare - no LRU, no stamps, no eviction, no key space.
 *
 * Overflow past TILE_LUT_SLOTS falls back to a scratch slot rebuilt per
 * call. That is still a net win, so exceeding the slot count degrades
 * gracefully instead of failing. */
/*#define TILE_LUT_STATS*/

/* 10 palettes observed in use; 16 gives headroom at 512 bytes each = 8 KB. */
#define TILE_LUT_SLOTS 16
#define TILE_LUT_SCRATCH TILE_LUT_SLOTS	/* rebuilt per call on overflow */
#define TILE_LUT_UNBUILT 0xFF

typedef struct {
	union {			/* union gives the 4-byte alignment the fill needs */
		uint8  b[256];
		uint32 l[64];
	} hi, lo;
} TileLut;

static TileLut s_tileLut[TILE_LUT_SLOTS + 1];
/* Palette index -> slot, or TILE_LUT_UNBUILT. Identifies a slot's contents
 * outright, so the slots themselves need no key and no comparison. */
static uint8  s_tileLutSlotOf[256];
static uint8  s_tileLutNextSlot = 0;
static bool   s_tileLutInit = false;

/**
 * Expand a 16-colour palette into the two nibble lookup tables.
 */
static void GFX_BuildTileLut(TileLut *lut, const uint8 *palette)
{
	union { uint8 b[4]; uint32 l; } q;
	uint32 *hi, *lo;
	uint32 a, b, c, d;
	int i;

	/* lo[] is the palette repeated 16 times. The palette is either
	 * g_iconRPAL + (index << 4), which inherits calloc's alignment, or a
	 * 16-byte local, so it may be misaligned; assembling through a byte
	 * union keeps this both alignment-safe and endian-neutral. */
	q.b[0] = palette[0];  q.b[1] = palette[1];  q.b[2] = palette[2];  q.b[3] = palette[3];  a = q.l;
	q.b[0] = palette[4];  q.b[1] = palette[5];  q.b[2] = palette[6];  q.b[3] = palette[7];  b = q.l;
	q.b[0] = palette[8];  q.b[1] = palette[9];  q.b[2] = palette[10]; q.b[3] = palette[11]; c = q.l;
	q.b[0] = palette[12]; q.b[1] = palette[13]; q.b[2] = palette[14]; q.b[3] = palette[15]; d = q.l;

	lo = lut->lo.l;
	for (i = 0; i < 16; i++) {
		*lo++ = a; *lo++ = b; *lo++ = c; *lo++ = d;
	}

	/* hi[] holds each palette byte replicated over 16 consecutive entries. */
	hi = lut->hi.l;
	for (i = 0; i < 16; i++) {
		uint32 v = palette[i];

		v |= v << 8;
		v |= v << 16;
		*hi++ = v; *hi++ = v; *hi++ = v; *hi++ = v;
	}
}

/**
 * Fetch the nibble tables for a palette held in g_iconRPAL, building on
 * first use.
 *
 * @param palette The 16-entry palette.
 * @param index Its index within g_iconRPAL; identifies it exactly.
 */
static TileLut *GFX_GetTileLut(const uint8 *palette, uint8 index)
{
	uint8 slot = s_tileLutSlotOf[index];

	if (slot != TILE_LUT_UNBUILT) return &s_tileLut[slot];

	if (s_tileLutNextSlot < TILE_LUT_SLOTS) {
		slot = s_tileLutNextSlot++;
		s_tileLutSlotOf[index] = slot;
	} else {
		slot = TILE_LUT_SCRATCH;	/* out of slots: rebuild every call */
	}

	GFX_BuildTileLut(&s_tileLut[slot], palette);
	return &s_tileLut[slot];
}

/**
 * Invalidate the tile lookup tables.
 * Must be called whenever the icon palette data itself may have changed,
 * since a slot is identified only by its index into g_iconRPAL.
 */
void GFX_InvalidateTileLut(void)
{
	memset(s_tileLutSlotOf, TILE_LUT_UNBUILT, sizeof(s_tileLutSlotOf));
	s_tileLutNextSlot = 0;
	s_tileLutInit = true;
}

/* SCREEN_0 = 320x200 = 64000 = 0xFA00   The main screen buffer, 0xA0000 Video RAM in DOS Dune 2
 * SCREEN_1 = 64506 = 0xFBFA
 * SCREEN_2 = 320x200 = 64000 = 0xFA00
 * SCREEN_3 = 64781 = 0xFD0D    * NEVER ACTIVE * only used for game credits and intro */
#define GFX_SCREEN_BUFFER_COUNT 4
static const uint16 s_screenBufferSize[GFX_SCREEN_BUFFER_COUNT] = { 0xFA00, 0xFBF4, 0xFA00, 0xFD0D/*, 0xA044*/ };
static void *s_screenBuffer[GFX_SCREEN_BUFFER_COUNT] = { NULL, NULL, NULL, NULL };
#ifdef GFX_STORE_DIRTY_AREA
static bool s_screen0_is_dirty = false;
static struct dirty_area s_screen0_dirty_area = { 0, 0, 0, 0 };
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
uint32 g_dirty_blocks[200];
#endif
#endif

/* The active screen. Exposed (rather than static) so that the
 * GFX_Screen_SetDirty() macro in gfx.h can test the target screen inline
 * and discard the call entirely for non-visible screens. s_screenActiveID
 * remains as an alias so the rest of this file is unchanged. */
Screen g_screenActiveID = SCREEN_0;
#define s_screenActiveID g_screenActiveID

#if 0
/**
 * Get the codesegment of the active screen buffer.
 * @return The codesegment of the screen buffer.
 */
void *GFX_Screen_GetActive(void)
{
	return GFX_Screen_Get_ByIndex(s_screenActiveID);
}
#endif

/**
 * Returns the size of a screenbuffer.
 * @param screenID The screenID to get the size of.
 * @return Some size value.
 */
uint16 GFX_Screen_GetSize_ByIndex(Screen screenID)
{
	if (screenID == SCREEN_ACTIVE)
		screenID = s_screenActiveID;
	assert(screenID >= 0 && screenID < GFX_SCREEN_BUFFER_COUNT);
	return s_screenBufferSize[screenID];
}

/**
 * Get the pointer to a screenbuffer.
 * @param screenID The screenbuffer to get.
 * @return A pointer to the screenbuffer.
 */
void *GFX_Screen_Get_ByIndex(Screen screenID)
{
	if (screenID == SCREEN_ACTIVE)
		screenID = s_screenActiveID;
	assert(screenID >= 0 && screenID < GFX_SCREEN_BUFFER_COUNT);
	return s_screenBuffer[screenID];
}

/**
 * Change the current active screen to the new value.
 * @param screenID The new screen to get active.
 * @return Old screenID that was currently active.
 */
Screen GFX_Screen_SetActive(Screen screenID)
{
	Screen oldScreen = s_screenActiveID;
	if (screenID != SCREEN_ACTIVE) {
		s_screenActiveID = screenID;
	}
	return oldScreen;
}

/**
* Checks if the screen is active.
* @param screenID The screen to check for being active
* @return true or false.
*/
bool GFX_Screen_IsActive(Screen screenID)
{
	if (screenID == SCREEN_ACTIVE) return true;
	return (screenID == s_screenActiveID);
}

#ifdef GFX_STORE_DIRTY_AREA
#ifdef GFX_DIRTY_SOURCE_STATS
static int s_dirtySource = DIRTY_SRC_OTHER;
static uint32 s_dirtyPx[DIRTY_SRC_COUNT];	/* pixels marked dirty, per producer */
static uint32 s_dirtyAlignedPx[DIRTY_SRC_COUNT];/* of those, in fully 16px-aligned boxes */
static uint32 s_dirtyCalls[DIRTY_SRC_COUNT];
/* Blocks newly set by this producer, i.e. excluding blocks another producer
 * already dirtied. This is the marginal cost each producer imposes on c2p. */
static uint32 s_dirtyNewBlocks[DIRTY_SRC_COUNT];
static uint32 s_dirtyReports = 0;

static const char * const s_dirtySourceName[DIRTY_SRC_COUNT] = {
	"viewport", "screencopy", "sprite", "mouserestore",
	"wsa", "text", "rect", "fullscreen", "other"
};

void GFX_Screen_SetDirtySource(int source)
{
	s_dirtySource = source;
}

void GFX_DirtyStats_Report(void)
{
	int i;
	uint32 totPx = 0, totNew = 0;

	for (i = 0; i < DIRTY_SRC_COUNT; i++) {
		totPx += s_dirtyPx[i];
		totNew += s_dirtyNewBlocks[i];
	}
	if (totPx == 0) return;

	Warning("dirty sources (report %lu):\n", (unsigned long)++s_dirtyReports);
	for (i = 0; i < DIRTY_SRC_COUNT; i++) {
		if (s_dirtyPx[i] == 0) continue;
		Warning("  %-12s %6lu calls, %8lu px (%2lu%%), aligned %2lu%%, new blocks %lu px\n",
		        s_dirtySourceName[i],
		        (unsigned long)s_dirtyCalls[i],
		        (unsigned long)s_dirtyPx[i],
		        (unsigned long)(s_dirtyPx[i] * 100 / totPx),
		        (unsigned long)(s_dirtyAlignedPx[i] * 100 / s_dirtyPx[i]),
		        (unsigned long)(s_dirtyNewBlocks[i] << 4));
	}
	Warning("  TOTAL marked %lu px, c2p-relevant new blocks %lu px\n",
	        (unsigned long)totPx, (unsigned long)(totNew << 4));

	memset(s_dirtyPx, 0, sizeof(s_dirtyPx));
	memset(s_dirtyAlignedPx, 0, sizeof(s_dirtyAlignedPx));
	memset(s_dirtyCalls, 0, sizeof(s_dirtyCalls));
	memset(s_dirtyNewBlocks, 0, sizeof(s_dirtyNewBlocks));
}
#endif /* GFX_DIRTY_SOURCE_STATS */

void GFX_Screen_SetDirty_(uint16 left, uint16 top, uint16 right, uint16 bottom)
{
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
	uint32 mask;
	uint16 y;
#endif
	/* The SCREEN_ACTIVE resolution and the SCREEN_0 test are done by the
	 * GFX_Screen_SetDirty() macro in gfx.h, so callers that target another
	 * screen never reach here and the screen ID need not be passed. */
	s_screen0_is_dirty = true;
	if (left < s_screen0_dirty_area.left) s_screen0_dirty_area.left = left;
	if (top < s_screen0_dirty_area.top) s_screen0_dirty_area.top = top;
	if (right > s_screen0_dirty_area.right) s_screen0_dirty_area.right = right;
	if (bottom > s_screen0_dirty_area.bottom) s_screen0_dirty_area.bottom = bottom;
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
	mask = (1 << ((right + 15) >> 4)) - 1;
	mask -= (1 << (left >> 4)) - 1;
#ifdef GFX_DIRTY_SOURCE_STATS
	{
		int src = s_dirtySource;
		uint32 px = (uint32)(right - left) * (bottom - top);

		s_dirtyCalls[src]++;
		s_dirtyPx[src] += px;
		/* A box is c2p-friendly only if both edges land on 16px block
		 * boundaries: then the block mask covers exactly the box and a
		 * planar-direct blit would need no read-modify-write. */
		if ((left & 15) == 0 && (right & 15) == 0) s_dirtyAlignedPx[src] += px;
		for (y = top; y < bottom; y++) {
			s_dirtyNewBlocks[src] += __builtin_popcount(mask & ~g_dirty_blocks[y]);
		}
	}
#endif
	for (y = top; y < bottom; y++) g_dirty_blocks[y] |= mask;
#endif
}

void GFX_Screen_SetClean(Screen screenID)
{
	if(screenID == SCREEN_ACTIVE) screenID = s_screenActiveID;
	if(screenID != SCREEN_0) return;
	s_screen0_is_dirty = false;
	s_screen0_dirty_area.left = 0xffff;
	s_screen0_dirty_area.top = 0xffff;
	s_screen0_dirty_area.right = 0;
	s_screen0_dirty_area.bottom = 0;
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
	memset(g_dirty_blocks, 0, sizeof(g_dirty_blocks));
#endif
}

bool GFX_Screen_IsDirty(Screen screenID)
{
	if(screenID == SCREEN_ACTIVE) screenID = s_screenActiveID;
	if(screenID != SCREEN_0) return true;
	return s_screen0_is_dirty;
}

struct dirty_area * GFX_Screen_GetDirtyArea(Screen screenID)
{
	if(screenID == SCREEN_ACTIVE) screenID = s_screenActiveID;
	if(screenID != SCREEN_0) return NULL;
	return &s_screen0_dirty_area;
}

#endif /* GFX_STORE_DIRTY_AREA */

/**
 * Initialize the GFX system.
 */
void GFX_Init(void)
{
	uint8 *screenBuffers;
	uint32 totalSize = 0;
	int i;

	/* init g_paletteActive with invalid values so first GFX_SetPalette() will be ok */
	memset(g_paletteActive, 0xff, 3*256);

	for (i = 1; i < GFX_SCREEN_BUFFER_COUNT; i++) {
		totalSize += GFX_Screen_GetSize_ByIndex(i);
	}

	screenBuffers = calloc(1, totalSize);

	for (i = 1; i < GFX_SCREEN_BUFFER_COUNT; i++) {
		s_screenBuffer[i] = screenBuffers;

		screenBuffers += GFX_Screen_GetSize_ByIndex(i);
	}

	/* special case for SCREEN_0 which is the MCGA frame buffer */
	s_screenBuffer[0] = Video_GetFrameBuffer(GFX_Screen_GetSize_ByIndex(0));

	s_screenActiveID = SCREEN_0;
}

/**
 * Uninitialize the GFX system.
 */
void GFX_Uninit(void)
{
	int i;

	free(s_screenBuffer[1]);

	for (i = 0; i < GFX_SCREEN_BUFFER_COUNT; i++) {
		s_screenBuffer[i] = NULL;
	}
}

/**
 * Draw a tile on the screen.
 * @param tileID The tile to draw.
 * @param x The x-coordinate to draw the sprite.
 * @param y The y-coordinate to draw the sprite.
 * @param houseID The house the sprite belongs (for recolouring).
 */
void GFX_DrawTile(uint16 tileID, uint16 x, uint16 y, uint8 houseID)
{
	int i, j;
	uint8 *icon_palette;
	uint8 *wptr;
	uint8 *rptr;
	uint8 local_palette[16];
	TileLut *lut;
	const uint8 *lutHi;
	const uint8 *lutLo;
	uint8 paletteIndex;

	assert(houseID < HOUSE_MAX);

	if (s_tileMode == 4) return;

	if (!s_tileLutInit) GFX_InvalidateTileLut();

	/* ENHANCEMENT -- Pre-decoded fast path, taken before any palette or LUT
	 * work: those exist only to expand nibbles, which is already done. */
	if (s_tilesDecoded != NULL && houseID == 0 && tileID < s_tileCount) {
		const uint8 *dr = s_tilesDecoded + ((uint32)tileID * s_tileByteSize * 2);
		const uint16 rowBytes = s_tileWidth * 2;

		wptr = GFX_Screen_GetActive();
		wptr += y * SCREEN_WIDTH + x;

		if (!s_tileHasTransparency[tileID]) {
			/* Longword copy needs both pointers long-aligned. The map draws
			 * come from viewport.c with left = x << 4 and SCREEN_WIDTH 320,
			 * so they always are; widget.c passes an arbitrary left, hence
			 * the runtime test and the byte fallback. */
			if ((((size_t)wptr | (size_t)dr | rowBytes) & 3) == 0) {
				/* 16x16 is the only geometry ICON.ICN actually uses, so the
				 * 16-byte row is straight-lined; the generic loop stays for
				 * the other sizes GFX_Init_TilesInfo can produce. */
				if (rowBytes == 16) {
					for (j = 0; j < s_tileHeight; j++) {
						const uint32 *r32 = (const uint32 *)dr;
						uint32 *w32 = (uint32 *)wptr;

						w32[0] = r32[0];
						w32[1] = r32[1];
						w32[2] = r32[2];
						w32[3] = r32[3];
						dr += 16;
						wptr += SCREEN_WIDTH;
					}
				} else {
					uint16 longs = rowBytes >> 2;

					for (j = 0; j < s_tileHeight; j++) {
						uint32 *w32 = (uint32 *)wptr;
						const uint32 *r32 = (const uint32 *)dr;

						for (i = 0; i < longs; i++) *w32++ = *r32++;
						dr += rowBytes;
						wptr += SCREEN_WIDTH;
					}
				}
			} else {
				for (j = 0; j < s_tileHeight; j++) {
					memcpy(wptr, dr, rowBytes);
					dr += rowBytes;
					wptr += SCREEN_WIDTH;
				}
			}
		} else {
			/* An end-pointer walk keeps both operands in post-increment
			 * form. Indexing by a counter instead made GCC emit
			 * MOVE.B (A2,D0.L) at 16 cycles where (A2)+ costs 8. */
			for (j = 0; j < s_tileHeight; j++) {
				uint8 *w = wptr;
				const uint8 *r = dr;
				const uint8 *rEnd = dr + rowBytes;

				do {
					uint8 c = *r++;

					if (c != 0) *w = c;
					w++;
				} while (r != rEnd);
				dr = rEnd;
				wptr += SCREEN_WIDTH;
			}
		}
		return;
	}

	paletteIndex = g_iconRTBL[tileID];
	icon_palette = g_iconRPAL + (paletteIndex << 4);

	if (houseID != 0) {
		/* Remap colors for the right house */
		for (i = 0; i < 16; i++) {
			uint8 colour = icon_palette[i];

			/* ENHANCEMENT -- Dune2 recolours too many colours, causing clear graphical glitches in the IX building */
			if ((colour & 0xF0) == 0x90) {
				if (colour <= 0x96 || !g_dune2_enhanced) colour += houseID << 4;
			}
			local_palette[i] = colour;
		}
		icon_palette = local_palette;
	}

	/* The recoloured palette is synthesised per call and is not in
	 * g_iconRPAL, so it cannot be identified by index. It is only 1.5% of
	 * calls and a build costs less than a call saves, so it simply uses
	 * the scratch slot rather than needing a key space of its own. */
	if (houseID != 0) {
		lut = &s_tileLut[TILE_LUT_SCRATCH];
		GFX_BuildTileLut(lut, icon_palette);
	} else {
		lut = GFX_GetTileLut(icon_palette, paletteIndex);
	}
	/* Hold the two tables in locals: reaching through the struct makes GCC
	 * derive the second base with an extra LEA inside the inner loop. */
	lutHi = lut->hi.b;
	lutLo = lut->lo.b;

	wptr = GFX_Screen_GetActive();
	wptr += y * SCREEN_WIDTH + x;
	rptr = g_tilesPixels + (tileID * s_tileByteSize);

	/* tiles with transparent pixels : [1 : 33] U [108 : 122] and 124
	 * palettes 1 to 18 and 22 and 24 */
	/*if (tileID <= 33 || (tileID >= 108 && tileID <= 124)) {*/
	/* We've found that all "transparent" icons/tiles have 0 (transparent) as color 0 */
	/* The inner loops below load the source byte once into an 'unsigned'
	 * local and keep the loop counter in a register. Indexing the palette
	 * with a plain uint8 expression makes GCC widen to a longword and then
	 * re-mask with AND.L #$000000FF on every lookup (24% of this function
	 * on 68000); sourcing both nibbles from one already-widened value
	 * avoids that, and also avoids reloading s_tileWidth each iteration. */
	if (icon_palette[0] == 0) {

		for (j = 0; j < s_tileHeight; j++) {
			uint8 *w = wptr;
			uint8 *r = rptr;

			for (i = 0; i < s_tileWidth; i++) {
				unsigned b = *r++;
				uint8 left  = lutHi[b];
				uint8 right = lutLo[b];

				if (left != 0) *w = left;
				w++;
				if (right != 0) *w = right;
				w++;
			}
			rptr = r;
			wptr = w + s_tileSpacing;
		}
	} else {

		for (j = 0; j < s_tileHeight; j++) {
			uint8 *w = wptr;
			uint8 *r = rptr;

			for (i = 0; i < s_tileWidth; i++) {
				unsigned b = *r++;
				*w++ = lutHi[b];
				*w++ = lutLo[b];
			}
			rptr = r;
			wptr = w + s_tileSpacing;
		}
	}
}

/**
 * Discard the pre-decoded tile cache.
 */
void GFX_FreeDecodedTiles(void)
{
	free(s_tilesDecoded);
	s_tilesDecoded = NULL;
	free(s_tileHasTransparency);
	s_tileHasTransparency = NULL;
	s_tileCount = 0;
}

/**
 * Pre-decode every tile from 2-pixels-per-byte to one byte per pixel,
 * applying each tile's palette. Must be called after g_tilesPixels,
 * g_iconRTBL and g_iconRPAL are all loaded, and after GFX_Init_TilesInfo.
 *
 * Failure is not fatal: GFX_DrawTile falls back to decoding per draw.
 *
 * @param tilesDataLength Size of the decoded SSET chunk, in bytes.
 */
void GFX_Init_DecodedTiles(uint32 tilesDataLength)
{
	uint32 decodedSize;
	uint16 tileID;

	GFX_FreeDecodedTiles();

	if (s_tileMode == 4 || s_tileByteSize == 0) return;
	if (g_tilesPixels == NULL || g_iconRTBL == NULL || g_iconRPAL == NULL) return;

	s_tileCount = (uint16)(tilesDataLength / s_tileByteSize);
	if (s_tileCount == 0) return;

	decodedSize = (uint32)s_tileCount * s_tileByteSize * 2;
	s_tilesDecoded = malloc(decodedSize);
	s_tileHasTransparency = malloc(s_tileCount);
	if (s_tilesDecoded == NULL || s_tileHasTransparency == NULL) {
		Warning("Tile pre-decode disabled: out of memory (%lu bytes)\n",
		        (unsigned long)decodedSize);
		GFX_FreeDecodedTiles();
		return;
	}

	for (tileID = 0; tileID < s_tileCount; tileID++) {
		const uint8 *palette = g_iconRPAL + (g_iconRTBL[tileID] << 4);
		const uint8 *r = g_tilesPixels + ((uint32)tileID * s_tileByteSize);
		uint8 *w = s_tilesDecoded + ((uint32)tileID * s_tileByteSize * 2);
		uint16 i;

		/* A tile is transparent when colour 0 of its palette is 0; that is
		 * the same test GFX_DrawTile applies, kept per tile so the draw
		 * does not have to reach into the palette at all. */
		s_tileHasTransparency[tileID] = (palette[0] == 0) ? 1 : 0;

		for (i = 0; i < s_tileByteSize; i++) {
			unsigned b = *r++;
			*w++ = palette[b >> 4];
			*w++ = palette[b & 0x0F];
		}
	}
}

#ifdef GFX_TILE_SIZE_STATS
/**
 * Report the tile geometry and what pre-decoding tiles to byte-per-pixel
 * would cost in RAM. See ATARI_TODO_TILE_PREDECODE.md: the tile count is the
 * gate on that idea and can only be measured on the target, since the data
 * lives in the game's PAK files.
 *
 * @param tilesDataLength Size of the decoded SSET chunk, in bytes.
 */
void GFX_Report_TilesInfo(uint32 tilesDataLength)
{
	uint32 tileCount;
	uint32 decodedLength;

	if (s_tileByteSize == 0) {
		Error("TILESTATS: s_tileByteSize is 0, cannot report\n");
		return;
	}

	/* s_tileByteSize is the packed size: 2 pixels per byte. */
	tileCount = tilesDataLength / s_tileByteSize;
	decodedLength = tileCount * (uint32)s_tileByteSize * 2;

	Error("TILESTATS: mode=%u %ux%u bytes (%ux%u px) byteSize=%u spacing=%u\n",
	      (unsigned)s_tileMode, (unsigned)s_tileWidth, (unsigned)s_tileHeight,
	      (unsigned)(s_tileWidth * 2), (unsigned)s_tileHeight,
	      (unsigned)s_tileByteSize, (unsigned)s_tileSpacing);
	Error("TILESTATS: SSET=%lu bytes, tiles=%lu, remainder=%lu\n",
	      (unsigned long)tilesDataLength, (unsigned long)tileCount,
	      (unsigned long)(tilesDataLength % s_tileByteSize));
	Error("TILESTATS: decoded would be %lu bytes, extra %lu bytes (%lu KB)\n",
	      (unsigned long)decodedLength,
	      (unsigned long)(decodedLength - tilesDataLength),
	      (unsigned long)((decodedLength - tilesDataLength + 1023) / 1024));
}
#endif /* GFX_TILE_SIZE_STATS */

/**
 * Initialize sprite information.
 *
 * @param widthSize Value between 0 and 2, indicating the width of the sprite. x8 to get actuel width of sprite
 * @param heightSize Value between 0 and 2, indicating the width of the sprite. x8 to get actuel width of sprite
 */
void GFX_Init_TilesInfo(uint16 widthSize, uint16 heightSize)
{
	/* NOTE : shouldn't it be (heightSize < 3 && widthSize < 3) ??? */
	if (widthSize == heightSize && widthSize < 3) {
		s_tileMode = widthSize & 2;

		s_tileWidth   = widthSize << 2;
		s_tileHeight  = heightSize << 3;
		s_tileSpacing = SCREEN_WIDTH - s_tileHeight;
		s_tileByteSize = s_tileWidth * s_tileHeight;
	} else {
		/* NOTE : is it dead code ? */
		/* default to 8x8 sprites */
		s_tileMode = 4;
		s_tileByteSize = 8*4;

		s_tileWidth   = 4;
		s_tileHeight  = 8;
		s_tileSpacing = 312;
	}
}

/**
 * Put a pixel on the screen.
 * @param x The X-coordinate on the screen.
 * @param y The Y-coordinate on the screen.
 * @param colour The colour of the pixel to put on the screen.
 */
void GFX_PutPixel(uint16 x, uint16 y, uint8 colour)
{
	if (y >= SCREEN_HEIGHT) return;
	if (x >= SCREEN_WIDTH) return;

	*((uint8 *)GFX_Screen_GetActive() + y * SCREEN_WIDTH + x) = colour;
}

/**
 * Copy information from one screenbuffer to the other.
 * @param xSrc The X-coordinate on the source.
 * @param ySrc The Y-coordinate on the source.
 * @param xDst The X-coordinate on the destination.
 * @param yDst The Y-coordinate on the destination.
 * @param width The width.
 * @param height The height.
 * @param screenSrc The ID of the source screen.
 * @param screenDst The ID of the destination screen.
 * @param skipNull Wether to skip pixel colour 0.
 */
void GFX_Screen_Copy2(int16 xSrc, int16 ySrc, int16 xDst, int16 yDst, int16 width, int16 height, Screen screenSrc, Screen screenDst, bool skipNull)
{
	uint8 *src;
	uint8 *dst;

	if (xSrc >= SCREEN_WIDTH) return;
	if (xSrc < 0) {
		xDst += xSrc;
		width += xSrc;
		xSrc = 0;
	}

	if (ySrc >= SCREEN_HEIGHT) return;
	if (ySrc < 0) {
		yDst += ySrc;
		height += ySrc;
		ySrc = 0;
	}

	if (xDst >= SCREEN_WIDTH) return;
	if (xDst < 0) {
		xSrc += xDst;
		width += xDst;
		xDst = 0;
	}

	if (yDst >= SCREEN_HEIGHT) return;
	if (yDst < 0) {
		ySrc += yDst;
		height += yDst;
		yDst = 0;
	}

	if (SCREEN_WIDTH - xSrc - width < 0) width = SCREEN_WIDTH - xSrc;
	if (SCREEN_HEIGHT - ySrc - height < 0) height = SCREEN_HEIGHT - ySrc;
	if (SCREEN_WIDTH - xDst - width < 0) width = SCREEN_WIDTH - xDst;
	if (SCREEN_HEIGHT - yDst - height < 0) height = SCREEN_HEIGHT - yDst;

	if (xSrc < 0 || xSrc >= SCREEN_WIDTH) return;
	if (xDst < 0 || xDst >= SCREEN_WIDTH) return;
	if (ySrc < 0 || ySrc >= SCREEN_HEIGHT) return;
	if (yDst < 0 || yDst >= SCREEN_HEIGHT) return;
	if (width < 0 || width >= SCREEN_WIDTH) return;
	if (height < 0 || height >= SCREEN_HEIGHT) return;

	GFX_Screen_SetDirty(screenDst, xDst, yDst, xDst + width, yDst + height);

	src = GFX_Screen_Get_ByIndex(screenSrc);
	dst = GFX_Screen_Get_ByIndex(screenDst);

	src += xSrc + ySrc * SCREEN_WIDTH;
	dst += xDst + yDst * SCREEN_WIDTH;

	while (height-- != 0) {
		if (skipNull) {
			uint16 i;
			for (i = 0; i < width; i++) {
				if (src[i] != 0) dst[i] = src[i];
			}
		} else {
			memmove(dst, src, width);
		}
		dst += SCREEN_WIDTH;
		src += SCREEN_WIDTH;
	}
}

/**
 * Copy information from one screenbuffer to the other.
 * @param xSrc The X-coordinate on the source.
 * @param ySrc The Y-coordinate on the source.
 * @param xDst The X-coordinate on the destination.
 * @param yDst The Y-coordinate on the destination.
 * @param width The width.
 * @param height The height.
 * @param screenSrc The ID of the source screen.
 * @param screenDst The ID of the destination screen.
 */
/**
 * Copy \a height rows of \a width bytes between two screen buffers.
 *
 * This replaces a per-row memmove(). The rows are short (the viewport bands
 * average ~52 bytes), so the generic memmove() spent ~264 cycles per call on
 * argument passing, register saves, an overlap test and alignment probing -
 * about as much as the copy itself. Screen rows are always disjoint and
 * SCREEN_WIDTH is a multiple of 4, so when both pointers start long-aligned
 * every subsequent row stays long-aligned and a plain long-word loop is safe.
 * Anything that does not meet that precondition falls back to memmove().
 */
#ifdef __m68k__
/* Hand-written unrolled DBRA copier: GCC emits a 4-instruction loop that
 * spends half its cycles on loop control, so the C version below runs at
 * 10.0 cyc/byte versus 5.3 for this one. See src/video/atari_copyrows.s. */
extern void GFX_CopyRows_asm(void *dst, const void *src, int32 width, int32 height, int32 stride);
#endif

static void GFX_CopyRows(uint8 *dst, uint8 *src, uint16 width, int16 height)
{
	/* 68000 faults on word/long access to an odd address, so only take the
	 * fast path when both pointers share long alignment. size_t is wide
	 * enough to hold a pointer on every target OpenDUNE builds for. */
	if ((((size_t)dst | (size_t)src) & 3) != 0) {
		while (height-- != 0) {
			memmove(dst, src, width);
			dst += SCREEN_WIDTH;
			src += SCREEN_WIDTH;
		}
		return;
	}

#ifdef __m68k__
	GFX_CopyRows_asm(dst, src, (int32)width, (int32)height, SCREEN_WIDTH);
#else
	while (height-- != 0) {
		uint32 *d = (uint32 *)dst;
		const uint32 *s = (const uint32 *)src;
		uint16 n = width >> 2;
		uint16 rest = width & 3;

		while (n-- != 0) *d++ = *s++;

		if (rest != 0) {
			uint8 *db = (uint8 *)d;
			const uint8 *sb = (const uint8 *)s;

			while (rest-- != 0) *db++ = *sb++;
		}

		dst += SCREEN_WIDTH;
		src += SCREEN_WIDTH;
	}
#endif
}

void GFX_Screen_Copy(int16 xSrc, int16 ySrc, int16 xDst, int16 yDst, int16 width, int16 height, Screen screenSrc, Screen screenDst)
{
	uint8 *src;
	uint8 *dst;

	if (xSrc >= SCREEN_WIDTH) return;
	if (xSrc < 0) xSrc = 0;

	if (ySrc >= SCREEN_HEIGHT) return;
	if (ySrc < 0) ySrc = 0;

	if (xDst >= SCREEN_WIDTH) return;
	if (xDst < 0) xDst = 0;

	if ((yDst + height) > SCREEN_HEIGHT) {
		height = SCREEN_HEIGHT - 1 - yDst;
	}
	if (height <= 0) return;

	if (yDst >= SCREEN_HEIGHT) return;
	if (yDst < 0) yDst = 0;

	if (width <= 0 || width > SCREEN_WIDTH) return;

	src = GFX_Screen_Get_ByIndex(screenSrc);
	dst = GFX_Screen_Get_ByIndex(screenDst);

	src += xSrc + ySrc * SCREEN_WIDTH;
	dst += xDst + yDst * SCREEN_WIDTH;

	GFX_Screen_SetDirty(screenDst, xDst, yDst, xDst + width, yDst + height);

	if (width == SCREEN_WIDTH) {
		memmove(dst, src, height * SCREEN_WIDTH);
	} else {
		GFX_CopyRows(dst, src, (uint16)width, height);
	}
}

/**
 * Clears the screen.
 */
void GFX_ClearScreen(Screen screenID)
{
	memset(GFX_Screen_Get_ByIndex(screenID), 0, SCREEN_WIDTH * SCREEN_HEIGHT);
	GFX_Screen_SetDirtySource(DIRTY_SRC_FULL);
	GFX_Screen_SetDirty(screenID, 0, 0, SCREEN_WIDTH, SCREEN_HEIGHT);
}

/**
 * Clears the given memory block.
 * @param index The memory block.
 */
void GFX_ClearBlock(Screen index)
{
	memset(GFX_Screen_Get_ByIndex(index), 0, GFX_Screen_GetSize_ByIndex(index));
	GFX_Screen_SetDirtySource(DIRTY_SRC_FULL);
	GFX_Screen_SetDirty(index, 0, 0, SCREEN_WIDTH, SCREEN_HEIGHT);
}

/**
 * Set a new palette for the screen.
 * @param palette The palette in RGB order.
 */
void GFX_SetPalette(uint8 *palette)
{
	int from, to;

	for (from = 0; from < 256; from++) {
		if(palette[from*3] != g_paletteActive[from*3] ||
		   palette[from*3+1] != g_paletteActive[from*3+1] ||
		   palette[from*3+2] != g_paletteActive[from*3+2]) break;
	}
	if (from >= 256) {
		Warning("Useless GFX_SetPalette() call\n");
		return;
	}
	for (to = 255; to > from; to--) {
		if(palette[to*3] != g_paletteActive[to*3] ||
		   palette[to*3+1] != g_paletteActive[to*3+1] ||
		   palette[to*3+2] != g_paletteActive[to*3+2]) break;
	}
	Video_SetPalette(palette + 3 * from, from, to - from + 1);

	memcpy(g_paletteActive + 3 * from, palette + 3 * from, (to - from + 1) * 3);
}

/**
 * Get a pixel on the screen.
 * @param x The X-coordinate on the screen.
 * @param y The Y-coordinate on the screen.
 * @return The colour of the pixel.
 */
uint8 GFX_GetPixel(uint16 x, uint16 y)
{
	if (y >= SCREEN_HEIGHT) return 0;
	if (x >= SCREEN_WIDTH) return 0;

	return *((uint8 *)GFX_Screen_GetActive() + y * SCREEN_WIDTH + x);
}

uint16 GFX_GetSize(int16 width, int16 height)
{
	if (width < 1) width = 1;
	if (width > SCREEN_WIDTH) width = SCREEN_WIDTH;
	if (height < 1) height = 1;
	if (height > SCREEN_HEIGHT) height = SCREEN_HEIGHT;

	return width * height;
}

/**
 * Copy information from a buffer to the screen.
 * @param x The X-coordinate on the screen.
 * @param y The Y-coordinate on the screen.
 * @param width The width.
 * @param height The height.
 * @param buffer The buffer to copy from.
 */
void GFX_CopyFromBuffer(int16 left, int16 top, uint16 width, uint16 height, uint8 *buffer)
{
	uint8 *screen;

	if (width == 0) return;
	if (height == 0) return;

	if (left < 0) left = 0;
	if (left >= SCREEN_WIDTH) left = SCREEN_WIDTH - 1;

	if (top < 0) top = 0;
	if (top >= SCREEN_HEIGHT) top = SCREEN_HEIGHT - 1;

	if (width  > SCREEN_WIDTH - left) width  = SCREEN_WIDTH - left;
	if (height > SCREEN_HEIGHT - top) height = SCREEN_HEIGHT - top;

	screen = GFX_Screen_Get_ByIndex(SCREEN_0);
	screen += top * SCREEN_WIDTH + left;

	GFX_Screen_SetDirtySource(DIRTY_SRC_MOUSERESTORE);
	GFX_Screen_SetDirty(SCREEN_0, left, top, left + width, top + height);

	while (height-- != 0) {
		memcpy(screen, buffer, width);
		screen += SCREEN_WIDTH;
		buffer += width;
	}
}

/**
 * Copy information from the screen to a buffer.
 * @param x The X-coordinate on the screen.
 * @param y The Y-coordinate on the screen.
 * @param width The width.
 * @param height The height.
 * @param buffer The buffer to copy to.
 */
void GFX_CopyToBuffer(int16 left, int16 top, uint16 width, uint16 height, uint8 *buffer)
{
	uint8 *screen;

	if (width == 0) return;
	if (height == 0) return;

	if (left < 0) left = 0;
	if (left >= SCREEN_WIDTH) left = SCREEN_WIDTH - 1;

	if (top < 0) top = 0;
	if (top >= SCREEN_HEIGHT) top = SCREEN_HEIGHT - 1;

	if (width  > SCREEN_WIDTH - left) width  = SCREEN_WIDTH - left;
	if (height > SCREEN_HEIGHT - top) height = SCREEN_HEIGHT - top;

	screen = GFX_Screen_Get_ByIndex(SCREEN_0);
	screen += top * SCREEN_WIDTH + left;

	while (height-- != 0) {
		memcpy(buffer, screen, width);
		screen += SCREEN_WIDTH;
		buffer += width;
	}
}
