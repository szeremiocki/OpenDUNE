/* ATARI Falcon / TT Video Driver */

#include <string.h>
#include <stdlib.h>
#include <assert.h>

#include <mint/sysbind.h>
#include <mint/osbind.h>
#include <mint/ostruct.h>
#include <mint/falcon.h>
#include <mint/cookie.h>

#include "types.h"
#include "video.h"
#include "atari_mono.h"
#include "atari_planar.h"
#include "atari_mono_palette.h"
#include "../config.h"
#include "../gfx.h"
#include "../gui/gui.h"
#include "../input/input.h"
#include "../input/mouse.h"
#include "../inifile.h"
#include "../opendune.h"
#include "../os/endian.h"
#include "../os/atari.h"
#include "../os/error.h"
#include "../os/math.h"
#include "../os/sleep.h"
#include "../sprites.h"
#include "../timer.h"

/* ATARI IKBD doc : https://www.kernel.org/doc/Documentation/input/atarikbd.txt
 * see  */
extern void install_ikbd_handler(void);
extern void uninstall_ikbd_handler(void);

/* chunky to planar routine : */
extern void c2p1x1_8_falcon(void * planar, void * chunky, uint32 count);
extern void c2p1x1_8_tt(void * planar, void * chunky, uint32 count);
extern void c2p1x1_8_tt_partial(void * planar, void * chunky, uint32 count);
extern void c2p1x1_4_st_pens(void *planar, const uint8 *pens, uint32 count, uint32 lines);
extern void c2p1x1_4_st_pens_strided(void *planar, const uint8 *pens, uint32 count, uint32 lines,
                                    uint32 srcStride, uint32 dstStride);
extern void c2p1x1_4_st_byte(void *planar, const void *chunky, uint32 count, uint32 lines,
                            const uint8 *pal);
extern void c2p1x1_4_st_byte_strided(void *planar, const void *chunky, uint32 count, uint32 lines,
                                    const uint8 *pal, uint32 srcStride, uint32 dstStride);

/* switch FPS display */
extern void Video_SwitchFPSDisplay(uint8 key);

/* Chunky buffer. What a shame that the TT030 and Falcon030 have no
 * chunky 256 colors mode, that would spare us expensive chunky to planar
 * conversion. */
static uint8 * s_framebuffer = NULL;

/* offset to center the 320x200 image in 320x240 display */
static uint32 s_center_image_offset = 0;
/* Logical screen base, fixed after Setscreen(); shaking only reprograms the
 * hardware base (Video_ST_SetBase) and never changes Logbase(). */
uint8 *g_videoPlanarBase = NULL;	/* read by atari_viewport_tile.s */
#define s_planarBase g_videoPlanarBase
/* ST/STE: composite the mouse cursor directly into the planar screen */
bool g_videoAtariCursorDirect = false;
bool g_videoAtariMono = false;
static inline uint16 Video_Atari_GroupWords(void) { return Video_Atari_Mono() ? 2 : 4; }
static bool s_monoWhiteIsOne;
static uint16 s_spriteHighlightEffect;
#define s_curDirect g_videoAtariCursorDirect
#ifdef VIEWPORT_DEBUG_DAMAGE
static bool s_damageDebugOverlay;
static bool s_damageDebugAccepted;
static uint16 s_damageDebugRows[10];
#endif
bool g_videoViewportBlitter = false;
#define s_viewportBlitter g_videoViewportBlitter
bool g_videoScrollPending;
bool g_videoBlitterTileSetup = false;	/* read by atari_viewport_tile.s */
#define s_blitterTileSetup g_videoBlitterTileSetup
static bool s_blitterDestinationWord;
extern void Video_Atari_ConfigureBlitterDestination(uint32 wordOnly, uint32 mono);

#define BLITTER_SRC_XINC ((volatile int16 *)0xFFFF8A20UL)
#define BLITTER_SRC_YINC ((volatile int16 *)0xFFFF8A22UL)
#define BLITTER_SRC_ADDR ((volatile uint32 *)0xFFFF8A24UL)
#define BLITTER_ENDMASK1 ((volatile uint16 *)0xFFFF8A28UL)
#define BLITTER_ENDMASK2 ((volatile uint16 *)0xFFFF8A2AUL)
#define BLITTER_ENDMASK3 ((volatile uint16 *)0xFFFF8A2CUL)
#define BLITTER_DST_XINC ((volatile int16 *)0xFFFF8A2EUL)
#define BLITTER_DST_YINC ((volatile int16 *)0xFFFF8A30UL)
#define BLITTER_DST_ADDR ((volatile uint32 *)0xFFFF8A32UL)
#define BLITTER_DST_ADDR_HIGH ((volatile uint16 *)0xFFFF8A32UL)
#define BLITTER_XCOUNT ((volatile uint16 *)0xFFFF8A36UL)
#define BLITTER_YCOUNT ((volatile uint16 *)0xFFFF8A38UL)
#define BLITTER_HOP ((volatile uint8 *)0xFFFF8A3AUL)
#define BLITTER_OP ((volatile uint8 *)0xFFFF8A3BUL)
#define BLITTER_CTRL ((volatile uint8 *)0xFFFF8A3CUL)
#define BLITTER_SKEW ((volatile uint8 *)0xFFFF8A3DUL)

static short s_savedMode = 0;
static void* s_savedLogBase = 0;
static void* s_savedPhysBase = 0;

static enum {
	MCH_UNKNOWN=0, MCH_ST, MCH_STE, MCH_MEGA_STE, MCH_TT, MCH_FALCON, MCH_OTHER
} s_machine_type = MCH_UNKNOWN;

/* The Mega STE is the only machine with the cache / CPU speed register at
 * $FFFF8E21 : reading it anywhere else is a bus error.
 * bit 0 = 16MHz, bit 1 = cache enable. Supervisor mode only. */
static int s_savedCpuSpeed = -1;	/* -1 = not touched, else value to restore */
#define MEGASTE_CPUCTL	((volatile uint8 *)0xFFFF8E21UL)

/* ST/STE video base address registers. The low byte only exists on the
 * STE (on a plain ST the address is fixed at a 256 byte boundary), and
 * must always be written *last*: writing the high or mid byte clears it
 * again for ST compatibility. Supervisor mode only. */
#define VIDEO_BASE_HIGH	((volatile uint8 *)0xFFFF8201UL)
#define VIDEO_BASE_MID	((volatile uint8 *)0xFFFF8203UL)
#define VIDEO_BASE_LOW	((volatile uint8 *)0xFFFF820DUL)

#define ST_PLANAR_LINE_BYTES	(SCREEN_WIDTH / 2)	/* 4 bitplanes, 1 nibble/pixel */

static uint32 s_stScreenBase = 0;	/* address to program, incl. shake offset */
const uint16 *g_videoBlitterHalftonePattern;	/* shared with the native cursor kernel */
#define s_blitterHalftonePattern g_videoBlitterHalftonePattern

static uint32 s_paletteBackup[256];
static uint16 s_SquareTable[256];

static uint16 s_screenOffset = 0;
static bool s_screen_needrepaint = false;

#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
/* The 68000 has no bit scan instruction, so __builtin_ctz/__builtin_clz/
 * __builtin_popcount each compile into a libgcc call (___ctzsi2 etc). These
 * run once or twice per dirty screen line, every frame, and showed up as
 * ~1.9% of all cycles in a Hatari profile. g_dirty_blocks[] only ever uses
 * the low 20 bits (SCREEN_WIDTH / 16 = 20 blocks), so a small nibble table
 * replaces the calls with a few shifts and byte loads. */
static const uint8 s_nibbleFirstSet[16] = {	/* lowest set bit, 4 if none */
	4, 0, 1, 0, 2, 0, 1, 0, 3, 0, 1, 0, 2, 0, 1, 0
};
static const uint8 s_nibbleLastSet[16] = {	/* highest set bit + 1, 0 if none */
	0, 1, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4
};
/*#define VIDEO_C2P_STATS 1*/
#ifdef VIDEO_C2P_STATS
static const uint8 s_nibbleCount[16] = {
	0, 1, 1, 2, 1, 2, 2, 3, 1, 2, 2, 3, 2, 3, 3, 4
};
#endif

/* Index of the lowest set bit. Must not be called with mask == 0. */
static uint16 Video_FirstDirtyBlock(uint32 mask)
{
	uint16 base = 0;

	while ((mask & 0xF) == 0) {
		mask >>= 4;
		base += 4;
	}
	return base + s_nibbleFirstSet[mask & 0xF];
}

/* Index of the highest set bit, plus one. Returns 0 when mask == 0. */
static uint16 Video_LastDirtyBlock(uint32 mask)
{
	uint16 base = 0;

	while ((mask >> 4) != 0) {
		mask >>= 4;
		base += 4;
	}
	return base + s_nibbleLastSet[mask & 0xF];
}

/* Index of the lowest *clear* bit. Must not be called with mask == ~0.
 * Used to find where a run of contiguous dirty blocks ends: the caller
 * shifts the mask down so that bit 0 is the first dirty block of the run,
 * and the first clear bit is then the length of that run. Since
 * g_dirty_blocks[] only ever uses the low 20 bits, the shifted-down mask
 * always has clear bits left in its high end, so this always terminates. */
static uint16 Video_FirstCleanBlock(uint32 mask)
{
	uint16 base = 0;

	while ((mask & 0xF) == 0xF) {
		mask >>= 4;
		base += 4;
	}
	return base + s_nibbleFirstSet[(~mask) & 0xF];
}

#ifdef VIDEO_C2P_STATS
static uint16 Video_CountDirtyBlocks(uint32 mask)
{
	uint16 n = 0;

	while (mask != 0) {
		n += s_nibbleCount[mask & 0xF];
		mask >>= 4;
	}
	return n;
}
#endif
#endif /* GFX_STORE_DIRTY_AREA_BLOCKS */

static bool s_showFPS = false;
static volatile bool s_fpsReset = true;

/* Temporary migration diagnostics. Disable with -DVIDEO_ATARI_SWEEP_LOG=0
 * for profiling: synchronous Warning output can cause a reporting hiccup. */
#ifndef VIDEO_ATARI_SWEEP_LOG
#define VIDEO_ATARI_SWEEP_LOG 0
#endif

typedef enum DirtySweepKind {
	DIRTY_SWEEP_LEGACY,
	DIRTY_SWEEP_VIEWPORT,
	DIRTY_SWEEP_REPAINT,
	DIRTY_SWEEP_COUNT
} DirtySweepKind;

#if VIDEO_ATARI_SWEEP_LOG
#define DIRTY_SWEEP_REPORT_MS 5000

typedef struct DirtySweepStats {
	uint32 ticks, calls, pixels, peak;
} DirtySweepStats;

static DirtySweepStats s_sweepTick[DIRTY_SWEEP_COUNT];
static DirtySweepStats s_sweepPeriod[DIRTY_SWEEP_COUNT];
static uint32 s_sweepStart, s_sweepTicks, s_sweepActive, s_sweepPeak;
static bool s_sweepStarted;
static uint32 s_sweepFieldPixels, s_sweepMinimapPixels, s_sweepOtherPixels;
static uint32 s_sweepRowPixels[10], s_sweepRowMasks[10], s_sweepRowWidest[10];
static uint16 s_sweepRowWidth[10];

static void Video_Atari_DirtySweepBeginTick(void)
{
	if (!s_curDirect) return;
	if (!s_sweepStarted) {
		s_sweepStart = Timer_GetTime();
		s_sweepStarted = true;
	}
	memset(s_sweepTick, 0, sizeof(s_sweepTick));
}

/* Fold local sweep totals once, rather than adding global counters for
 * every c2p run. Dirty flags alone do not count as converted pixels. */
static void Video_Atari_DirtySweepRecord(DirtySweepKind kind, uint32 pixels, uint32 calls)
{
	s_sweepTick[kind].pixels += pixels;
	s_sweepTick[kind].calls += calls;
}

static uint16 Video_Atari_SweepMaskWidth(uint32 mask)
{
	uint16 width = 0;
	while (mask != 0) {
		width += 16;
		mask &= mask - 1;
	}
	return width;
}

/* Classify actual converted bands, not producer rectangles that might
 * coalesce or be cleared by an immediate present before the sweep. */
static void Video_Atari_DirtySweepBand(uint32 mask, uint16 top, uint16 bottom, uint16 width)
{
	uint32 fieldMask = mask & 0x7fff;
	uint16 fieldWidth = Video_Atari_SweepMaskWidth(fieldMask);
	uint16 minimapWidth = Video_Atari_SweepMaskWidth(mask & 0xf0000);
	uint16 fieldTop = max(top, 40), fieldBottom = min(bottom, SCREEN_HEIGHT);
	uint16 minimapTop = max(top, 136), minimapBottom = min(bottom, SCREEN_HEIGHT);
	uint32 field = 0, minimap = 0;

	if (fieldTop < fieldBottom && fieldWidth != 0) {
		uint16 firstRow = (fieldTop - 40) >> 4;
		uint16 lastRow = (fieldBottom - 1 - 40) >> 4;
		uint16 row;
		field = (uint32)(fieldBottom - fieldTop) * fieldWidth;
		for (row = firstRow; row <= lastRow; row++) {
			uint16 rowTop = max(fieldTop, 40 + row * 16);
			uint16 rowBottom = min(fieldBottom, 40 + (row + 1) * 16);
			s_sweepRowPixels[row] += (uint32)(rowBottom - rowTop) * fieldWidth;
			s_sweepRowMasks[row] |= fieldMask;
			if (fieldWidth > s_sweepRowWidth[row]) {
				s_sweepRowWidth[row] = fieldWidth;
				s_sweepRowWidest[row] = fieldMask;
			}
		}
	}
	if (minimapTop < minimapBottom) minimap = (uint32)(minimapBottom - minimapTop) * minimapWidth;
	s_sweepFieldPixels += field;
	s_sweepMinimapPixels += minimap;
	s_sweepOtherPixels += (uint32)(bottom - top) * width - field - minimap;
}

static void Video_Atari_DirtySweepEndTick(void)
{
	uint32 now, elapsed, total = 0, pixels = 0, average, coverage;
	int kind;
	const DirtySweepStats *legacy = &s_sweepPeriod[DIRTY_SWEEP_LEGACY];
	const DirtySweepStats *viewport = &s_sweepPeriod[DIRTY_SWEEP_VIEWPORT];
	const DirtySweepStats *repaint = &s_sweepPeriod[DIRTY_SWEEP_REPAINT];

	if (!s_curDirect) return;
	s_sweepTicks++;
	for (kind = 0; kind < DIRTY_SWEEP_COUNT; kind++) {
		DirtySweepStats *period = &s_sweepPeriod[kind];
		uint32 tickPixels = s_sweepTick[kind].pixels;
		if (tickPixels != 0) period->ticks++;
		period->calls += s_sweepTick[kind].calls;
		period->pixels += tickPixels;
		if (tickPixels > period->peak) period->peak = tickPixels;
		total += tickPixels;
		pixels += period->pixels;
	}
	if (total != 0) s_sweepActive++;
	if (total > s_sweepPeak) s_sweepPeak = total;
	now = Timer_GetTime();
	elapsed = now - s_sweepStart;
	if (elapsed < DIRTY_SWEEP_REPORT_MS) return;
	average = pixels / s_sweepTicks;
	coverage = average * 1000 / (SCREEN_WIDTH * SCREEN_HEIGHT);
	Warning("dirty-c2p %lums: ticks=%lu active=%lu idle=%lu px=%lu avg/tick=%lu frame=%lu.%lu%% peak=%lu\n"
	        "  legacy: ticks=%lu calls=%lu px=%lu avg/active=%lu peak=%lu\n"
	        "  viewport: ticks=%lu calls=%lu px=%lu avg/active=%lu peak=%lu\n"
	        "  repaint: ticks=%lu calls=%lu px=%lu avg/active=%lu peak=%lu\n",
	        (unsigned long)elapsed, (unsigned long)s_sweepTicks,
	        (unsigned long)s_sweepActive, (unsigned long)(s_sweepTicks - s_sweepActive),
	        (unsigned long)pixels, (unsigned long)average,
	        (unsigned long)(coverage / 10), (unsigned long)(coverage % 10), (unsigned long)s_sweepPeak,
	        (unsigned long)legacy->ticks, (unsigned long)legacy->calls, (unsigned long)legacy->pixels,
	        (unsigned long)(legacy->ticks != 0 ? legacy->pixels / legacy->ticks : 0), (unsigned long)legacy->peak,
	        (unsigned long)viewport->ticks, (unsigned long)viewport->calls, (unsigned long)viewport->pixels,
	        (unsigned long)(viewport->ticks != 0 ? viewport->pixels / viewport->ticks : 0), (unsigned long)viewport->peak,
	        (unsigned long)repaint->ticks, (unsigned long)repaint->calls, (unsigned long)repaint->pixels,
	        (unsigned long)(repaint->ticks != 0 ? repaint->pixels / repaint->ticks : 0), (unsigned long)repaint->peak);
	if (viewport->pixels != 0) {
		Warning("  vp-area: field=%lu minimap=%lu other=%lu\n"
		        "  vp-field row-px: %lu %lu %lu %lu %lu %lu %lu %lu %lu %lu\n"
		        "  vp-field mask-union: %05lx %05lx %05lx %05lx %05lx %05lx %05lx %05lx %05lx %05lx\n"
		        "  vp-field widest-mask: %05lx %05lx %05lx %05lx %05lx %05lx %05lx %05lx %05lx %05lx\n",
		        (unsigned long)s_sweepFieldPixels, (unsigned long)s_sweepMinimapPixels, (unsigned long)s_sweepOtherPixels,
		        (unsigned long)s_sweepRowPixels[0], (unsigned long)s_sweepRowPixels[1], (unsigned long)s_sweepRowPixels[2],
		        (unsigned long)s_sweepRowPixels[3], (unsigned long)s_sweepRowPixels[4], (unsigned long)s_sweepRowPixels[5],
		        (unsigned long)s_sweepRowPixels[6], (unsigned long)s_sweepRowPixels[7], (unsigned long)s_sweepRowPixels[8],
		        (unsigned long)s_sweepRowPixels[9],
		        (unsigned long)s_sweepRowMasks[0], (unsigned long)s_sweepRowMasks[1], (unsigned long)s_sweepRowMasks[2],
		        (unsigned long)s_sweepRowMasks[3], (unsigned long)s_sweepRowMasks[4], (unsigned long)s_sweepRowMasks[5],
		        (unsigned long)s_sweepRowMasks[6], (unsigned long)s_sweepRowMasks[7], (unsigned long)s_sweepRowMasks[8],
		        (unsigned long)s_sweepRowMasks[9],
		        (unsigned long)s_sweepRowWidest[0], (unsigned long)s_sweepRowWidest[1], (unsigned long)s_sweepRowWidest[2],
		        (unsigned long)s_sweepRowWidest[3], (unsigned long)s_sweepRowWidest[4], (unsigned long)s_sweepRowWidest[5],
		        (unsigned long)s_sweepRowWidest[6], (unsigned long)s_sweepRowWidest[7], (unsigned long)s_sweepRowWidest[8],
		        (unsigned long)s_sweepRowWidest[9]);
	}
	memset(s_sweepPeriod, 0, sizeof(s_sweepPeriod));
	memset(s_sweepRowPixels, 0, sizeof(s_sweepRowPixels));
	memset(s_sweepRowMasks, 0, sizeof(s_sweepRowMasks));
	memset(s_sweepRowWidest, 0, sizeof(s_sweepRowWidest));
	memset(s_sweepRowWidth, 0, sizeof(s_sweepRowWidth));
	s_sweepFieldPixels = s_sweepMinimapPixels = s_sweepOtherPixels = 0;
	s_sweepTicks = s_sweepActive = s_sweepPeak = 0;
	s_sweepStart = now;
}
#else
#define Video_Atari_DirtySweepBeginTick() ((void)0)
#define Video_Atari_DirtySweepRecord(kind, pixels, calls) ((void)0)
#define Video_Atari_DirtySweepBand(mask, top, bottom, width) ((void)0)
#define Video_Atari_DirtySweepEndTick() ((void)0)
#endif

/* Instrumentation for the ST/STE chunky-to-planar path.
 * DISABLED BY DEFAULT: the reports are written with unbuffered Warning()
 * calls from inside Video_Tick(), so enabling this measurably slows the
 * game down (a visible hiccup every reporting period) and skews any
 * profiling done while it is on. Build with -DVIDEO_C2P_STATS to turn it
 * back on when investigating the c2p pipeline.
 * Distinguishes the "full width snap" branch (which ignores g_dirty_blocks[]
 * and converts whole lines) from the per line branch, and compares the
 * converted pixel count against the number of pixels really marked dirty. */
#ifdef VIDEO_C2P_STATS
#define VIDEO_C2P_STATS_PERIOD 1000	/* report every N Video_Tick() calls */

/* Per box logging: report every converted box where more than this
 * percentage of the converted pixels were not actually dirty.
 * Capped per period so the log does not flood. */
#define VIDEO_C2P_STATS_VERBOSE
#define VIDEO_C2P_STATS_WASTE_PCT 50
#define VIDEO_C2P_STATS_MAX_LOGS 20
/* A single tick converting more than this many pixels is a visible stutter:
 * at ~40 cycles/pixel, 6400 px is already a whole 8MHz frame of work. Forced
 * full repaints (palette fades) are deliberately excluded from all of this. */
#define VIDEO_C2P_STATS_TICK_PX 6400
#define VIDEO_C2P_STATS_MAX_SPIKES 12

static uint32 s_statTicks = 0;		/* Video_Tick() calls */
static uint32 s_statConverts = 0;	/* ticks that actually converted something */
static uint32 s_statSnapCalls = 0;	/* c2p calls taking the full width branch */
static uint32 s_statSnapPixels = 0;	/* pixels converted by that branch */
static uint32 s_statLineCalls = 0;	/* c2p calls taking the per line branch */
static uint32 s_statLinePixels = 0;	/* pixels converted by that branch */
static uint32 s_statSpanPixels = 0;	/* what the old first..last span logic would have converted */
static uint32 s_statDirtyPixels = 0;	/* pixels really dirty (popcount based) */
static uint32 s_statForcedRepaints = 0;	/* s_screen_needrepaint forced full frames */
static uint32 s_statForcedPixels = 0;	/* pixels converted by forced repaints */
static uint32 s_statTickPixels = 0;	/* pixels converted by the current tick */
static uint32 s_statTickDirty = 0;	/* really dirty pixels of the current tick */
static uint32 s_statTickCalls = 0;	/* c2p calls issued by the current tick */
static uint32 s_statTickRows = 0;	/* scanlines converted by the current tick */
static uint32 s_statPeakTickPx = 0;	/* worst single tick of this period */
static uint32 s_statSpikes = 0;		/* ticks above the stutter threshold */
#ifdef VIDEO_C2P_STATS_VERBOSE
static uint32 s_statSpikesLogged = 0;
static uint32 s_statLogged = 0;		/* boxes logged during this period */
#endif

/* ENHANCEMENT (measurement only, not yet acted on) -- bucket every c2p'd
 * pixel into one of three screen regions, so we can tell how much of the
 * c2p workload is actually spent on the battlefield viewport versus the
 * top credits bar and the right-hand sidebar, both of which are drawn
 * from small, mostly-static widget sets (see widget.c's g_widgetProperties:
 * widget 0 = full-width top bar, y<VIDEO_C2P_TOPBAR_HEIGHT; widget 3/6/8/
 * etc = sidebar, x>=VIDEO_C2P_SIDEBAR_LEFT, spanning the full height).
 * x=256 and y=40 are both exact 16px/word-aligned boundaries, so no pixel
 * is ever split across two regions by the alignment c2p already requires.
 * This does not itself save any cycles -- it exists to decide whether a
 * separate direct-to-planar path for the top bar/sidebar (bypassing the
 * chunky buffer and c2p entirely for those widgets) is worth building. */
#define VIDEO_C2P_TOPBAR_HEIGHT 40
#define VIDEO_C2P_SIDEBAR_LEFT 256
static uint32 s_statTopBarPixels = 0;
static uint32 s_statSidebarPixels = 0;
static uint32 s_statBattlefieldPixels = 0;

/* Split a converted [top,bottom) x [left,left+rowWidth) box across the
 * top bar / sidebar / battlefield regions and add its pixel count to the
 * matching counter(s). Handles boxes that straddle the y=40 boundary
 * (splits rows) and/or the x=256 boundary (splits columns for the rows
 * that are below the top bar). */
static void Video_C2PStats_Region(uint16 top, uint16 bottom, uint16 left, uint16 rowWidth)
{
	uint16 topBarRows = 0;
	uint16 fieldRows;
	uint16 right = left + rowWidth;

	if (top < VIDEO_C2P_TOPBAR_HEIGHT) {
		uint16 topBarBottom = (bottom < VIDEO_C2P_TOPBAR_HEIGHT) ? bottom : VIDEO_C2P_TOPBAR_HEIGHT;
		topBarRows = topBarBottom - top;
		s_statTopBarPixels += (uint32)topBarRows * rowWidth;
	}

	fieldRows = (bottom - top) - topBarRows;
	if (fieldRows != 0) {
		uint16 battRight = (right < VIDEO_C2P_SIDEBAR_LEFT) ? right : VIDEO_C2P_SIDEBAR_LEFT;
		uint16 sideLeft = (left > VIDEO_C2P_SIDEBAR_LEFT) ? left : VIDEO_C2P_SIDEBAR_LEFT;
		uint32 battWidth = (battRight > left) ? (uint32)(battRight - left) : 0;
		uint32 sideWidth = (right > sideLeft) ? (uint32)(right - sideLeft) : 0;

		s_statBattlefieldPixels += (uint32)fieldRows * battWidth;
		s_statSidebarPixels += (uint32)fieldRows * sideWidth;
	}
}

/* Sum the truly dirty pixels of lines [top;bottom[ from the block masks. */
static uint32 Video_C2PStats_CountDirty(uint16 top, uint16 bottom)
{
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
	uint32 dirty = 0;
	uint16 y;

	if (bottom > SCREEN_HEIGHT) bottom = SCREEN_HEIGHT;
	for (y = top; y < bottom; y++) {
		dirty += (uint32)Video_CountDirtyBlocks(g_dirty_blocks[y]) << 4;
	}
	return dirty;
#else
	(void)top;
	(void)bottom;
	return 0;
#endif
}

/* Account one converted box, and log it when it wastes too much. */
static void Video_C2PStats_Box(const char * kind, uint16 top, uint16 bottom,
                               uint16 left, uint32 converted, uint32 dirty, uint32 mask)
{
	s_statDirtyPixels += dirty;
	s_statTickPixels += converted;
	s_statTickDirty += dirty;
#ifdef VIDEO_C2P_STATS_VERBOSE
	if (converted != 0 && s_statLogged < VIDEO_C2P_STATS_MAX_LOGS
	 && (converted - dirty) * 100 > (uint32)VIDEO_C2P_STATS_WASTE_PCT * converted) {
		s_statLogged++;
		Warning("c2p %s box y=%hu..%hu x=%hu w=%lu: %lu px, dirty %lu px, waste %lu px (%lu%%) mask=%05lx\n",
		        kind, top, bottom, left,
		        (unsigned long)(bottom > top ? converted / (bottom - top) : converted),
		        (unsigned long)converted, (unsigned long)dirty,
		        (unsigned long)(converted - dirty),
		        (unsigned long)(((converted - dirty) * 100) / converted),
		        (unsigned long)mask);
	}
#else
	(void)kind;
	(void)top;
	(void)bottom;
	(void)left;
	(void)converted;
	(void)mask;
#endif
}

/* Called once per converting tick. A stutter is a *single* tick doing too much
 * work, which a 100-tick average completely hides, so report those directly. */
static void Video_C2PStats_EndTick(void)
{
	if (s_screen_needrepaint) return;	/* forced repaint: not our problem */

	if (s_statTickPixels > s_statPeakTickPx) s_statPeakTickPx = s_statTickPixels;

	if (s_statTickPixels >= VIDEO_C2P_STATS_TICK_PX) {
		s_statSpikes++;
#ifdef VIDEO_C2P_STATS_VERBOSE
		if (s_statSpikesLogged < VIDEO_C2P_STATS_MAX_SPIKES) {
			s_statSpikesLogged++;
			Warning("c2p SPIKE tick: %lu px in %lu rows / %lu calls, dirty %lu px, waste %lu px (%lu%%), ~%lu ms\n",
			        (unsigned long)s_statTickPixels,
			        (unsigned long)s_statTickRows,
			        (unsigned long)s_statTickCalls,
			        (unsigned long)s_statTickDirty,
			        (unsigned long)(s_statTickPixels - s_statTickDirty),
			        (unsigned long)((s_statTickPixels - s_statTickDirty) * 100 / s_statTickPixels),
			        (unsigned long)(s_statTickPixels * 41 / 8000));
		}
#endif
	}
}

static void Video_C2PStats_Report(void)
{
	uint32 total;

	if (++s_statTicks < VIDEO_C2P_STATS_PERIOD) return;

	total = s_statSnapPixels + s_statLinePixels;
	if (s_statDirtyPixels > total) s_statDirtyPixels = total;	/* never underflow */

	Warning("c2p stats over %lu ticks (%lu converting):\n",
	        (unsigned long)s_statTicks, (unsigned long)s_statConverts);
	Warning("  snap branch : %lu calls, %lu px\n",
	        (unsigned long)s_statSnapCalls, (unsigned long)s_statSnapPixels);
	Warning("  line branch : %lu calls, %lu px\n",
	        (unsigned long)s_statLineCalls, (unsigned long)s_statLinePixels);
	Warning("  line runs   : %lu px vs %lu px if spanned first..last (saved %lu px, %lu%%)\n",
	        (unsigned long)s_statLinePixels, (unsigned long)s_statSpanPixels,
	        (unsigned long)(s_statSpanPixels - s_statLinePixels),
	        (unsigned long)(s_statSpanPixels != 0
	                        ? ((s_statSpanPixels - s_statLinePixels) * 100) / s_statSpanPixels : 0));
	Warning("  converted %lu px, really dirty %lu px, waste %lu px (%lu%%)\n",
	        (unsigned long)total, (unsigned long)s_statDirtyPixels,
	        (unsigned long)(total - s_statDirtyPixels),
	        (unsigned long)(total != 0 ? ((total - s_statDirtyPixels) * 100) / total : 0));
	Warning("  peak tick %lu px (~%lu ms), %lu spikes >=%u px, avg %lu px/converting tick\n",
	        (unsigned long)s_statPeakTickPx,
	        (unsigned long)(s_statPeakTickPx * 41 / 8000),
	        (unsigned long)s_statSpikes, VIDEO_C2P_STATS_TICK_PX,
	        (unsigned long)(s_statConverts != 0 ? total / s_statConverts : 0));
	{
		uint32 regionTotal = s_statTopBarPixels + s_statSidebarPixels + s_statBattlefieldPixels;
		Warning("  regions: topbar %lu px (%lu%%), sidebar %lu px (%lu%%), battlefield %lu px (%lu%%)\n",
		        (unsigned long)s_statTopBarPixels,
		        (unsigned long)(regionTotal != 0 ? (s_statTopBarPixels * 100) / regionTotal : 0),
		        (unsigned long)s_statSidebarPixels,
		        (unsigned long)(regionTotal != 0 ? (s_statSidebarPixels * 100) / regionTotal : 0),
		        (unsigned long)s_statBattlefieldPixels,
		        (unsigned long)(regionTotal != 0 ? (s_statBattlefieldPixels * 100) / regionTotal : 0));
	}
	if (s_statForcedRepaints != 0)
		Warning("  (excluded: %lu forced full repaints, %lu px - palette fades)\n",
		        (unsigned long)s_statForcedRepaints,
		        (unsigned long)s_statForcedPixels);
	GFX_DirtyStats_Report();
#ifdef GFX_DIRTY_SOURCE_STATS
	extern void Viewport_EagerReport(void);
	Viewport_EagerReport();
#endif

	s_statTicks = 0;
	s_statConverts = 0;
	s_statSnapCalls = 0;
	s_statSnapPixels = 0;
	s_statLineCalls = 0;
	s_statLinePixels = 0;
	s_statSpanPixels = 0;
	s_statDirtyPixels = 0;
	s_statForcedRepaints = 0;
	s_statForcedPixels = 0;
	s_statPeakTickPx = 0;
	s_statSpikes = 0;
	s_statTopBarPixels = 0;
	s_statSidebarPixels = 0;
	s_statBattlefieldPixels = 0;
#ifdef VIDEO_C2P_STATS_VERBOSE
	s_statLogged = 0;
	s_statSpikesLogged = 0;
#endif
}
#endif /* VIDEO_C2P_STATS */

/* 4bit palette */
#define MAKE_PC_COLOR(_r,_g,_b) _r>>2,_g>>2,_b>>2,0
const uint8 s_palette4BitPC[16*4] =
{
	MAKE_PC_COLOR( 16, 16, 16), MAKE_PC_COLOR( 48,112, 48), MAKE_PC_COLOR(176, 16, 16), MAKE_PC_COLOR( 48, 48,176),
	MAKE_PC_COLOR(240,240,240), MAKE_PC_COLOR( 80, 80, 80), MAKE_PC_COLOR(176,176,144), MAKE_PC_COLOR( 80, 48, 48),
	MAKE_PC_COLOR(176,112, 48), MAKE_PC_COLOR( 80, 80,240), MAKE_PC_COLOR(240,240, 80), MAKE_PC_COLOR(240,208,112),
	MAKE_PC_COLOR(144,208,240), MAKE_PC_COLOR(208,144,112), MAKE_PC_COLOR( 80,176, 80), MAKE_PC_COLOR(112,112,144)
/*
 * Original PICO-8 palette
	MAKE_PC_COLOR(20,12,28), MAKE_PC_COLOR(68,36,52), MAKE_PC_COLOR(48,52,109),	MAKE_PC_COLOR(78,74,78),
	MAKE_PC_COLOR(133,76,48), MAKE_PC_COLOR(52,101,36), MAKE_PC_COLOR(208,70,72), MAKE_PC_COLOR(117,113,97),
	MAKE_PC_COLOR(89,125,206), MAKE_PC_COLOR(210,125,44), MAKE_PC_COLOR(133,149,161), MAKE_PC_COLOR(109,170,44),
	MAKE_PC_COLOR(210,170,153), MAKE_PC_COLOR(109,194,202), MAKE_PC_COLOR(218,212,94), MAKE_PC_COLOR(222,238,214)
*/

};

static uint8 s_palette4BitMap[256];
static uint8 s_paletteMonoCoverage[256];

static AtariDitherLookup s_palette4BitDither = {.flat = true}, s_tileDither = {.flat = true};
static AtariMonoPackedLookup s_paletteMonoPacked, s_tileMonoPacked, s_unitMonoPacked;
static AtariMonoPackedLookup s_buildingMonoPacked;

typedef struct AtariPlanarBackend {
	void (*prepare)(const AtariDitherSource *, const AtariDitherLookup *, uint16 *, uint16);
	void (*convert)(const AtariDitherSource *, const AtariDitherLookup *, uint16 *, uint16);
	void (*readGroup)(const uint16 *, uint16, uint16, uint16, uint16[4]);
	void (*copyRun)(uint8 *, uint16, const uint8 *, uint16, uint16, uint16);
	void (*composeTile)(const uint16 *, const uint16 *, const uint16 *, const uint16 *, uint16 *, uint16 *);
	void (*paint)(uint16 *, uint16, uint16, uint16, uint16, uint16, const uint16 *, uint16, uint8, int16, int16);
	uint8 xShift;
	uint8 chunkyAlignment;
	bool maskedQueue;
	uint8 spriteYShift;
	bool blitterSpriteEffects;
	bool blitterProtectedSprites;
} AtariPlanarBackend;

static void Video_Atari_PrepareColour(const AtariDitherSource *, const AtariDitherLookup *, uint16 *, uint16);
static void Video_Atari_PrepareMono(const AtariDitherSource *, const AtariDitherLookup *, uint16 *, uint16);
static void Video_Atari_ConvertColour(const AtariDitherSource *, const AtariDitherLookup *, uint16 *, uint16);
static void Video_Atari_ColourReadGroup(const uint16 *, uint16, uint16, uint16, uint16[4]);
static void Video_Atari_CopyColourRun(uint8 *, uint16, const uint8 *, uint16, uint16, uint16);
static void Video_Atari_CopyMonoRun(uint8 *, uint16, const uint8 *, uint16, uint16, uint16);
static void Video_Atari_ComposeColourTile(const uint16 *, const uint16 *, const uint16 *, const uint16 *, uint16 *, uint16 *);
static void Video_Atari_PaintColour(uint16 *, uint16, uint16, uint16, uint16, uint16, const uint16 *, uint16, uint8, int16, int16);
static void Video_Atari_PaintMono(uint16 *, uint16, uint16, uint16, uint16, uint16, const uint16 *, uint16, uint8, int16, int16);
static const AtariPlanarBackend s_colourBackend = {
	Video_Atari_PrepareColour, Video_Atari_ConvertColour, Video_Atari_ColourReadGroup,
	Video_Atari_CopyColourRun, Video_Atari_ComposeColourTile, Video_Atari_PaintColour, 1, 2, true, 0, true, true
};
static const AtariPlanarBackend s_monoBackend = {
	Video_Atari_PrepareMono, Video_Atari_PrepareMono, Video_Atari_MonoReadGroup,
	Video_Atari_CopyMonoRun, Video_Atari_MonoComposeTile, Video_Atari_PaintMono, 2, 1, false, 1, false, false
};
static const AtariPlanarBackend *s_planarBackend = &s_colourBackend;
static void Video_Atari_InitTileCursorBackend(void);

static void Video_Atari_CopyColourRun(uint8 *dst, uint16 dstStride, const uint8 *src,
	uint16 srcStride, uint16 groups, uint16 height)
{
	while (height-- != 0) {
		memcpy(dst, src, groups * 8);
		dst += dstStride;
		src += srcStride;
	}
}

static void Video_Atari_CopyMonoRun(uint8 *dst, uint16 dstStride, const uint8 *src,
	uint16 srcStride, uint16 groups, uint16 height)
{
	while (height-- != 0) {
		memcpy(dst, src, groups * 4);
		memcpy(dst + dstStride / 2, src + srcStride / 2, groups * 4);
		dst += dstStride;
		src += srcStride;
	}
}

static uint8 Video_Atari_MonoCoverage(uint8 r, uint8 g, uint8 b)
{
	uint32 luma = (r & 63) * 299UL + (g & 63) * 587UL + (b & 63) * 114UL;
	return (luma * 16 + 31500) / 63000;
}

static void Video_Atari_SetMonoCoverage(AtariDitherLookup *lookup, uint8 colour, uint8 coverage)
{
	uint16 x, y, pattern = s_paletteMonoLuma[coverage];
	lookup->flat = false;
	for (y = 0; y < 4; y++)
		for (x = 0; x < 4; x++)
			lookup->pens[y][x][colour] = (pattern >> (15 - y * 4 - x)) & 1;
}

static uint8 Video_Atari_ReducedMonoCoverage(uint8 coverage)
{
	return coverage < 3 ? 0 : coverage < 6 ? 4 : coverage < 9 ? 8 : 12;
}

static void Video_Atari_SetPackedMonoCoverage(AtariMonoPackedLookup *lookup, uint8 colour, uint8 coverage)
{
	uint16 x, y;
	uint16 pattern = s_paletteMonoLuma[coverage];
	uint32 invert = s_monoWhiteIsOne ? 0 : 0x00030003UL;

	for (y = 0; y < 2; y++) {
		for (x = 0; x < 2; x++) {
			uint16 shift = y * 8 + x * 2;
			uint32 top = (pattern >> (14 - shift)) & 3;
			uint32 bottom = (pattern >> (10 - shift)) & 3;
			lookup->cells[y][x][colour] = ((top << 16) | bottom) ^ invert;
		}
	}
}

void Video_Atari_MonoPenWords(uint8 pen, int16 x, int16 y, uint16 words[4])
{
	uint16 row, pattern = s_paletteMonoST[pen];
	for (row = 0; row < 2; row++) {
		uint16 nibble = (pattern >> (12 - (((y * 2 + row) & 3) * 4))) & 15;
		uint16 bits;
		if (x & 1) nibble = ((nibble << 2) | (nibble >> 2)) & 15;
		bits = (nibble << 12) | (nibble << 8) | (nibble << 4) | nibble;
		if (!s_monoWhiteIsOne) bits = ~bits;
		words[row * 2] = words[row * 2 + 1] = bits;
	}
}

static void Video_Atari_PaintColour(uint16 *dst, uint16 stride, uint16 x, uint16 y,
	uint16 width, uint16 height, const uint16 *masks, uint16 maskStride,
	uint8 pen, int16 originX, int16 originY)
{
	uint16 first = x >> 4, end = (x + width + 15) >> 4, row, group, plane;
	uint16 fill[4], left = 0xffffu >> (x & 15);
	uint16 right = 0xffffu << (15 - ((x + width - 1) & 15));
	(void)originX;
	(void)originY;
	for (plane = 0; plane < 4; plane++) fill[plane] = (uint16)-(int16)((pen >> plane) & 1);
	dst += (uint32)y * stride + first * 4;
	for (row = 0; row < height; row++, dst += stride) {
		for (group = first; group < end; group++) {
			uint16 mask = masks == NULL ? 0xffff : masks[row * maskStride + group - first];
			uint16 *out = dst + (group - first) * 4;
			if (group == first) mask &= left;
			if (group + 1 == end) mask &= right;
			if (mask == 0xffff) memcpy(out, fill, sizeof(fill));
			else if (mask != 0)
				for (plane = 0; plane < 4; plane++) out[plane] = (out[plane] & ~mask) | (fill[plane] & mask);
		}
	}
}

static void Video_Atari_PaintMono(uint16 *dst, uint16 stride, uint16 x, uint16 y,
	uint16 width, uint16 height, const uint16 *masks, uint16 maskStride,
	uint8 pen, int16 originX, int16 originY)
{
	uint16 first = x >> 4, end = (x + width + 15) >> 4, row, group;
	uint16 fill[2][4], left = 0xffffu >> (x & 15);
	uint16 right = 0xffffu << (15 - ((x + width - 1) & 15));
	Video_Atari_MonoPenWords(pen, originX - (x & 15), originY, fill[0]);
	Video_Atari_MonoPenWords(pen, originX - (x & 15), (uint16)(originY + 1) & 1, fill[1]);
	dst += (uint32)y * stride + first * 2;
	for (row = 0; row < height; row++, dst += stride) {
		const uint16 *pattern = fill[row & 1];
		for (group = first; group < end; group++) {
			uint16 mask = masks == NULL ? 0xffff : masks[row * maskStride + group - first];
			uint16 opacity[4], word, *out = dst + (group - first) * 2;
			if (group == first) mask &= left;
			if (group + 1 == end) mask &= right;
			if (mask == 0) continue;
			Video_Atari_MonoMaskWords(mask, opacity);
			for (word = 0; word < 4; word++) {
				uint16 *p = out + (word / 2) * (stride / 2) + (word & 1);
				*p = (*p & ~opacity[word]) | (pattern[word] & opacity[word]);
			}
		}
	}
}

uint32 Video_Atari_PlanarOffset(uint16 stride, uint16 x, uint16 y)
{
	assert((x & 15) == 0 && x / 4 < stride);
	return (uint32)y * stride + (x >> (s_planarBackend->xShift + 1));
}

void Video_Atari_PaintPlanar(uint16 *dst, uint16 stride, uint16 x, uint16 y,
	uint16 width, uint16 height, const uint16 *masks, uint16 maskStride,
	uint8 pen, int16 originX, int16 originY)
{
	assert(dst != NULL && width != 0 && height != 0 && pen < 16);
	assert((uint32)x + width <= (uint32)stride * 4);
	assert(masks == NULL || maskStride >= ((x & 15) + width + 15) / 16);
	s_planarBackend->paint(dst, stride, x, y, width, height, masks, maskStride, pen, originX, originY);
}

void Video_Atari_CopyPlanar(uint16 *dst, uint16 dstStride, uint16 dstX, uint16 dstY,
	const uint16 *src, uint16 srcStride, uint16 srcX, uint16 srcY, uint16 width, uint16 height)
{
	assert(dst != NULL && src != NULL && width != 0 && height != 0);
	assert(((dstX | srcX | width) & 15) == 0);
	assert((uint32)dstX + width <= (uint32)dstStride * 4);
	assert((uint32)srcX + width <= (uint32)srcStride * 4);
	s_planarBackend->copyRun(
		(uint8 *)(dst + Video_Atari_PlanarOffset(dstStride, dstX, dstY)), dstStride * 2,
		(const uint8 *)(src + Video_Atari_PlanarOffset(srcStride, srcX, srcY)), srcStride * 2,
		width / 16, height);
}

void Video_Atari_DrawPlanarBorder(uint16 *dst, uint16 stride, uint16 x,
	uint16 width, uint16 height, const uint8 colours[4])
{
	uint16 groups[16], i;
	uint8 pens[4];
	assert(dst != NULL && width >= 2 && height >= 3 && (uint32)x + width <= (uint32)stride * 4);
	for (i = 0; i < 4; i++) pens[i] = Video_Atari_GetPalettePen(colours[i]);
	if (Video_Atari_Mono()) {
		/* Preserve each full fill/edge request's phase when skipping overwritten pixels. */
		if (width > 2)
			Video_Atari_PaintMono(dst, stride, x + 1, 1, width - 2, height - 2, NULL, 0, pens[0], 1, 1);
		Video_Atari_PaintMono(dst, stride, x, 0, width - 1, 1, NULL, 0, pens[2], 0, 0);
		Video_Atari_PaintMono(dst, stride, x, 1, 1, height - 2, NULL, 0, pens[2], 0, 1);
		Video_Atari_PaintMono(dst, stride, x + width - 1, 1, 1, height - 1, NULL, 0, pens[1], 0, 1);
		if (width > 2)
			Video_Atari_PaintMono(dst, stride, x + 1, height - 1, width - 2, 1, NULL, 0, pens[1], 1, 0);
		Video_Atari_PaintMono(dst, stride, x + width - 1, 0, 1, 1, NULL, 0, pens[3], 0, 0);
		Video_Atari_PaintMono(dst, stride, x, height - 1, 1, 1, NULL, 0, pens[3], 0, 0);
		return;
	}
	for (i = 0; i < 4; i++) Planar_SolidGroup(groups + i * 4, pens[i]);
	Planar_DrawBorder(dst, stride, x, width, height, groups);
}

static inline __attribute__((always_inline)) void Video_Atari_GlyphValue(
	const uint16 *src, uint16 *dst, uint16 *mdst, uint16 rows, uint16 sh,
	uint16 planeStride, uint16 maskStride, const uint16 pen)
{
	uint16 moff = 0;
	for (; rows != 0; rows--, src++, dst += planeStride, moff += maskStride) {
		uint32 v;
		uint16 hi, lo;
		if (*src == 0) continue;
		v = (uint32)*src << sh;
		hi = (uint16)(v >> 16);
		lo = (uint16)v;
		if (pen & 1) dst[0] |= hi; else dst[0] &= ~hi;
		if (pen & 2) dst[1] |= hi; else dst[1] &= ~hi;
		if (pen & 4) dst[2] |= hi; else dst[2] &= ~hi;
		if (pen & 8) dst[3] |= hi; else dst[3] &= ~hi;
		if (lo != 0) {
			if (pen & 1) dst[4] |= lo; else dst[4] &= ~lo;
			if (pen & 2) dst[5] |= lo; else dst[5] &= ~lo;
			if (pen & 4) dst[6] |= lo; else dst[6] &= ~lo;
			if (pen & 8) dst[7] |= lo; else dst[7] &= ~lo;
		}
		if (mdst != NULL) {
			mdst[moff] |= hi;
			if (lo != 0) mdst[moff + 1] |= lo;
		}
	}
}

static void Video_Atari_DrawColourGlyphs(const VideoAtariGlyphRun *run,
	uint16 *dst, uint16 stride, uint16 *masks, uint16 maskStride)
{
	uint8 pens[8];
	uint16 i, j;
	assert(run->valueCount <= lengthof(pens));
	for (j = 0; j < run->valueCount; j++) pens[j] = Video_Atari_GetPalettePen(run->values[j].colour);
	for (i = 0; i < run->count; i++) {
		uint16 x = run->glyphs[i].x, sh = 16 - (x & 15);
		uint16 *out = dst + run->firstRow * stride + (x >> 4) * 4;
		uint16 *opacity = masks == NULL ? NULL : masks + run->firstRow * maskStride + (x >> 4);
		for (j = 0; j < run->valueCount; j++) {
			const uint16 *src = run->glyphs[i].masks + run->values[j].offset;
#define VALUE(n) case n: Video_Atari_GlyphValue(src, out, opacity, run->rows, sh, stride, maskStride, n); break
			switch (pens[j] & 15) {
			VALUE(0); VALUE(1); VALUE(2); VALUE(3); VALUE(4); VALUE(5); VALUE(6); VALUE(7);
			VALUE(8); VALUE(9); VALUE(10); VALUE(11); VALUE(12); VALUE(13); VALUE(14); VALUE(15);
			}
#undef VALUE
		}
	}
}

static void Video_Atari_DrawMonoGlyphs(const VideoAtariGlyphRun *run,
	uint16 *dst, uint16 stride, uint16 *masks, uint16 maskStride)
{
	uint16 patterns[8][4], i, j, y;
	assert(run->valueCount <= lengthof(patterns));
	for (j = 0; j < run->valueCount; j++) {
		uint8 colour = run->values[j].colour;
		for (y = 0; y < 4; y++) {
			uint16 x, nibble = 0;
			for (x = 0; x < 4; x++)
				nibble = (nibble << 1) | s_palette4BitDither.pens[y][x][colour];
			patterns[j][y] = nibble * 0x1111u;
			if (!s_monoWhiteIsOne) patterns[j][y] = ~patterns[j][y];
		}
	}
	for (i = 0; i < run->count; i++) {
		uint16 x = run->glyphs[i].x;
		for (j = 0; j < run->valueCount; j++) {
			const uint16 *src = run->glyphs[i].masks + run->values[j].offset;
			uint16 fill[4], p;
			for (p = 0; p < 4; p++) {
				fill[p] = patterns[j][p];
				if (x & 1) fill[p] = (fill[p] << 2) | (fill[p] >> 14);
			}
			for (y = 0; y < run->rows; y++) {
				uint32 bits = (uint32)src[y] << (16 - (x & 15));
				uint16 row = run->firstRow + y, part;
				if (bits == 0) continue;
				for (part = 0; part < 2; part++) {
					uint16 mask = part == 0 ? bits >> 16 : (uint16)bits;
					uint16 expanded[4], word, group = (x >> 4) + part;
					uint16 *out = dst + row * stride + group * 2;
					if (mask == 0) continue;
					Video_Atari_MonoMaskWords(mask, expanded);
					for (word = 0; word < 4; word++) {
						uint16 *d = out + (word / 2) * (stride / 2) + (word & 1);
						uint16 pattern = fill[(row * 2 + word / 2) & 3];
						*d = (*d & ~expanded[word]) | (pattern & expanded[word]);
					}
					if (masks != NULL) masks[row * maskStride + group] |= mask;
				}
			}
		}
	}
}

void Video_Atari_DrawPlanarGlyphs(const VideoAtariGlyphRun *run,
	uint16 *dst, uint16 stride, uint16 *masks, uint16 maskStride)
{
	assert(run != NULL && dst != NULL);
	if (Video_Atari_Mono()) Video_Atari_DrawMonoGlyphs(run, dst, stride, masks, maskStride);
	else Video_Atari_DrawColourGlyphs(run, dst, stride, masks, maskStride);
}

void Video_Atari_BlitChunkyTransparent(uint16 *dst, uint16 stride, uint16 dstGroups,
	const uint8 *src, uint16 srcStride, uint16 width, uint16 height, uint16 x)
{
	uint16 pixels[32 * 32 / 4], masks[32 * 2] = {0};
	uint16 rounded = (width + 15) & ~15, row, col;
	const AtariDitherSource source = {src, width, height, srcStride, 0, 0, 1, 1};
	assert(width != 0 && width <= 32 && height != 0 && height <= 32);
	for (row = 0; row < height; row++)
		for (col = 0; col < width; col++)
			if (src[row * srcStride + col] != 0)
				masks[row * (rounded / 16) + col / 16] |= 0x8000u >> (col & 15);
	Video_Atari_PreparePlanar(&source, NULL, pixels);
	Video_Atari_BlitPlanarSprite(dst, stride, dstGroups, pixels, masks, rounded, height, x);
}

void Video_Atari_MergePlanarRows(uint16 *dst, uint16 dstStride,
	const uint16 *src, uint16 srcStride, const uint16 *masks, uint16 maskStride,
	uint16 groups, uint16 height)
{
	uint16 row, group, word;
	assert(dst != NULL && src != NULL && masks != NULL && groups != 0 && height != 0);
	assert(groups * 4 <= dstStride && groups * 4 <= srcStride);
	assert(maskStride == 0 || maskStride >= groups);
	if (Video_Atari_Mono()) {
		for (row = 0; row < height; row++, dst += dstStride, src += srcStride, masks += maskStride) {
			for (group = 0; group < groups; group++) {
				uint16 opacity[4], mask = masks[group];
				if (mask == 0) continue;
				Video_Atari_MonoMaskWords(mask, opacity);
				for (word = 0; word < 4; word++) {
					uint16 *d = dst + group * 2 + (word / 2) * (dstStride / 2) + (word & 1);
					uint16 value = src[group * 2 + (word / 2) * (srcStride / 2) + (word & 1)];
					*d = (*d & ~opacity[word]) | (value & opacity[word]);
				}
			}
		}
		return;
	}
	for (row = 0; row < height; row++, dst += dstStride, src += srcStride, masks += maskStride) {
		for (group = 0; group < groups; group++) {
			uint16 mask = masks[group];
			if (mask == 0) continue;
			for (word = 0; word < 4; word++)
				dst[group * 4 + word] = (dst[group * 4 + word] & ~mask) | (src[group * 4 + word] & mask);
		}
	}
}

void Video_Atari_ShiftPlanarGroup(const uint16 *src, const uint16 *masks,
	uint16 height, uint16 shift, uint16 *dst)
{
	uint16 row, word;
	assert(src != NULL && masks != NULL && dst != NULL && height != 0 && shift < 16);
	if (Video_Atari_Mono()) {
		uint16 bits = shift * 2;
		for (row = 0; row < height; row++, src += 4, dst += 8) {
			uint16 opacity[4];
			Video_Atari_MonoMaskWords(masks[row], opacity);
			for (word = 0; word < 2; word++) {
				uint32 value = ((uint32)(src[word * 2] & opacity[word * 2]) << 16) |
					(src[word * 2 + 1] & opacity[word * 2 + 1]);
				uint32 first = value >> bits, second = bits == 0 ? 0 : value << (32 - bits);
				dst[word * 4] = first >> 16;
				dst[word * 4 + 1] = first;
				dst[word * 4 + 2] = second >> 16;
				dst[word * 4 + 3] = second;
			}
		}
		return;
	}
	for (row = 0; row < height; row++, src += 4, dst += 8) {
		for (word = 0; word < 4; word++) {
			uint16 value = src[word] & masks[row];
			dst[word] = value >> shift;
			dst[word + 4] = shift == 0 ? 0 : (uint16)(value << (16 - shift));
		}
	}
}

void Video_Atari_ExpandSpriteMasks(uint16 *pixels, uint16 *expanded,
	const uint16 *compact, uint16 width, uint16 height)
{
	uint16 count = width / 16 * height;
	if (Video_Atari_Mono()) {
		Video_Atari_MonoMaskBitmap(pixels, expanded, compact, width, height);
		return;
	}
	while (count-- != 0) {
		uint16 plane, mask = compact[count];
		for (plane = 0; plane < 4; plane++) {
			pixels[count * 4 + plane] &= mask;
			if (expanded != NULL) expanded[count * 4 + plane] = mask;
		}
	}
}

static void Video_Atari_UpdatePaletteLookups(int from, int length)
{
	int hi;
	int to = from + length;

	if (Video_Atari_Mono()) {
		for (hi = from; hi < to; hi++) {
			uint8 coverage = s_paletteMonoCoverage[hi];
			Video_Atari_SetMonoCoverage(&s_palette4BitDither, hi, coverage);
			Video_Atari_SetPackedMonoCoverage(&s_unitMonoPacked, hi,
				Video_Atari_ReducedMonoCoverage(coverage));
		}
		Video_Atari_MonoPreparePackedLookup(&s_paletteMonoPacked, &s_palette4BitDither,
			from, length, s_monoWhiteIsOne);
		return;
	}
	if (from == 0 && length == 256) s_palette4BitDither.flat = true;
	for (hi = from; hi < to; hi++)
		Video_Atari_DitherSetPen(&s_palette4BitDither, hi, s_palette4BitMap[hi]);
}

static inline uint8 Palette_FindClosestColor(uint8 r, uint8 g, uint8 b)
{
	uint8 i;
	uint32 ar, ag, ab, sum;
	uint8 bestItem = 0;
	uint32 bestSum = (uint32) - 1;
	const uint8 *pal = s_palette4BitPC;

	r &= ~3; g &= ~3; b &= ~3;
	for (i=0; i<16; i++, pal+=4)
	{
		ar = pal[0] & ~3;
		ag = pal[1] & ~3;
		ab = pal[2] & ~3;
		if (ar==r && ag==g && ab==b)
			return i;

		ar = (ar > r) ? ar - r : r - ar;
		ag = (ag > g) ? ag - g : g - ag;
		ab = (ab > b) ? ab - b : b - ab;

		ar = s_SquareTable[ar];
		ag = s_SquareTable[ag];
		ab = s_SquareTable[ab];
		sum = ((ar<<1)+ar) + ((ag<<2)+(ag<<1)) + (ab<<1);	/* (r*3 + g*6 + b*2) */

		if (sum < bestSum)
		{
			bestSum = sum;
			bestItem = i;
		}
	}
	return bestItem;
}

/* Current hw register brightness for each of the 16 fixed pens, in the
 * same 3-bit-per-channel 0-7 format Setcolor() uses (see the init loop in
 * Video_Init() this mirrors). Index = pen*3 + {r=0,g=1,b=2}. Kept in sync
 * whenever Video_Atari_TryPaletteFadeUniform() ramps the registers,
 * so a fade-out followed later by a fade-in always starts from wherever
 * the hardware registers actually are (normally either the full catalog
 * value or black, but never assumed - just tracked). */
static uint8 s_hwPalette[16*3];
static bool s_hwPaletteInit = false;

static inline uint16 Video_Atari_HwColorWord(uint8 r3, uint8 g3, uint8 b3)
{
	return ((uint16)r3 << 8) | ((uint16)g3 << 4) | b3;
}

/* Ramp the 16 hardware color registers, in-place, from wherever they
 * currently are (s_hwPalette) towards target[16*3] (also 0-7/channel),
 * using the same additive step-size/clamp-on-overshoot scheme as the
 * software 256-entry fade in GUI_SetPaletteAnimated() - just applied to
 * 48 bytes instead of 768, without changing the logical-to-hardware
 * pen mapping during the ramp. */
static void Video_Atari_HwPaletteRamp(const uint8 *target, int16 ticksOfAnimation)
{
	int16 highestDiff = 0;
	int16 diffPerTick, tickSlice, ticks;
	uint16 tickCurrent = 0;
	uint32 timerCurrent = g_timerSleep;
	int i;
	bool progress;

	for (i = 0; i < 16*3; i++) {
		int16 diff = (int16)target[i] - (int16)s_hwPalette[i];
		if (diff < 0) diff = -diff;
		if (diff > highestDiff) highestDiff = diff;
	}
	if (highestDiff == 0) return;

	ticks = ticksOfAnimation << 8;
	ticks /= highestDiff;
	tickSlice = ticks;
	diffPerTick = 1;
	while (diffPerTick <= highestDiff && ticks < (2 << 8)) {
		ticks += tickSlice;
		diffPerTick++;
	}

	for (;;) {
		progress = false;
		tickCurrent  += (uint16)ticks;
		timerCurrent += (uint32)(tickCurrent >> 8);
		tickCurrent  &= 0xFF;

		for (i = 0; i < 16; i++) {
			bool changed = false;
			int c;

			for (c = 0; c < 3; c++) {
				int16 goal = target[i*3+c];
				int16 cur = s_hwPalette[i*3+c];

				if (goal == cur) continue;
				progress = true;
				changed = true;
				if (goal > cur) {
					cur++;
					if (cur > goal) cur = goal;
				} else {
					cur--;
					if (cur < goal) cur = goal;
				}
				s_hwPalette[i*3+c] = (uint8)cur;
			}

			if (changed) {
				Setcolor(i, Video_Atari_HwColorWord(s_hwPalette[i*3+0], s_hwPalette[i*3+1], s_hwPalette[i*3+2]));
			}
		}

		if (!progress) break;
		while (g_timerSleep < timerCurrent) sleepIdle();
	}
}

/* Subtitle colours live at palette indices 215..220 (see the
 * memcpy(&g_palette_998A[215*3], s_palettePartCurrent, 18) calls in
 * cutscene.c). A "fade to white" deliberately leaves them alone, so they
 * are the one range that legitimately differs from an otherwise uniform
 * target. They are excluded from the uniformity test below. */
#define PALETTE_SUBTITLE_FIRST	215
#define PALETTE_SUBTITLE_LAST	220

/* Return the single 0-63 intensity every channel of every (considered)
 * palette entry holds, or -1 if the palette is not uniform.
 *
 * "Considered" excludes two ranges:
 *  - the subtitle pens (see above),
 *  - index 0, which is allowed to stay black while the rest goes to some
 *    other uniform value (a fade to white memsets from index 1 upwards
 *    and never touches index 0).
 *
 * Both exclusions make this an approximation rather than an identity: the
 * register-only ramp drives *all 16* pens to the uniform value, so pixels
 * whose chunky value is 0 (or a subtitle index) end up at the uniform
 * brightness too instead of keeping their own colour. For a fade to black
 * that is exact (they were black anyway). For a fade to white it means the
 * flash is fully white rather than white-with-black-holes, which is the
 * intended effect of the flash regardless. Revisit if a future fade target
 * needs those pens preserved. */
static int Video_Atari_PaletteUniformValue(const uint8 *pal)
{
	int i, c;
	int value = -1;

	/* establish (and verify) the uniform value over indices 1..255 */
	for (i = 1; i < 256; i++) {
		if (i >= PALETTE_SUBTITLE_FIRST && i <= PALETTE_SUBTITLE_LAST) continue;

		for (c = 0; c < 3; c++) {
			uint8 v = pal[i*3+c];

			if (value < 0) value = v;
			else if (v != value) return -1;
		}
	}

	/* index 0 may hold the uniform value or stay black */
	for (c = 0; c < 3; c++) {
		if (pal[c] != value && pal[c] != 0) return -1;
	}

	return value;
}

/**
 * Fast path for GUI_SetPaletteAnimated(). See the comment above the
 * prototype in video.h for the full rationale. "data" is the 256*3 array
 * of the currently active (on-screen) logical palette, "palette" is the
 * 256*3 fade target - exactly what GUI_SetPaletteAnimated() already has.
 */
bool Video_Atari_TryPaletteFadeUniform(uint8 *data, const uint8 *palette, int16 ticksOfAnimation)
{
	int toUniform, fromUniform;
	int i;
	uint8 targetHw[16*3];

	if (Video_Atari_Mono()) {
		memcpy(data, palette, 256 * 3);
		/* Do not replace native battlefield pixels with a stale chunky repaint. */
		Video_SetPalette(data, 0, 256);
		return true;
	}

	if (!s_hwPaletteInit) {
		/* first call: derive the currently-programmed register values from
		 * the fixed master palette, same formula as the Video_Init() setup
		 * loop, so a fade started before any prior fade ever ran still has
		 * a correct starting point to ramp from/to. */
		for (i = 0; i < 16; i++) {
			s_hwPalette[i*3+0] = (s_palette4BitPC[i*4+0] >> 3) & 7;
			s_hwPalette[i*3+1] = (s_palette4BitPC[i*4+1] >> 3) & 7;
			s_hwPalette[i*3+2] = (s_palette4BitPC[i*4+2] >> 3) & 7;
		}
		s_hwPaletteInit = true;
	}

	toUniform   = Video_Atari_PaletteUniformValue(palette);
	fromUniform = Video_Atari_PaletteUniformValue(data);

#ifdef PALETTE_FADE_DEBUG
	Warning("PaletteFade: toUniform=%d fromUniform=%d ticks=%d hw=%02x%02x%02x..\n",
	        toUniform, fromUniform, ticksOfAnimation,
	        s_hwPalette[0], s_hwPalette[1], s_hwPalette[2]);
#endif

	if (toUniform < 0 && fromUniform < 0) {
		/* Neither end of the fade is a uniform colour - falls back to the
		 * original software-only quantize path below, which only ever
		 * rebuilds the chunky->pen LUT and never touches Setcolor(). That
		 * path implicitly
		 * assumes the 16 hardware registers already sit at the fixed
		 * catalog brightness (their historical, pre-hw-fade invariant).
		 * If a previous uniform-target fade-out (or an Options-menu shade)
		 * left the registers anywhere else - e.g. ramped down to literal
		 * black - restore them to the catalog now, instantly, so the
		 * fallback quantize path still displays correctly. */
		uint8 catalogHw[16*3];
		bool atCatalog = true;

		for (i = 0; i < 16; i++) {
			catalogHw[i*3+0] = (s_palette4BitPC[i*4+0] >> 3) & 7;
			catalogHw[i*3+1] = (s_palette4BitPC[i*4+1] >> 3) & 7;
			catalogHw[i*3+2] = (s_palette4BitPC[i*4+2] >> 3) & 7;
		}
		for (i = 0; i < 16*3 && atCatalog; i++) {
			if (s_hwPalette[i] != catalogHw[i]) atCatalog = false;
		}
		if (!atCatalog) {
#ifdef PALETTE_FADE_DEBUG
			Warning("PaletteFade: restoring hw registers to catalog (fallback path)\n");
#endif
			memcpy(s_hwPalette, catalogHw, sizeof(s_hwPalette));
			for (i = 0; i < 16; i++) {
				Setcolor(i, Video_Atari_HwColorWord(s_hwPalette[i*3+0], s_hwPalette[i*3+1], s_hwPalette[i*3+2]));
			}
		}
		return false;	/* not a uniform-target fade */
	}

	if (toUniform >= 0) {
		/* Fade out to a uniform colour (black, white, ...): the on-screen
		 * pen mapping already matches "data" (the current, still
		 * fully-lit picture) and stays valid - every pixel simply ends up
		 * showing the same colour, so there is nothing to re-quantize.
		 * Just ramp all 16 registers to that one intensity. The logical
		 * palette is 6-bit per channel, the ST/STE registers are 3-bit. */
		uint8 v3 = (uint8)((toUniform >> 3) & 7);

		memset(targetHw, v3, sizeof(targetHw));
		Video_Atari_HwPaletteRamp(targetHw, ticksOfAnimation);
	} else {
		/* Fade in from a uniform colour to a real picture: quantize/rebuild
		 * once, up front, against the *target* (final, fully-lit) palette
		 * so every chunky pixel already shows the right pen index
		 * throughout the whole fade; then ramp the registers to the fixed
		 * catalog. Until the ramp moves them, all 16 registers still hold
		 * the uniform value, so the screen keeps showing that flat colour
		 * and the new picture is revealed by the ramp rather than
		 * appearing abruptly. */
		for (i = 0; i < 16; i++) {
			targetHw[i*3+0] = (s_palette4BitPC[i*4+0] >> 3) & 7;
			targetHw[i*3+1] = (s_palette4BitPC[i*4+1] >> 3) & 7;
			targetHw[i*3+2] = (s_palette4BitPC[i*4+2] >> 3) & 7;
		}
		{
			union { const uint8 *cp; void *p; } u;
			u.cp = palette;
			Video_SetPalette(u.p, 0, 256);
		}
		/* fromUniform is guaranteed >= 0 here (the both-negative case
		 * already returned above) - registers should already be at that
		 * uniform intensity from the preceding fade-out, but ramp from
		 * wherever s_hwPalette actually is rather than assuming. */
		Video_Atari_HwPaletteRamp(targetHw, ticksOfAnimation);
	}

	memcpy(data, palette, 256*3);
	return true;
}

/* Backup of the 16 hw registers' pre-shade values, saved by
 * Video_Atari_ShadeHwPalette(true) and restored verbatim by
 * Video_Atari_ShadeHwPalette(false) - restoring from this exact backup
 * (rather than adding back to clamped values) preserves the original
 * zero components, matching the original code's pattern of restoring
 * from its own g_palette_998A backup rather than re-deriving it. */
static uint8 s_hwPaletteShadeBackup[16*3];

void Video_Atari_ShadeHwPalette(bool shade)
{
	int i;

	/* OPTIONS dimming is intentionally disabled in both ST backends. */
	if (s_machine_type == MCH_ST || s_machine_type == MCH_STE || s_machine_type == MCH_MEGA_STE) return;
	if (!s_hwPaletteInit) {
		for (i = 0; i < 16; i++) {
			s_hwPalette[i*3+0] = (s_palette4BitPC[i*4+0] >> 3) & 7;
			s_hwPalette[i*3+1] = (s_palette4BitPC[i*4+1] >> 3) & 7;
			s_hwPalette[i*3+2] = (s_palette4BitPC[i*4+2] >> 3) & 7;
		}
		s_hwPaletteInit = true;
	}

	if (shade) {
		memcpy(s_hwPaletteShadeBackup, s_hwPalette, sizeof(s_hwPalette));
		for (i = 0; i < 16*3; i++) {
			if (s_hwPalette[i] > 0) s_hwPalette[i]--;
		}
	} else {
		memcpy(s_hwPalette, s_hwPaletteShadeBackup, sizeof(s_hwPalette));
	}

	for (i = 0; i < 16; i++) {
		Setcolor(i, Video_Atari_HwColorWord(s_hwPalette[i*3+0], s_hwPalette[i*3+1], s_hwPalette[i*3+2]));
	}
}


/* mouse : */
static int s_mouse_x = SCREEN_WIDTH/2;
static int s_mouse_x_min = 0;
static int s_mouse_x_max = SCREEN_WIDTH-1;
static int s_mouse_y = SCREEN_HEIGHT/2;
static int s_mouse_y_min = 0;
static int s_mouse_y_max = SCREEN_HEIGHT-1;
static bool s_mouse_left_btn = false;
static bool s_mouse_right_btn = true;
static volatile bool s_mouse_state_changed = false;

/**
 * Mouse interrupt Handler
 *
 * Receive and process Mouse IKBD packets.
 */
void Mouse_Handler(char * ikbd_packet)
{
	/* The relative mouse position record is a three byte record of the form
	(regardless of keyboard mode):
    %111110xy           ; mouse position record flag
                        ; where y is the right button state
                        ; and x is the left button state
    X                   ; delta x as twos complement integer
    Y                   ; delta y as twos complement integer
	*/
	s_mouse_x += (int)ikbd_packet[1];
	s_mouse_y += (int)ikbd_packet[2];
	if(s_mouse_x < s_mouse_x_min) {
		s_mouse_x = s_mouse_x_min;
	} else if(s_mouse_x > s_mouse_x_max) {
		s_mouse_x = s_mouse_x_max;
	}
	if(s_mouse_y < s_mouse_y_min) {
		s_mouse_y = s_mouse_y_min;
	} else if(s_mouse_y > s_mouse_y_max) {
		s_mouse_y = s_mouse_y_max;
	}
#if 0
	Mouse_EventHandler(s_mouse_x, s_mouse_y,
	                   ikbd_packet[0]&2 /*left*/, ikbd_packet[0]&1 /*right*/);
#endif
	s_mouse_left_btn = ikbd_packet[0]&2;
	s_mouse_right_btn = ikbd_packet[0]&1;
	s_mouse_state_changed = true;
}

static void Detect_Machine(void)
{
	long machine_type;
	/* Get machine type with '_MCH' cookie */
	if(Getcookie(C__MCH, &machine_type) == C_FOUND) {
		switch(machine_type >> 16) {
		case 0:
			s_machine_type = MCH_ST;
			break;
		case 1:
			/* the Mega STE has $0010 in the low word of the cookie */
			s_machine_type = ((machine_type & 0xFFFF) == 0x0010) ? MCH_MEGA_STE : MCH_STE;
			break;
		case 2:
			s_machine_type = MCH_TT;
			break;
		case 3:
			s_machine_type = MCH_FALCON;
			break;
		default:
			s_machine_type = MCH_OTHER;
		}
		Debug("_MCH cookie value : %08lx\n", machine_type);
	} else {
		/* Failed to get Cookie => Plain old ST ? */
		s_machine_type = MCH_ST;
		Warning("Failed to get _MCH cookie\n");
	}
}

/* Supervisor-only: switch a Mega STE to 16MHz with the cache on. */
static void MegaSTE_SpeedUp(void)
{
	s_savedCpuSpeed = *MEGASTE_CPUCTL;
	*MEGASTE_CPUCTL = 0x03;	/* 16MHz + cache */
}

/* Supervisor-only: put back what MegaSTE_SpeedUp() found. */
static void MegaSTE_SpeedRestore(void)
{
	*MEGASTE_CPUCTL = (uint8)s_savedCpuSpeed;
}

/* Supervisor callback: set the base reloaded by the shifter each frame.
 * The explosion caller supplies the delay, not this register setter. */
static void Video_ST_SetBase(void)
{
	uint32 base = s_stScreenBase;

	*VIDEO_BASE_HIGH = (uint8)(base >> 16);
	*VIDEO_BASE_MID  = (uint8)(base >> 8);
	if (s_machine_type == MCH_STE || s_machine_type == MCH_MEGA_STE) {
		*VIDEO_BASE_LOW = (uint8)base;
	}
}

static bool Video_Atari_BlitterDestinationFits(uint32 base)
{
	/* Include the address advanced beyond the last row, not just written pixels. */
	return base != 0 && (base & 1) == 0 &&
	    (base >> 16) == ((base + (SCREEN_HEIGHT + 1) * ST_PLANAR_LINE_BYTES - 1) >> 16);
}

static void Video_Atari_InitBlitterDestination(void)
{
	uint32 base = (uint32)(size_t)s_planarBase;

	s_blitterDestinationWord = s_viewportBlitter && Video_Atari_BlitterDestinationFits(base);
	if (s_blitterDestinationWord) {
		while ((*BLITTER_CTRL & 0x80) != 0) {}
		*BLITTER_DST_ADDR_HIGH = base >> 16;
	}
	Video_Atari_ConfigureBlitterDestination(s_blitterDestinationWord, Video_Atari_Mono());
}

/**
 * Initialize the video driver.
 */
static void Video_Atari_CursorInitStorage(void);

bool Video_Init(int screen_magnification, VideoScaleFilter filter)
{
	VARIABLE_NOT_USED(filter);
	VARIABLE_NOT_USED(screen_magnification);
	int i;

	s_blitterHalftonePattern = NULL;
	Video_Atari_CursorInitStorage();

	s_framebuffer = calloc(1, SCREEN_WIDTH * (SCREEN_HEIGHT + 4));
	if (s_framebuffer == NULL) {
		Error("Failed to allocate %d bytes.\n", SCREEN_WIDTH * (SCREEN_HEIGHT + 4));
		return false;
	}

	(void)Cconws("Video_Init()\r\n");
	if(s_machine_type == MCH_UNKNOWN) Detect_Machine();
	if (IniFile_GetInteger("viewport_blitter", 0) != 0) {
		s_viewportBlitter = (s_machine_type == MCH_ST || s_machine_type == MCH_STE ||
		    s_machine_type == MCH_MEGA_STE) && (Blitmode(-1) & 2) != 0;
		if (!s_viewportBlitter) {
			Warning("viewport_blitter requested but no ST/STE BLiTTER is available; using CPU renderer\n");
		} else {
			Debug("Viewport publication: unshifted sprite BLiTTER experiment\n");
		}
	}

	if(s_machine_type == MCH_MEGA_STE && s_savedCpuSpeed < 0) {
		Atari_SupervisorExec(MegaSTE_SpeedUp);
		Debug("Mega STE : 16MHz + cache enabled (was $%02x)\n", s_savedCpuSpeed);
	}

	(void)Cursconf(0, 0);	/* switch cursor Off */
	g_consoleActive = false;

	if(s_machine_type == MCH_FALCON) {
		short newMode;
		long vSize, saddr;
		s_savedMode = VsetMode(VM_INQUIRE);	/* get current mode */
		/*  8 planes 256 colours + 40 columns + double line (if VGA) */
		newMode = (s_savedMode & (VGA | PAL)) | BPS8 | COL40 | ((s_savedMode & VGA) ? VERTFLAG : 0);
		vSize = VgetSize(newMode);
		s_center_image_offset = (vSize-(SCREEN_WIDTH*SCREEN_HEIGHT)) >> 1;
		Debug("allocate %ld + %d bytes for mode $%04x\n", vSize, 4*SCREEN_WIDTH, (int)newMode);
		saddr = Srealloc(vSize + 4*SCREEN_WIDTH);	/* allocate 4 lines more for explosions */
#if 0
		(void)VsetMode((s_savedMode & (VGA | PAL)) | BPS8 | COL40 | ((s_savedMode & VGA) ? VERTFLAG : 0));
#else
		VsetScreen(saddr, saddr, 3, newMode);
#endif
		VgetRGB(0, 256, s_paletteBackup);	/* backup palette */
	} else if(s_machine_type == MCH_TT) {
		/* set TT 8bps video mode */
		s_savedMode = EgetShift();
		EsetShift(TT_LOW); /* set TT 8bps video mode */
		EgetPalette(0, 256, s_paletteBackup);	/* backup palette */
		s_center_image_offset = 320*40;
	} else if (s_machine_type == MCH_ST || s_machine_type == MCH_STE || s_machine_type == MCH_MEGA_STE) {
		s_savedMode = Getrez();
		g_videoAtariMono = s_savedMode == 2;
		s_planarBackend = Video_Atari_Mono() ? &s_monoBackend : &s_colourBackend;
		Video_Atari_InitTileCursorBackend();
		s_savedLogBase = Logbase();
		s_savedPhysBase = Physbase();
		if (!Video_Atari_Mono()) Setscreen(-1, -1, 0);
		else s_monoWhiteIsOne = (Setcolor(0, -1) & 1) == 0;
		s_planarBase = (uint8 *)Logbase() + s_center_image_offset;
		s_blitterTileSetup = false;
		Atari_SupervisorExec(Video_Atari_InitBlitterDestination);
		Warning("ST/STE planar screen base: $%08lx (Logbase)\n", (unsigned long)Logbase());
		Debug("BLiTTER destination: %s writes\n", s_blitterDestinationWord ? "low-word" : "full-address");
		/* set and backup system palette */
		for (i=0; !Video_Atari_Mono() && i<16; i++) {
			s_paletteBackup[i] = Setcolor(i, ((s_palette4BitPC[i*4+0] << 5) & 0x0700) | ((s_palette4BitPC[i*4+1] << 1) & 0x0070) | ((s_palette4BitPC[i*4+2]>>3) & 0x007));
		}
		/* the mouse cursor is composited straight into the planar screen */
		s_curDirect = true;
		if (Video_Atari_Mono()) {
			Video_Atari_UpdatePaletteLookups(0, 256);
			Warning("ST-High mono backend: 640x400, native 1-plane assets, white bit %u\n", s_monoWhiteIsOne);
		}
	} else {
		Error("Unsupported machine type.\nPlease contact us if you know how to initialize a 256 color mode on your machine.\n");
		return false;
	}

	/* build square table */
	for (i=0; i<256; i++)
		s_SquareTable[i] = (uint16)(i * i);

	Debug("old video mode = $%04hx\n", s_savedMode);
	Debug("Physbase() = $%08x  Logbase() = $%08x\n", Physbase(), Logbase());
	/* install IKBD handler for mouse and keyboard IRQ */
	Atari_SupervisorExec(install_ikbd_handler);
	return true;
}

/**
 * Uninitialize the video driver.
 */
void Video_Uninit(void)
{
	Video_Atari_DisplayListFree();
	(void)Cursconf(1, 0);	/* switch cursor On */
	if(s_machine_type == MCH_FALCON) {
		long saddr;
		VsetRGB(0, 256, s_paletteBackup);
#if 0
		(void)VsetMode(s_savedMode);
#else
		saddr = Srealloc(VgetSize(s_savedMode));
		VsetScreen(saddr, saddr, 3, s_savedMode);
#endif
	} else if(s_machine_type == MCH_TT) {
		EsetPalette(0, 256, s_paletteBackup);
		(void)EsetShift(s_savedMode);
	} else if (s_machine_type == MCH_ST || s_machine_type == MCH_STE || s_machine_type == MCH_MEGA_STE) {
		int i;
		for (i=0; !Video_Atari_Mono() && i<16; i++) {
			int oldColor = Setcolor(i, s_paletteBackup[i]);
			VARIABLE_NOT_USED(oldColor);
		}
		if (!Video_Atari_Mono()) Setscreen(s_savedLogBase, s_savedPhysBase, s_savedMode);
		else {
			s_stScreenBase = (uint32)(size_t)s_savedPhysBase;
			Atari_SupervisorExec(Video_ST_SetBase);
		}
		s_planarBase = NULL;
		s_blitterDestinationWord = false;
		Video_Atari_ConfigureBlitterDestination(false, false);
	}
	Atari_SupervisorExec(uninstall_ikbd_handler);
	if(s_savedCpuSpeed >= 0) {
		Atari_SupervisorExec(MegaSTE_SpeedRestore);
		s_savedCpuSpeed = -1;
	}
	g_consoleActive = true;
	free(s_framebuffer);
	s_framebuffer = NULL;
	s_viewportBlitter = false;
}

void Video_SwitchFPSDisplay(uint8 key)
{
	if (Video_Atari_Mono()) return;
	Debug("Video_SwitchFPSDisplay key=$%02x\n", key);
	if(key & 0x80) {	/* key UP */
		s_showFPS = !s_showFPS;
		s_fpsReset = true;
	}
}

static uint32 s_fps_chars[5];

static void Video_Atari_DrawChar(uint16 x, uint8 digit)
{
	static const uint8 fontdigits[10] = {0167,044,0135,0155,056,0153,0173,045,0177,0157};
	static const uint8 fonttestsegments[15] = {03,01,05, 02,0,04, 032,010,054, 020,0,040, 0120,0100,0140};
	static const uint8 slash[5] = {01, 01, 02, 04, 04};
	uint8 segments;
	int i, line;
	uint32 pixels = 0;

	if (digit == 10) {
		for (line = 0; line < 5; line++) {
			s_fps_chars[line] |= (uint32)(slash[line] << 1) << (320-4-x);
		}
		return;
	}

	segments = fontdigits[digit];
	for (i = 0, line = 0; i<15; i++) {
		pixels <<= 1;
		if (segments & fonttestsegments[i])	pixels++;
		if((i % 3) == 2) {
			pixels <<= 1;
			s_fps_chars[line] |= pixels << (320-4-x);
			line++;
			pixels = 0;
		}
	}
}

static uint16 Video_Atari_DrawFPSNumber(uint16 x, uint32 fps)
{
	do {
		Video_Atari_DrawChar(x, fps % 10);
		fps /= 10;
		x -= 4;
	} while (fps != 0);

	return x;
}

static void Video_Atari_UpdateFPS(void)
{
	static uint32 previousTime;
	static uint32 updates;
	static uint32 averagePreviousTime;
	static uint32 averageUpdates;
	static uint32 averageFPS;
	uint32 now = Timer_GetTime();
	uint32 elapsed;
	uint32 fps;
	uint16 x;

	if (s_fpsReset) {
		s_fpsReset = false;
		previousTime = now;
		averagePreviousTime = now;
		updates = 0;
		averageUpdates = 0;
		averageFPS = 0;
		fps = 0;
	} else {
		updates++;
		averageUpdates++;

		elapsed = now - averagePreviousTime;
		if (elapsed >= 10000) {
			averageFPS = averageUpdates * 1000 / elapsed;
			averagePreviousTime = now;
			averageUpdates = 0;
		}

		elapsed = now - previousTime;
		if (elapsed < 1000) return;
		fps = updates * 1000 / elapsed;
		previousTime = now;
		updates = 0;
	}

	memset(s_fps_chars, 0, sizeof(s_fps_chars));
	x = 320 - 4;
	x = Video_Atari_DrawFPSNumber(x, averageFPS);
	Video_Atari_DrawChar(x, 10);
	Video_Atari_DrawFPSNumber(x - 4, fps);
}

/* ------------------------------------------------------------------------
 * Direct-to-planar mouse cursor (ST/STE only)
 *
 * The mouse cursor is by far the biggest producer of dirty blocks: every
 * move dirties the chunky framebuffer twice (the sprite draw and the
 * background restore), and each 16x16 cursor covers up to 32 blocks of
 * chunky-to-planar work at ~630 cycles a block.
 *
 * Planar writers maintain a cursor-free backup and synchronously composite
 * the mouse over changed groups. Video_Tick only reconciles requested cursor
 * position, appearance and visibility with the cursor actually drawn.
 *
 * The bitplane form of the sprite only depends on its content and on the
 * horizontal position modulo 16, so it is cached and rebuilt only when one
 * of those (or the palette) actually changes.
 * ------------------------------------------------------------------------ */

#define CURSOR_MAX_H      VIDEO_ATARI_CURSOR_MAX_HEIGHT
#define CURSOR_MAX_GROUPS (VIDEO_ATARI_CURSOR_MAX_WIDTH / 16)

static bool s_curVisible = false;	/* the game wants a cursor displayed */
static bool s_curDrawn = false;		/* the cursor is currently in the planar screen */
static bool s_curDirty = true;		/* position or content changed */

static uint16 s_curY, s_curW, s_curH;
static uint16 s_curGroup, s_curGroups, s_curShift;

/* geometry of the composite that is currently on screen, needed to undo it */
static uint8 *s_curDrawnBase = NULL;
static uint16 s_curDrawnY, s_curDrawnH, s_curDrawnGroup, s_curDrawnGroups;
uint16 s_curViewportTiles[10];	/* read by atari_viewport_tile.s */

/* cursor.s moves longs, but the AOUT object format only aligns statics to 2:
 * these buffers live in s_curStorage and are aligned by Video_Atari_CursorInitStorage(). */
typedef uint16 CursorPlaneRow[CURSOR_MAX_GROUPS * 4];
static uint16 s_curStorage[3 * CURSOR_MAX_H * CURSOR_MAX_GROUPS * 4 + 2];
static CursorPlaneRow *s_curData, *s_curSave, *s_curDrawnData;
static uint16 s_curMask[CURSOR_MAX_H][CURSOR_MAX_GROUPS];
/* Requested icon caches can be rebuilt before the old cursor moves. Keep
 * the actual on-screen pixels/mask independent of those cache lifetimes. */
static uint16 s_curDrawnMask[CURSOR_MAX_H][CURSOR_MAX_GROUPS];

static void Video_Atari_CursorInitStorage(void)
{
	uint16 *p = s_curStorage;

	if (((size_t)p & 3) != 0) p++;
	s_curData = (CursorPlaneRow *)p;
	s_curSave = s_curData + CURSOR_MAX_H;
	s_curDrawnData = s_curSave + CURSOR_MAX_H;
}

/* cache key of the currently built bitplane form (slow/edge path, see
 * Video_Atari_CursorPrepare() below) */
static const void *s_curKeySprite = NULL;
static uint16 s_curKeyW = 0, s_curKeyH = 0, s_curKeyShift = 0, s_curKeyPal = 0xffff;
static int16 s_curKeyDx = 0, s_curKeyDy = 0;
static uint16 s_paletteGeneration = 0;
static uint16 s_curSelectedIcon = 0xffff;
static int16 s_curIconLeft, s_curIconTop;

/* Selected bitplane source for the next Video_Atari_CursorDraw() call: a
 * flat, row-major view (s_curH rows of s_curDrawStride*4/ s_curDrawStride
 * words for data/mask respectively) so that both the fixed-size slow-path
 * buffers above (stride == CURSOR_MAX_GROUPS) and the per-icon, tightly
 * sized pre-shift cache below (stride == that icon/phase's own group
 * count) can be composited through the same code. */
static const uint16 *s_curDrawData = NULL;
static const uint16 *s_curDrawMask = NULL;
static uint16 s_curDrawStride = CURSOR_MAX_GROUPS;
static bool s_curPointer, s_curDrawnPointer, s_curKeyPointer;

static uint8 Video_Atari_CursorPen(uint8 colour, bool pointer)
{
	/* ID 0: retain the white/light-grey fill; make all shading a black outline. */
	if (pointer) return colour == 232 || colour == 233 ? 4 : 0;
	return s_palette4BitMap[colour];
}

/* ------------------------------------------------------------------------
 * Cursor icon preload -- persistent, pre-shifted bitplane cache
 *
 * MOUSE.SHP only ever contains a handful of distinct icons (the pointer,
 * the four scroll arrows and the targeting cross-hair -- MOUSE_ICON_COUNT
 * below must track Sprites_Init()'s `Sprites_Load("MOUSE.SHP", NULL, 7)`).
 * All of them are tiny and every one of them is shown repeatedly for the
 * entire length of a game session, so instead of rebuilding the bitplane
 * form of whichever icon is current every time its horizontal sub-16px
 * phase changes (i.e. on almost every mouse movement, see the history in
 * ATARI_C2P_DIRTY_RUNS.md), each icon is decoded and transposed for all 16
 * possible phases exactly once -- at load time, right after MOUSE.SHP is
 * read in Sprites_Init(), and again (for all icons at once) on the rare
 * event of a palette-quantization change. Normal cursor movement, even
 * across 16px group boundaries, then costs nothing but picking the right
 * pointer out of this table: no chunky render, no per-pixel transpose.
 *
 * Sizing is per icon/phase (not the worst-case CURSOR_MAX_H x
 * CURSOR_MAX_GROUPS used by the slow path), because real cursor icons are
 * far smaller than that: a handful of KB total for all 7 icons x 16
 * phases, instead of the ~430KB a naive CURSOR_MAX_H x CURSOR_MAX_GROUPS x
 * 16 x 7 static table would cost. */

#define MOUSE_ICON_COUNT  7
#define CURSOR_PHASES     16

typedef struct {
	bool valid;
	uint16 w, h;			/* size of the tight (non-transparent-only)
	                                 * bounding box, in pixels -- NOT the
	                                 * sprite's nominal/declared size, see
	                                 * Video_Atari_CursorPreloadIcons() */
	uint16 bboxX, bboxY;		/* offset of that tight box within the
	                                 * sprite's nominal top-left/hotspot
	                                 * origin; added to the caller's (left,
	                                 * top) before any table lookup */
	uint16 groups[CURSOR_PHASES];	/* groups needed for that phase (also the
	                                 * per-icon/phase buffers' row stride) */
	uint16 *data[CURSOR_PHASES];	/* h rows of groups[phase]*4 words each */
	uint16 *mask[CURSOR_PHASES];	/* h rows of groups[phase] words each */
} CursorIcon;

static CursorIcon s_curIcon[MOUSE_ICON_COUNT];
static uint16 s_curIconPaletteGeneration = 0xffff;

#if !defined(__m68k__)
bool Video_Atari_CursorDirect(void)
{
	return s_curDirect;
}
#endif

/**
 * Record the cursor geometry for this frame.
 * @return true when the caller must render the sprite and call
 *         Video_Atari_CursorBuild(), false when the cached form still applies.
 */
bool Video_Atari_CursorPrepare(const void *sprite, uint16 x, uint16 y,
                               uint16 w, uint16 h, int16 dx, int16 dy)
{
	uint16 shift = x & 0xf;
	uint16 groups;
	s_curSelectedIcon = 0xffff;
	s_curPointer = g_mouseSpriteIconIndex == 0;

	if (h > CURSOR_MAX_H) h = CURSOR_MAX_H;
	groups = (uint16)((shift + w + 0xf) >> 4);
	if (groups > CURSOR_MAX_GROUPS) {
		groups = CURSOR_MAX_GROUPS;
		w = (uint16)((groups << 4) - shift);
	}

	s_curY = y;
	s_curW = w;
	s_curH = h;
	s_curShift = shift;
	s_curGroup = (uint16)(x >> 4);
	s_curGroups = groups;
	s_curVisible = true;
	s_curDirty = true;

	s_curDrawData = &s_curData[0][0];
	s_curDrawMask = &s_curMask[0][0];
	s_curDrawStride = CURSOR_MAX_GROUPS;

	if (sprite == s_curKeySprite && w == s_curKeyW && h == s_curKeyH
	 && shift == s_curKeyShift && dx == s_curKeyDx && dy == s_curKeyDy
	 && s_paletteGeneration == s_curKeyPal && s_curPointer == s_curKeyPointer) return false;

	s_curKeySprite = sprite;
	s_curKeyW = w;
	s_curKeyH = h;
	s_curKeyShift = shift;
	s_curKeyDx = dx;
	s_curKeyDy = dy;
	s_curKeyPal = s_paletteGeneration;
	s_curKeyPointer = s_curPointer;
	return true;
}

/**
 * Convert the freshly rendered cursor to bitplanes.
 * @param chunky Top left of a private chunky buffer cleared to 0 before drawing, so
 *               that colour 0 marks the transparent pixels.
 * @param stride Bytes between source rows.
 */
void Video_Atari_CursorBuild(const uint8 *chunky, uint16 stride)
{
	uint16 line, g, px;

	for (line = 0; line < s_curH; line++) {
		uint16 *data = s_curData[line];
		uint16 *mask = s_curMask[line];

		for (g = 0; g < s_curGroups; g++) {
			mask[g] = 0;
			data[(g << 2) + 0] = 0;
			data[(g << 2) + 1] = 0;
			data[(g << 2) + 2] = 0;
			data[(g << 2) + 3] = 0;
		}
		for (px = 0; px < s_curW; px++) {
			uint8 colour = chunky[px];

			if (colour != 0) {
				uint16 pos = (uint16)(px + s_curShift);
				uint16 bit = (uint16)(0x8000 >> (pos & 0xf));
				uint16 *d = data + ((pos >> 4) << 2);
				uint8 pen = Video_Atari_CursorPen(colour, s_curPointer);

				mask[pos >> 4] |= bit;
				if (Video_Atari_Mono()) {
					uint16 words[4], index = (pos & 15) / 8, shift = 14 - (pos & 7) * 2;
					Video_Atari_MonoPenWords(pen, px, line, words);
					d[index] |= (words[0] >> 14) << shift;
					d[index + 2] |= (words[2] >> 14) << shift;
					continue;
				}
				if (pen & 1) d[0] |= bit;
				if (pen & 2) d[1] |= bit;
				if (pen & 4) d[2] |= bit;
				if (pen & 8) d[3] |= bit;
			}
		}
		chunky += stride;
	}
}

/**
 * Build one of the 16 pre-shifted phase variants of `icon` from a single
 * canonical (unshifted) chunky render of that icon -- see the "Cursor icon
 * preload" block comment above for why this is mathematically sufficient
 * to cover every on-screen horizontal sub-position. Otherwise identical to
 * Video_Atari_CursorBuild() above, just writing into freshly malloc()'d,
 * exactly-sized per-phase buffers instead of the shared, worst-case-sized
 * slow-path arrays.
 * @return false if malloc() failed (icon left invalid for this phase).
 */
static bool Video_Atari_CursorBuildPhase(CursorIcon *icon, uint16 phase, const uint8 *chunky,
                                        uint16 stride, bool pointer)
{
	uint16 groups = (uint16)((phase + icon->w + 0xf) >> 4);
	uint16 line, g, px;
	uint16 *data, *mask;

	icon->groups[phase] = groups;
	data = (uint16 *)malloc(sizeof(uint16) * (size_t)icon->h * groups * 4);
	mask = (uint16 *)malloc(sizeof(uint16) * (size_t)icon->h * groups);
	icon->data[phase] = data;
	icon->mask[phase] = mask;
	/* cursor.s reads the data in longs */
	if (data == NULL || mask == NULL || (((size_t)data) & 3) != 0) return false;

	for (line = 0; line < icon->h; line++) {
		uint16 *d = data + (uint32)line * groups * 4;
		uint16 *m = mask + (uint32)line * groups;

		for (g = 0; g < groups; g++) {
			m[g] = 0;
			d[(g << 2) + 0] = 0;
			d[(g << 2) + 1] = 0;
			d[(g << 2) + 2] = 0;
			d[(g << 2) + 3] = 0;
		}
		for (px = 0; px < icon->w; px++) {
			uint8 colour = chunky[px];

			if (colour != 0) {
				uint16 pos = (uint16)(px + phase);
				uint16 bit = (uint16)(0x8000 >> (pos & 0xf));
				uint16 *dd = d + ((pos >> 4) << 2);
				uint8 pen = Video_Atari_CursorPen(colour, pointer);

				m[pos >> 4] |= bit;
				if (Video_Atari_Mono()) {
					uint16 words[4], index = (pos & 15) / 8, shift = 14 - (pos & 7) * 2;
					Video_Atari_MonoPenWords(pen, px, line, words);
					dd[index] |= (words[0] >> 14) << shift;
					dd[index + 2] |= (words[2] >> 14) << shift;
					continue;
				}
				if (pen & 1) dd[0] |= bit;
				if (pen & 2) dd[1] |= bit;
				if (pen & 4) dd[2] |= bit;
				if (pen & 8) dd[3] |= bit;
			}
		}
		chunky += stride;
	}
	return true;
}

/** Free every phase buffer of one icon and mark it invalid. */
static void Video_Atari_CursorFreeIcon(CursorIcon *icon)
{
	uint16 phase;

	for (phase = 0; phase < CURSOR_PHASES; phase++) {
		free(icon->data[phase]);
		free(icon->mask[phase]);
		icon->data[phase] = NULL;
		icon->mask[phase] = NULL;
	}
	icon->valid = false;
}

/**
 * (Re)build the persistent pre-shifted bitplane cache for every MOUSE.SHP
 * icon (g_sprites[0..MOUSE_ICON_COUNT-1]). Called once, right after
 * Sprites_Init() loads MOUSE.SHP, and again -- for every icon at once --
 * whenever the palette quantization changes (see Video_SetPalette()),
 * since a changed s_palette4BitMap[] invalidates every previously built
 * pen value. Cheap and rare either way: this never runs on the cursor
 * movement hot path.
 *
 * Each icon is rendered once into a private, tightly packed chunky buffer.
 * Colour 0 supplies the transparency mask; no screen buffer is touched.
 */
void Video_Atari_CursorPreloadIcons(void)
{
	uint16 i;
	bool visible = s_curVisible;

	if (!Video_Atari_CursorDirect()) return;
	if (g_sprites == NULL) return;

	for (i = 0; i < MOUSE_ICON_COUNT; i++) {
		const uint8 *sprite = g_sprites[i];
		uint16 w, h, phase, line, x;
		uint16 minX, minY, maxX, maxY;	/* tight non-transparent bbox, inclusive */
		bool ok, any;
		uint8 *box;

		Video_Atari_CursorFreeIcon(&s_curIcon[i]);
		if (sprite == NULL) continue;

		w = READ_LE_UINT16(sprite + 3);
		h = sprite[2];
		/* implausible size (corrupt data?) -- be defensive, just skip it */
		if (w == 0 || h == 0 || w > SCREEN_WIDTH || h > CURSOR_MAX_H) continue;

		box = (uint8 *)calloc((size_t)w, h);
		if (box == NULL) {
			Warning("Unable to allocate cursor icon scratch buffer\n");
			continue;
		}
		GUI_DrawSpriteToBuffer(box, w, h, sprite, 0, 0);

		/* Crop to the tight non-transparent (colour != 0) bounding box: the
		 * sprite's own declared w/h is a coarse outer bound that includes
		 * however much blank padding the original art happened to have
		 * (see the on-screen pixel counts in ATARI_C2P_DIRTY_RUNS.md), but
		 * every phase/group/mask buffer below is sized off icon->w/h -- so
		 * cropping here directly shrinks the whole pre-shift cache (both
		 * its memory footprint and the per-tick draw/erase word count) to
		 * only the pixels a cursor can actually show. bboxX/bboxY record
		 * the crop's offset so screen positioning still lines up. */
		minX = w; maxX = 0; minY = h; maxY = 0; any = false;
		for (line = 0; line < h; line++) {
			const uint8 *row = box + line * w;

			for (x = 0; x < w; x++) {
				if (row[x] == 0) continue;
				any = true;
				if (x < minX) minX = x;
				if (x > maxX) maxX = x;
				if (line < minY) minY = line;
				if (line > maxY) maxY = line;
			}
		}

		if (!any) {
			/* fully transparent icon (shouldn't happen for a real cursor,
			 * but be defensive) -- leave it invalid rather than divide by
			 * a zero-sized box */
			free(box);
			continue;
		}

		s_curIcon[i].bboxX = minX;
		s_curIcon[i].bboxY = minY;
		s_curIcon[i].w = (uint16)(maxX - minX + 1);
		s_curIcon[i].h = (uint16)(maxY - minY + 1);

		ok = true;
		for (phase = 0; phase < CURSOR_PHASES; phase++) {
			if (!Video_Atari_CursorBuildPhase(&s_curIcon[i], phase, box + minY * w + minX, w, i == 0)) ok = false;
		}
		s_curIcon[i].valid = ok;

		free(box);
	}
	s_curIconPaletteGeneration = s_paletteGeneration;
	if (s_curSelectedIcon != 0xffff) {
		if (!Video_Atari_CursorUseIcon(s_curSelectedIcon, s_curIconLeft, s_curIconTop)) {
			Warning("Unable to refresh selected cursor icon\n");
			s_curDrawData = NULL;
			s_curDrawMask = NULL;
			Video_Atari_CursorHide();
		} else if (!visible) {
			Video_Atari_CursorHide();
		}
	}
}

/**
 * Select the pre-shifted bitplane phase of icon `iconIndex` for a cursor
 * whose (unclipped) screen-space box would be [left, left+icon width) x
 * [top, top+icon height), and set up the composite state for the next
 * Video_Atari_CursorDraw() exactly like Video_Atari_CursorPrepare()+
 * Video_Atari_CursorBuild() would -- but as a pure table lookup plus
 * trimming whole leading/trailing groups or lines, with no chunky render
 * or per-pixel transpose at all.
 *
 * Edge clipping needs no sub-pixel masking: `group = left >> 4` is an
 * arithmetic (floor) shift, so every column-group boundary is 16px
 * aligned in screen space -- a group is always either entirely off-
 * screen or entirely on-screen, never straddling column 0 or column
 * SCREEN_WIDTH. The same holds per-scanline for the top/bottom edges.
 * So clipping is just: drop whole leading/trailing groups (by advancing
 * the table's data/mask pointers and shrinking the group count) and
 * whole leading/trailing lines (by advancing the row pointer and
 * shrinking the line count) -- the existing per-bit opacity mask
 * already makes whatever remains correct.
 *
 * @return true if the fast path was used (caller must not call
 *         Video_Atari_CursorPrepare()/CursorBuild() this tick); false
 *         only for an unknown/not-yet-preloaded icon, or the
 *         exceedingly unlikely case of an icon wider than this module's
 *         fixed CURSOR_MAX_GROUPS/CURSOR_MAX_H budget. If the icon is
 *         fully clipped off-screen, this still returns true, with the
 *         cursor simply not drawn this tick (s_curGroups/s_curH == 0).
 */
bool Video_Atari_CursorUseIcon(uint16 iconIndex, int16 left, int16 top)
{
	const CursorIcon *icon;
	uint16 phase, stride, h;
	int16 group, groupEnd, lineEnd;
	uint16 visGroup0, visGroupEnd, lineSkip, groupSkip;

	if (iconIndex >= MOUSE_ICON_COUNT) return false;

	if (s_curIconPaletteGeneration != s_paletteGeneration) Video_Atari_CursorPreloadIcons();

	icon = &s_curIcon[iconIndex];
	if (!icon->valid) return false;
	s_curSelectedIcon = iconIndex;
	s_curIconLeft = left;
	s_curIconTop = top;

	/* the table only covers the tight non-transparent bbox, offset from
	 * the sprite's nominal top-left/hotspot origin -- shift into that
	 * bbox's own screen-space coordinates before anything else */
	left = (int16)(left + icon->bboxX);
	top = (int16)(top + icon->bboxY);

	h = icon->h;
	if (h > CURSOR_MAX_H) return false;	/* should never happen, be defensive */

	phase = (uint16)((uint16)left & 0xf);
	stride = icon->groups[phase];
	if (stride > CURSOR_MAX_GROUPS) return false;

	group = left >> 4;
	groupEnd = group + (int16)stride;	/* one-past-last table group, screen-space */
	lineEnd = top + (int16)h;		/* one-past-last table line, screen-space */

	/* clip to whole groups/lines only -- see comment above for why no
	 * partial-group/partial-line masking is ever needed */
	visGroup0 = (uint16)((group < 0) ? 0 : group);
	visGroupEnd = (uint16)((groupEnd > SCREEN_WIDTH / 16) ? SCREEN_WIDTH / 16 : groupEnd);
	groupSkip = (uint16)(visGroup0 - group);

	lineSkip = (uint16)((top < 0) ? -top : 0);
	if (lineEnd > SCREEN_HEIGHT) lineEnd = SCREEN_HEIGHT;

	if (visGroupEnd <= visGroup0 || lineEnd <= top + (int16)lineSkip) {
		/* fully clipped off-screen: nothing to draw this tick, but the
		 * fast path still "handled" it -- no fall back needed */
		s_curVisible = false;
		s_curDirty = true;
		s_curGroups = 0;
		s_curH = 0;
		s_curKeySprite = NULL;
		return true;
	}

	s_curY = top + (int16)lineSkip;
	s_curH = (uint16)(lineEnd - s_curY);
	s_curShift = phase;
	s_curGroup = visGroup0;
	s_curGroups = (uint16)(visGroupEnd - visGroup0);
	s_curVisible = true;
	s_curDirty = true;

	s_curDrawData = icon->data[phase] + (uint32)lineSkip * stride * 4 + (uint32)groupSkip * 4;
	s_curDrawMask = icon->mask[phase] + (uint32)lineSkip * stride + groupSkip;
	s_curDrawStride = stride;
	s_curPointer = iconIndex == 0;

	/* the slow-path cache key no longer describes what is on screen --
	 * make sure a later fall-back call always rebuilds rather than
	 * wrongly trusting a stale cache hit */
	s_curKeySprite = NULL;

	return true;
}

void Video_Atari_CursorHide(void)
{
	if (s_curVisible) {
		s_curVisible = false;
		s_curDirty = true;
	}
}

static void Video_Atari_MarkViewportTiles(uint16 tiles[10], int16 x, int16 y,
                                         uint16 width, uint16 height)
{
	int left = max(0, x), right = min(240, (int)x + width);
	int top = max(40, y), bottom = min(200, (int)y + height);
	uint16 bits, row, lastRow;

	memset(tiles, 0, 10 * sizeof(*tiles));
	if (left >= right || top >= bottom) return;
	bits = (uint16)(((1u << ((right + 15) >> 4)) - 1) &
	                ~((1u << (left >> 4)) - 1));
	row = (uint16)((top - 40) >> 4);
	lastRow = (uint16)((bottom - 41) >> 4);
	for (; row <= lastRow; row++) tiles[row] = bits;
}

static bool s_curSuppress;

static bool Video_Atari_CursorSuppressed(void)
{
	if (!s_curSuppress) return false;
	if (g_tileCursor != 0 && g_selectionType != SELECTIONTYPE_PLACE) {
		/* Use the hotspot, not the sprite box, across both activation strips. */
		return (g_mouseSpriteIconIndex >= 1 && g_mouseSpriteIconIndex <= 4) ||
		    (g_mouseX <= 250 && g_mouseY >= 24 && g_mouseY < 200);
	}
	return s_curGroup < 15 && s_curY + s_curH > 40;
}

typedef struct CursorComposeArgs {
	uint16 *dst, *save, *drawnData, *drawnMask;
	const uint16 *data, *mask;
	uint32 lines, groups, dstSkip, saveSkip, drawnMaskSkip, dataSkip, maskSkip;
} CursorComposeArgs;

typedef struct CursorRefreshArgs {
	uint16 *dst, *save, *drawnData, *drawnMask;
	const uint16 *masks;
	uint32 lines, groups, dstSkip, saveSkip, drawnMaskSkip, masksSkip;
} CursorRefreshArgs;

/* cursor.s: plain 68000 loops over long-aligned screen/backup buffers */
extern void Video_Atari_CursorRestore(uint16 *dst, const uint16 *save, long saveStride,
                                      long lines, long groups);
extern void Video_Atari_CursorCompose(const CursorComposeArgs *args);
extern void Video_Atari_CursorComposePointer(const CursorComposeArgs *args);
extern void Video_Atari_CursorRefreshGroups(CursorRefreshArgs *args);
extern void Video_Atari_CursorRefreshPointer(CursorRefreshArgs *args);
extern long Video_Atari_CursorRowsEqual(const uint16 *a, long strideA, const uint16 *b,
                                        long strideB, long lines, long words);
static const uint16 s_cursorAllOnes[CURSOR_MAX_GROUPS] = {
	0xffff, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff
};

/* Movement, actual hiding and screen shifts restore this backup.
 * Ordinary drawing updates it synchronously instead. */
static void Video_Atari_CursorEraseFull(void)
{
	Video_Atari_DisplayListFlush();
	uint16 *p;

	if (!s_curDrawn) return;

	if (Video_Atari_Mono()) {
		uint16 row, group;
		for (row = 0; row < s_curDrawnH; row++)
			for (group = 0; group < s_curDrawnGroups; group++)
				Video_Atari_MonoWriteGroup((uint16 *)s_curDrawnBase, 80,
					s_curDrawnY + row, s_curDrawnGroup + group, &s_curSave[row][group * 4]);
		s_curDrawn = false;
		memset(s_curViewportTiles, 0, sizeof(s_curViewportTiles));
		return;
	}

	p = (uint16 *)(s_curDrawnBase + s_curDrawnY * (SCREEN_WIDTH >> 1)
	                             + (s_curDrawnGroup << 3));
	Video_Atari_CursorRestore(p, &s_curSave[0][0], sizeof(s_curSave[0]), s_curDrawnH, s_curDrawnGroups);
	s_curDrawn = false;
	memset(s_curViewportTiles, 0, sizeof(s_curViewportTiles));
}

/** Save the planar background and composite the cursor over it. */
static void Video_Atari_CursorDraw(uint8 *base)
{
	Video_Atari_DisplayListFlush();
	uint16 *p;

	if (s_curDrawn || !s_curVisible) return;
	if (s_curH == 0 || s_curGroups == 0) return;
	if (s_curDrawData == NULL || s_curDrawMask == NULL) return;

	if (Video_Atari_Mono()) {
		uint16 row, group;
		for (row = 0; row < s_curH; row++) {
			for (group = 0; group < s_curGroups; group++) {
				uint16 words[4], mask = s_curDrawMask[row * s_curDrawStride + group];
				const uint16 *data = s_curDrawData + (row * s_curDrawStride + group) * 4;
				Video_Atari_MonoReadGroup((uint16 *)base, 80, s_curY + row, s_curGroup + group, words);
				memcpy(&s_curSave[row][group * 4], words, sizeof(words));
				memcpy(&s_curDrawnData[row][group * 4], data, sizeof(words));
				s_curDrawnMask[row][group] = mask;
				Video_Atari_MonoMergeWords(words, data, mask);
				Video_Atari_MonoWriteGroup((uint16 *)base, 80, s_curY + row, s_curGroup + group, words);
			}
		}
	} else {
	p = (uint16 *)(base + s_curY * (SCREEN_WIDTH >> 1) + (s_curGroup << 3));
	{
		CursorComposeArgs args;

		args.dst = p;
		args.save = &s_curSave[0][0];
		args.drawnData = &s_curDrawnData[0][0];
		args.drawnMask = &s_curDrawnMask[0][0];
		args.data = s_curDrawData;
		args.mask = s_curDrawMask;
		args.lines = s_curH;
		args.groups = s_curGroups;
		args.dstSkip = 160 - (s_curGroups << 3);
		args.saveSkip = sizeof(s_curSave[0]) - (s_curGroups << 3);
		args.drawnMaskSkip = sizeof(s_curDrawnMask[0]) - (s_curGroups << 1);
		args.dataSkip = ((uint32)s_curDrawStride << 3) - (s_curGroups << 3);
		args.maskSkip = ((uint32)s_curDrawStride << 1) - (s_curGroups << 1);
		if (s_curPointer) Video_Atari_CursorComposePointer(&args);
		else Video_Atari_CursorCompose(&args);
	}
	}
	s_curDrawnPointer = s_curPointer;
	s_curDrawnBase = base;
	s_curDrawnY = s_curY;
	s_curDrawnH = s_curH;
	s_curDrawnGroup = s_curGroup;
	s_curDrawnGroups = s_curGroups;
	s_curDrawn = true;
	Video_Atari_MarkViewportTiles(s_curViewportTiles, s_curDrawnGroup << 4, s_curDrawnY,
	                            s_curDrawnGroups << 4, s_curDrawnH);
}

static void Video_Atari_CursorSync(uint8 *base)
{
	bool same;

	/* Palette changes rebuild icon caches eagerly. Uncached sprites need
	 * their private chunky render again; defer it if a GUI mouse lock or
	 * an outstanding hide is active. */
	if (s_curSelectedIcon == 0xffff && s_curKeySprite != NULL &&
	    s_curKeyPal != s_paletteGeneration && s_curVisible &&
	    g_mouseHiddenDepth == 0 && g_mouseLock == 0) {
		GUI_Mouse_Hide();
		GUI_Mouse_Show();
	}
	if (Video_Atari_CursorSuppressed()) {
		if (s_curDrawn) Video_Atari_CursorEraseFull();
		s_curDirty = false;
		return;
	}
	same = s_curDrawn && s_curVisible && s_curDrawnBase == base &&
	       s_curDrawnY == s_curY && s_curDrawnH == s_curH &&
	       s_curDrawnGroup == s_curGroup && s_curDrawnGroups == s_curGroups;

	if (same && !s_curDirty) return;
	if (same) {
		same = s_curH == 0 || s_curGroups == 0 ||
		    (Video_Atari_CursorRowsEqual(&s_curDrawnData[0][0], sizeof(s_curDrawnData[0]),
		        s_curDrawData, (long)s_curDrawStride << 3, s_curH, s_curGroups << 2) &&
		     Video_Atari_CursorRowsEqual(&s_curDrawnMask[0][0], sizeof(s_curDrawnMask[0]),
		        s_curDrawMask, (long)s_curDrawStride << 1, s_curH, s_curGroups));
	}
	if (!same) {
		Video_Atari_CursorEraseFull();
		Video_Atari_CursorDraw(base);
	}
	s_curDirty = false;
}

/* Placement footprints are at most 3x3 tiles. Save only planar groups
 * containing outline pixels; the chunky screens remain free of overlays. */
#define PLACEMENT_MAX_H 48
#define PLACEMENT_MAX_GROUPS 3

typedef struct PlacementBlock {
	uint16 y, group, mask;
	uint16 saved[4];
} PlacementBlock;

static uint16 s_placeMask[PLACEMENT_MAX_H][PLACEMENT_MAX_GROUPS];
static PlacementBlock s_placeBlocks[PLACEMENT_MAX_H * PLACEMENT_MAX_GROUPS];
static uint16 s_placeBlockCount;
static uint8 *s_placeDrawnBase;
static int16 s_placeX, s_placeY;
static uint16 s_placeWidth, s_placeHeight;
static uint8 s_placePen;
static bool s_placeVisible, s_placeDirty;
static int16 s_placeDrawnX, s_placeDrawnY;
static uint16 s_placeDrawnWidth, s_placeDrawnHeight;
static uint16 s_placeViewportTiles[10];

static inline bool Video_Atari_CursorRectOverlap(uint8 *base, uint16 first, uint16 end,
                                                uint16 y, uint16 h)
{
	return s_curDrawn && base == s_curDrawnBase &&
	       y < s_curDrawnY + s_curDrawnH && y + h > s_curDrawnY &&
	       first < s_curDrawnGroup + s_curDrawnGroups && end > s_curDrawnGroup;
}

static inline bool Video_Atari_PlacementRectOverlap(uint8 *base, uint16 left, uint16 right,
                                                   uint16 y, uint16 h)
{
	return s_placeBlockCount != 0 && base == s_placeDrawnBase &&
	       (int)y < s_placeDrawnY + s_placeDrawnHeight && (int)(y + h) > s_placeDrawnY &&
	       (int)left < s_placeDrawnX + s_placeDrawnWidth && (int)right > s_placeDrawnX;
}

static inline bool Video_Atari_PlanarOverlaysOverlap(uint8 *base, uint16 x, uint16 y,
                                             uint16 w, uint16 h)
{
	uint16 first = x >> 4, end = (x + w + 15) >> 4;

	/* Backups cover whole groups, including pixels outside an edge mask. */
	return Video_Atari_CursorRectOverlap(base, first, end, y, h) ||
	       Video_Atari_PlacementRectOverlap(base, first << 4, end << 4, y, h);
}

static inline bool Video_Atari_TileOverlaysOverlap(uint8 *base, uint16 x, uint16 y)
{
	static const uint16 columnBits[15] = {
		0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040, 0x0080,
		0x0100, 0x0200, 0x0400, 0x0800, 0x1000, 0x2000, 0x4000
	};

	if (x < 240 && y >= 40 && y < 200 && ((y - 40) & 15) == 0) {
		uint16 row = (y - 40) >> 4;
		return ((s_curViewportTiles[row] | s_placeViewportTiles[row]) & columnBits[x >> 4]) != 0;
	}
	return Video_Atari_PlanarOverlaysOverlap(base, x, y, 16, 16);
}

static inline void Video_Atari_PlanarMergePlain(uint16 *dst, uint16 mask, const uint16 pixels[4])
{
	uint16 plane;

	for (plane = 0; plane < 4; plane++) {
		dst[plane] = (uint16)((dst[plane] & (uint16)~mask) | (pixels[plane] & mask));
	}
}

static inline void Video_Atari_PlanarCopyGroup(uint16 *dst, const uint16 *src)
{
	dst[0] = src[0];
	dst[1] = src[1];
	dst[2] = src[2];
	dst[3] = src[3];
}

static inline void Video_Atari_MergeNativeWords(uint16 dst[4], const uint16 pixels[4], uint16 mask)
{
	if (Video_Atari_Mono()) Video_Atari_MonoMergeWords(dst, pixels, mask);
	else Video_Atari_PlanarMergePlain(dst, mask, pixels);
}

static inline void Video_Atari_WriteNativeGroup(uint8 *base, uint16 y, uint16 group,
	const uint16 words[4])
{
	if (Video_Atari_Mono()) Video_Atari_MonoWriteGroup((uint16 *)base, 80, y, group, words);
	else Video_Atari_PlanarCopyGroup((uint16 *)(base + (uint32)y * 160 + group * 8), words);
}

static inline void Video_Atari_PenGroupWords(uint8 pen, int16 x, int16 y, uint16 words[4])
{
	uint16 plane;
	if (Video_Atari_Mono()) Video_Atari_MonoPenWords(pen, x, y, words);
	else for (plane = 0; plane < 4; plane++) words[plane] = (pen & (1u << plane)) ? 0xffff : 0;
}

static int Video_Atari_CursorGroup(uint8 *base, uint16 y, uint16 group)
{
	if (!s_curDrawn || base != s_curDrawnBase ||
	    y < s_curDrawnY || y >= s_curDrawnY + s_curDrawnH ||
	    group < s_curDrawnGroup || group >= s_curDrawnGroup + s_curDrawnGroups) return -1;
	return group - s_curDrawnGroup;
}

static const uint16 *Video_Atari_CursorBackground(uint8 *base, uint16 y, uint16 group)
{
	static uint16 monoWords[4];
	int g = Video_Atari_CursorGroup(base, y, group);
	if (g >= 0) return &s_curSave[y - s_curDrawnY][g * 4];
	if (Video_Atari_Mono()) {
		Video_Atari_MonoReadGroup((const uint16 *)base, 80, y, group, monoWords);
		return monoWords;
	}
	return (uint16 *)(base + (uint32)y * 160 + group * 8);
}

static void Video_Atari_CursorWriteGroup(uint8 *base, uint16 y, uint16 group, const uint16 words[4])
{
	int g = Video_Atari_CursorGroup(base, y, group);
	uint16 result[4], line;

	if (g < 0) {
		Video_Atari_WriteNativeGroup(base, y, group, words);
		return;
	}
	line = y - s_curDrawnY;
	memcpy(&s_curSave[line][g * 4], words, sizeof(result));
	memcpy(result, words, sizeof(result));
	Video_Atari_MergeNativeWords(result, &s_curDrawnData[line][g * 4], s_curDrawnMask[line][g]);
	Video_Atari_WriteNativeGroup(base, y, group, result);
}

static PlacementBlock *Video_Atari_PlacementBlock(uint8 *base, uint16 y, uint16 group)
{
	uint16 i;
	if (s_placeBlockCount == 0 || base != s_placeDrawnBase ||
	    (int)y < s_placeDrawnY || (int)y >= s_placeDrawnY + s_placeDrawnHeight ||
	    (int)(group * 16) < s_placeDrawnX ||
	    (int)(group * 16) >= s_placeDrawnX + s_placeDrawnWidth) return NULL;
	for (i = 0; i < s_placeBlockCount; i++) {
		if (s_placeBlocks[i].y == y && s_placeBlocks[i].group == group) return &s_placeBlocks[i];
	}
	return NULL;
}

/* Merge against the scene without either overlay, then rebuild placement
 * and mouse in that order. A full-word write ignores the old scene. */
static void Video_Atari_PlanarMergeGroup(uint8 *base, uint16 y, uint16 group,
                                       uint16 mask, const uint16 pixels[4])
{
	const uint16 *old = Video_Atari_CursorBackground(base, y, group);
	PlacementBlock *block = Video_Atari_PlacementBlock(base, y, group);
	uint16 words[4];

	memcpy(words, old, sizeof(words));
	if (block != NULL) Video_Atari_MergeNativeWords(words, block->saved, block->mask);
	Video_Atari_MergeNativeWords(words, pixels, mask);
	if (block != NULL) {
		uint16 tint[4];
		memcpy(block->saved, words, sizeof(words));
		Video_Atari_PenGroupWords(s_placePen, group * 16 - s_placeDrawnX, y - s_placeDrawnY, tint);
		Video_Atari_MergeNativeWords(words, tint, block->mask);
	}
	Video_Atari_CursorWriteGroup(base, y, group, words);
}

static void Video_Atari_RefreshViewportCursor(uint8 *base, uint16 first, uint16 end,
                                             uint16 top, uint16 bottom,
                                             const uint16 *masks, uint16 stride)
{
	uint16 maskFirst = first, maskTop = top;

	assert(first < end && end <= 15 && top >= 40 && top < bottom && bottom <= 200);
	if (!s_curDrawn || base != s_curDrawnBase) return;
	Video_Atari_DisplayListFlush();
	first = max(first, s_curDrawnGroup);
	end = min(end, s_curDrawnGroup + s_curDrawnGroups);
	top = max(top, s_curDrawnY);
	bottom = min(bottom, s_curDrawnY + s_curDrawnH);
	if (first >= end || top >= bottom) return;
	if (Video_Atari_Mono()) {
		uint16 row, group;
		for (row = top; row < bottom; row++) {
			for (group = first; group < end; group++) {
				uint16 pixels[4], words[4];
				uint16 mask = masks != NULL ? masks[(uint32)(row - maskTop) * stride + group - maskFirst] : 0xffff;
				if (mask == 0) continue;
				Video_Atari_MonoReadGroup((const uint16 *)base, 80, row, group, pixels);
				memcpy(words, &s_curSave[row - s_curDrawnY][(group - s_curDrawnGroup) * 4], sizeof(words));
				Video_Atari_MonoMergeWords(words, pixels, mask);
				Video_Atari_CursorWriteGroup(base, row, group, words);
			}
		}
		return;
	}
	{
		CursorRefreshArgs args;
		uint16 cursorRow = top - s_curDrawnY, cursorGroup = first - s_curDrawnGroup;
		uint32 count = end - first;

		args.dst = (uint16 *)(base + (uint32)top * 160 + first * 8);
		args.save = &s_curSave[cursorRow][cursorGroup * 4];
		args.drawnData = &s_curDrawnData[cursorRow][cursorGroup * 4];
		args.drawnMask = &s_curDrawnMask[cursorRow][cursorGroup];
		args.lines = bottom - top;
		args.groups = count;
		args.dstSkip = 160 - (count << 3);
		args.saveSkip = sizeof(s_curSave[0]) - (count << 3);
		args.drawnMaskSkip = sizeof(s_curDrawnMask[0]) - (count << 1);
		if (masks != NULL) {
			args.masks = masks + (uint32)(top - maskTop) * stride + (first - maskFirst);
			args.masksSkip = ((uint32)stride << 1) - (count << 1);
		} else {
			args.masks = s_cursorAllOnes;
			args.masksSkip = -(int32)(count << 1);
		}
		if (s_curDrawnPointer) Video_Atari_CursorRefreshPointer(&args);
		else Video_Atari_CursorRefreshGroups(&args);
	}
}

/* The c2p inner loop remains unchanged. Visit only overwritten overlay
 * groups after an opaque conversion, not every group in the blit. */
static void Video_Atari_PlanarFinishRun(uint8 *base, uint16 x, uint16 y, uint16 w, uint16 h)
{
	uint16 first = x >> 4, end = (x + w) >> 4;
	uint16 line, group, i;

	if (Video_Atari_CursorRectOverlap(base, first, end, y, h)) {
		uint16 top = max(y, s_curDrawnY), bottom = min(y + h, s_curDrawnY + s_curDrawnH);
		uint16 left = max(first, s_curDrawnGroup), right = min(end, s_curDrawnGroup + s_curDrawnGroups);
		for (line = top; line < bottom; line++) {
			for (group = left; group < right; group++) {
				uint16 words[4];
				if (Video_Atari_Mono()) Video_Atari_MonoReadGroup((uint16 *)base, 80, line, group, words);
				else memcpy(words, base + (uint32)line * 160 + group * 8, sizeof(words));
				Video_Atari_PlanarMergeGroup(base, line, group, 0xffff, words);
			}
		}
	}
	if (!Video_Atari_PlacementRectOverlap(base, x, x + w, y, h)) return;
	for (i = 0; i < s_placeBlockCount; i++) {
		PlacementBlock *block = &s_placeBlocks[i];
		uint16 words[4];
		if (block->y < y || block->y >= y + h || block->group < first || block->group >= end ||
		    Video_Atari_CursorGroup(base, block->y, block->group) >= 0) continue;
		if (Video_Atari_Mono()) Video_Atari_MonoReadGroup((uint16 *)base, 80, block->y, block->group, words);
		else memcpy(words, base + (uint32)block->y * 160 + block->group * 8, sizeof(words));
		Video_Atari_PlanarMergeGroup(base, block->y, block->group, 0xffff, words);
	}
}

static void Video_Atari_BlitterStart(void);
static uint8 *Video_Atari_PlanarBase(void);
extern bool GUI_Widget_Viewport_TileCursorActive(void);

typedef struct PlacementTint {
	uint8 *dst;
	const uint16 *pattern;	/* 16 line words, or NULL for the checkerboard */
	uint16 words, height;
	uint16 pen;	/* tile cursor only: colour forced on every plane */
} PlacementTint;

static PlacementTint s_placeTint;

extern void Video_Atari_RunDisplayList(const uint16 *stream);
extern void Video_Atari_BlitPlaneCode(void);
static const uint16 *s_displayStream;

static void Video_Atari_DisplayExecute(void)
{
	Video_Atari_RunDisplayList(s_displayStream);
}

void Video_Atari_ExecuteDisplayList(const uint16 *stream)
{
	if (g_videoScrollPending) Video_Atari_FinishScroll();
	s_displayStream = stream;
	s_blitterTileSetup = false;
	Atari_SupervisorExec(Video_Atari_DisplayExecute);
	s_blitterTileSetup = false;
}

static uint16 *Video_Atari_DisplayMoveLong(uint16 *out, uint16 opcode, uint32 value)
{
	*out++ = HTOBE16(opcode);
	*out++ = HTOBE16(value >> 16);
	*out++ = HTOBE16(value);
	return out;
}

static uint16 *Video_Atari_DisplayGeometry(uint16 *out, const Video_Atari_SpriteBlitPlan *plan)
{
	out = Video_Atari_DisplayMoveLong(out, 0x21fc,
	    ((uint32)(uint16)plan->sourceXinc << 16) | (uint16)plan->sourceYinc);
	*out++ = HTOBE16(0x8a20);
	out = Video_Atari_DisplayMoveLong(out, 0x21fc,
	    ((uint32)plan->firstMask << 16) | plan->middleMask);
	*out++ = HTOBE16(0x8a28);
	out = Video_Atari_DisplayMoveLong(out, 0x21fc,
	    ((uint32)plan->lastMask << 16) | (uint16)plan->destinationXinc);
	*out++ = HTOBE16(0x8a2c);
	*out++ = HTOBE16(0x31fc);
	*out++ = HTOBE16(plan->destinationYinc);
	*out++ = HTOBE16(0x8a30);
	*out++ = HTOBE16(0x31fc);
	*out++ = HTOBE16(plan->words);
	*out++ = HTOBE16(0x8a36);
	*out++ = HTOBE16(0x11fc);
	*out++ = HTOBE16(plan->skew);
	*out++ = HTOBE16(0x8a3d);
	return Video_Atari_DisplayMoveLong(out, 0x4239, (uint32)(size_t)&s_blitterTileSetup);
}

static uint16 *Video_Atari_DisplayPattern(uint16 *out, const uint16 *pattern)
{
	uint16 i;
	out = Video_Atari_DisplayMoveLong(out, 0x42b9, (uint32)(size_t)&s_blitterHalftonePattern);
	for (i = 0; i < 16; i++) {
		*out++ = HTOBE16(0x31fc);
		*out++ = HTOBE16(pattern[i]);
		*out++ = HTOBE16(0x8a00 + i * 2);
	}
	return out;
}

static uint16 *Video_Atari_DisplayPlane(uint16 *out, const uint16 *pixels, uint16 *dst,
                                      uint16 height, uint16 operation, uint16 start)
{
	out = Video_Atari_DisplayMoveLong(out, 0x207c, (uint32)(size_t)pixels);
	out = Video_Atari_DisplayMoveLong(out, 0x247c, (uint32)(size_t)dst);
	*out++ = HTOBE16(0x303c);
	*out++ = HTOBE16(height);
	*out++ = HTOBE16(0x323c);
	*out++ = HTOBE16(operation);
	*out++ = HTOBE16(0x343c);
	*out++ = HTOBE16(start);
	return Video_Atari_DisplayMoveLong(out, 0x4eb9, (uint32)(size_t)Video_Atari_BlitPlaneCode);
}

/* Halftone users share ownership; source-only blits leave this RAM intact. */
static void Video_Atari_SetHalftonePattern(const uint16 *pattern)
{
	volatile uint16 *halftone = (volatile uint16 *)0xFFFF8A00UL;
	uint16 i;

	if (s_blitterHalftonePattern == pattern) return;
	for (i = 0; i < 16; i++) halftone[i] = pattern[i];
	s_blitterHalftonePattern = pattern;
}

static void Video_Atari_QueueTintBlit(const Video_Atari_SpriteBlitPlan *plan,
                                    const uint16 *pattern, uint16 operation,
                                    uint16 *dst, uint16 height)
{
	uint16 *out = g_videoDisplayListNext;
	assert(g_videoDisplayListLimit - out >= VIDEO_ATARI_DISPLAY_TINT_BYTES / 2);
	out = Video_Atari_DisplayGeometry(out, plan);
	out = Video_Atari_DisplayPattern(out, pattern);
	out = Video_Atari_DisplayPlane(out, NULL, dst, height, operation, 0xc0);
	g_videoDisplayListNext = out;
}

static void Video_Atari_PlacementTintBlit(void)
{
	while ((*BLITTER_CTRL & 0x80) != 0) {}
	Video_Atari_SetHalftonePattern(s_placeTint.pattern);
	*BLITTER_ENDMASK1 = 0xffff;
	*BLITTER_ENDMASK2 = 0xffff;
	*BLITTER_ENDMASK3 = 0xffff;
	*BLITTER_DST_XINC = 8;
	*BLITTER_DST_YINC = (int16)(ST_PLANAR_LINE_BYTES - (s_placeTint.words - 1) * 8);
	*BLITTER_XCOUNT = s_placeTint.words;
	*BLITTER_HOP = 1;
	*BLITTER_OP = 7;
#ifdef VIEWPORT_DEBUG_DAMAGE
	if (s_damageDebugOverlay) *BLITTER_OP = 6;
#endif
	*BLITTER_SKEW = 0;
	*BLITTER_DST_ADDR = (uint32)(size_t)s_placeTint.dst;
	*BLITTER_YCOUNT = s_placeTint.height;
	Video_Atari_BlitterStart();
	*BLITTER_HOP = 2;
}

/* Tint a checkerboard in the footprint (viewport coordinates, clipped to
 * the viewport). Idempotent, so it may be repeated. */
void Video_Atari_PlacementTint(int16 x, int16 y, uint16 width, uint16 height, bool invalid)
{
	static const uint16 checkerboard[16] = {
		0xaaaa, 0x5555, 0xaaaa, 0x5555, 0xaaaa, 0x5555, 0xaaaa, 0x5555,
		0xaaaa, 0x5555, 0xaaaa, 0x5555, 0xaaaa, 0x5555, 0xaaaa, 0x5555
	};
	int16 right = x + (int16)width, bottom = y + (int16)height;
	uint16 plane = invalid ? g_placementInvalidPlane : g_placementValidPlane;
	uint16 words, lines, line, group;
	uint8 *dst;

	if (x < 0) x = 0;
	if (y < 40) y = 40;
	if (right > 240) right = 240;
	if (bottom > 200) bottom = 200;
	if (x >= right || y >= bottom) return;
	if (Video_Atari_Mono()) {
		uint16 row, col;
		uint8 *base = Video_Atari_PlanarBase();
		if (g_videoDisplayListActive && !Video_Atari_PlanarOverlaysOverlap(base, x, y, right - x, bottom - y)) {
			static const uint16 monoSet[16] = {
				0xcccc, 0xcccc, 0x3333, 0x3333, 0xcccc, 0xcccc, 0x3333, 0x3333,
				0xcccc, 0xcccc, 0x3333, 0x3333, 0xcccc, 0xcccc, 0x3333, 0x3333
			};
			static const uint16 monoKeep[16] = {
				0x3333, 0x3333, 0xcccc, 0xcccc, 0x3333, 0x3333, 0xcccc, 0xcccc,
				0x3333, 0x3333, 0xcccc, 0xcccc, 0x3333, 0x3333, 0xcccc, 0xcccc
			};
			bool set = invalid != s_monoWhiteIsOne;
			uint16 first = 0xffffu >> ((x & 7) * 2);
			uint16 last = (uint16)(0xffffu << (((-right) & 7) * 2));
			uint16 count = (right + 7) / 8 - x / 8;
			Video_Atari_SpriteBlitPlan plan = {
				2, 2, count == 1 ? first & last : first, 0xffff, last, 2,
				80 - (count - 1) * 2, count, 0
			};
			Video_Atari_DisplayListCheck(VIDEO_ATARI_DISPLAY_TINT_BYTES);
			Video_Atari_QueueTintBlit(&plan, set ? monoSet : monoKeep, set ? 0x0107 : 0x0101,
			    (uint16 *)base + (uint32)y * 80 + x / 8, (bottom - y) * 2);
			return;
		}
		Video_Atari_DisplayListFlush();
		for (row = y; row < bottom; row++) {
			for (col = x / 16; col < (right + 15) / 16; col++) {
				uint16 fill[4], mask = checkerboard[(row - y) & 15];
				Video_Atari_MonoPenWords(invalid ? 0 : 4, 0, row - y, fill);
				if (col * 16 < x) mask &= 0xffffu >> (x & 15);
				if ((col + 1) * 16 > right) mask &= 0xffffu << (16 - (right & 15));
				Video_Atari_PlanarMergeGroup(Video_Atari_PlanarBase(), row, col, mask, fill);
			}
		}
		return;
	}
	if (!g_videoDisplayListActive && g_videoScrollPending) Video_Atari_FinishScroll();
	words = (uint16)((right - x) >> 4);
	lines = (uint16)(bottom - y);
	dst = Video_Atari_PlanarBase() + (uint32)y * ST_PLANAR_LINE_BYTES + (x >> 1) + plane * 2;
	if (s_viewportBlitter) {
		s_placeTint.dst = dst;
		s_placeTint.pattern = checkerboard;
		s_placeTint.words = words;
		s_placeTint.height = lines;
		s_blitterTileSetup = false;
		if (g_videoDisplayListActive) {
			Video_Atari_SpriteBlitPlan plan = {
				8, 8, 0xffff, 0xffff, 0xffff, 8,
				ST_PLANAR_LINE_BYTES - (words - 1) * 8, words, 0
			};
			uint16 operation = 0x0107;
#ifdef VIEWPORT_DEBUG_DAMAGE
			if (s_damageDebugOverlay) operation = 0x0106;
#endif
			Video_Atari_QueueTintBlit(&plan, checkerboard, operation, (uint16 *)dst, lines);
		} else {
			Atari_SupervisorExec(Video_Atari_PlacementTintBlit);
		}
		return;
	}
	for (line = 0; line < lines; line++) {
		uint16 *p = (uint16 *)(dst + (uint32)line * ST_PLANAR_LINE_BYTES);
		uint16 pattern = (line & 1) ? 0x5555 : 0xaaaa;

		for (group = 0; group < words; group++) {
#ifdef VIEWPORT_DEBUG_DAMAGE
			if (s_damageDebugOverlay) {
				p[group * 4] ^= pattern;
				continue;
			}
#endif
			p[group * 4] |= pattern;
		}
	}
}

#ifdef VIEWPORT_DEBUG_DAMAGE
static void Video_Atari_DebugDamageTint(void)
{
	uint16 row, col;

	for (row = 0; row < 10; row++) {
		for (col = 0; col < 15; col++) {
			if ((s_damageDebugRows[row] & (1u << col)) != 0)
				Video_Atari_PlacementTint(col << 4, (row << 4) + 40, 16, 16, s_damageDebugAccepted);
		}
	}
}

void Video_Atari_DebugDamageBegin(const uint16 rows[10], bool accepted)
{
	assert(s_curDirect && !s_damageDebugOverlay);
	s_damageDebugOverlay = true;
	s_damageDebugAccepted = accepted;
	memcpy(s_damageDebugRows, rows, sizeof(s_damageDebugRows));
	GUI_Mouse_Hide();
	Video_Atari_CursorEraseFull();
	Video_Atari_DebugDamageTint();
}

void Video_Atari_DebugDamageEnd(void)
{
	assert(s_damageDebugOverlay);
	Video_Atari_DebugDamageTint();
	if (s_viewportBlitter) while ((*BLITTER_CTRL & 0x80) != 0) {}
	s_damageDebugOverlay = false;
	GUI_Mouse_Show();
	Video_Atari_CursorSync(Video_Atari_PlanarBase());
}
#endif

static const uint16 s_tileCursorPatterns[6][16] = {
	{ 0xf00f, 0x8001, 0x8001, 0x8001, 0, 0, 0, 0, 0, 0, 0, 0, 0x8001, 0x8001, 0x8001, 0xf00f },
	{ 0xfc3f, 0x8001, 0x8001, 0x8001, 0x8001, 0x8001, 0x0080, 0x0080, 0x03e0, 0x0080, 0x8081, 0x8001, 0x8001, 0x8001, 0x8001, 0xfc3f },
	{ 0xf00f, 0x8001, 0x8001, 0x8001, 0x0180, 0x03c0, 0x07e0, 0x0ff0, 0, 0, 0, 0, 0x8001, 0x8001, 0x8001, 0xf00f },
	{ 0xf00f, 0x8001, 0x8001, 0x8001, 0x0080, 0x00c0, 0x00e0, 0x00f0, 0x00f0, 0x00e0, 0x00c0, 0x0080, 0x8001, 0x8001, 0x8001, 0xf00f },
	{ 0xf00f, 0x8001, 0x8001, 0x8001, 0, 0, 0, 0, 0x0ff0, 0x07e0, 0x03c0, 0x0180, 0x8001, 0x8001, 0x8001, 0xf00f },
	{ 0xf00f, 0x8001, 0x8001, 0x8001, 0x0100, 0x0300, 0x0700, 0x0f00, 0x0f00, 0x0700, 0x0300, 0x0100, 0x8001, 0x8001, 0x8001, 0xf00f }
};
static const uint8 s_tileCursorOperations[16][4] = {
	{4,4,4,4}, {7,4,4,4}, {4,7,4,4}, {7,7,4,4},
	{4,4,7,4}, {7,4,7,4}, {4,7,7,4}, {7,7,7,4},
	{4,4,4,7}, {7,4,4,7}, {4,7,4,7}, {7,7,4,7},
	{4,4,7,7}, {7,4,7,7}, {4,7,7,7}, {7,7,7,7}
};
static const uint16 *s_viewportFogWritable[10][15];
static uint16 s_viewportProtectedRows[10], s_viewportHiddenRows[10];
static bool s_viewportProtectionActive;
void (*g_videoTileCursorTail)(void);
Video_Atari_TileCursorBlit g_videoTileCursorBlit;
bool g_videoTileCursorRestored;
static uint16 s_tileCursorCol, s_tileCursorTop;
static uint16 s_tileCursorPixels[64], s_tileCursorMasks[64], s_tileCursorPen;
static const uint16 *s_tileCursorPattern;
static Video_Atari_SpriteBlitPlan s_tileCursorPlan;
static Video_Atari_SpriteBlitCode s_tileCursorCode;

typedef struct AtariTileCursorBackend {
	void (*prepare)(const uint16 *, uint16);
	void (*blit)(void);
} AtariTileCursorBackend;

static void Video_Atari_PrepareColourTileCursor(const uint16 *, uint16);
static void Video_Atari_PrepareMonoTileCursor(const uint16 *, uint16);
static void Video_Atari_BlitMonoTileCursor(void);
static const AtariTileCursorBackend s_colourTileCursorBackend = {
	Video_Atari_PrepareColourTileCursor, Video_Atari_TileCursorTail
};
static const AtariTileCursorBackend s_monoTileCursorBackend = {
	Video_Atari_PrepareMonoTileCursor, Video_Atari_BlitMonoTileCursor
};
static const AtariTileCursorBackend *s_tileCursorBackend;

static void Video_Atari_BuildSpriteBlitPlan(Video_Atari_SpriteBlitPlan *,
	uint16, uint16, uint16, uint16);

static void Video_Atari_InitTileCursorBackend(void)
{
	s_tileCursorBackend = Video_Atari_Mono() ? &s_monoTileCursorBackend : &s_colourTileCursorBackend;
	s_tileCursorPattern = NULL;
}

static void Video_Atari_PrepareColourTileCursor(const uint16 *pattern, uint16 pen)
{
	uint16 line, plane;
	for (line = 0; line < 16; line++)
		for (plane = 0; plane < 4; plane++)
			s_tileCursorPixels[line * 4 + plane] = (pen & (1u << plane)) != 0 ? pattern[line] : 0;
	g_videoTileCursorBlit.pattern = pattern;
	g_videoTileCursorBlit.operations = s_tileCursorOperations[pen];
}

static void Video_Atari_PrepareMonoTileCursor(const uint16 *pattern, uint16 pen)
{
	uint16 line;
	for (line = 0; line < 16; line++) {
		uint16 words[4];
		Video_Atari_MonoPenWords(pen, 0, line, words);
		Video_Atari_MonoWriteGroup(s_tileCursorPixels, 4, line, 0, words);
	}
	Video_Atari_MonoMaskBitmap(s_tileCursorPixels, s_tileCursorMasks, pattern, 16, 16);
	Video_Atari_BuildSpriteBlitPlan(&s_tileCursorPlan, 16, 0, 16, 0);
	Video_Atari_CompileSpriteBlitCode(&s_tileCursorCode, 0x11);
}

static void Video_Atari_PrepareTileCursor(uint16 col, uint16 row, const uint16 *pattern, uint16 pen)
{
	assert(pen < 16);
	if (s_tileCursorPattern != pattern || s_tileCursorPen != pen) {
		/* Queued commands reference this frame-stable native storage. */
		Video_Atari_DisplayListFlush();
		s_tileCursorBackend->prepare(pattern, pen);
		s_tileCursorPattern = pattern;
		s_tileCursorPen = pen;
	}
	s_tileCursorCol = col;
	s_tileCursorTop = 40 + row * 16;
	g_videoTileCursorBlit.dst = Video_Atari_PlanarBase() +
	    (uint32)s_tileCursorTop * ST_PLANAR_LINE_BYTES + ((col * 16) >> s_planarBackend->xShift);
}

static void Video_Atari_DrawTileCursorCPU(void)
{
	uint16 line;
	for (line = 0; line < 16; line++) {
		uint16 words[4];
		s_planarBackend->readGroup(s_tileCursorPixels, 4, line, 0, words);
		Video_Atari_PlanarMergeGroup(Video_Atari_PlanarBase(),
		    s_tileCursorTop + line, s_tileCursorCol, s_tileCursorPattern[line], words);
	}
	g_videoTileCursorRestored = true;
}

void Video_Atari_ResetViewportProtection(void)
{
	memset(s_viewportFogWritable, 0, sizeof(s_viewportFogWritable));
	memset(s_viewportProtectedRows, 0, sizeof(s_viewportProtectedRows));
	memset(s_viewportHiddenRows, 0, sizeof(s_viewportHiddenRows));
	Video_Atari_EndViewportProtection();
	s_tileCursorPattern = NULL;
	s_blitterHalftonePattern = NULL;
}

void Video_Atari_SetViewportFog(uint16 col, uint16 row, const uint16 *writable)
{
	uint16 line, any = 0, all = 0xffff, bit = 1u << col;

	assert(col < 15 && row < 10);
	if (writable != NULL) {
		for (line = 0; line < 16; line++) {
			any |= writable[line];
			all &= writable[line];
		}
		if (all == 0xffff) writable = NULL;
	}
	s_viewportFogWritable[row][col] = writable;
	s_viewportProtectedRows[row] &= (uint16)~bit;
	s_viewportHiddenRows[row] &= (uint16)~bit;
	if (writable == NULL) return;
	s_viewportProtectedRows[row] |= bit;
	if (any == 0) s_viewportHiddenRows[row] |= bit;
}

void Video_Atari_BeginViewportProtection(bool cursor, uint16 col, uint16 row, VideoAtariTileCursorShape shape)
{
	s_viewportProtectionActive = true;
	g_videoTileCursorTail = NULL;
	g_videoTileCursorRestored = false;
	if (!cursor) return;
	assert(col < 15 && row < 10);
	assert(shape >= TILE_CURSOR_NORMAL && shape <= TILE_CURSOR_SCROLL_LEFT);
	Video_Atari_PrepareTileCursor(col, row, s_tileCursorPatterns[shape],
	    shape == TILE_CURSOR_TARGET ? g_tileCursorTargetPen : g_tileCursorPen);
	g_videoTileCursorTail = s_viewportBlitter ? s_tileCursorBackend->blit : Video_Atari_DrawTileCursorCPU;
}

void Video_Atari_EndViewportProtection(void)
{
	g_videoTileCursorTail = NULL;
	s_viewportProtectionActive = false;
}

static bool Video_Atari_ViewportProtectionOverlap(uint16 x, uint16 y, uint16 width, uint16 height)
{
	uint16 row, end = (y + height - 41) >> 4;
	uint16 columns = (0x7fff >> (15 - ((x + width + 15) >> 4))) & (0x7fff << (x >> 4));

	if (!s_viewportProtectionActive) return false;
	for (row = (y - 40) >> 4; row <= end; row++)
		if ((s_viewportProtectedRows[row] & columns) != 0) return true;
	return false;
}

static const uint16 *Video_Atari_ViewportWritable(uint16 col, uint16 row)
{
	return s_viewportFogWritable[row][col];
}

/* Battlefield tile cursor: a one-tile frame in an exact pen. The blitter
 * runs from line 0 of the halftone RAM on every start, so the 16 words are
 * the tile's lines. Idempotent like the placement tint; the tile is redrawn
 * to remove it. */
void Video_Atari_TileCursorFrame(uint16 col, uint16 row, VideoAtariTileCursorShape shape)
{
	uint16 pen = shape == TILE_CURSOR_TARGET ? g_tileCursorTargetPen : g_tileCursorPen;
	const uint16 *pattern, *savedPattern;
	uint16 savedCol, savedTop, savedPen;
	bool restored;

	if (col >= 15 || row >= 10) return;
	assert(shape >= TILE_CURSOR_NORMAL && shape <= TILE_CURSOR_SCROLL_LEFT);
	if (g_videoScrollPending) Video_Atari_FinishScroll();
	pattern = s_tileCursorPatterns[shape];
	if (g_videoTileCursorTail != NULL && col == s_tileCursorCol &&
	    40 + row * 16 == s_tileCursorTop && pattern == s_tileCursorPattern && pen == s_tileCursorPen) {
		if (!g_videoTileCursorRestored) Video_Atari_RestoreTileCursor();
		return;
	}
	Video_Atari_DisplayListFlush();
	savedPattern = s_tileCursorPattern;
	savedCol = s_tileCursorCol; savedTop = s_tileCursorTop; savedPen = s_tileCursorPen;
	restored = g_videoTileCursorRestored;
	Video_Atari_PrepareTileCursor(col, row, pattern, pen);
	if (s_viewportBlitter) Atari_SupervisorExec(s_tileCursorBackend->blit);
	else Video_Atari_DrawTileCursorCPU();
	if (savedPattern != NULL)
		Video_Atari_PrepareTileCursor(savedCol, (savedTop - 40) / 16, savedPattern, savedPen);
	g_videoTileCursorRestored = restored;
}

void Video_Atari_RestoreTileCursor(void)
{
	if (g_videoTileCursorTail == NULL) return;
	assert(!Video_Atari_DisplayListPending());
	if (g_videoScrollPending) Video_Atari_FinishScroll();
	Atari_SupervisorExec(g_videoTileCursorTail);
}

/* While placing, the software cursor stays off the viewport (no restore bookkeeping). */
void Video_Atari_PlacementCursor(bool hidden)
{
	if (s_curSuppress == hidden) return;
	s_curSuppress = hidden;
	if (hidden && s_curDrawn &&
	    ((s_curDrawnGroup < 15 && s_curDrawnY + s_curDrawnH > 40) || Video_Atari_CursorSuppressed())) {
		Video_Atari_CursorEraseFull();
	}
	s_curDirty = true;
}

static void Video_Atari_PlacementEnd(uint8 *base);

void Video_Atari_PlacementHide(void)
{
	Video_Atari_PlacementCursor(false);
	if (s_placeVisible) {
		s_placeVisible = false;
		s_placeDirty = true;
	}
	if (s_placeBlockCount != 0) Video_Atari_PlacementEnd(s_placeDrawnBase);
}

static bool Video_Atari_PlacementBegin(void)
{
	if (!s_placeVisible && s_placeBlockCount == 0) {
		s_placeDirty = false;
		return false;
	}
	return s_placeDirty || (s_placeVisible && s_placePen != s_palette4BitMap[255]);
}

static void Video_Atari_PlacementEnd(uint8 *base)
{
	uint16 i, line, group, plane;

	Video_Atari_DisplayListFlush();
	for (i = 0; i < s_placeBlockCount; i++) {
		const PlacementBlock *block = &s_placeBlocks[i];
		const uint16 *p = Video_Atari_CursorBackground(s_placeDrawnBase, block->y, block->group);
		uint16 words[4];
		if (Video_Atari_Mono()) {
			memcpy(words, p, sizeof(words));
			Video_Atari_MonoMergeWords(words, block->saved, block->mask);
			Video_Atari_CursorWriteGroup(s_placeDrawnBase, block->y, block->group, words);
			continue;
		}
		for (plane = 0; plane < 4; plane++) {
			words[plane] = (p[plane] & (uint16)~block->mask) | (block->saved[plane] & block->mask);
		}
		Video_Atari_CursorWriteGroup(s_placeDrawnBase, block->y, block->group, words);
	}
	s_placeBlockCount = 0;
	memset(s_placeViewportTiles, 0, sizeof(s_placeViewportTiles));
	s_placeDirty = false;
	if (!s_placeVisible) return;

	s_placeDrawnBase = base;
	s_placeDrawnX = s_placeX;
	s_placeDrawnY = s_placeY;
	s_placeDrawnWidth = s_placeWidth;
	s_placeDrawnHeight = s_placeHeight;
	s_placePen = s_palette4BitMap[255];
	for (line = 0; line < s_placeHeight; line++) {
		int16 y = s_placeY + line;
		if (y < 40 || y >= SCREEN_HEIGHT) continue;
		for (group = 0; group < s_placeWidth / 16; group++) {
			int16 x = s_placeX + group * 16;
			uint16 mask = s_placeMask[line][group];
			const uint16 *p;
			uint16 words[4];
			PlacementBlock *block;

			if (x < 0 || x >= 240 || mask == 0) continue;
			p = Video_Atari_CursorBackground(base, (uint16)y, (uint16)(x / 16));
			block = &s_placeBlocks[s_placeBlockCount++];
			block->y = y;
			block->group = x / 16;
			block->mask = mask;
			if (Video_Atari_Mono()) {
				uint16 tint[4];
				memcpy(block->saved, p, sizeof(words));
				memcpy(words, p, sizeof(words));
				Video_Atari_MonoPenWords(s_placePen, group * 16, line, tint);
				Video_Atari_MonoMergeWords(words, tint, mask);
				Video_Atari_CursorWriteGroup(base, y, x / 16, words);
				continue;
			}
			for (plane = 0; plane < 4; plane++) {
				block->saved[plane] = p[plane];
				words[plane] = (p[plane] & (uint16)~mask) | ((s_placePen & (1u << plane)) ? mask : 0);
			}
			Video_Atari_CursorWriteGroup(base, (uint16)y, (uint16)(x / 16), words);
		}
	}
	if (s_placeBlockCount != 0)
		Video_Atari_MarkViewportTiles(s_placeViewportTiles, s_placeDrawnX, s_placeDrawnY,
		                            s_placeDrawnWidth, s_placeDrawnHeight);
}

/* ------------------------------------------------------------------
 * Direct chunky -> planar presentation ("present mode")
 *
 * Normally a visible pixel reaches the screen a tick late: the game
 * writes it into the chunky 8bpp SCREEN_0, marks the rectangle dirty,
 * and the next Video_Tick() c2p pass reads it back out and transposes it
 * into the planar screen. Present mode converts the rectangle as soon as
 * it is written and clears the dirty blocks it covered, so the c2p pass
 * is left with only whatever was written behind present mode's back.
 *
 * It is write-through: the chunky write still happens, and SCREEN_0 stays
 * a valid shadow of the visible picture. An earlier version skipped the
 * chunky write for hooked rectangles, on the theory that a sequence could
 * be audited to never read SCREEN_0 back. That turned out to be far too
 * fragile -- chunky SCREEN_0 is also the XOR accumulator that WSA
 * animations decode their frame deltas into, so the intro's continuation
 * animations (INTRO7B, INTRO8B, INTRO8C, which carry no first frame)
 * silently accumulated garbage. See ATARI_SCREEN0_PLANARIZATION.md.
 *
 * What is left is worth having on its own: no one-tick lag, and no
 * partially converted frames. The visible win is that a picture appears
 * atomically instead of being revealed piecemeal by the next c2p pass.
 *
 * Presentation bakes pen numbers in: c2p resolves every chunky byte
 * through the current quantization, and pixels keep the pens they were
 * converted with until something re-converts them. The game routinely
 * draws a picture while the palette is still all black and only then
 * fades it in, so presenting naively would bake black pens into
 * everything.
 *
 * The fix exploits the fact that on ST/STE the software quantization and
 * the 16 hardware colour registers are independent: Video_SetPalette()
 * only rebuilds the chunky->pen tables and never calls Setcolor(), while
 * the registers are moved only by the fade helpers. So an enclave calls
 * Video_Atari_PresentPalette() with the picture's real palette *before*
 * drawing it. The pens are then correct from the first converted pixel,
 * and the picture stays invisible anyway because the registers are still
 * black - exactly the state the following fade-in ramps up from. Native
 * assets have no chunky shadow: palette changes inside the enclave must
 * not trigger a reconstruction from SCREEN_0.
 */

static bool s_presentMode = false;

static uint8 *Video_Atari_PlanarBase(void)
{
	if (s_planarBase != NULL) return s_planarBase;
	return (uint8 *)Logbase() + s_center_image_offset;
}

/* Direct access to the live planar screen for callers that draw it in place. A drawn cursor
 * over the rectangle is restored first, so stale backup pixels cannot overwrite the new ones;
 * the next cursor sync draws it again. */
uint16 *Video_Atari_LiveBegin(uint16 x, uint16 y, uint16 width, uint16 height)
{
	uint8 *base = Video_Atari_PlanarBase();

	Video_Atari_DisplayListFlush();
	if (Video_Atari_CursorRectOverlap(base, x >> 4, (x + width + 15) >> 4, y, height))
		Video_Atari_CursorEraseFull();
	return (uint16 *)(base + (uint32)y * ST_PLANAR_LINE_BYTES +
		(uint32)(x >> 4) * Video_Atari_GroupWords() * sizeof(uint16));
}

void Video_Atari_LiveEnd(uint16 x, uint16 y, uint16 width, uint16 height)
{
	Video_Atari_RestoreTileCursor();
	GFX_Screen_ClearDirtyRect(x & ~15, y, (x + width + 15) & ~15, y + height);
	if (s_viewportBlitter) Video_Atari_CursorSync(Video_Atari_PlanarBase());
}

static void Video_Atari_PublishSpriteRows(uint8 *, const uint16 *, const uint16 *,
	uint16, uint16, uint16, uint16, uint16, uint16, bool, bool, const uint16 *, uint16);

static void Video_Atari_PublishNativeRect(const uint16 *pixels, const uint16 *masks,
	uint16 sourceWidth, uint16 sourceX, uint16 width, uint16 height,
	int16 x, int16 y)
{
	int left = max(0, x), right = min(SCREEN_WIDTH, (int)x + width);
	int top = max(0, y), bottom = min(SCREEN_HEIGHT, (int)y + height);
	uint8 *base = Video_Atari_PlanarBase();
	if (left >= right || top >= bottom) return;
	Video_Atari_DisplayListFlush();
	pixels += (uint32)(top - y) * (sourceWidth / 4);
	if (masks != NULL) masks += (uint32)(top - y) * (sourceWidth / 16);
	Video_Atari_PublishSpriteRows(base, pixels, masks, sourceWidth, sourceX + left - x,
	    right - left, bottom - top, left, top, false,
	    Video_Atari_PlanarOverlaysOverlap(base, left, top, right - left, bottom - top), NULL, 0);
	Video_Atari_RestoreTileCursor();
	GFX_Screen_ClearDirtyRect(left & ~15, top, (right + 15) & ~15, bottom);
}

static void Video_Atari_MonoChunky(const uint8 *src, uint16 stride,
	uint16 x, uint16 y, uint16 width, uint16 height, bool transparent,
	int16 originX, int16 originY)
{
	uint16 pixels[SCREEN_WIDTH / 4 * 8], masks[SCREEN_WIDTH / 16 * 8];
	uint16 padded = (width + 15) & ~15, row;
	for (row = 0; row < height; row += 8) {
		uint16 lines = min(8, height - row), line, col;
		AtariDitherSource source = {src + (uint32)row * stride, width, lines, stride,
			originX, originY + row, 1, 1};
		Video_Atari_PreparePlanar(&source, NULL, pixels);
		for (line = 0; line < lines; line++) {
			uint16 *m = masks + line * (padded / 16);
			memset(m, 0, padded / 16 * sizeof(*m));
			for (col = 0; col < width; col++)
				if (!transparent || source.pixels[line * stride + col] != 0)
					m[col >> 4] |= 0x8000u >> (col & 15);
		}
		Video_Atari_PublishNativeRect(pixels, masks, padded, 0, width, lines, x, y + row);
	}
}

/* Flat-colour planar fill. Unlike the c2p path this handles rectangles
 * that do not start/end on a 16 pixel group boundary, by masking the
 * partially covered groups. */
static void Video_Atari_PlanarFill(uint16 x, uint16 y, uint16 w, uint16 h, uint8 pen)
{
	if (Video_Atari_Mono()) {
		uint16 row, group, right = x + w;
		Video_Atari_DisplayListFlush();
		for (row = 0; row < h; row++) {
			for (group = x / 16; group < (right + 15) / 16; group++) {
				uint16 words[4], mask = 0xffff;
				if (group * 16 < x) mask &= 0xffffu >> (x & 15);
				if ((group + 1) * 16 > right) mask &= 0xffffu << (16 - (right & 15));
				Video_Atari_MonoPenWords(pen, group * 16 - x, row, words);
				Video_Atari_PlanarMergeGroup(Video_Atari_PlanarBase(), y + row, group, mask, words);
			}
		}
		return;
	}
	uint8 *base = Video_Atari_PlanarBase();
	bool overlays = Video_Atari_PlanarOverlaysOverlap(base, x, y, w, h);
	uint16 first = (uint16)(x >> 4);
	uint16 last = (uint16)((x + w + 15) >> 4);	/* exclusive */
	uint16 *row = (uint16 *)(base + (uint32)y * ST_PLANAR_LINE_BYTES + first * 8);
	uint16 g, line, plane;

	Video_Atari_DisplayListFlush();
	for (line = 0; line < h; line++) {
		uint16 *dst = row;
		for (g = first; g < last; g++) {
			uint16 gx = (uint16)(g << 4);
			uint16 a = (x > gx) ? (uint16)(x - gx) : 0;
			uint16 b = ((uint16)(x + w) < (uint16)(gx + 16)) ? (uint16)(x + w - gx) : 16;
			uint16 mask = (uint16)((0xFFFFu >> a) & (0xFFFFu << (16 - b)));
			uint16 pixels[4];

			for (plane = 0; plane < 4; plane++) {
				pixels[plane] = (pen & (1u << plane)) ? mask : 0;
			}
			if (overlays) {
				Video_Atari_PlanarMergeGroup(base, (uint16)(y + line), g, mask, pixels);
			} else {
				Video_Atari_PlanarMergePlain(dst, mask, pixels);
			}
			dst += 4;
		}
		row += ST_PLANAR_LINE_BYTES / sizeof(uint16);
	}
	Video_Atari_RestoreTileCursor();
}

static void Video_Atari_PublishPlanarRun(uint8 *base, const uint8 *pixels, uint16 srcStride,
	uint16 x, uint16 y, uint16 width, uint16 height)
{
	s_planarBackend->copyRun(base + (uint32)y * ST_PLANAR_LINE_BYTES +
		(x >> s_planarBackend->xShift), ST_PLANAR_LINE_BYTES,
		pixels, srcStride, width / 16, height);
	Video_Atari_PlanarFinishRun(base, x, y, width, height);
}

/* Source and destination have matching group phase; strides count bytes per logical row. */
static void Video_Atari_PublishPlanarRect(const uint8 *pixels, uint16 srcStride, uint16 sourceX,
	uint16 x, uint16 y, uint16 width, uint16 height)
{
	uint8 *base = Video_Atari_PlanarBase();
	uint16 right = x + width, first = x / 16, last = (right - 1) / 16;
	uint16 firstFull = (x + 15) & ~15, endFull = right & ~15, row;

	assert(pixels != NULL && width != 0 && height != 0 &&
		(uint32)x + width <= SCREEN_WIDTH && (uint32)y + height <= SCREEN_HEIGHT);
	assert(((sourceX ^ x) & 15) == 0);
	Video_Atari_DisplayListFlush();
	if (endFull > firstFull)
		Video_Atari_PublishPlanarRun(base, pixels +
			((sourceX + firstFull - x) >> s_planarBackend->xShift), srcStride,
			firstFull, y, endFull - firstFull, height);
	for (row = 0; row < height; row++) {
		uint16 edge;
		for (edge = 0; edge < 2; edge++) {
			uint16 group = edge == 0 ? first : last, words[4], mask = 0xffff;
			if (edge == 0) {
				if ((x & 15) == 0) continue;
				mask >>= x & 15;
				if (first == last && (right & 15) != 0) mask &= 0xffffu << (16 - (right & 15));
			} else {
				if ((right & 15) == 0 || ((x & 15) != 0 && first == last)) continue;
				mask <<= 16 - (right & 15);
			}
			s_planarBackend->copyRun((uint8 *)words, sizeof(words), pixels +
				(uint32)row * srcStride + ((sourceX + group * 16 - x) >> s_planarBackend->xShift),
				srcStride, 1, 1);
			Video_Atari_PlanarMergeGroup(base, y + row, group, mask, words);
		}
	}
	Video_Atari_RestoreTileCursor();
	GFX_Screen_ClearDirtyRect(first * 16, y, (last + 1) * 16, y + height);
}

static void Video_Atari_ConvertRun(uint8 *base, const uint8 *src, uint16 srcStride,
	uint16 x, uint16 y, uint16 w, uint16 h, int16 originX, int16 originY)
{
	AtariDitherSource source = {src, w, h, srcStride, originX, originY, 1, 1};
	Video_Atari_DisplayListFlush();
	s_planarBackend->convert(&source, NULL,
		(uint16 *)(base + (uint32)y * ST_PLANAR_LINE_BYTES + (x >> s_planarBackend->xShift)), 80);
	Video_Atari_PlanarFinishRun(base, x, y, w, h);
}

static void Video_Atari_PresentRun(const uint8 *src, uint16 srcStride,
	uint16 x, uint16 y, uint16 w, uint16 h)
{
	Video_Atari_ConvertRun(Video_Atari_PlanarBase(), src, srcStride, x, y, w, h, 0, 0);
}

/* Convert one partially covered 16 pixel group and merge it into what is
 * already on screen. Only source pixels inside [x0,x1) are read, so this
 * stays in bounds even when the source row is exactly as wide as the
 * rectangle (a WSA frame buffer, for instance). */
static void Video_Atari_PresentGroupMasked(const uint8 *srcRow, uint16 gx,
                                           uint16 x0, uint16 x1, uint8 *base, uint16 y,
                                           uint16 sourceY)
{
	uint16 a = (x0 > gx) ? (uint16)(x0 - gx) : 0;
	uint16 b = (x1 < (uint16)(gx + 16)) ? (uint16)(x1 - gx) : 16;
	uint16 mask = (uint16)((0xFFFFu >> a) & (0xFFFFu << (16 - b)));
	uint16 pl[4], chunky[8] = {0};
	AtariDitherSource source = {(const uint8 *)chunky, 16, 1, 16,
		(int16)(gx - x0), sourceY, 1, 1};

	memcpy((uint8 *)chunky + a, srcRow + gx + a - x0, b - a);
	s_planarBackend->convert(&source, NULL, pl, 4);
	Video_Atari_PlanarMergeGroup(base, y, gx / 16, mask, pl);
}

/* Present a rectangle whose left edge and/or width are not multiples of
 * 16. The interior, which is group aligned, still goes through the fast
 * c2p; only the (at most two) partially covered edge groups take the
 * read-modify-write path above. */
static void Video_Atari_PresentRunMasked(const uint8 *src, uint16 srcStride,
                                         uint16 x, uint16 y, uint16 w, uint16 h)
{
	Video_Atari_DisplayListFlush();
	uint16 x1 = (uint16)(x + w);
	int gLeft = (int)(x >> 4);
	int gRight = (int)((x1 - 1) >> 4);	/* group holding the last pixel */
	int firstFull = ((x & 0xf) != 0) ? gLeft + 1 : gLeft;
	int lastFull = ((x1 & 0xf) != 0) ? gRight - 1 : gRight;
	/* A group is partial when its 16 pixel span is not wholly inside the
	 * rectangle. When both edges fall in the same group, that one group
	 * is partial and the single masked call below covers both edges. */
	bool doLeft = ((x & 0xf) != 0) || (gLeft == gRight && (x1 & 0xf) != 0);
	bool doRight = (gRight != gLeft) && ((x1 & 0xf) != 0);
	uint8 *base = Video_Atari_PlanarBase();
	uint16 line;

	if (lastFull >= firstFull) {
		const uint8 *fullSrc = src + (uint16)((firstFull << 4) - (int)x);

		if ((((uint32)fullSrc) & (s_planarBackend->chunkyAlignment - 1)) ||
		    ((srcStride & (s_planarBackend->chunkyAlignment - 1)) != 0 && h > 1)) {
			/* Stage unaligned colour sources through the edge converter's
			 * aligned scratch instead of faulting on word-wide pair reads. */
			const uint8 *mSrc = src;
			int g;

			for (line = 0; line < h; line++) {
				for (g = firstFull; g <= lastFull; g++) {
					Video_Atari_PresentGroupMasked(mSrc, (uint16)(g << 4), x, x1,
					                               base, (uint16)(y + line), line);
				}
				mSrc += srcStride;
			}
		} else {
			Video_Atari_ConvertRun(base, fullSrc, srcStride,
				(uint16)(firstFull << 4), y,
				(uint16)((lastFull - firstFull + 1) << 4), h,
				(uint16)((firstFull << 4) - x), 0);
		}
	}

	if (!doLeft && !doRight) return;

	for (line = 0; line < h; line++) {
		if (doLeft) {
			Video_Atari_PresentGroupMasked(src, (uint16)(gLeft << 4), x, x1,
			                               base, (uint16)(y + line), line);
		}
		if (doRight) {
			Video_Atari_PresentGroupMasked(src, (uint16)(gRight << 4), x, x1,
			                               base, (uint16)(y + line), line);
		}
		src += srcStride;
	}
}

/* Like Video_Atari_PresentGroupMasked(), but a source byte of 0 means
 * "transparent" (skip this pixel, leave the existing planar bit alone)
 * instead of being a real colour to draw. Unlike the alignment-only mask
 * above, this must inspect every covered pixel's content, not just its
 * position -- there is no "fully covered, no need to check" fast case. */
static uint16 Video_Atari_ConvertGroupTransparent(const uint8 *srcRow, uint16 gx,
                                                 uint16 x0, uint16 x1, uint16 pl[4])
{
	uint16 a = (x0 > gx) ? (uint16)(x0 - gx) : 0;
	uint16 b = (x1 < (uint16)(gx + 16)) ? (uint16)(x1 - gx) : 16;
	uint16 mask = 0;
	uint16 i;

	pl[0] = pl[1] = pl[2] = pl[3] = 0;

	for (i = a; i < b; i++) {
		uint8 src = srcRow[gx + i - x0];
		uint16 bit;
		uint8 pen;

		if (src == 0) continue;

		bit = (uint16)(0x8000u >> i);
		mask |= bit;

		pen = s_palette4BitMap[src];
		if (pen & 1) pl[0] |= bit;
		if (pen & 2) pl[1] |= bit;
		if (pen & 4) pl[2] |= bit;
		if (pen & 8) pl[3] |= bit;
	}

	return mask;
}

/* Present a small, content-transparent rectangle (glyphs): every 16 pixel
 * group the rectangle touches goes through the masked merge above, since
 * a group may hold a mix of drawn and transparent pixels anywhere within
 * it, not just at its edges. Rectangles are expected to be tiny (a
 * handful of groups at most), so there is no need for the fast unmasked
 * middle-groups path that Video_Atari_PresentRunMasked() has. */
static void Video_Atari_PresentTransparent(const uint8 *src, uint16 srcStride,
                                           uint16 x, uint16 y, uint16 w, uint16 h)
{
	Video_Atari_DisplayListFlush();
	uint16 x1 = (uint16)(x + w);
	int gLeft = (int)(x >> 4);
	int gRight = (int)((x1 - 1) >> 4);
	uint8 *base = Video_Atari_PlanarBase();
	uint16 line;

	if (!Video_Atari_PlanarOverlaysOverlap(base, x, y, w, h)) {
		uint16 *row = (uint16 *)(base + (uint32)y * ST_PLANAR_LINE_BYTES + gLeft * 8);

		for (line = 0; line < h; line++) {
			uint16 *dst = row;
			int g;

			for (g = gLeft; g <= gRight; g++) {
				uint16 pl[4];
				uint16 mask = Video_Atari_ConvertGroupTransparent(src, (uint16)(g << 4), x, x1, pl);
				if (mask != 0) Video_Atari_PlanarMergePlain(dst, mask, pl);
				dst += 4;
			}
			src += srcStride;
			row += ST_PLANAR_LINE_BYTES / sizeof(uint16);
		}
		return;
	}

	for (line = 0; line < h; line++) {
		int g;

		for (g = gLeft; g <= gRight; g++) {
			uint16 pl[4];
			uint16 mask = Video_Atari_ConvertGroupTransparent(src, (uint16)(g << 4), x, x1, pl);
			if (mask != 0) Video_Atari_PlanarMergeGroup(base, (uint16)(y + line),
			                                         (uint16)g, mask, pl);
		}
		src += srcStride;
	}
}

/* GFX_CopyToBuffer()/GFX_CopyFromBuffer() (modal message boxes, the drag
 * preview and, in principle, the mouse cursor fallback) save a rectangle
 * before overwriting it and blit it back afterwards. On ST/STE
 * the planar screen is the only buffer guaranteed to hold what is
 * actually visible -- direct-to-planar draws (see GUI_DrawSprite()'s
 * toPlanar path) never touch SCREEN_0 or SCREEN_1 at all. So instead of
 * saving/restoring through a chunky shadow that may not agree with the
 * screen, these two save and restore the raw planar bytes of the
 * (16px-group-aligned) rectangle directly: a plain per-line memcpy,
 * blind to pixel content, palette or dirty-block accounting. The pair is
 * exact -- restoring puts back exactly what was there, regardless of how
 * it got drawn -- and self-consistent, since both compute the same
 * widened rectangle from the same (x, width) the caller passes both
 * times. Saves exclude mouse and placement pixels; restores reapply the
 * current overlays and update their backgrounds. PresentRestore clears the dirty blocks it
 * covers (same reasoning as Video_Atari_PresentChunky()) so a later
 * Video_Tick() sweep never reconverts this rectangle from stale SCREEN_1
 * content. Callers are expected to size their buffer for the chunky
 * (1 byte/pixel) rectangle, same as on other platforms; the planar
 * encoding is at most 2 pixels/byte, so that allocation is always enough
 * as long as the rectangle is at least 16 pixels wide (true for every
 * current caller -- the mouse cursor fallback this also covers is dead
 * code under Video_Atari_CursorDirect(), see GUI_Mouse_Show()/Hide()). */
bool Video_Atari_PresentSave(int16 x, int16 y, uint16 width, uint16 height, uint8 *buffer)
{
	uint16 left, right, bytesPerLine;
	uint8 *base = Video_Atari_PlanarBase();
	const uint8 *src;

	if (buffer == NULL || width == 0 || height == 0) return false;
	if (x < 0 || y < 0) return false;
	if ((int)y + (int)height > SCREEN_HEIGHT) return false;

	left = (uint16)(x & ~0xf);
	right = (uint16)((x + width + 0xf) & ~0xf);
	if (right > SCREEN_WIDTH) right = SCREEN_WIDTH;
	bytesPerLine = (uint16)(((right - left) >> 4) << 3);

	Video_Atari_DisplayListFlush();
	if (Video_Atari_Mono()) {
		uint16 row, group;
		for (row = 0; row < height; row++) {
			for (group = left / 16; group < right / 16; group++) {
				uint16 words[4];
				PlacementBlock *block = Video_Atari_PlacementBlock(base, y + row, group);
				memcpy(words, Video_Atari_CursorBackground(base, y + row, group), sizeof(words));
				if (block != NULL) Video_Atari_MonoMergeWords(words, block->saved, block->mask);
				Video_Atari_MonoWriteGroup((uint16 *)buffer, bytesPerLine / 2,
					row, group - left / 16, words);
			}
		}
		return true;
	}
	src = base + (uint32)y * ST_PLANAR_LINE_BYTES + (uint32)(left >> 4) * 8;

	while (height-- != 0) {
		uint16 group;
		memcpy(buffer, src, bytesPerLine);
		if (s_curDrawn && base == s_curDrawnBase && y >= s_curDrawnY && y < s_curDrawnY + s_curDrawnH) {
			uint16 first = max(left >> 4, s_curDrawnGroup);
			uint16 end = min(right >> 4, s_curDrawnGroup + s_curDrawnGroups);
			for (group = first; group < end; group++) {
				memcpy(buffer + (group - (left >> 4)) * 8,
				       Video_Atari_CursorBackground(base, (uint16)y, group), 8);
			}
		}
		if (base == s_placeDrawnBase) {
			uint16 i;
			for (i = 0; i < s_placeBlockCount; i++) {
				const PlacementBlock *block = &s_placeBlocks[i];
				uint16 words[4], plane;
				uint8 *saved;
				if (block->y != y || block->group < (left >> 4) || block->group >= (right >> 4)) continue;
				saved = buffer + (block->group - (left >> 4)) * 8;
				memcpy(words, saved, sizeof(words));
				for (plane = 0; plane < 4; plane++) {
					words[plane] = (uint16)((words[plane] & (uint16)~block->mask) |
					                       (block->saved[plane] & block->mask));
				}
				memcpy(saved, words, sizeof(words));
			}
		}
		buffer += bytesPerLine;
		src += ST_PLANAR_LINE_BYTES;
		y++;
	}
	return true;
}

bool Video_Atari_PresentRestore(int16 x, int16 y, uint16 width, uint16 height, const uint8 *buffer)
{
	return Video_Atari_PresentRestoreStrided(x, y, width, height, buffer, 0);
}

bool Video_Atari_PresentRestoreStrided(int16 x, int16 y, uint16 width, uint16 height,
                                     const uint8 *buffer, uint16 srcStride)
{
	uint16 left, right, bytesPerLine;

	if (buffer == NULL || width == 0 || height == 0) return false;
	if (x < 0 || x >= SCREEN_WIDTH || y < 0) return false;
	if ((int)y + (int)height > SCREEN_HEIGHT) return false;

	left = (uint16)(x & ~0xf);
	right = width > SCREEN_WIDTH - x ? SCREEN_WIDTH : (uint16)((x + width + 0xf) & ~0xf);
	bytesPerLine = (uint16)(((right - left) >> 4) << 3);
	if (srcStride == 0) srcStride = bytesPerLine;
	if (srcStride < bytesPerLine) return false;
	Video_Atari_PublishPlanarRect(buffer, srcStride, 0,
		left, (uint16)y, right - left, height);
	return true;
}

uint16 Video_Atari_GetPaletteGeneration(void)
{
	return s_paletteGeneration;
}

uint8 Video_Atari_GetPalettePen(uint8 colour)
{
	return s_palette4BitMap[colour];
}

static void Video_Atari_EncodePlanarPens(const uint8 *pens, uint16 *pixels,
                                        uint16 width, uint16 height, uint16 dstStride)
{
	assert(Video_Atari_CursorDirect() && pens != NULL && pixels != NULL);
	assert(((size_t)pens & 1) == 0 && height != 0 && height <= SCREEN_HEIGHT);
	assert(width != 0 && width <= SCREEN_WIDTH && (width & 15) == 0);
	assert(dstStride >= width / 2 && (dstStride & 1) == 0);
	if (height == 1 || (width == SCREEN_WIDTH && dstStride == SCREEN_WIDTH / 2))
		c2p1x1_4_st_pens(pixels, pens, width, height);
	else
		c2p1x1_4_st_pens_strided(pixels, pens, width, height, width, dstStride);
}

static void Video_Atari_ColourReadGroup(const uint16 *pixels, uint16 stride,
	uint16 row, uint16 group, uint16 words[4])
{
	memcpy(words, pixels + (uint32)row * stride + group * 4, sizeof(uint16) * 4);
}

static void Video_Atari_ComposeColourTile(const uint16 *pixels, const uint16 *masks,
	const uint16 *overlay, const uint16 *overlayMasks, uint16 *result, uint16 *resultMasks)
{
	uint16 row, plane;

	for (row = 0; row < 16; row++) {
		uint16 mask = masks[row], overlayMask = overlay == NULL ? 0 : overlayMasks[row];
		resultMasks[row] = mask | overlayMask;
		for (plane = 0; plane < 4; plane++) {
			uint16 value = pixels[row * 4 + plane] & mask;
			if (overlay != NULL) value = (value & ~overlayMask) | (overlay[row * 4 + plane] & overlayMask);
			result[row * 4 + plane] = value;
		}
	}
}

static void Video_Atari_ConvertColour(const AtariDitherSource *source,
	const AtariDitherLookup *lookup, uint16 *pixels, uint16 stride)
{
	(void)lookup;
	if (source->stride == SCREEN_WIDTH && stride == 80)
		c2p1x1_4_st_byte(pixels, source->pixels, source->width, source->height, s_palette4BitMap);
	else c2p1x1_4_st_byte_strided(pixels, source->pixels, source->width, source->height,
		s_palette4BitMap, source->stride, stride * 2);
}

static void Video_Atari_PrepareMonoCustom(const AtariDitherSource *source,
	const AtariDitherLookup *lookup, uint16 *pixels, uint16 stride)
{
	AtariMonoPackedLookup packed;
	Video_Atari_MonoPreparePackedLookup(&packed, lookup, 0, 256, s_monoWhiteIsOne);
	Video_Atari_MonoPackNative(source, &packed, pixels, stride);
}

static void Video_Atari_PrepareMono(const AtariDitherSource *source,
	const AtariDitherLookup *lookup, uint16 *pixels, uint16 stride)
{
	if (lookup == NULL || lookup == &s_palette4BitDither)
		Video_Atari_MonoPackNative(source, &s_paletteMonoPacked, pixels, stride);
	else if (lookup == &s_tileDither)
		Video_Atari_MonoPackNative(source, &s_tileMonoPacked, pixels, stride);
	else Video_Atari_PrepareMonoCustom(source, lookup, pixels, stride);
}

static void Video_Atari_PrepareColour(const AtariDitherSource *source,
	const AtariDitherLookup *lookup, uint16 *pixels, uint16 stride)
{
	union { uint32 aligned; uint8 bytes[4096]; } pens;
	uint16 width, row = 0, capacity;

	if ((lookup == NULL || lookup == &s_palette4BitDither) && s_palette4BitDither.flat &&
	    (source->width & 15) == 0 && ((size_t)source->pixels & 1) == 0 &&
	    (source->stride & 1) == 0 &&
	    memcmp(s_palette4BitDither.pens[0][0], s_palette4BitMap, sizeof(s_palette4BitMap)) == 0) {
		Video_Atari_ConvertColour(source, &s_palette4BitDither, pixels, stride);
		return;
	}
	width = (source->width + 15) & ~15;
	capacity = sizeof(pens.bytes) / width;
	if (lookup == NULL) lookup = &s_palette4BitDither;
	while (row < source->height) {
		AtariDitherSource band = *source;
		AtariDitherTarget target = {pens.bytes, width, 1};
		uint16 line;

		band.pixels += (size_t)row * source->stride;
		band.height = source->height - row;
		if (band.height > capacity) band.height = capacity;
		/* Preserve phase across bands without overflowing the signed origin. */
		band.originY = (uint16)(source->originY + (int32)row * source->stepY) & 3;
		Video_Atari_PreparePens(&band, lookup, &target);
		if (width != source->width) {
			for (line = 0; line < band.height; line++)
				memset(pens.bytes + line * width + source->width, 0, width - source->width);
		}
		Video_Atari_EncodePlanarPens(pens.bytes, pixels + (uint32)row * stride,
			width, band.height, stride * 2);
		row += band.height;
	}
}

void Video_Atari_PreparePlanar(const AtariDitherSource *source,
	const AtariDitherLookup *lookup, uint16 *pixels)
{
	assert(Video_Atari_CursorDirect() && source != NULL && pixels != NULL);
	assert(source->pixels != NULL && source->stride >= source->width);
	assert(source->width != 0 && source->width <= SCREEN_WIDTH);
	assert(source->height != 0 && source->height <= SCREEN_HEIGHT);
	assert(source->stepX == 1 || source->stepX == -1);
	assert(source->stepY == 1 || source->stepY == -1);
	s_planarBackend->prepare(source, lookup, pixels, ((source->width + 15) & ~15) / 4);
}

void Video_Atari_PrepareUnitPlanar(const AtariDitherSource *source, uint16 *pixels)
{
	assert(Video_Atari_Mono());
	Video_Atari_MonoPackNative(source, &s_unitMonoPacked, pixels, ((source->width + 15) & ~15) / 4);
}

void Video_Atari_EncodePlanar(const uint8 *src, uint16 *pixels, uint16 width, uint16 height)
{
	const AtariDitherSource source = {src, width, height, width, 0, 0, 1, 1};

	Video_Atari_PreparePlanar(&source, NULL, pixels);
}

void Video_Atari_EncodePlanarStrided(const uint8 *src, uint16 srcStride,
                                    uint16 *pixels, uint16 width, uint16 height)
{
	const AtariDitherSource source = {src, width, height, srcStride, 0, 0, 1, 1};

	Video_Atari_PreparePlanar(&source, NULL, pixels);
}

void Video_Atari_GetPlanarCacheInfo(VideoAtariPlanarCacheInfo *info)
{
	info->extension = Video_Atari_Mono() ? ".PWM" : ".PWS";
	info->format = Video_Atari_Mono() ? 0x00010001UL | (s_monoWhiteIsOne ? 0x100 : 0) : 0x00010004UL;
}

uint32 Video_Atari_PlanarMappingHash(const uint8 colours[32])
{
	uint32 hash = 5381;
	uint16 colour, x, y;
	for (colour = 0; colour < 256; colour++) {
		if ((colours[colour >> 3] & (1u << (colour & 7))) == 0) continue;
		hash = (hash * 33) ^ colour;
		for (y = 0; y < 4; y++)
			for (x = 0; x < 4; x++)
				hash = (hash * 33) ^ s_palette4BitDither.pens[y][x][colour];
	}
	return hash;
}

static bool Video_Atari_PlanarDeltaChanged(const uint16 *a, const uint16 *b, uint16 second)
{
	return a[0] != b[0] || a[1] != b[1] || a[second] != b[second] || a[second + 1] != b[second + 1];
}

uint32 Video_Atari_EncodePlanarDelta(uint16 *dst, const uint16 *previous,
	const uint16 *next, uint16 groups, uint16 height)
{
	uint16 step = Video_Atari_GroupWords(), second = step == 4 ? 2 : groups * 2;
	uint16 row, end = 0;
	uint32 words = 0;

	for (row = 0; row < height; row++) {
		uint16 column = 0;
		const uint16 *a = previous + (uint32)row * groups * 4;
		const uint16 *b = next + (uint32)row * groups * 4;
		while (column < groups) {
			uint16 first, count, i;
			if (!Video_Atari_PlanarDeltaChanged(a + column * step, b + column * step, second)) {
				column++;
				continue;
			}
			first = column++;
			while (column < groups &&
			       Video_Atari_PlanarDeltaChanged(a + column * step, b + column * step, second)) column++;
			count = column - first;
			if (dst != NULL) {
				dst[words] = row * groups + first - end;
				dst[words + 1] = count;
				for (i = 0; i < count; i++) {
					const uint16 *p = a + (first + i) * step, *q = b + (first + i) * step;
					uint16 *out = dst + words + 2 + i * 4;
					out[0] = p[0] ^ q[0];
					out[1] = p[1] ^ q[1];
					out[2] = p[second] ^ q[second];
					out[3] = p[second + 1] ^ q[second + 1];
				}
			}
			words += 2 + count * 4;
			end = row * groups + column;
		}
	}
	if (dst != NULL) dst[words] = dst[words + 1] = 0;
	return (words + 2) * sizeof(uint16);
}

void Video_Atari_ApplyPlanarDelta(uint16 *pixels, const uint16 *delta,
	uint16 groups, uint32 *dirty)
{
	uint16 step = Video_Atari_GroupWords(), second = step == 4 ? 2 : groups * 2;
	uint16 group = 0;
	while (true) {
		uint16 count, row, first;
		uint16 *dst;
		group += *delta++;
		count = *delta++;
		if (count == 0) break;
		row = group / groups;
		first = group % groups;
		dirty[row] |= ((1UL << count) - 1) << first;
		dst = pixels + (uint32)row * groups * 4 + first * step;
		group += count;
		do {
			dst[0] ^= *delta++;
			dst[1] ^= *delta++;
			dst[second] ^= *delta++;
			dst[second + 1] ^= *delta++;
			dst += step;
		} while (--count != 0);
	}
}

void Video_Atari_PresentPlanarWindow(const uint16 *pixels, uint16 x, uint16 y,
                                    uint16 width, uint16 height)
{
	assert(Video_Atari_CursorDirect());
	Video_Atari_PublishPlanarRect((const uint8 *)pixels, ST_PLANAR_LINE_BYTES, x, x, y, width, height);
}

bool Video_Atari_PresentPlanarSubRect(const uint16 *pixels, uint16 srcStride, uint16 srcX,
                                     uint16 x, uint16 y, uint16 width, uint16 height)
{
	uint16 first = x >> 4, end = (x + width + 15) >> 4, line, group;
	uint8 *base;
	bool overlays;

	if (pixels == NULL || width == 0 || height == 0 || (srcStride & 1) != 0 ||
	    (uint32)x + width > SCREEN_WIDTH || (uint32)y + height > SCREEN_HEIGHT ||
	    ((uint32)srcX + width + 15) / 16 * 8 > srcStride) return false;
	if (((srcX ^ x) & 15) == 0) {
		/* Half-group edges are full physical words in mono. In colour they
		 * use constant masks, without staging or merging the full groups. */
		if ((x & 15) == 8 && (width & 15) == 0) {
			bool isMono = Video_Atari_Mono();
			base = Video_Atari_PlanarBase();
			if ((!isMono || (srcStride & 3) == 0) &&
			    !Video_Atari_PlanarOverlaysOverlap(base, x, y, width, height)) {
				uint8 *dst = base + (uint32)y * ST_PLANAR_LINE_BYTES;
				Video_Atari_DisplayListFlush();
				if (isMono) {
					const uint8 *src = (const uint8 *)pixels + srcX / 4;
					uint16 stride = srcStride / 2, bytes = width / 4;
					dst += x / 4;
					line = height * 2;
					while (true) {
						memcpy(dst, src, bytes);
						if (--line == 0) break;
						dst += ST_PLANAR_LINE_BYTES / 2;
						src += stride;
					}
				} else {
					const uint16 *src = pixels + (srcX >> 4) * 4;
					uint16 *out = (uint16 *)dst + first * 4;
					uint16 last = (width >> 4) * 4;
					line = height;
					while (true) {
						Video_Atari_PlanarMergePlain(out, 0x00ff, src);
						for (group = 4; group < last; group += 4)
							memcpy(out + group, src + group, 8);
						Video_Atari_PlanarMergePlain(out + last, 0xff00, src + last);
						if (--line == 0) break;
						out += ST_PLANAR_LINE_BYTES / 2;
						src += srcStride / 2;
					}
				}
				Video_Atari_RestoreTileCursor();
				GFX_Screen_ClearDirtyRect(first * 16, y, end * 16, y + height);
				return true;
			}
		}
		Video_Atari_PublishPlanarRect((const uint8 *)pixels, srcStride, srcX, x, y, width, height);
		return true;
	}
	if (Video_Atari_Mono()) {
		Video_Atari_PublishNativeRect(pixels, NULL, srcStride * 2, srcX, width, height, x, y);
		return true;
	}
	Video_Atari_DisplayListFlush();
	base = Video_Atari_PlanarBase();
	overlays = Video_Atari_PlanarOverlaysOverlap(base, first * 16, y, (end - first) * 16, height);
	for (line = 0; line < height; line++) {
		const uint16 *src = (const uint16 *)((const uint8 *)pixels + (uint32)line * srcStride);
		for (group = first; group < end; group++) {
			int32 bit = (int32)group * 16 - x + srcX;
			uint16 words[4], plane, mask = 0xffff;
			if (group == first) mask &= 0xffffu >> (x & 15);
			if (group + 1 == end && ((x + width) & 15) != 0)
				mask &= 0xffffu << (16 - ((x + width) & 15));
			for (plane = 0; plane < 4; plane++) {
				if (bit < 0) {
					words[plane] = src[plane] >> -bit;
				} else {
					uint16 index = (bit >> 4) * 4, shift = bit & 15;
					words[plane] = src[index + plane] << shift;
					if (shift != 0 && (uint32)bit + 16 - shift < (uint32)srcX + width)
						words[plane] |= src[index + 4 + plane] >> (16 - shift);
				}
			}
			if (overlays) Video_Atari_PlanarMergeGroup(base, y + line, group, mask, words);
			else Video_Atari_PlanarMergePlain(
			    (uint16 *)(base + (uint32)(y + line) * ST_PLANAR_LINE_BYTES + group * 8), mask, words);
		}
	}
	Video_Atari_RestoreTileCursor();
	GFX_Screen_ClearDirtyRect(first * 16, y, end * 16, y + height);
	return true;
}

bool Video_Atari_PresentPlanarRect(const uint16 *pixels, uint16 srcStride,
                                  uint16 x, uint16 y, uint16 width, uint16 height)
{
	return Video_Atari_PresentPlanarSubRect(pixels, srcStride, 0, x, y, width, height);
}

bool Video_Atari_PresentChunkyTransparent(const void *src, uint16 srcStride,
                                          int16 x, int16 y, uint16 width, uint16 height)
{
	uint16 left, right;

	if (src == NULL || width == 0 || height == 0) return false;
	if (x < 0 || y < 0) return false;
	if ((int)x + (int)width > SCREEN_WIDTH) return false;
	if ((int)y + (int)height > SCREEN_HEIGHT) return false;

	if (Video_Atari_Mono()) {
		Video_Atari_MonoChunky(src, srcStride, x, y, width, height, true, 0, 0);
		return true;
	}
	Video_Atari_PresentTransparent((const uint8 *)src, srcStride,
	                               (uint16)x, (uint16)y, width, height);

	/* ENHANCEMENT: skip-write callers (see GUI_DrawChar()/GUI_DrawSprite())
	 * never mark this exact rectangle dirty themselves -- but an
	 * unrelated, wider dirty mark (e.g. a full-screen GFX_ClearBlock()
	 * when opening a menu) can still overlap it and linger, since nothing
	 * else "consumes" that mark for this rectangle's blocks. Left alone,
	 * a later Video_Tick() old-sweep pass would reconvert those blocks
	 * from SCREEN_1 -- which this private-scratch-buffer present never
	 * touched -- clobbering what was just drawn straight to planar with
	 * stale SCREEN_1 content. Clear the (16px-aligned) dirty blocks this
	 * covers, same as Video_Atari_PresentChunky(), so no such leftover
	 * mark can survive past this present. */
	left = (uint16)(x & ~0xf);
	right = (uint16)((x + width + 0xf) & ~0xf);
	if (right > SCREEN_WIDTH) right = SCREEN_WIDTH;
	Video_Atari_RestoreTileCursor();
	GFX_Screen_ClearDirtyRect(left, (uint16)y, right, (uint16)(y + height));

	return true;
}

bool Video_Atari_PresentActive(void)
{
	return s_presentMode;
}

void Video_Atari_InitTileMapping(const uint8 *palette)
{
	unsigned hi;

	assert(Video_Atari_CursorDirect() && palette != NULL);
	s_tileDither.flat = true;
	for (hi = 0; hi < 256; hi++) {
		const uint8 *rgb = palette + hi * 3;
		if (Video_Atari_Mono()) {
			uint8 coverage = Video_Atari_MonoCoverage(rgb[0], rgb[1], rgb[2]);
			Video_Atari_SetMonoCoverage(&s_tileDither, hi, coverage);
			Video_Atari_SetPackedMonoCoverage(&s_buildingMonoPacked, hi,
				Video_Atari_ReducedMonoCoverage(coverage));
		} else
			Video_Atari_DitherSetPen(&s_tileDither, hi, Palette_FindClosestColor(rgb[0] & 63, rgb[1] & 63, rgb[2] & 63));
	}
	if (Video_Atari_Mono())
		Video_Atari_MonoPreparePackedLookup(&s_tileMonoPacked, &s_tileDither, 0, 256, s_monoWhiteIsOne);
}

extern void Video_Atari_ExpandTileNibbles(const uint8 *src, const uint8 *pens, uint8 *chunky);

void Video_Atari_DecodePlanarTile(const uint8 *src, const uint8 *palette, uint16 *pixels)
{
	union { uint32 aligned; uint8 bytes[16 * 16]; } chunky;
	const AtariDitherSource source = {chunky.bytes, 16, 16, 16, 0, 0, 1, 1};

	assert(src != NULL && palette != NULL && pixels != NULL);
	if (!Video_Atari_Mono() && s_tileDither.flat) {
		uint8 pens[16];
		uint16 colour;
		for (colour = 0; colour < 16; colour++) pens[colour] = s_tileDither.pens[0][0][palette[colour]];
		Video_Atari_ExpandTileNibbles(src, pens, chunky.bytes);
		Video_Atari_EncodePlanarPens(chunky.bytes, pixels, 16, 16, 8);
		return;
	}
	Video_Atari_ExpandTileNibbles(src, palette, chunky.bytes);
	Video_Atari_PreparePlanar(&source, &s_tileDither, pixels);
}

void Video_Atari_DecodePlanarBuildingTile(const uint8 *src, const uint8 *palette, uint16 *pixels)
{
	union { uint32 aligned; uint8 bytes[16 * 16]; } chunky;
	const AtariDitherSource source = {chunky.bytes, 16, 16, 16, 0, 0, 1, 1};

	assert(Video_Atari_Mono());
	Video_Atari_ExpandTileNibbles(src, palette, chunky.bytes);
	Video_Atari_MonoPackNative(&source, &s_buildingMonoPacked, pixels, 4);
}

void Video_Atari_ComposePlanarTile(const uint16 *pixels, const uint16 *masks,
	const uint16 *overlay, const uint16 *overlayMasks, uint16 *result, uint16 *resultMasks)
{
	assert(pixels != NULL && masks != NULL && result != NULL && resultMasks != NULL);
	assert((overlay == NULL) == (overlayMasks == NULL));
	s_planarBackend->composeTile(pixels, masks, overlay, overlayMasks, result, resultMasks);
}

#if 0 /* Experimental exclusive BLiTTER ownership: no IRQ barriers. */
static uint16 Video_Atari_BlitterLock(void)
{
	uint16 status;

	__asm__ volatile (
		"move.w %%sr,%0\n\t"
		"ori.w #0x0700,%%sr"
		: "=d" (status) : : "cc", "memory"
	);
	return status;
}

static void Video_Atari_BlitterUnlock(uint16 status)
{
	__asm__ volatile ("move.w %0,%%sr" : : "d" (status) : "cc", "memory");
}
#endif

static void Video_Atari_BlitterStart(void)
{
	*BLITTER_CTRL = 0xc0;
	while ((*BLITTER_CTRL & 0x80) != 0) {}
}

static void Video_Atari_CompleteScroll(void)
{
	Video_Atari_BlitterStart();
	/* A reverse bulk copy can finish before the first screen row. */
	if (s_blitterDestinationWord)
		*BLITTER_DST_ADDR_HIGH = (uint32)(size_t)s_planarBase >> 16;
}

void __attribute__((noinline)) Video_Atari_FinishScroll(void)
{
	assert(g_videoScrollPending);
	/* Resume the remaining copy in HOG mode without reloading geometry. */
	Atari_SupervisorExec(Video_Atari_CompleteScroll);
	g_videoScrollPending = false;
}

static void Video_Atari_BlitterSetup(const Video_Atari_SpriteBlitPlan *plan,
                                    int16 destinationXinc)
{
	while ((*BLITTER_CTRL & 0x80) != 0) {}
	*BLITTER_SRC_XINC = plan->sourceXinc;
	*BLITTER_SRC_YINC = plan->sourceYinc;
	*BLITTER_ENDMASK1 = plan->firstMask;
	*BLITTER_ENDMASK2 = plan->middleMask;
	*BLITTER_ENDMASK3 = plan->lastMask;
	*BLITTER_DST_XINC = destinationXinc;
	*BLITTER_DST_YINC = plan->destinationYinc;
	*BLITTER_XCOUNT = plan->words;
	*BLITTER_HOP = 2;
	*BLITTER_SKEW = plan->skew;
}

typedef struct PlanarBlit {
	uint16 *dst;
	const uint16 *pixels, *masks;
	const Video_Atari_SpriteBlitPlan *plan;
	const Video_Atari_SpriteBlitGeometry *geometry;
	const Video_Atari_SpriteBlitCode *code;
	uint16 height;
	const uint16 *writable;
	uint16 firstLine;
} PlanarBlit;

/* Highlight recipes: per destination plane, 0-3 copy a source colour plane,
 * 4-7 fill the plane inside the sprite's opacity (masks are replicated per
 * plane), HL_ZERO leaves it clear. Colours change in a fixed, not chosen, way. */
#define HL_ZERO 8
static const uint8 s_highlightRecipes[VIDEO_ATARI_HIGHLIGHT_EFFECTS][4] = {
	{0, 1, 2, 7},       /* 1: force plane 3 */
	{3, 1, 2, 0},       /* 2: swap planes 0 and 3 */
	{0, 2, 1, 3},       /* 3: swap planes 1 and 2 */
	{4, 1, 2, 3},       /* 4: force plane 0 */
	{3, 2, 1, 0},       /* 5: reverse planes */
	{1, 2, 3, 0},       /* 6: rotate planes */
	{0, 1, 2, HL_ZERO}, /* 7: clear plane 3 */
	{0, 5, 2, 3},       /* 8: force plane 1 */
	{0, 1, 6, 3}        /* 9: force plane 2 */
};

void Video_Atari_SetSpriteHighlight(uint16 effect)
{
	s_spriteHighlightEffect = effect <= VIDEO_ATARI_HIGHLIGHT_EFFECTS ? effect : 0;
}

void Video_Atari_HighlightPixels(uint16 *dst, const uint16 *pixels, const uint16 *masks,
                                 uint16 groups, uint16 effect)
{
	uint16 group, plane;

	assert(effect != 0 && effect <= VIDEO_ATARI_HIGHLIGHT_EFFECTS);
	if (Video_Atari_Mono()) {
		/* Mono target flashes invert the prepared texture; opacity is unchanged. */
		for (group = 0; group < groups * 4; group++) dst[group] = ~pixels[group];
		return;
	}
	const uint8 *recipe = s_highlightRecipes[effect - 1];
	for (group = 0; group < groups; group++, pixels += 4, masks += 4, dst += 4) {
		for (plane = 0; plane < 4; plane++) {
			uint8 source = recipe[plane];
			dst[plane] = source < 4 ? pixels[source] : source < HL_ZERO ? masks[source - 4] : 0;
		}
	}
}

static const uint16 s_blitterLeftMasks[16] = {
	0xffff, 0x7fff, 0x3fff, 0x1fff, 0x0fff, 0x07ff, 0x03ff, 0x01ff,
	0x00ff, 0x007f, 0x003f, 0x001f, 0x000f, 0x0007, 0x0003, 0x0001
};
static const uint16 s_blitterRightMasks[16] = {
	0xffff, 0x8000, 0xc000, 0xe000, 0xf000, 0xf800, 0xfc00, 0xfe00,
	0xff00, 0xff80, 0xffc0, 0xffe0, 0xfff0, 0xfff8, 0xfffc, 0xfffe
};

static PlanarBlit s_planarBlit;

static void Video_Atari_BuildSpriteBlitPlan(Video_Atari_SpriteBlitPlan *plan,
                                          uint16 sourceWidth, uint16 sourceX,
                                          uint16 width, uint16 destinationPhase)
{
	uint16 sourcePhase = sourceX & 15;
	uint16 words = (destinationPhase + width + 15) >> 4;
	uint16 sourceWords = (sourcePhase + width + 15) >> 4;
	bool leftShift = sourcePhase > destinationPhase;
	bool extra = leftShift && (words > 1 || sourceWords > 1);
	bool suppress = words > 1 && sourceWords < words + (extra ? 1 : 0);
	/* A one-word left shift uses the latch's high half without prefetch. */
	int16 sourceXinc = !extra && leftShift ? -8 : 8;
	uint16 firstMask = s_blitterLeftMasks[destinationPhase];
	uint16 lastMask = s_blitterRightMasks[(destinationPhase + width) & 15];

	if (Video_Atari_Mono()) {
		sourcePhase = (sourceX * 2) & 15;
		destinationPhase = (destinationPhase * 2) & 15;
		width *= 2;
		words = (destinationPhase + width + 15) >> 4;
		sourceWords = (sourcePhase + width + 15) >> 4;
		leftShift = sourcePhase > destinationPhase;
		extra = leftShift && (words > 1 || sourceWords > 1);
		suppress = words > 1 && sourceWords < words + (extra ? 1 : 0);
		sourceXinc = !extra && leftShift ? -2 : 2;
		firstMask = s_blitterLeftMasks[destinationPhase];
		lastMask = s_blitterRightMasks[(destinationPhase + width) & 15];
		plan->words = words;
		plan->firstMask = words == 1 ? firstMask & lastMask : firstMask;
		plan->middleMask = 0xffff;
		plan->lastMask = lastMask;
		plan->sourceXinc = sourceXinc;
		plan->sourceYinc = sourceWidth / 4 - (words - 1) * sourceXinc -
			(extra ? sourceXinc : 0) + (suppress ? sourceXinc : 0);
		plan->destinationXinc = 2;
		plan->destinationYinc = 80 - (words - 1) * 2;
		plan->skew = ((destinationPhase - sourcePhase) & 15) |
			(extra ? 0x80 : 0) | (suppress ? 0x40 : 0);
		return;
	}
	plan->words = words;
	plan->firstMask = words == 1 ? firstMask & lastMask : firstMask;
	plan->middleMask = 0xffff;
	plan->lastMask = lastMask;
	plan->sourceXinc = sourceXinc;
	/* FXSR adds a source fetch; NFSR moves YINC to the penultimate word. */
	plan->sourceYinc = (int16)(sourceWidth / 2 - (words - 1) * sourceXinc -
	    (extra ? sourceXinc : 0) + (suppress ? sourceXinc : 0));
	plan->destinationYinc = ST_PLANAR_LINE_BYTES - (words - 1) * 8;
	plan->destinationXinc = 8;
	plan->skew = ((destinationPhase - sourcePhase) & 15) |
	    (extra ? 0x80 : 0) | (suppress ? 0x40 : 0);
}

void Video_Atari_BuildSpriteBlitPlans(Video_Atari_SpriteBlitPlan plans[16],
                                    uint16 sourceWidth, uint16 sourceX, uint16 width)
{
	uint16 phase;

	assert(sourceWidth > 0 && sourceWidth <= 80 && (sourceWidth & 15) == 0);
	assert(width > 0 && sourceX + width <= sourceWidth);
	for (phase = 0; phase < 16; phase++)
		Video_Atari_BuildSpriteBlitPlan(&plans[phase], sourceWidth, sourceX, width, phase);
}

void Video_Atari_BuildSpriteBlitGeometry(Video_Atari_SpriteBlitGeometry geometry[16],
                                       uint16 sourceWidth, uint16 sourceX, uint16 width)
{
	uint16 phase;

	assert(sourceWidth > 0 && sourceWidth <= 80 && (sourceWidth & 15) == 0);
	assert(width > 0 && sourceX + width <= sourceWidth);
	for (phase = 0; phase < 16; phase++) {
		Video_Atari_SpriteBlitPlan plan;
		uint16 *out;
		Video_Atari_BuildSpriteBlitPlan(&plan, sourceWidth, sourceX, width, phase);
		out = Video_Atari_DisplayGeometry(geometry[phase].words, &plan);
		*out++ = HTOBE16(0x4ed4); /* jmp (a4) */
		assert(out == geometry[phase].words + VIDEO_ATARI_SPRITE_BLIT_GEOMETRY_WORDS);
	}
}

static void Video_Atari_BlitScroll(void)
{
	s_blitterTileSetup = false;
	Video_Atari_BlitterSetup(s_planarBlit.plan, s_planarBlit.plan->destinationXinc);
	*BLITTER_OP = 3;
	*BLITTER_SRC_ADDR = (uint32)(size_t)s_planarBlit.pixels;
	*BLITTER_DST_ADDR = (uint32)(size_t)s_planarBlit.dst;
	*BLITTER_YCOUNT = s_planarBlit.height;
	g_videoScrollPending = true;
	*BLITTER_CTRL = 0x80;
}

static void Video_Atari_BlitOpaque(void)
{
	static const Video_Atari_SpriteBlitPlan tilePlan = {
		.sourceXinc = 2, .sourceYinc = 2,
		.firstMask = 0xffff, .middleMask = 0xffff, .lastMask = 0xffff,
		.destinationXinc = 2, .destinationYinc = 154, .words = 4, .skew = 0
	};
	static const Video_Atari_SpriteBlitPlan monoPlan = {
		.sourceXinc = 2, .sourceYinc = 2,
		.firstMask = 0xffff, .middleMask = 0xffff, .lastMask = 0xffff,
		.destinationXinc = 2, .destinationYinc = 78, .words = 2, .skew = 0
	};
	/* uint16 status = Video_Atari_BlitterLock(); */
	if (!s_blitterTileSetup) {
		Video_Atari_BlitterSetup(Video_Atari_Mono() ? &monoPlan : &tilePlan, 2);
		*BLITTER_OP = 3;
		s_blitterTileSetup = true;
	}
	*BLITTER_SRC_ADDR = (uint32)(size_t)s_planarBlit.pixels;
	*BLITTER_DST_ADDR = (uint32)(size_t)s_planarBlit.dst;
	*BLITTER_YCOUNT = Video_Atari_Mono() ? 32 : 16;
	Video_Atari_BlitterStart();
	/* Video_Atari_BlitterUnlock(status); */
}

uint8 Video_Atari_BuildSpriteBlitRecipe(const uint16 *pixels, const uint16 *masks,
                                      uint16 groups)
{
	uint16 set[4] = {0}, clear[4] = {0}, plane;
	uint8 passes = 0;

	if (Video_Atari_Mono()) return 0x11;
	while (groups-- != 0) {
		uint16 opacity = *masks++;
		for (plane = 0; plane < 4; plane++) {
			uint16 colour = *pixels++;
			set[plane] |= colour & opacity;
			clear[plane] |= (uint16)~colour & opacity;
		}
	}
	for (plane = 0; plane < 4; plane++) {
		if (clear[plane] != 0) passes |= 1u << plane;
		if (set[plane] != 0) passes |= 0x10u << plane;
	}
	return passes;
}

bool Video_Atari_UnitOutlineEnabled(void)
{
	return Video_Atari_Mono();
}

void Video_Atari_OutlineUnit(uint16 *pixels, const uint16 *masks, uint16 width, uint16 height)
{
	Video_Atari_MonoOutline(pixels, masks, width, height, s_monoWhiteIsOne);
}

static void Video_Atari_CompileSpriteBlit(Video_Atari_SpriteBlitCode *code, uint8 passes,
                                         uint16 hop, uint16 firstLine)
{
	uint16 *out = code->words;
	uint16 pass, plane;

	for (pass = 0; pass < 2; pass++) {
		uint16 planes = (passes >> (pass * 4)) & 15;
		if (planes == 0) continue;
		*out++ = HTOBE16(0x31fc); /* move.w #HOP/OP,BLITTER_HOP */
		*out++ = HTOBE16((hop << 8) | (pass == 0 ? 4 : 7));
		*out++ = HTOBE16(0x8a3a);
		for (plane = 0; plane < 4; plane++) {
			if ((planes & (1u << plane)) == 0) continue;
			if (plane != 0) {
				*out++ = HTOBE16(pass == 0 ? 0x47e9 : 0x47e8); /* lea plane(a1/a0),a3 */
				*out++ = HTOBE16(plane * 2);
			}
			*out++ = HTOBE16(plane != 0 ? 0x21cb : pass == 0 ? 0x21c9 : 0x21c8);
			*out++ = HTOBE16(0x8a24);
			if (plane != 0) {
				*out++ = HTOBE16(0x47ea); /* lea plane(a2),a3 */
				*out++ = HTOBE16(plane * 2);
			}
			*out++ = HTOBE16((plane != 0 ? 0x21cb : 0x21ca) |
			    (s_blitterDestinationWord ? 0x1000 : 0));
			*out++ = HTOBE16(s_blitterDestinationWord ? 0x8a34 : 0x8a32);
			*out++ = HTOBE16(0x31c0); /* move.w d0,BLITTER_YCOUNT */
			*out++ = HTOBE16(0x8a38);
			*out++ = HTOBE16(0x11fc);
			*out++ = HTOBE16(0x00c0 | firstLine);
			*out++ = HTOBE16(0x8a3c);
			if ((planes >> (plane + 1)) != 0 || (pass == 0 && (passes >> 4) != 0))
				*out++ = HTOBE16(0x4e71); /* HOG launch boundary; final launch returns directly. */
		}
	}
	*out++ = HTOBE16(0x4e75);
	code->passes = passes;
	assert(out <= code->words + VIDEO_ATARI_SPRITE_BLIT_CODE_WORDS);
}

void Video_Atari_CompileSpriteBlitCode(Video_Atari_SpriteBlitCode *code, uint8 passes)
{
	Video_Atari_CompileSpriteBlit(code, passes, 2, 0);
}

static inline void Video_Atari_ExecuteSpriteBlitCode(const Video_Atari_SpriteBlitCode *code,
                                                    const uint16 *pixels, const uint16 *masks,
                                                    uint16 *dst, uint16 height,
                                                    const Video_Atari_SpriteBlitPlan *plan)
{
	register const uint16 *sourcePixels __asm__("a0") = pixels;
	register const uint16 *sourceMasks __asm__("a1") = masks;
	register uint16 *destination __asm__("a2") = dst;
	register const Video_Atari_SpriteBlitPlan *geometry __asm__("a3") = plan;
	register const Video_Atari_SpriteBlitCode *recipe __asm__("a4") = code;
	register uint32 rows __asm__("d0") = height;

	__asm__ volatile ("jsr _Video_Atari_BlitSpriteCode"
	    : "+a" (geometry)
	    : "a" (sourcePixels), "a" (sourceMasks), "a" (destination), "a" (recipe), "d" (rows)
	    : "cc", "memory");
}

static inline void Video_Atari_ExecuteSpriteBlitGeometry(const Video_Atari_SpriteBlitCode *code,
                                                        const uint16 *pixels, const uint16 *masks,
                                                        uint16 *dst, uint16 height,
                                                        const Video_Atari_SpriteBlitGeometry *geometry)
{
	register const uint16 *sourcePixels __asm__("a0") = pixels;
	register const uint16 *sourceMasks __asm__("a1") = masks;
	register uint16 *destination __asm__("a2") = dst;
	register const Video_Atari_SpriteBlitGeometry *phaseCode __asm__("a3") = geometry;
	register const Video_Atari_SpriteBlitCode *recipe __asm__("a4") = code;
	register uint32 rows __asm__("d0") = height;

	__asm__ volatile ("jsr _Video_Atari_BlitSpriteGeometry"
	    : "+a" (phaseCode)
	    : "a" (sourcePixels), "a" (sourceMasks), "a" (destination), "a" (recipe), "d" (rows)
	    : "cc", "memory");
}

static inline void Video_Atari_QueueSpriteBlitCode(const Video_Atari_SpriteBlitCode *code,
                                                 const uint16 *pixels, const uint16 *masks,
                                                 uint16 *dst, uint16 height,
                                                 const Video_Atari_SpriteBlitPlan *plan)
{
	register const uint16 *sourcePixels __asm__("a0") = pixels;
	register const uint16 *sourceMasks __asm__("a1") = masks;
	register uint16 *destination __asm__("a2") = dst;
	register const Video_Atari_SpriteBlitPlan *geometry __asm__("a3") = plan;
	register const Video_Atari_SpriteBlitCode *recipe __asm__("a4") = code;
	register uint32 rows __asm__("d0") = height;

	__asm__ volatile ("jsr _Video_Atari_QueueSpriteBlit"
	    : "+a" (geometry)
	    : "a" (sourcePixels), "a" (sourceMasks), "a" (destination), "a" (recipe), "d" (rows)
	    : "cc", "memory");
}

static inline void Video_Atari_QueueSpriteBlitGeometry(const Video_Atari_SpriteBlitCode *code,
                                                     const uint16 *pixels, const uint16 *masks,
                                                     uint16 *dst, uint16 height,
                                                     const Video_Atari_SpriteBlitGeometry *geometry)
{
	register const uint16 *sourcePixels __asm__("a0") = pixels;
	register const uint16 *sourceMasks __asm__("a1") = masks;
	register uint16 *destination __asm__("a2") = dst;
	register const Video_Atari_SpriteBlitGeometry *phaseCode __asm__("a3") = geometry;
	register const Video_Atari_SpriteBlitCode *recipe __asm__("a4") = code;
	register uint32 rows __asm__("d0") = height;

	__asm__ volatile ("jsr _Video_Atari_QueueSpriteGeometry"
	    : "+a" (phaseCode)
	    : "a" (sourcePixels), "a" (sourceMasks), "a" (destination), "a" (recipe), "d" (rows)
	    : "cc", "memory");
}

static void Video_Atari_BlitCompiledSprite(void)
{
	if (s_planarBlit.geometry != NULL) {
		Video_Atari_ExecuteSpriteBlitGeometry(s_planarBlit.code, s_planarBlit.pixels,
		    s_planarBlit.masks, s_planarBlit.dst, s_planarBlit.height, s_planarBlit.geometry);
	} else {
		Video_Atari_ExecuteSpriteBlitCode(s_planarBlit.code, s_planarBlit.pixels,
		    s_planarBlit.masks, s_planarBlit.dst, s_planarBlit.height, s_planarBlit.plan);
	}
}

static void Video_Atari_BlitMonoTileCursor(void)
{
	s_blitterTileSetup = false;
	Video_Atari_ExecuteSpriteBlitCode(&s_tileCursorCode, s_tileCursorPixels, s_tileCursorMasks,
	    (uint16 *)g_videoTileCursorBlit.dst, 32, &s_tileCursorPlan);
	g_videoTileCursorRestored = true;
}

static void Video_Atari_QueueMaskedBlit(bool protected)
{
	uint16 launches = 0, pass, plane;
	const uint8 *recipe = s_spriteHighlightEffect != 0 ? s_highlightRecipes[s_spriteHighlightEffect - 1] : NULL;
	uint8 passes = recipe != NULL ? 0xff : s_planarBlit.code->passes;
	uint16 *out = g_videoDisplayListNext;

	for (pass = 0; pass < 2; pass++)
		for (plane = 0; plane < 4; plane++)
			if ((passes & (1u << (pass * 4 + plane))) != 0 &&
			    (pass == 0 || recipe == NULL || recipe[plane] != HL_ZERO))
				launches++;
	if (launches == 0) return;
	assert(g_videoDisplayListLimit - out >= (48 + (protected ? 102 : 0) + launches * 30) / 2);
	out = Video_Atari_DisplayGeometry(out, s_planarBlit.plan);
	if (protected) out = Video_Atari_DisplayPattern(out, s_planarBlit.writable);
	for (pass = 0; pass < 2; pass++) {
		for (plane = 0; plane < 4; plane++) {
			uint8 source = pass == 0 ? plane + 4 :
			    recipe != NULL ? recipe[plane] : plane;
			const uint16 *pixels;
			if ((passes & (1u << (pass * 4 + plane))) == 0 || source == HL_ZERO) continue;
			pixels = source < 4 ? s_planarBlit.pixels + source : s_planarBlit.masks + source - 4;
			out = Video_Atari_DisplayPlane(out, pixels, s_planarBlit.dst + plane,
			    s_planarBlit.height, ((protected ? 3 : 2) << 8) | (pass == 0 ? 4 : 7),
			    0xc0 | (protected ? s_planarBlit.firstLine : 0));
		}
	}
	g_videoDisplayListNext = out;
}

static void Video_Atari_BlitMaskedHighlight(void)
{
	const uint8 *recipe = s_highlightRecipes[s_spriteHighlightEffect - 1];
	uint16 pass, plane;

	s_blitterTileSetup = false;
	Video_Atari_BlitterSetup(s_planarBlit.plan, 8);
	for (pass = 0; pass < 2; pass++) {
		*BLITTER_OP = pass == 0 ? 4 : 7;
		for (plane = 0; plane < 4; plane++) {
			const uint16 *src;
			if (pass == 0) {
				src = s_planarBlit.masks + plane;
			} else {
				uint8 source = recipe[plane];
				if (source == HL_ZERO) continue;
				src = source < 4 ? s_planarBlit.pixels + source : s_planarBlit.masks + source - 4;
			}
			*BLITTER_SRC_ADDR = (uint32)(size_t)src;
			*BLITTER_DST_ADDR = (uint32)(size_t)(s_planarBlit.dst + plane);
			*BLITTER_YCOUNT = s_planarBlit.height;
			Video_Atari_BlitterStart();
		}
	}
}

static void Video_Atari_BlitterStartLine(uint16 line)
{
	*BLITTER_CTRL = 0xc0 | line;
	while ((*BLITTER_CTRL & 0x80) != 0) {}
}

static void Video_Atari_BlitProtectedSprite(void)
{
	static Video_Atari_SpriteBlitCode code;
	static uint16 key = 0xffff;
	uint16 next = ((uint16)s_planarBlit.code->passes << 4) | s_planarBlit.firstLine;
	uint16 pass, plane;
	const uint8 *recipe;

	s_blitterTileSetup = false;
	Video_Atari_SetHalftonePattern(s_planarBlit.writable);
	if (s_spriteHighlightEffect == 0) {
		if (key != next) {
			Video_Atari_CompileSpriteBlit(&code, s_planarBlit.code->passes, 3, s_planarBlit.firstLine);
			key = next;
		}
		Video_Atari_ExecuteSpriteBlitCode(&code, s_planarBlit.pixels, s_planarBlit.masks,
		    s_planarBlit.dst, s_planarBlit.height, s_planarBlit.plan);
		return;
	}
	recipe = s_highlightRecipes[s_spriteHighlightEffect - 1];
	Video_Atari_BlitterSetup(s_planarBlit.plan, 8);
	*BLITTER_HOP = 3;
	for (pass = 0; pass < 2; pass++) {
		*BLITTER_OP = pass == 0 ? 4 : 7;
		for (plane = 0; plane < 4; plane++) {
			uint8 source = pass == 0 ? plane + 4 : recipe[plane];
			if (source == HL_ZERO) continue;
			*BLITTER_SRC_ADDR = (uint32)(size_t)(source < 4 ?
			    s_planarBlit.pixels + source : s_planarBlit.masks + source - 4);
			*BLITTER_DST_ADDR = (uint32)(size_t)(s_planarBlit.dst + plane);
			*BLITTER_YCOUNT = s_planarBlit.height;
			Video_Atari_BlitterStartLine(s_planarBlit.firstLine);
		}
	}
}

static void Video_Atari_BlitTile(const uint16 *pixels, uint8 *base, uint16 x, uint16 y)
{
	uint16 *dst = (uint16 *)base + (uint32)y * 80 + (x >> 4) * Video_Atari_GroupWords();

	if (g_videoScrollPending) Video_Atari_FinishScroll();
	s_planarBlit.dst = dst;
	s_planarBlit.pixels = pixels;
	Atari_SupervisorExec(Video_Atari_BlitOpaque);
	Video_Atari_RestoreTileCursor();
}

/* Queue-only opaque repair; false means "use the general publication path". */
bool Video_Atari_QueueViewportTile(const uint16 *pixels, uint16 col, uint16 row)
{
	static const uint16 rowOffsets[10] = {
		40 * ST_PLANAR_LINE_BYTES, 56 * ST_PLANAR_LINE_BYTES, 72 * ST_PLANAR_LINE_BYTES,
		88 * ST_PLANAR_LINE_BYTES, 104 * ST_PLANAR_LINE_BYTES, 120 * ST_PLANAR_LINE_BYTES,
		136 * ST_PLANAR_LINE_BYTES, 152 * ST_PLANAR_LINE_BYTES, 168 * ST_PLANAR_LINE_BYTES,
		184 * ST_PLANAR_LINE_BYTES
	};
	uint8 *dst;

	if (!s_viewportBlitter || ((s_curViewportTiles[row] >> col) & 1) != 0) return false;
	dst = Video_Atari_PlanarBase() + rowOffsets[row] + col * Video_Atari_GroupWords() * 2;
	assert(g_videoDisplayListActive);
	Video_Atari_QueueTile(pixels, (uint16 *)dst);
	return true;
}

static void Video_Atari_PublishMonoRows(uint8 *base, const uint16 *pixels, const uint16 *masks,
	uint16 stride, uint16 first, uint16 end, uint16 top, uint16 bottom, bool protected)
{
	uint16 row, group;
	for (row = top; row < bottom; row++) {
		for (group = first; group < end; group++) {
			uint16 index = group - first;
			uint16 mask = masks != NULL ? masks[(uint32)(row - top) * stride + index] : 0xffff;
			uint16 words[4];
			if (mask == 0) continue;
			Video_Atari_MonoReadGroup(pixels, stride * 4, row - top, index, words);
			if (protected) Video_Atari_PlanarMergeGroup(base, row, group, mask, words);
			else {
				uint16 old[4];
				Video_Atari_MonoReadGroup((const uint16 *)base, 80, row, group, old);
				Video_Atari_MonoMergeWords(old, words, mask);
				Video_Atari_MonoWriteGroup((uint16 *)base, 80, row, group, old);
			}
		}
	}
}

/* Keep post-write state out of the ordinary publishers' register allocation. */
static void __attribute__((noinline)) Video_Atari_PublishViewportCursorRect(
    uint8 *base, const uint16 *pixels, const uint16 *masks, uint16 stride,
    uint16 first, uint16 end, uint16 top, uint16 bottom, bool protected)
{
	const uint16 *written = masks;
	uint16 line, group;
	uint16 *dstRow = (uint16 *)(base + (uint32)top * 160 + first * 8);

	Video_Atari_DisplayListFlush();
	if (Video_Atari_Mono())
		Video_Atari_PublishMonoRows(base, pixels, masks, stride, first, end, top, bottom, protected);
	else for (line = top; line < bottom; line++, dstRow += 80) {
		for (group = first; group < end; group++) {
			uint16 index = group - first, mask = masks != NULL ? masks[index] : 0xffff;
			const uint16 *src = pixels + index * 4;
			uint16 *dst = dstRow + index * 4;
			if (mask == 0) continue;
			if (protected) Video_Atari_PlanarMergeGroup(base, line, group, mask, src);
			else if (mask == 0xffff) Video_Atari_PlanarCopyGroup(dst, src);
			else Video_Atari_PlanarMergePlain(dst, mask, src);
		}
		if (line + 1 < bottom) {
			pixels += stride * 4;
			if (masks != NULL) masks += stride;
		}
	}
	if (!protected && Video_Atari_CursorRectOverlap(base, first, end, top, bottom - top))
		Video_Atari_RefreshViewportCursor(base, first, end, top, bottom, written, stride);
	Video_Atari_RestoreTileCursor();
	GFX_Screen_ClearDirtyRect(first * 16, top, end * 16, bottom);
}

static void Video_Atari_RippleTile(uint16 pixels[64], const uint16 *opacity,
    const VideoAtariTerrainRipple *ripple, const uint16 *writable, const uint16 *protected, bool mono)
{
	static const uint16 specks[8] = {0x8422, 0x2920, 0x1094, 0x4209, 0x8910, 0x2441, 0x1288, 0x4054};
	uint16 row, plane;

	for (row = 0; row < 16; row += 2) {
		uint16 mask = ripple->displacement[row] & opacity[row];
		uint16 *dst = pixels + row * 4;
		if (!mono) mask &= opacity[row + 1];
		if (writable != NULL) {
			mask &= writable[row];
			if (!mono) mask &= writable[row + 1];
		}
		if (protected != NULL) {
			mask &= ~protected[row];
			if (!mono) mask &= ~protected[row + 1];
		}
		if (mask == 0) continue;
		if (mono) {
			uint16 expanded[4];
			Video_Atari_MonoMaskWords(mask, expanded);
			for (plane = 0; plane < 4; plane++) dst[plane] ^= expanded[plane];
		} else {
			uint16 accent = mask & ripple->worm[row] & specks[row >> 1];
			Video_Atari_PlanarMergePlain(dst, mask, dst + 4);
			if (accent != 0) {
				/* Replace sand pen 8 with dark brown pen 7, not the light flecks. */
				accent &= dst[3] & ~(dst[0] | dst[1] | dst[2]);
				for (plane = 0; plane < 4; plane++) dst[plane] ^= accent;
			}
		}
	}
}

void Video_Atari_DrawRippleTile(const uint16 *pixels, const uint16 *masks,
    uint16 col, uint16 row, const VideoAtariTerrainRipple *ripple, const uint16 *protected)
{
	uint16 result[64], y = 40 + 16 * row;
	uint8 *base = Video_Atari_PlanarBase();

	memcpy(result, pixels, sizeof(result));
	Video_Atari_RippleTile(result, masks, ripple, Video_Atari_ViewportWritable(col, row),
	    protected, Video_Atari_Mono());
	/* Publish synchronously: the modified tile lives on the stack. */
	Video_Atari_PublishViewportCursorRect(base, result, masks, 1, col, col + 1, y, y + 16,
	    Video_Atari_TileOverlaysOverlap(base, col * 16, y));
}

void Video_Atari_DrawPlanarTile(const uint16 *pixels, const uint16 *masks, uint16 x, uint16 y,
                              const uint16 *copyPixels)
{
	uint8 *base = Video_Atari_PlanarBase();
	bool overlays = Video_Atari_TileOverlaysOverlap(base, x, y);

	assert((x & 15) == 0 && x + 16 <= SCREEN_WIDTH && y + 16 <= SCREEN_HEIGHT);
	if (s_viewportBlitter && !overlays && copyPixels != NULL && x < 240 && y >= 40) {
		if (g_videoDisplayListActive)
			Video_Atari_QueueTile(copyPixels, (uint16 *)base + (uint32)y * 80 + (x >> 4) * Video_Atari_GroupWords());
		else
			Video_Atari_BlitTile(copyPixels, base, x, y);
		GFX_Screen_ClearDirtyRect(x, y, x + 16, y + 16);
		return;
	}
	if (copyPixels != NULL && !overlays) {
		Video_Atari_DisplayListFlush();
		Video_Atari_PublishPlanarRun(base, (const uint8 *)copyPixels, 8, x, y, 16, 16);
		Video_Atari_RestoreTileCursor();
		GFX_Screen_ClearDirtyRect(x, y, x + 16, y + 16);
		return;
	}
	if (g_videoDisplayListActive && s_planarBackend->maskedQueue && !overlays &&
	    copyPixels == NULL && x < 240 && y >= 40) {
		assert(g_videoDisplayListLimit - g_videoDisplayListNext >= 12);
		Video_Atari_QueueMaskedTile(pixels, masks,
		    (uint16 *)(base + (uint32)y * ST_PLANAR_LINE_BYTES + (x >> 1)));
		GFX_Screen_ClearDirtyRect(x, y, x + 16, y + 16);
		return;
	}
	if (overlays && x < 240 && y >= 40 &&
	    !Video_Atari_PlacementRectOverlap(base, x, x + 16, y, 16)) {
		Video_Atari_PublishViewportCursorRect(base, copyPixels != NULL ? copyPixels : pixels,
		    copyPixels != NULL ? NULL : masks, 1, x >> 4, (x >> 4) + 1, y, y + 16, false);
		return;
	}
	Video_Atari_PublishViewportCursorRect(base, copyPixels != NULL ? copyPixels : pixels,
	    copyPixels != NULL ? NULL : masks, 1, x >> 4, (x >> 4) + 1, y, y + 16, overlays);
}

void Video_Atari_PresentSprite(const uint8 *src, uint16 stride,
                              uint16 x, uint16 y, uint16 width, uint16 height,
                              const uint16 *masks)
{
	uint16 pixels[48 / 4 * 8], row;

	assert((x & 15) == 0 && (width & 15) == 0 && width <= 48);
	assert(x + width <= 240 && y >= 40 && y + height <= SCREEN_HEIGHT);
	for (row = 0; row < height; row += 8) {
		uint16 lines = min(8, height - row);
		Video_Atari_EncodePlanarStrided(src + (uint32)row * stride, stride, pixels, width, lines);
		Video_Atari_PresentPlanarSpriteStrided(pixels, masks + (uint32)row * (width / 16),
		    width, lines, x, y + row, width);
	}
}

void Video_Atari_ComposePlanarSprite(uint16 *dstPixels, uint16 *dstMasks,
                                   uint16 dstWidth, uint16 dstHeight,
                                   const uint16 *pixels, const uint16 *masks,
                                   uint16 width, uint16 height, uint16 x, uint16 y)
{
	if (Video_Atari_Mono()) {
		Video_Atari_MonoCompose(dstPixels, dstWidth / 4, dstMasks, dstWidth / 16,
			dstWidth, dstHeight, pixels, masks, width, height, x, y);
		return;
	}
	uint16 dstGroups = dstWidth >> 4, groups = width >> 4;
	uint16 shift = x & 15, first = x >> 4, row, group;

	assert(dstWidth > 0 && (dstWidth & 15) == 0 && width > 0 && (width & 15) == 0);
	assert(x < dstWidth && height > 0 && y + height <= dstHeight);
	VARIABLE_NOT_USED(dstHeight);
	dstPixels += ((uint32)y * dstGroups + first) * 4;
	dstMasks += (uint32)y * dstGroups + first;
	for (row = 0; row < height; row++) {
		for (group = 0; group < groups && first + group < dstGroups; group++) {
			uint16 mask = masks[group];
			const uint16 *src = pixels + group * 4;
			uint16 *dst = dstPixels + group * 4;
			if (mask == 0) continue;
			if (shift == 0) {
				Video_Atari_PlanarMergePlain(dst, mask, src);
				dstMasks[group] |= mask;
			} else {
				uint16 words[4], plane, part = mask >> shift;
				if (part != 0) {
					for (plane = 0; plane < 4; plane++) words[plane] = src[plane] >> shift;
					Video_Atari_PlanarMergePlain(dst, part, words);
					dstMasks[group] |= part;
				}
				part = (uint16)(mask << (16 - shift));
				if (part != 0 && first + group + 1 < dstGroups) {
					for (plane = 0; plane < 4; plane++) words[plane] = src[plane] << (16 - shift);
					Video_Atari_PlanarMergePlain(dst + 4, part, words);
					dstMasks[group + 1] |= part;
				}
			}
		}
		pixels += groups * 4;
		masks += groups;
		if (row + 1 < height) {
			dstPixels += dstGroups * 4;
			dstMasks += dstGroups;
		}
	}
}

void Video_Atari_ComposePlanarSpriteClipped(uint16 *dstPixels, uint16 *dstMasks,
                                          uint16 dstWidth, uint16 dstHeight,
                                          const uint16 *pixels, const uint16 *masks,
                                          uint16 width, uint16 height, int16 x, int16 y)
{
	if (Video_Atari_Mono()) {
		Video_Atari_MonoCompose(dstPixels, dstWidth / 4, dstMasks, dstWidth / 16,
			dstWidth, dstHeight, pixels, masks, width, height, x, y);
		return;
	}
	uint16 dstGroups = dstWidth >> 4, groups = width >> 4;
	uint16 shift = (uint16)x & 15;
	int16 first = x >= 0 ? x >> 4 : -((15 - x) >> 4);
	int16 firstRow = max(0, -y), endRow = min(height, (int)dstHeight - y), row;
	uint16 group;

	assert(dstWidth > 0 && (dstWidth & 15) == 0 && width > 0 && (width & 15) == 0);
	assert(dstHeight > 0 && height > 0);
	for (row = firstRow; row < endRow; row++) {
		uint16 *dstRow = dstPixels + (uint32)(y + row) * dstGroups * 4;
		uint16 *maskRow = dstMasks + (uint32)(y + row) * dstGroups;
		const uint16 *srcRow = pixels + (uint32)row * groups * 4;
		const uint16 *srcMasks = masks + (uint32)row * groups;
		for (group = 0; group < groups; group++) {
			int16 column = first + group;
			uint16 mask = srcMasks[group], words[4], part, plane;
			const uint16 *src = srcRow + group * 4;
			if (mask == 0 || column < -1 || column >= dstGroups) continue;
			part = mask >> shift;
			if (column >= 0 && part != 0) {
				for (plane = 0; plane < 4; plane++) words[plane] = src[plane] >> shift;
				Video_Atari_PlanarMergePlain(dstRow + column * 4, part, words);
				maskRow[column] |= part;
			}
			if (shift == 0) continue;
			part = (uint16)(mask << (16 - shift));
			if (column + 1 >= 0 && column + 1 < dstGroups && part != 0) {
				for (plane = 0; plane < 4; plane++) words[plane] = src[plane] << (16 - shift);
				Video_Atari_PlanarMergePlain(dstRow + (column + 1) * 4, part, words);
				maskRow[column + 1] |= part;
			}
		}
	}
}

/* As Video_Atari_ComposePlanarSprite() but into any planar surface: `dst` is its row 0, group 0
 * and no mask is accumulated. Source rows are group-aligned; groups past dstGroups are clipped. */
void Video_Atari_BlitPlanarSprite(uint16 *dst, uint16 dstStride, uint16 dstGroups,
                                  const uint16 *pixels, const uint16 *masks,
                                  uint16 width, uint16 height, int16 x)
{
	if (Video_Atari_Mono()) {
		Video_Atari_MonoCompose(dst, dstStride, NULL, 0, dstGroups * 16, height,
			pixels, masks, width, height, x, 0);
		return;
	}
	uint16 groups = width >> 4, shift = (uint16)x & 15, row, group;
	int16 first = x >= 0 ? x >> 4 : -((15 - x) >> 4);

	assert(width > 0 && (width & 15) == 0 && height > 0 && dstStride >= dstGroups * 4);
	for (row = 0; row < height; row++, dst += dstStride, pixels += groups * 4, masks += groups) {
		for (group = 0; group < groups; group++) {
			int16 column = first + group;
			uint16 mask = masks[group];
			const uint16 *src = pixels + group * 4;
			uint16 *d;
			if (column < -1 || column >= dstGroups) continue;
			if (mask == 0) continue;
			d = column >= 0 ? dst + column * 4 : dst;
			if (shift == 0) {
				if (column >= 0) Video_Atari_PlanarMergePlain(d, mask, src);
			} else {
				uint16 words[4], plane, part = mask >> shift;
				if (column >= 0 && part != 0) {
					for (plane = 0; plane < 4; plane++) words[plane] = src[plane] >> shift;
					Video_Atari_PlanarMergePlain(d, part, words);
				}
				part = (uint16)(mask << (16 - shift));
				if (part != 0 && column + 1 >= 0 && column + 1 < dstGroups) {
					for (plane = 0; plane < 4; plane++) words[plane] = src[plane] << (16 - shift);
					Video_Atari_PlanarMergePlain(dst + (column + 1) * 4, part, words);
				}
			}
		}
	}
}

static void __attribute__((noinline)) Video_Atari_PresentPlanarSpriteOverlays(
    const uint16 *pixels, const uint16 *masks, uint16 width, uint16 height, int16 x, int16 y,
    uint16 sourceGroups)
{
	uint16 left = max(0, x), right = min(240, x + width);
	uint16 top = max(40, y), bottom = min(200, y + height);
	uint16 first = left >> 4, end = (right + 15) >> 4;
	uint8 *base = Video_Atari_PlanarBase();
	bool placement = Video_Atari_PlacementRectOverlap(base, first * 16, end * 16, top, bottom - top);

	pixels += (top - y) * sourceGroups * 4 + (left - x) / 16 * Video_Atari_GroupWords();
	masks += (top - y) * sourceGroups + (left - x) / 16;
	Video_Atari_PublishViewportCursorRect(base, pixels, masks, sourceGroups, first, end, top, bottom, placement);
}

static void __attribute__((noinline)) Video_Atari_PublishPlanarSpritePlain(
    uint16 *dstRow, const uint16 *pixels, const uint16 *masks,
    uint16 groups, uint16 rows, uint16 stride)
{
	uint16 padding = stride - groups;

	while (true) {
		const uint16 *end = masks + groups;
		uint16 *dst = dstRow;
		do {
			uint16 mask = *masks++;
			if (mask != 0) {
				if (mask == 0xffff) Video_Atari_PlanarCopyGroup(dst, pixels);
				else Video_Atari_PlanarMergePlain(dst, mask, pixels);
			}
			pixels += 4;
			dst += 4;
		} while (masks != end);
		if (--rows == 0) break;
		pixels += padding * 4;
		masks += padding;
		dstRow += 80;
	}
}

static void Video_Atari_PresentProtectedSprite(const uint16 *pixels, const uint16 *masks,
    uint16 sourceWidth, uint16 sourceX, uint16 width, uint16 height, uint16 x, uint16 y,
    bool expanded, const Video_Atari_SpriteBlitCode *code);

static void Video_Atari_PublishCompactSpriteRows(uint8 *base,
	const uint16 *pixels, const uint16 *masks, uint16 stride,
	uint16 first, uint16 end, uint16 top, uint16 bottom)
{
	if (Video_Atari_Mono())
		Video_Atari_PublishSpriteRows(base, pixels, masks, stride * 16, 0,
		    (end - first) * 16, bottom - top, first * 16, top, false, false, NULL,
		    s_spriteHighlightEffect);
	else
		Video_Atari_PublishPlanarSpritePlain((uint16 *)base + (uint32)top * 80 + first * 4,
		    pixels, masks, end - first, bottom - top, stride);
}

void Video_Atari_PresentPlanarSpriteStrided(const uint16 *pixels, const uint16 *masks,
                                          uint16 width, uint16 height, int16 x, int16 y,
                                          uint16 sourceWidth)
{
	uint16 left = 0, top = 40, right = 240, bottom = 200;
	uint16 sourceGroups = sourceWidth >> 4, first, end;
	uint8 *base = Video_Atari_PlanarBase();
	bool overlays;

	assert(width > 0 && width <= 80 && (width & 15) == 0 && (x & 15) == 0 &&
	       height > 0 && height <= 64);
	assert(sourceWidth >= width && sourceWidth <= 80 && (sourceWidth & 15) == 0);
	if (x >= right || x + width <= left || y >= bottom || y + height <= top) return;
	left = max((int)left, x);
	top = max((int)top, y);
	right = min((int)right, x + width);
	bottom = min((int)bottom, y + height);
	if (left >= right || top >= bottom) return;
	first = left >> 4;
	end = (right + 15) >> 4;
	if (Video_Atari_ViewportProtectionOverlap(left, top, right - left, bottom - top)) {
		uint16 offset = (top - y) * sourceGroups;
		Video_Atari_PresentProtectedSprite(pixels + offset * 4, masks + offset,
		    sourceWidth, left - x, right - left, bottom - top, left, top, false, NULL);
		return;
	}
	overlays = Video_Atari_PlanarOverlaysOverlap(base, first * 16, top, (end - first) * 16, bottom - top);
	if (overlays && s_spriteHighlightEffect == 0) {
		Video_Atari_PresentPlanarSpriteOverlays(pixels, masks, width, height, x, y, sourceGroups);
		return;
	}
	pixels += (top - y) * sourceGroups * 4 + (left - x) / 16 * Video_Atari_GroupWords();
	masks += (top - y) * sourceGroups + (left - x) / 16;
	Video_Atari_DisplayListFlush();
	if (s_spriteHighlightEffect != 0)
		Video_Atari_PublishSpriteRows(base, pixels, masks, sourceWidth, 0,
		    right - left, bottom - top, left, top, false, overlays, NULL, s_spriteHighlightEffect);
	else
		Video_Atari_PublishCompactSpriteRows(base, pixels, masks, sourceGroups, first, end, top, bottom);
	Video_Atari_RestoreTileCursor();
	GFX_Screen_ClearDirtyRect(first * 16, top, end * 16, bottom);
}

void Video_Atari_PresentPlanarSprite(const uint16 *pixels, const uint16 *masks,
                                   uint16 width, uint16 height, int16 x, int16 y)
{
	Video_Atari_PresentPlanarSpriteStrided(pixels, masks, width, height, x, y, width);
}

void Video_Atari_PresentPlanarText(const uint16 *pixels, const uint16 *masks,
                                  uint16 width, uint16 height, uint16 x, uint16 y)
{
	uint8 *base = Video_Atari_PlanarBase();
	uint16 groups = width >> 4, first = x >> 4;
	bool overlays;

	assert(pixels != NULL && masks != NULL && width != 0 && height != 0);
	assert((width & 15) == 0 && (x & 15) == 0 &&
	       (uint32)x + width <= SCREEN_WIDTH && (uint32)y + height <= SCREEN_HEIGHT);
	overlays = Video_Atari_PlanarOverlaysOverlap(base, x, y, width, height);
	if (g_videoDisplayListActive && !overlays) {
		uint16 *dst = (uint16 *)base + (uint32)y * 80 + first * Video_Atari_GroupWords();
		Video_Atari_DisplayListCheck(VIDEO_ATARI_DISPLAY_TEXT_BYTES);
		if (Video_Atari_Mono()) Video_Atari_QueueMonoMaskedRect(pixels, masks, dst, groups, height);
		else Video_Atari_QueueMaskedRect(pixels, masks, dst, groups, height);
		GFX_Screen_ClearDirtyRect(x, y, x + width, y + height);
		return;
	}
	Video_Atari_PublishViewportCursorRect(base, pixels, masks, groups,
	    first, first + groups, y, y + height, overlays);
}

static uint16 Video_Atari_ShiftSpriteWord(const uint16 *row, uint16 groups,
                                         uint16 sourceX, uint16 destinationPhase, uint16 plane)
{
	uint16 group = sourceX >> 4, shift = sourceX & 15;
	uint16 word = (uint16)(row[group * 4 + plane] << shift);

	if (shift != 0 && group + 1 < groups)
		word |= row[(group + 1) * 4 + plane] >> (16 - shift);
	return word >> destinationPhase;
}

static uint16 Video_Atari_ReadColourSpriteMask(const uint16 *masks, uint16 sourceWidth,
    uint16 sourceX, uint16 phase, bool expanded)
{
	if (expanded) return Video_Atari_ShiftSpriteWord(masks, sourceWidth >> 4, sourceX, phase, 0);
	if (masks == NULL) return 0xffffu >> phase;
	uint16 group = sourceX >> 4, shift = sourceX & 15;
	uint16 mask = (uint16)(masks[group] << shift);
	if (shift != 0 && group + 1 < sourceWidth / 16) mask |= masks[group + 1] >> (16 - shift);
	return mask >> phase;
}

static uint16 Video_Atari_ReadSpriteMask(const uint16 *masks, uint16 sourceWidth,
    uint16 sourceX, uint16 phase, bool expanded)
{
	if (Video_Atari_Mono())
		return Video_Atari_MonoReadMask(masks, sourceWidth, 0, (int16)sourceX - phase, expanded);
	return Video_Atari_ReadColourSpriteMask(masks, sourceWidth, sourceX, phase, expanded);
}

static void Video_Atari_ReadColourSprite(const uint16 *pixels, const uint16 *masks,
    uint16 sourceWidth, uint16 sourceX, uint16 phase, bool expanded, uint16 colours[4], uint16 effect)
{
	uint16 plane;
	for (plane = 0; plane < 4; plane++) {
		uint8 recipe = effect != 0 && expanded ? s_highlightRecipes[effect - 1][plane] : plane;
		colours[plane] = recipe == HL_ZERO ? 0 : Video_Atari_ShiftSpriteWord(
		    recipe < 4 ? pixels : masks, sourceWidth >> 4, sourceX, phase, recipe < 4 ? recipe : recipe - 4);
	}
}

static void __attribute__((noinline)) Video_Atari_RefreshViewportCursorUnshifted(
    uint8 *base, const uint16 *masks, uint16 sourceWidth, uint16 sourceX,
    uint16 width, uint16 height, uint16 x, uint16 y)
{
	uint16 first = max(x >> 4, s_curDrawnGroup);
	uint16 end = min((x + width + 15) >> 4, s_curDrawnGroup + s_curDrawnGroups);
	uint16 top = max(y, s_curDrawnY), bottom = min(y + height, s_curDrawnY + s_curDrawnH);
	uint16 aligned[CURSOR_MAX_H * CURSOR_MAX_GROUPS], row, group, stride = end - first;
	uint16 groups = sourceWidth >> 4;

	if (first >= end || top >= bottom) return;
	for (row = top; row < bottom; row++) {
		const uint16 *src = masks + (uint32)(row - y) * groups * 4;
		for (group = first; group < end; group++) {
			uint16 start = max(x, group * 16), stop = min(x + width, (group + 1) * 16);
			uint16 phase = start & 15;
			uint16 edge = s_blitterLeftMasks[phase] & s_blitterRightMasks[stop & 15];
			aligned[(row - top) * stride + group - first] =
			    Video_Atari_ReadSpriteMask(src, sourceWidth, sourceX + start - x, phase, true) & edge;
		}
	}
	Video_Atari_RefreshViewportCursor(base, first, end, top, bottom, aligned, stride);
}

static void Video_Atari_PublishColourSpriteRows(
    uint8 *base, const uint16 *pixels, const uint16 *masks,
    uint16 sourceWidth, uint16 sourceX, uint16 width, uint16 height,
    uint16 x, uint16 y, bool expanded, bool overlays, const uint16 *writable, uint16 effect)
{
	uint16 destinationPhase = x & 15, first = x >> 4, groups = sourceWidth >> 4;
	uint16 words = (destinationPhase + width + 15) >> 4;
	uint16 row, group;
	uint16 firstMask = s_blitterLeftMasks[destinationPhase];
	uint16 lastMask = s_blitterRightMasks[(x + width) & 15];

	for (row = 0; row < height; row++) {
		uint16 writableMask = writable != NULL ? writable[(y + row - 40) & 15] : 0xffff;
		for (group = 0; group < words; group++) {
			uint16 colours[4], phase = group == 0 ? destinationPhase : 0;
			uint16 source = sourceX + (group == 0 ? 0 : group * 16 - destinationPhase);
			uint16 edge = group == 0 ? firstMask : 0xffff;
			uint16 mask;
			if (group + 1 == words) edge &= lastMask;
			mask = Video_Atari_ReadColourSpriteMask(masks, sourceWidth, source, phase, expanded) & edge & writableMask;
			if (mask == 0) continue;
			Video_Atari_ReadColourSprite(pixels, masks, sourceWidth, source, phase, expanded, colours, effect);
			if (overlays) Video_Atari_PlanarMergeGroup(base, y + row, first + group, mask, colours);
			else Video_Atari_PlanarMergePlain(
			    (uint16 *)(base + (uint32)(y + row) * ST_PLANAR_LINE_BYTES + (first + group) * 8),
			    mask, colours);
		}
		pixels += groups * 4;
		if (masks != NULL) masks += groups * (expanded ? 4 : 1);
	}
}

static void Video_Atari_PublishMonoSpriteRows(
    uint8 *base, const uint16 *pixels, const uint16 *masks,
    uint16 sourceWidth, uint16 sourceX, uint16 width, uint16 height,
    uint16 x, uint16 y, bool expanded, bool overlays, const uint16 *writable, uint16 effect)
{
	uint16 first = x >> 4, end = (x + width + 15) >> 4, row, group;
	for (row = 0; row < height; row++) {
		uint16 writableMask = writable != NULL ? writable[(y + row - 40) & 15] : 0xffff;
		for (group = first; group < end; group++) {
			int16 sx = sourceX + group * 16 - x;
			uint16 words[4], mask = Video_Atari_MonoReadMask(masks, sourceWidth, row, sx, expanded);
			if (group == first) mask &= 0xffffu >> (x & 15);
			if (group + 1 == end && ((x + width) & 15) != 0) mask &= 0xffffu << (16 - ((x + width) & 15));
			mask &= writableMask;
			if (mask == 0) continue;
			Video_Atari_MonoReadSpan(pixels, sourceWidth / 4, row, sx, words);
			if (effect != 0) {
				uint16 i;
				for (i = 0; i < 4; i++) words[i] = ~words[i];
			}
			if (overlays) Video_Atari_PlanarMergeGroup(base, y + row, group, mask, words);
			else {
				uint16 old[4];
				Video_Atari_MonoReadGroup((const uint16 *)base, 80, y + row, group, old);
				Video_Atari_MonoMergeWords(old, words, mask);
				Video_Atari_MonoWriteGroup((uint16 *)base, 80, y + row, group, old);
			}
		}
	}
}

static void __attribute__((noinline)) Video_Atari_PublishSpriteRows(
    uint8 *base, const uint16 *pixels, const uint16 *masks,
    uint16 sourceWidth, uint16 sourceX, uint16 width, uint16 height,
    uint16 x, uint16 y, bool expanded, bool overlays, const uint16 *writable, uint16 effect)
{
	if (Video_Atari_Mono())
		Video_Atari_PublishMonoSpriteRows(base, pixels, masks, sourceWidth, sourceX,
		    width, height, x, y, expanded, overlays, writable, effect);
	else
		Video_Atari_PublishColourSpriteRows(base, pixels, masks, sourceWidth, sourceX,
		    width, height, x, y, expanded, overlays, writable, effect);
}

static uint16 Video_Atari_SpriteWordOffset(uint16 x)
{
	return Video_Atari_Mono() ? x / 8 : (x >> 4) * 4;
}

void Video_Atari_PresentPlanarSpriteUnshifted(const uint16 *pixels, const uint16 *masks,
                                            uint16 sourceWidth, uint16 sourceX,
                                            uint16 width, uint16 height, uint16 x, uint16 y,
                                            const Video_Atari_SpriteBlitGeometry *geometry,
                                            const Video_Atari_SpriteBlitCode *code)
{
	uint8 *base = Video_Atari_PlanarBase();
	uint16 destinationPhase = x & 15;
	uint16 first = x >> 4;
	uint16 words = (destinationPhase + width + 15) >> 4;
	bool queued = g_videoDisplayListActive;
	bool cursor, placement;

	assert(sourceWidth > 0 && sourceWidth <= 80 && (sourceWidth & 15) == 0);
	assert(width > 0 && sourceX + width <= sourceWidth);
	assert(height > 0 && height <= 64 && x + width <= 240 && y >= 40 && y + height <= 200);
	if (!queued && g_videoScrollPending) Video_Atari_FinishScroll();
	if (Video_Atari_ViewportProtectionOverlap(x, y, width, height)) {
		Video_Atari_PresentProtectedSprite(pixels, masks, sourceWidth, sourceX,
		    width, height, x, y, true, code);
		return;
	}
	cursor = Video_Atari_CursorRectOverlap(base, first, first + words, y, height);
	placement = Video_Atari_PlacementRectOverlap(base, first * 16, (first + words) * 16, y, height);
	if (s_viewportBlitter && !placement && (s_spriteHighlightEffect == 0 || s_planarBackend->blitterSpriteEffects)) {
		Video_Atari_SpriteBlitPlan clippedPlan;
		const Video_Atari_SpriteBlitPlan *plan = NULL;
		uint16 offset = Video_Atari_SpriteWordOffset(sourceX);
		uint16 rows = height << s_planarBackend->spriteYShift;
		uint16 *dst = (uint16 *)base + (uint32)y * 80 + Video_Atari_SpriteWordOffset(x);
		if (geometry == NULL || s_spriteHighlightEffect != 0) {
			Video_Atari_BuildSpriteBlitPlan(&clippedPlan, sourceWidth, sourceX, width, destinationPhase);
			plan = &clippedPlan;
		}
		s_blitterTileSetup = false;
		if (queued && s_spriteHighlightEffect == 0) {
			if (geometry != NULL) {
				Video_Atari_QueueSpriteBlitGeometry(code, pixels + offset,
				    masks + offset, dst, rows, geometry);
			} else {
				Video_Atari_QueueSpriteBlitCode(code, pixels + offset,
				    masks + offset, dst, rows, plan);
			}
		} else
#if ATARI_SUPERVISOR_RESIDENT
		if (g_atariSupervisorResident && s_spriteHighlightEffect == 0) {
			if (geometry != NULL) {
				Video_Atari_ExecuteSpriteBlitGeometry(code, pixels + offset,
				    masks + offset, dst, rows, geometry);
			} else {
				Video_Atari_ExecuteSpriteBlitCode(code, pixels + offset,
				    masks + offset, dst, rows, plan);
			}
		} else
#endif
		{
			s_planarBlit.dst = dst;
			s_planarBlit.pixels = pixels + offset;
			s_planarBlit.masks = masks + offset;
			s_planarBlit.plan = plan;
			s_planarBlit.geometry = geometry;
			s_planarBlit.height = rows;
			s_planarBlit.code = code;
			if (queued) {
				Video_Atari_QueueMaskedBlit(false);
			} else {
				Atari_SupervisorExec(s_spriteHighlightEffect != 0 ?
				    Video_Atari_BlitMaskedHighlight : Video_Atari_BlitCompiledSprite);
			}
		}
		if (cursor) {
			Video_Atari_RefreshViewportCursorUnshifted(base, masks, sourceWidth, sourceX,
			    width, height, x, y);
		}
	} else {
		Video_Atari_DisplayListFlush();
		Video_Atari_PublishSpriteRows(base, pixels, masks, sourceWidth, sourceX,
		    width, height, x, y, true, cursor || placement, NULL, s_spriteHighlightEffect);
	}
	if (cursor || placement || !s_viewportBlitter || !queued)
		Video_Atari_RestoreTileCursor();
	GFX_Screen_ClearDirtyRect(first * 16, y, (first + words) * 16, y + height);
}

static bool __attribute__((noinline)) Video_Atari_QueueMonoFogFragment(
    uint8 *base, const uint16 *pixels, const uint16 *masks, uint16 sourceWidth,
    uint16 sourceX, uint16 left, uint16 top, uint16 right, uint16 bottom,
    const uint16 *writable, const Video_Atari_SpriteBlitCode *code)
{
	enum { monoFogMaskedBytes = 48 + 102 + 2 * 30, monoFogClearBytes = 78 };
	struct { uint16 x, y, w, h; bool masked; } pieces[4];
	uint16 pattern[16] = {0};
	uint16 x, y, count = 0, mixed = 0, bytes = 0;

	for (y = top; y < bottom; ) {
		uint16 endY = min(bottom, 40 + (((y - 40) | 7) + 1));
		for (x = left; x < right; ) {
			uint16 endX = min(right, (x | 7) + 1);
			uint16 edge = s_blitterLeftMasks[x & 15] & s_blitterRightMasks[endX & 15];
			uint16 any = 0, all = edge, line;
			bool masked;

			for (line = y; line < endY; line++) {
				uint16 word = writable[(line - 40) & 15];
				any |= word;
				all &= word;
			}
			if ((any & edge) == 0) {
				x = endX;
				continue;
			}
			masked = all != edge;
			if (masked && ++mixed > 1) return false;
			pieces[count].x = x;
			pieces[count].y = y;
			pieces[count].w = endX - x;
			pieces[count].h = endY - y;
			pieces[count++].masked = masked;
			bytes += masked ? monoFogMaskedBytes : monoFogClearBytes;
			x = endX;
		}
		y = endY;
	}
	if (g_videoDisplayListLimit - g_videoDisplayListNext < bytes / 2) return false;
	for (x = 0; x < count; x++) {
		uint16 px = pieces[x].x, py = pieces[x].y;
		uint16 sx = sourceX + px - left;
		uint16 offset = (py - top) * (sourceWidth / 4) + Video_Atari_SpriteWordOffset(sx);
		Video_Atari_SpriteBlitPlan plan;

		Video_Atari_BuildSpriteBlitPlan(&plan, sourceWidth, sx, pieces[x].w, px & 15);
		assert(plan.words == 1);
		if (!pieces[x].masked) {
			Video_Atari_QueueSpriteBlitCode(code, pixels + offset, masks + offset,
			    (uint16 *)base + (uint32)py * 80 + px / 8, pieces[x].h * 2, &plan);
		} else {
			uint16 line;
			/* One halftone word per physical row; the emitter copies the pattern. */
			for (line = 0; line < pieces[x].h; line++) {
				uint16 words[4];
				Video_Atari_MonoMaskWords(writable[(py + line - 40) & 15], words);
				pattern[line * 2] = pattern[line * 2 + 1] = words[(px >> 3) & 1];
			}
			s_planarBlit.plan = &plan;
			s_planarBlit.pixels = pixels + offset;
			s_planarBlit.masks = masks + offset;
			s_planarBlit.dst = (uint16 *)base + (uint32)py * 80 + px / 8;
			s_planarBlit.height = pieces[x].h * 2;
			s_planarBlit.code = code;
			s_planarBlit.writable = pattern;
			s_planarBlit.firstLine = 0;
			Video_Atari_QueueMaskedBlit(true);
		}
	}
	return true;
}

/* Only rectangles intersecting protection are split; clear runs still use the
 * ordinary publishers. Cached source pixels and opacity remain immutable. */
static void Video_Atari_PresentProtectedSprite(const uint16 *pixels, const uint16 *masks,
    uint16 sourceWidth, uint16 sourceX, uint16 width, uint16 height, uint16 x, uint16 y,
    bool expanded, const Video_Atari_SpriteBlitCode *code)
{
	uint16 endY = y + height, right = x + width, groups = sourceWidth >> 4;
	uint16 top, left;
	uint8 *base = Video_Atari_PlanarBase();

	for (top = y; top < endY; ) {
		uint16 row = (top - 40) >> 4;
		uint16 bottom = min(endY, 56 + (row << 4));
		uint16 rowOffset = (top - y) * groups;
		for (left = x; left < right; ) {
			uint16 col = left >> 4, end = min(right, (col + 1) << 4);
			const uint16 *writable = Video_Atari_ViewportWritable(col, row);
			if (writable == NULL) {
				while (end < right && Video_Atari_ViewportWritable(end >> 4, row) == NULL)
					end = min(right, end + 16);
				if (expanded) {
					Video_Atari_PresentPlanarSpriteUnshifted(pixels + rowOffset * 4,
					    masks + rowOffset * 4, sourceWidth, sourceX + left - x,
					    end - left, bottom - top, left, top, NULL, code);
				} else {
					uint16 column = (sourceX + left - x) >> 4;
					Video_Atari_PresentPlanarSpriteStrided(
					    pixels + rowOffset * 4 + column * Video_Atari_GroupWords(), masks + rowOffset + column,
					    end - left, bottom - top, left, top, sourceWidth);
				}
			} else if ((s_viewportHiddenRows[row] & (1u << col)) == 0) {
				uint16 srcX = sourceX + left - x, line;
				uint16 edge = s_blitterLeftMasks[left & 15] & s_blitterRightMasks[end & 15];
				const uint16 *srcPixels = pixels + rowOffset * 4;
				const uint16 *srcMasks = masks + rowOffset * (expanded ? 4 : 1);
				bool cursor = Video_Atari_CursorRectOverlap(base, col, col + 1, top, bottom - top);
				bool placement = Video_Atari_PlacementRectOverlap(base, col * 16, (col + 1) * 16, top, bottom - top);
				bool hardware = expanded && s_viewportBlitter && !placement &&
				    s_planarBackend->blitterProtectedSprites &&
				    (s_spriteHighlightEffect == 0 || s_planarBackend->blitterSpriteEffects);
				if (Video_Atari_Mono() && expanded && s_viewportBlitter &&
				    g_videoDisplayListActive && !cursor && !placement && s_spriteHighlightEffect == 0 &&
				    Video_Atari_QueueMonoFogFragment(base, srcPixels, srcMasks, sourceWidth,
				        srcX, left, top, end, bottom, writable, code)) {
					GFX_Screen_ClearDirtyRect(col * 16, top, (col + 1) * 16, bottom);
					left = end;
					continue;
				}
				if (hardware) {
					Video_Atari_SpriteBlitPlan plan;
					Video_Atari_BuildSpriteBlitPlan(&plan, sourceWidth, srcX, end - left, left & 15);
					s_planarBlit.plan = &plan;
					s_planarBlit.pixels = srcPixels + (srcX >> 4) * 4;
					s_planarBlit.masks = srcMasks + (srcX >> 4) * 4;
					s_planarBlit.dst = (uint16 *)(base + (uint32)top * ST_PLANAR_LINE_BYTES + col * 8);
					s_planarBlit.height = bottom - top;
					s_planarBlit.code = code;
					s_planarBlit.writable = writable;
					s_planarBlit.firstLine = (top - 40) & 15;
					if (g_videoDisplayListActive)
						Video_Atari_QueueMaskedBlit(true);
					else
						Atari_SupervisorExec(Video_Atari_BlitProtectedSprite);
				}
				if (!hardware) {
					Video_Atari_DisplayListFlush();
					Video_Atari_PublishSpriteRows(base, srcPixels, srcMasks, sourceWidth, srcX,
					    end - left, bottom - top, left, top, expanded, cursor || placement,
					    writable, s_spriteHighlightEffect);
				} else if (cursor) {
					uint16 written[16];
					Video_Atari_DisplayListFlush();
					for (line = 0; line < bottom - top; line++) {
						const uint16 *m = srcMasks + line * groups * (expanded ? 4 : 1);
						uint16 mask = Video_Atari_ReadSpriteMask(m, sourceWidth, srcX, left & 15, expanded);
						mask &= edge & writable[(top + line - 40) & 15];
						written[line] = mask;
					}
					Video_Atari_RefreshViewportCursor(base, col, col + 1, top, bottom, written, 1);
				}
				if (!hardware || cursor || !g_videoDisplayListActive) Video_Atari_RestoreTileCursor();
				GFX_Screen_ClearDirtyRect(col * 16, top, (col + 1) * 16, bottom);
			}
			left = end;
		}
		top = bottom;
	}
}

/* Install the quantization a following present must use, while the
 * hardware registers are still dark. See the section comment. */
void Video_Atari_PresentPaletteRange(const uint8 *palette, int from, int length)
{
	union { const uint8 *cp; void *p; } u;

	if (!s_presentMode) return;

	u.cp = palette;
	Video_SetPalette(u.p, from, length);
	/* Installing the quantization *before* anything is drawn is the whole
	 * point of this call, so the full repaint Video_SetPalette() may have
	 * just asked for has nothing to repaint yet. */
	s_screen_needrepaint = false;
}

void Video_Atari_PresentPalette(const uint8 *palette)
{
	Video_Atari_PresentPaletteRange(palette, 0, 256);
}

bool Video_Atari_PresentEnter(void)
{
	if (s_machine_type != MCH_ST && s_machine_type != MCH_STE
	 && s_machine_type != MCH_MEGA_STE) return false;
	if (s_presentMode) return true;

	/* Anything composited on top of the planar picture is about to be
	 * overwritten by presented pixels that know nothing about it, and its
	 * saved background would no longer match what is underneath. Take the
	 * placement preview and the cursor down first. (Present mode is only
	 * used by cutscenes, which hide the mouse anyway, but a cursor left
	 * composited from an earlier screen would otherwise linger.) */
	Video_Atari_PlacementHide();
	Video_Atari_CursorHide();
	Video_Atari_CursorEraseFull();

	s_presentMode = true;
	return true;
}

void Video_Atari_PresentLeave(void)
{
	if (!s_presentMode) return;

	s_presentMode = false;

	/* Native animations have no chunky shadow. The caller clears/composes
	 * the next screen explicitly before returning to ordinary rendering. */
}

bool Video_Atari_PresentChunky(const void *src, uint16 srcStride,
                               int16 x, int16 y, uint16 width, uint16 height)
{
	/* EXPERIMENT: no longer gated on s_presentMode -- GFX_Screen_Copy()
	 * calls this on every chunky write to SCREEN_0, present-mode enclave
	 * or not. The planar writers synchronously preserve cursor and
	 * placement backgrounds independently of GUI hide/show brackets. */
	if (src == NULL || width == 0 || height == 0) return false;
	if (x < 0 || y < 0) return false;
	if ((int)x + (int)width > SCREEN_WIDTH) return false;
	if ((int)y + (int)height > SCREEN_HEIGHT) return false;

	if (((x | width) & 15) != 0 ||
	    (((uint32)src) & (s_planarBackend->chunkyAlignment - 1)) != 0 ||
	    ((srcStride & (s_planarBackend->chunkyAlignment - 1)) != 0 && height > 1)) {
		/* A private, tightly packed source (not SCREEN_WIDTH strided)
		 * cannot be over-read outside [x, x+width): the masked
		 * read-modify-write path is the only safe option. */
		uint16 left = (uint16)(x & ~0xf);
		uint16 right = (uint16)((x + width + 0xf) & ~0xf);

		if (right > SCREEN_WIDTH) right = SCREEN_WIDTH;

		Video_Atari_PresentRunMasked((const uint8 *)src, srcStride,
		                             (uint16)x, (uint16)y, width, height);
		Video_Atari_RestoreTileCursor();
		/* Widen the clear to the enclosing 16px block(s), same as the
		 * fast unmasked path above: Video_Atari_PresentGroupMasked()
		 * (via PresentRunMasked) merges into whatever a partially
		 * covered edge group already held, so once this call returns
		 * the whole group -- not just [x, x+width) -- is final, correct
		 * planar content. Clearing only the exact, unaligned rectangle
		 * would leave the rest of that edge group's dirty bit set,
		 * which the old SCREEN_0-dirty-block sweep would later
		 * reconvert from chunky data that was never written for it. */
		GFX_Screen_ClearDirtyRect(left, (uint16)y, right, (uint16)(y + height));
		return true;
	}

	Video_Atari_PresentRun((const uint8 *)src, srcStride,
	                       (uint16)x, (uint16)y, width, height);
	Video_Atari_RestoreTileCursor();
	GFX_Screen_ClearDirtyRect((uint16)x, (uint16)y,
	                          (uint16)(x + width), (uint16)(y + height));
	return true;
}

bool Video_Atari_PresentFill(int16 x, int16 y, uint16 width, uint16 height, uint8 colour)
{
	/* EXPERIMENT: see Video_Atari_PresentChunky() -- no longer gated on
	 * s_presentMode. */
	if (width == 0 || height == 0) return false;
	if (x < 0 || y < 0) return false;
	if ((int)x + (int)width > SCREEN_WIDTH) return false;
	if ((int)y + (int)height > SCREEN_HEIGHT) return false;

	Video_Atari_PlanarFill((uint16)x, (uint16)y, width, height, s_palette4BitMap[colour]);
	/* Widen the clear to the enclosing 16px block(s): PlanarFill's own
	 * edge masking merges into whatever a partially covered edge group
	 * already held (same reasoning as PresentChunky's masked branch
	 * above), so the whole group is final afterwards, not just [x,
	 * x+width). Currently always called full-screen/block-aligned in
	 * practice, so this is a no-op today, but keeps the invariant true
	 * if that ever changes. */
	{
		uint16 left = (uint16)(x & ~0xf);
		uint16 right = (uint16)((x + width + 0xf) & ~0xf);

		if (right > SCREEN_WIDTH) right = SCREEN_WIDTH;
		GFX_Screen_ClearDirtyRect(left, (uint16)y, right, (uint16)(y + height));
	}
	return true;
}

/**
 * Shift a rectangle of the ST/STE planar screen buffer in place by
 * (dx, dy) pixels, without touching the chunky shadow or running c2p.
 * The caller must reconstruct the exposed tiles; they are not cleared.
 *
 * This is for the gameplay viewport scroll: it is always a whole number
 * of 16 pixel tiles in each direction, so x, width and dx are always a
 * multiple of 16 (one c2p group = four interleaved plane words).
 * The enabled viewport BLiTTER copies the rectangle in shared-bus mode,
 * allowing display-list construction to overlap the copy. The first
 * flush or immediate screen access finishes it in HOG mode. Otherwise
 * the copy uses memmove per scanline.
 * No bit-level shifting across word boundaries is needed.
 * The already-converted pixels being moved need no further c2p work;
 * only whatever the caller newly draws at the exposed edge does.
 *
 * Returns false (does nothing) on TT/Falcon, whose planar layout this
 * does not match, or if the geometry is not group aligned or would run
 * outside the screen. Callers must be prepared for that: the pixels
 * simply stay where they were and have to be re-presented/converted in
 * full by whatever normally would, exactly as before this function
 * existed.
 */
bool Video_Atari_ShiftPlanar(int16 x, int16 y, uint16 width, uint16 height, int16 dx, int16 dy)
{
	uint8 *base;
	uint8 *src;
	uint8 *dst;
	int16 srcX, dstX, srcY, dstY;
	uint16 bytes;
	uint16 rows;
	uint16 physicalStride = Video_Atari_Mono() ? 80 : ST_PLANAR_LINE_BYTES;
	bool placementVisible;

	if (s_machine_type != MCH_ST && s_machine_type != MCH_STE
	 && s_machine_type != MCH_MEGA_STE) return false;
	if (width == 0 || height == 0) return false;
	if (((x | (int16)width | dx) & 0xf) != 0) return false;
	if (dx == 0 && dy == 0) return true;
	srcX = x;
	dstX = (int16)(x + dx);
	srcY = y;
	dstY = (int16)(y + dy);

	if (srcX < 0 || dstX < 0) return false;
	if ((int)srcX + (int)width > SCREEN_WIDTH) return false;
	if ((int)dstX + (int)width > SCREEN_WIDTH) return false;
	if (srcY < 0 || dstY < 0) return false;
	if ((int)srcY + (int)height > SCREEN_HEIGHT) return false;
	if ((int)dstY + (int)height > SCREEN_HEIGHT) return false;

	base = Video_Atari_PlanarBase();
	/* Neither overlay may be copied as scene content. */
	Video_Atari_CursorEraseFull();
	placementVisible = s_placeVisible;
	s_placeVisible = false;
	Video_Atari_PlacementEnd(base);
	bytes = Video_Atari_Mono() ? width / 4 : width / 2;
	rows = Video_Atari_Mono() ? height * 2 : height;

	src = base + (uint32)srcY * ST_PLANAR_LINE_BYTES + (Video_Atari_Mono() ? srcX / 4 : srcX / 2);
	dst = base + (uint32)dstY * ST_PLANAR_LINE_BYTES + (Video_Atari_Mono() ? dstX / 4 : dstX / 2);

	if (s_viewportBlitter) {
		int16 increment = 2;
		int16 rowIncrement = physicalStride - bytes + 2;

		if (dst > src) {
			uint32 last = (uint32)(rows - 1) * physicalStride + bytes - 2;
			src += last;
			dst += last;
			increment = -increment;
			rowIncrement = -rowIncrement;
		}
		Video_Atari_SpriteBlitPlan plan = {
			.sourceXinc = increment, .sourceYinc = rowIncrement,
			.firstMask = 0xffff, .middleMask = 0xffff, .lastMask = 0xffff,
			.destinationXinc = increment, .destinationYinc = rowIncrement,
			/* Reverse reads enter the high latch half; prefetch then drain it. */
			.words = bytes / 2, .skew = increment < 0 ? 0xc0 : 0
		};
		s_planarBlit.pixels = (const uint16 *)src;
		s_planarBlit.dst = (uint16 *)dst;
		s_planarBlit.height = rows;
		s_planarBlit.plan = &plan;
		Atari_SupervisorExec(Video_Atari_BlitScroll);
		s_planarBlit.plan = NULL;
	} else if (dstY > srcY) {
		/* Destination rows are below source rows: copy bottom row first
		 * so a lower destination row never clobbers a source row a
		 * higher iteration still needs to read. memmove() per row
		 * already handles horizontal overlap either way. */
		src += (uint32)(rows - 1) * physicalStride;
		dst += (uint32)(rows - 1) * physicalStride;
		while (rows-- != 0) {
			memmove(dst, src, bytes);
			src -= physicalStride;
			dst -= physicalStride;
		}
	} else {
		while (rows-- != 0) {
			memmove(dst, src, bytes);
			src += physicalStride;
			dst += physicalStride;
		}
	}

	s_placeVisible = placementVisible;
	if (s_placeVisible) Video_Atari_PlacementEnd(base);
	if (s_curVisible) Video_Atari_CursorSync(base);
	return true;
}

#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
/**
 * Convert a set of 16px-block dirty masks (one word per scanline, indexed
 * from row 0 like g_dirty_blocks[]/g_dirty_blocks_viewport[]) to the planar
 * screen, for rows [top, bottom). screen/data must already point at row
 * top. This is the same band-batching + run-splitting c2p sweep
 * Video_Tick() runs over SCREEN_0's dirty blocks, factored out so the
 * viewport's independent SCREEN_1-sourced sweep (see g_dirty_blocks_viewport
 * in gfx.h) gets it -- and any future tuning of it -- unchanged, with no
 * awareness of which screen it is converting from needed on either side.
 */
static void Video_Atari_C2P_ConvertBlocks(uint8 *screen, uint8 *data, const uint32 *blocks,
	uint16 top, uint16 bottom, DirtySweepKind kind)
{
	uint8 *base = screen - (uint32)top * ST_PLANAR_LINE_BYTES;
	uint32 sweepPixels = 0, sweepCalls = 0;
	uint16 y;
	uint16 runCount = 0;
	uint16 runLeft[10];	/* first pixel of the run */
	uint16 runWidth[10];	/* pixels in the run */
	(void)kind; /* Sweep logging can be compiled out. */
#ifdef VIDEO_C2P_STATS
	uint32 tickRows = 0, tickSpan = 0, tickTopBar = 0, tickBattlefield = 0, tickSidebar = 0;
#endif

	for (y = top; y < bottom; ) {
		uint32 mask = blocks[y];
		uint16 bandTop = y;
		uint16 bandLines;

		do {
			y++;
		} while (y < bottom && blocks[y] == mask);
		bandLines = y - bandTop;

		if (mask != 0) {
			uint32 rest = mask;
			uint16 run;
			uint16 bandWidth = 0;

			runCount = 0;
			while (rest != 0) {
				uint16 runStart = Video_FirstDirtyBlock(rest);
				uint16 runEnd = runStart + Video_FirstCleanBlock(rest >> runStart);

				runLeft[runCount] = runStart << 4;
				runWidth[runCount] = (runEnd - runStart) << 4;
				bandWidth += runWidth[runCount];
				runCount++;
				rest &= ~(((uint32)1 << runEnd) - 1);
			}
			for (run = 0; run < runCount; run++) {
				uint16 left = runLeft[run];
				uint16 width = runWidth[run];

				Video_Atari_ConvertRun(base, data + left, SCREEN_WIDTH,
					left, bandTop, width, bandLines, left, bandTop);
#ifdef VIDEO_C2P_STATS
				if (kind == DIRTY_SWEEP_LEGACY) {
					uint16 topLines = bandTop < VIDEO_C2P_TOPBAR_HEIGHT ?
						min(y, VIDEO_C2P_TOPBAR_HEIGHT) - bandTop : 0;
					uint16 battRight = min(left + width, VIDEO_C2P_SIDEBAR_LEFT);
					uint16 sideLeft = max(left, VIDEO_C2P_SIDEBAR_LEFT);
					tickTopBar += (uint32)width * topLines;
					if (battRight > left) tickBattlefield += (uint32)(battRight - left) * (bandLines - topLines);
					if (left + width > sideLeft) tickSidebar += (uint32)(left + width - sideLeft) * (bandLines - topLines);
				}
#endif
			}
			sweepPixels += (uint32)bandWidth * bandLines;
			sweepCalls += runCount;
			Video_Atari_DirtySweepBand(mask, bandTop, y, bandWidth);
#ifdef VIDEO_C2P_STATS
			tickRows += bandLines;
			tickSpan += (uint32)((Video_LastDirtyBlock(mask) - Video_FirstDirtyBlock(mask)) << 4) * bandLines;
#endif
		}
		screen += (SCREEN_WIDTH >> 1) * bandLines;
		data += SCREEN_WIDTH * bandLines;
	}
	Video_Atari_DirtySweepRecord(kind, sweepPixels, sweepCalls);
#ifdef VIDEO_C2P_STATS
	if (kind == DIRTY_SWEEP_LEGACY) {
		s_statLineCalls += sweepCalls;
		s_statTickCalls += sweepCalls;
		s_statTickRows += tickRows;
		s_statLinePixels += sweepPixels;
		s_statDirtyPixels += sweepPixels;
		s_statTickPixels += sweepPixels;
		s_statTickDirty += sweepPixels;
		s_statSpanPixels += tickSpan;
		s_statTopBarPixels += tickTopBar;
		s_statBattlefieldPixels += tickBattlefield;
		s_statSidebarPixels += tickSidebar;
	}
#endif
}
#endif

/**
 * Runs every tick to handle video updates.
 */
void Video_Tick(void)
{
	Video_Atari_DisplayListFlush();
	/* EXPERIMENT: on ST/STE direct-cursor builds, GFX_Screen_Copy()/Copy2()
	 * skip the chunky SCREEN_0 write and convert straight from their
	 * (SCREEN_1) source instead, so SCREEN_0 itself may be stale wherever
	 * that skip-write path was taken. Read this old dirty-block sweep's
	 * source from SCREEN_1 too on those builds, since virtually every
	 * SCREEN_0 writer already mirrors through SCREEN_1 first -- risking
	 * only redundant double-conversion of blocks written straight to
	 * SCREEN_0 for real, not corruption. TT/Falcon (which still fully
	 * write SCREEN_0) keep reading from SCREEN_0 as before. */
	uint8 *data = GFX_Screen_Get_ByIndex(Video_Atari_CursorDirect() ? SCREEN_1 : SCREEN_0);
	uint8 *screen = s_planarBase != NULL ? s_planarBase - s_center_image_offset : (uint8 *)Logbase();
	uint8 *frameBase = screen + s_center_image_offset;
	bool placementRedraw = false;
	screen += s_center_image_offset;
	Video_Atari_DirtySweepBeginTick();

	/* send mouse event */
	if(s_mouse_state_changed) {
		s_mouse_state_changed = false;
		Mouse_EventHandler(s_mouse_x, s_mouse_y,
		                   s_mouse_left_btn, s_mouse_right_btn);
	}

#ifdef VIEWPORT_DEBUG_DAMAGE
	if (s_damageDebugOverlay) {
		Video_Atari_DirtySweepEndTick();
		return;
	}
#endif

	if (s_presentMode) {
		/* Direct publication consumes its dirty groups. Only remaining
		 * legacy writes reach the sweep; native WSA pixels have no shadow. */
		Video_Atari_PlacementHide();
		Video_Atari_CursorHide();
	}

	if (s_curDirect) {
		if (g_selectionType != SELECTIONTYPE_PLACE && !GUI_Widget_Viewport_TileCursorActive()) Video_Atari_PlacementHide();
		placementRedraw = Video_Atari_PlacementBegin();
	}

	if (GFX_Screen_IsDirty(SCREEN_0) || s_screen_needrepaint) {
		struct dirty_area * area;
		int height = SCREEN_HEIGHT;
#ifdef VIDEO_C2P_STATS
		s_statTickPixels = 0;
		s_statTickDirty = 0;
		s_statTickCalls = 0;
		s_statTickRows = 0;
#endif
		int width = SCREEN_WIDTH;
		int left = 0;

#ifdef VIDEO_C2P_STATS
		s_statConverts++;
#endif
		area = GFX_Screen_GetDirtyArea(SCREEN_0);
		if (!s_screen_needrepaint && area != NULL) {
			if (area->top >= area->bottom) {
				Warning("GFX_Screen_GetDirtyArea: (%hu, %hu) - (%hu, %hu)\n", area->left, area->top, area->right, area->bottom);
				goto l_overlays;
			}
			data += area->top * SCREEN_WIDTH;
			if (s_machine_type == MCH_TT) {
				screen += area->top * (SCREEN_WIDTH << 1);
			} else if (s_machine_type == MCH_ST || s_machine_type == MCH_STE || s_machine_type == MCH_MEGA_STE) {
				screen += area->top * (SCREEN_WIDTH >> 1);
			} else {
				screen += area->top * SCREEN_WIDTH;
			}

			if (area->bottom > SCREEN_HEIGHT) {
				Warning("GFX_Screen_GetDirtyArea: (%hu, %hu) - (%hu, %hu)\n", area->left, area->top, area->right, area->bottom);
				area->bottom = SCREEN_HEIGHT;
			}
			height = area->bottom - area->top;
			left = area->left & ~0xf;
			width = ((area->right + 0xf) & ~0xf) - left;
			if (width >= (SCREEN_WIDTH - 32)) {
				left = 0;
				width = SCREEN_WIDTH;
			}
		}

		/* chunky to planar conversion */
		if(s_machine_type == MCH_TT) {
			data += (s_screenOffset << 2);
			/* c2p1x1_8_tt is only able to convert full lines */
			if (width == SCREEN_WIDTH) {
				c2p1x1_8_tt(screen, data, height*SCREEN_WIDTH);
			} else {
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
				uint16 y;
				for (y = area->top; y < area->bottom; y++) {
					if (g_dirty_blocks[y] != 0) {
						uint32 blocks = g_dirty_blocks[y];
						left = Video_FirstDirtyBlock(blocks) << 4;
						width = (Video_LastDirtyBlock(blocks) << 4) - left;
						c2p1x1_8_tt_partial(screen + left, data + left, width);
					}
					screen += 2*SCREEN_WIDTH;
					data += SCREEN_WIDTH;
				}
#else
				screen += left;
				data += left;
				while(height > 0) {
					c2p1x1_8_tt_partial(screen, data, width);
					screen += 2*SCREEN_WIDTH;
					data += SCREEN_WIDTH;
					height--;
				}
#endif
			}
		} else if (s_machine_type == MCH_FALCON) {
			if (width == SCREEN_WIDTH) {
				c2p1x1_8_falcon(screen, data, height*SCREEN_WIDTH);
			} else {
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
				uint16 y;
				for (y = area->top; y < area->bottom; y++) {
					if (g_dirty_blocks[y] != 0) {
						uint32 blocks = g_dirty_blocks[y];
						left = Video_FirstDirtyBlock(blocks) << 4;
						width = (Video_LastDirtyBlock(blocks) << 4) - left;
						c2p1x1_8_falcon(screen + left, data + left, width);
					}
					screen += SCREEN_WIDTH;
					data += SCREEN_WIDTH;
				}
#else
				screen += left;
				data += left;
				while(height > 0) {
					c2p1x1_8_falcon(screen, data, width);
					screen += SCREEN_WIDTH;
					data += SCREEN_WIDTH;
					height--;
				}
#endif
			}
		} else if (s_machine_type == MCH_ST || s_machine_type == MCH_STE || s_machine_type == MCH_MEGA_STE) {
			/* No s_screenOffset shift of the chunky source here: on ST/STE
			 * the explosion shake moves the shifter's base address instead
			 * (see Video_SetOffset()), so the picture always occupies the
			 * same place in the planar buffer. */
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
			/* Always take the per line path when the block masks are
			 * available. The "full width" shortcut computed above converts
			 * every line of the bounding box completely, which is very
			 * wasteful as soon as a wide but thin element widens the box:
			 * the scrolling message bar (widget 7) alone spans pixels
			 * 8..312, so it sets all 20 block bits and forces the shortcut
			 * for the whole bounding box height. */
			if (s_screen_needrepaint || area == NULL) {
#else
			if (width == SCREEN_WIDTH) {
#endif
				if (s_screen_needrepaint) {
					/* The viewport rectangle's pixels only live in SCREEN_1
					 * now (see the SCREEN_0 dirty-mark-only change in
					 * GUI_Widget_Viewport_Draw()): this full-screen path
					 * still reads SCREEN_0 unconditionally, so it would
					 * show stale viewport content if it ever fires here.
					 * Gameplay never re-quantizes >=128 palette entries at
					 * once on ST/STE (only the 16 hardware pens change),
					 * so this is only expected from other contexts (e.g.
					 * cutscene fades, which use their own present-mode path
					 * instead of this one anyway) -- warn if that
					 * assumption ever turns out wrong. */
					Warning("Video_Tick: full SCREEN_0 repaint while viewport pixels live in SCREEN_1 -- viewport may show stale content this frame.\n");
				}
#ifdef VIDEO_C2P_STATS
				if (s_screen_needrepaint) {
					/* Legitimate: a palette change of >=128 entries
					 * (fade/transition) invalidates every pixel's pen,
					 * so the whole screen really is stale. Counted
					 * separately and kept out of the waste figures. */
					s_statForcedRepaints++;
					s_statForcedPixels += (uint32)height * SCREEN_WIDTH;
					Video_C2PStats_Region(0, (uint16)height, 0, SCREEN_WIDTH);
				} else {
					s_statSnapCalls++;
					s_statSnapPixels += (uint32)height * SCREEN_WIDTH;
					Video_C2PStats_Box("snap", area->top, area->bottom, 0,
					                   (uint32)height * SCREEN_WIDTH,
					                   Video_C2PStats_CountDirty(area->top, area->bottom), 0);
					Video_C2PStats_Region(area->top, area->bottom, 0, SCREEN_WIDTH);
				}
#endif
				uint16 top = (s_screen_needrepaint || area == NULL) ? 0 : area->top;
				Video_Atari_ConvertRun(frameBase, data, SCREEN_WIDTH,
					0, top, SCREEN_WIDTH, height, 0, top);
				Video_Atari_DirtySweepRecord(s_screen_needrepaint ? DIRTY_SWEEP_REPAINT : DIRTY_SWEEP_LEGACY,
				                            (uint32)height * SCREEN_WIDTH, 1);
			} else {
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
				Video_Atari_C2P_ConvertBlocks(screen, data, g_dirty_blocks,
					area->top, area->bottom, DIRTY_SWEEP_LEGACY);
#else
				data += left;
				uint16 top = area == NULL ? 0 : area->top;
				Video_Atari_ConvertRun(frameBase, data, SCREEN_WIDTH,
					left, top, width, height, left, top);
				Video_Atari_DirtySweepRecord(DIRTY_SWEEP_LEGACY, (uint32)width * height, 1);
#endif
			}
		}

		GFX_Screen_SetClean(SCREEN_0);
#ifdef VIDEO_C2P_STATS
		Video_C2PStats_EndTick();
#endif
		s_screen_needrepaint = false;
	}

#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
	/* Independent of the SCREEN_0 sweep above: the viewport rectangle's
	 * tiles/sprites are drawn straight into SCREEN_1 and only raise their
	 * own g_dirty_blocks_viewport bits (see GUI_Widget_Viewport_Draw() and
	 * GFX_Screen_SetDirtyViewport()), so this can and does fire on ticks
	 * where SCREEN_0 has nothing new (e.g. scrolling into already-explored,
	 * unchanging terrain touches no sidebar/topbar pixel). Only reachable
	 * with Video_Atari_CursorDirect(), i.e. ST/STE -- TT/Falcon still copy
	 * the viewport into SCREEN_0 the old way and never dirty this. */
	if (GFX_Screen_IsDirtyViewport()) {
		struct dirty_area *vpArea = GFX_Screen_GetDirtyAreaViewport();

		if (vpArea->top < vpArea->bottom) {
			uint8 *vpData = (uint8 *)GFX_Screen_Get_ByIndex(SCREEN_1) + vpArea->top * SCREEN_WIDTH;
			uint8 *vpScreen = Video_Atari_PlanarBase() + vpArea->top * (SCREEN_WIDTH >> 1);

			Video_Atari_C2P_ConvertBlocks(vpScreen, vpData, g_dirty_blocks_viewport,
				vpArea->top, vpArea->bottom, DIRTY_SWEEP_VIEWPORT);
		}
		GFX_Screen_SetCleanViewport();
	}
#endif

l_overlays:
	if (s_showFPS) {
		int line, plane;
		uint16 * screenwords;

		/* in 320xYYY resolution, each line is 20 words x bitdepth
		 * so on TT and Falcon 8bpp it is 160 words = 320 bytes,
		 * on the ST/STE in 4bpp it is 80 words = 160 bytes */
		screenwords = (uint16 *)Logbase();
		/* copy the characters in color 15 (00001111 or 1111) */
		if (s_machine_type == MCH_TT || s_machine_type == MCH_FALCON) {
			screenwords += (320-32)/2;
			for (line = 0; line < 5; line++) {
				for (plane = 0; plane < 4; plane++)
				{
					screenwords[plane] = (uint16)(s_fps_chars[line] >> 16);
					screenwords[plane+8] = (uint16)s_fps_chars[line];
				}
				for (; plane < 8; plane++)
				{
					screenwords[plane] = 0;
					screenwords[plane+8] = 0;
				}
				if(s_machine_type == MCH_TT) {	/* Double lines */
					for(plane = 0; plane < 16; plane++) {
						screenwords[(320/2)+plane] = screenwords[plane];
					}
					screenwords += 320;	/* two lines = 320 words */
				} else {
					screenwords += 320/2;
				}
			}
		} else {
			/* ST / STE */
			for (line = 0; line < 5; line++) {
				uint16 high[4], low[4];
				for (plane = 0; plane < 4; plane++)
				{
					high[plane] = (uint16)(s_fps_chars[line] >> 16);
					low[plane] = (uint16)s_fps_chars[line];
				}
				Video_Atari_PlanarMergeGroup(frameBase, (uint16)line, 18, 0xffff, high);
				Video_Atari_PlanarMergeGroup(frameBase, (uint16)line, 19, 0xffff, low);
			}
		}
	}

	if (s_curDirect) {
		if (placementRedraw) Video_Atari_PlacementEnd(frameBase);
		Video_Atari_CursorSync(frameBase);
	}

	/* Count completed updates, including ticks with no dirty game pixels.
	 * The resulting digits are displayed on the next video tick. */
	if (s_showFPS) Video_Atari_UpdateFPS();
	Video_Atari_DirtySweepEndTick();

#ifdef VIDEO_C2P_STATS
	Video_C2PStats_Report();
#endif
}

/**
 * Change the palette with the palette supplied.
 * @param palette The palette to replace the current with.
 * @param from From which colour.
 * @param length The length of the palette (in colours).
 */
void Video_SetPalette(void *palette, int from, int length)
{
	int i;
	uint8 *p = palette;

	if(s_machine_type == MCH_FALCON) {
		static uint8 falconpal[256*4];

		for(i = 0; i < length; i++) {
			falconpal[i*4+0] = 0;
			falconpal[i*4+1] = *p++ << 2; /* R */
			falconpal[i*4+2] = *p++ << 2; /* G */
			falconpal[i*4+3] = *p++ << 2; /* B */
		}
		VsetRGB(from, length, falconpal);
	} else if(s_machine_type == MCH_TT) {
		static uint16 rgb12[256];

		for(i = 0; i < length; i++) {
			rgb12[i] = (p[0] >> 2) << 8 | (p[1] >> 2) << 4 | (p[2] >> 2);
			p += 3;
		}
		EsetPalette(from, length, rgb12);
	} else if (s_machine_type == MCH_ST || s_machine_type == MCH_STE || s_machine_type == MCH_MEGA_STE) {
		uint8 red,green,blue;
		int changedFrom = -1, changedTo = -1;

		/* Quantize every incoming RGB, but refresh derived lookups and
		 * cached artwork only when a pen or mono coverage changes. */
		for (i = from; i < from + length; i++)
		{
			uint8 pen;
			bool changed;

			red = *p++;
			green = *p++;
			blue = *p++;
			pen = Palette_FindClosestColor(red, green, blue);
			changed = pen != s_palette4BitMap[i];
			s_palette4BitMap[i] = pen;
			/* Native UI helpers still use the ST pen map; imagery does not. */
			if (Video_Atari_Mono()) {
				uint8 coverage = Video_Atari_MonoCoverage(red, green, blue);
				changed |= coverage != s_paletteMonoCoverage[i];
				s_paletteMonoCoverage[i] = coverage;
			}
			if (changed) {
				if (changedFrom < 0) changedFrom = i;
				changedTo = i;
			}
		}
		if (changedFrom >= 0)
			Video_Atari_UpdatePaletteLookups(changedFrom, changedTo - changedFrom + 1);
		/* invalidate the cached bitplane form of the mouse cursor */
		if (changedFrom >= 0) s_paletteGeneration++;
		/* Eagerly rebuild the persistent per-icon pre-shift cache too: it
		 * has no per-call key check like the slow path, so without this it
		 * would otherwise go on serving stale pen values until the next
		 * icon switch happens to fall through to the (also stale-generation-
		 * aware) Video_Atari_CursorUseIcon() check. Rare event, cheap to
		 * redo eagerly here. */
		if (changedFrom >= 0) Video_Atari_CursorPreloadIcons();
		/* Repaint only when a large amount of colors are changing, for fading
		 * and so on. On ST/STE the screen only shows 16 quantized pens, so a
		 * wide palette update whose colours all re-quantize to the pens they
		 * already had (changedFrom < 0) leaves every on-screen pixel looking
		 * exactly the same - forcing a full 64000px convert for it is pure
		 * waste. Enclaves own native pixels rather than a chunky shadow. */
		if (length >= 128 && changedFrom >= 0 && !s_presentMode && !Video_Atari_Mono())
			s_screen_needrepaint = true;
	} else {
		Error("don't know how to set palette on this machine.\n");
	}
}

/**
 * Set the current position of the mouse.
 * @param x The new X-position of the mouse.
 * @param y The new Y-position of the mouse.
 */
void Video_Mouse_SetPosition(uint16 x, uint16 y)
{
	Debug("Video_Mouse_SetPosition(%hu, %hu)\n", x, y);
	s_mouse_x = x;
	s_mouse_y = y;
}

void Video_Mouse_SetRegion(uint16 minX, uint16 maxX, uint16 minY, uint16 maxY)
{
	Debug("Video_Mouse_SetRegion(%hu, %hu, %hu, %hu)\n", minX, maxX, minY, maxY);
	s_mouse_x_min = minX;
	s_mouse_x_max = maxX;
	s_mouse_y_min = minY;
	s_mouse_y_max = maxY;
	if(s_mouse_x < s_mouse_x_min) {
		s_mouse_x = s_mouse_x_min;
	} else if(s_mouse_x > s_mouse_x_max) {
		s_mouse_x = s_mouse_x_max;
	}
	if(s_mouse_y < s_mouse_y_min) {
		s_mouse_y = s_mouse_y_min;
	} else if(s_mouse_y > s_mouse_y_max) {
		s_mouse_y = s_mouse_y_max;
	}
}

/*
 * change the screen offset, equivalent to changing the
 * Start Address Register on a VGA card.
 * VGA Hardware has 4 "maps" of 64kB.
 * @param offset The address granularity is 4bytes
 */
void Video_SetOffset(uint16 offset)
{
	if(s_machine_type == MCH_FALCON) {
		/* Change Physbase(), but not Logbase() */
		VsetScreen(-1, Logbase() + (4 * offset), -1, -1);
		Vsync();
	} else if (s_machine_type == MCH_ST || s_machine_type == MCH_STE || s_machine_type == MCH_MEGA_STE) {
		/* Decrease the base to move the picture down without a c2p redraw.
		 * We reuse TOS's screen without padding: the exposed top rows
		 * intentionally read preceding RAM and may contain garbage.
		 * Do not clear that memory, which we do not own. */
		uint32 base = (uint32)Logbase();
		/* offset*4 counts *chunky* bytes, and the chunky screen is
		 * SCREEN_WIDTH bytes per line */
		uint16 lines = (uint16)(((uint32)offset * 4) / SCREEN_WIDTH);
		uint32 shift;

		if (s_machine_type == MCH_ST && lines != 0) {
			/* round up to a multiple of 8 lines, keeping the resulting
			 * address 256 byte aligned */
			lines = (uint16)((lines + 7) & ~7);
		}
		shift = (uint32)lines * ST_PLANAR_LINE_BYTES;
		if (shift > base) {
			Error("Screen shake offset exceeds the screen base address.\n");
			return;
		}

		s_stScreenBase = base - shift;
		Atari_SupervisorExec(Video_ST_SetBase);
	} else {
		s_screenOffset = offset;
		s_screen_needrepaint = true;	/* force repaint */
	}
}

void * Video_GetFrameBuffer(uint16 size)
{
	(void)size;
	return s_framebuffer;
}
