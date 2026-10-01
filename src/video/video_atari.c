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
#include "../gfx.h"
#include "../gui/gui.h"
#include "../input/input.h"
#include "../input/mouse.h"
#include "../opendune.h"
#include "../os/endian.h"
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
extern void c2p1x1_4_st(void * planar, const void * chunky, uint32 count, uint32 lines, const void * pal);

/* switch FPS display */
extern void Video_SwitchFPSDisplay(uint8 key);

/* Chunky buffer. What a shame that the TT030 and Falcon030 have no
 * chunky 256 colors mode, that would spare us expensive chunky to planar
 * conversion. */
static uint8 * s_framebuffer = NULL;

/* offset to center the 320x200 image in 320x240 display */
static uint32 s_center_image_offset = 0;
/* ST/STE: composite the mouse cursor directly into the planar screen */
static bool s_curDirect = false;

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

/* 64K word pair-LUT for c2p1x1_4_st: indexed by a chunky pixel-pair
 * (pixelA<<8 | pixelB), returns (remap[pixelA]<<8 | remap[pixelB]).
 * Patched incrementally from s_palette4BitMap whenever the palette
 * changes - see Rebuild_Palette4BitPairMap(). 128KB resident. */
static uint16 s_palette4BitPairMap[65536];

/* Only the rows/columns touched by the changed color range [from, from+length)
 * need patching: entries where hi (pixelA) is in range are a full contiguous
 * 256-word row each; entries where lo (pixelB) is in range are one column
 * across all 256 rows. For small changes (typical: 1-8 colors from palette
 * animation/cycling) this is orders of magnitude cheaper than rebuilding all
 * 65536 entries. Falls back to a full rebuild when length is large enough
 * (e.g. fades) that the row+column patch would touch most of the table anyway. */
static void Rebuild_Palette4BitPairMap(int from, int length)
{
	int hi, lo;
	int to = from + length;

	if (length >= 64) {
		/* large change (fade etc.): full rebuild is simpler and not much
		 * costlier than the partial patch would be at this size */
		for (hi = 0; hi < 256; hi++) {
			uint16 h = (uint16)(s_palette4BitMap[hi] << 8);
			uint16 *row = &s_palette4BitPairMap[hi << 8];

			for (lo = 0; lo < 256; lo++) {
				row[lo] = h | s_palette4BitMap[lo];
			}
		}
		return;
	}

	/* patch every row for each changed hi (pixelA) */
	for (hi = from; hi < to; hi++) {
		uint16 h = (uint16)(s_palette4BitMap[hi] << 8);
		uint16 *row = &s_palette4BitPairMap[hi << 8];

		for (lo = 0; lo < 256; lo++) {
			row[lo] = h | s_palette4BitMap[lo];
		}
	}

	/* patch the changed lo (pixelB) column in every row not already
	 * fully rewritten above */
	for (hi = 0; hi < 256; hi++) {
		uint16 h;
		uint16 *row;

		if (hi >= from && hi < to) continue; /* already handled above */

		h = (uint16)(s_palette4BitMap[hi] << 8);
		row = &s_palette4BitPairMap[hi << 8];

		for (lo = from; lo < to; lo++) {
			row[lo] = h | s_palette4BitMap[lo];
		}
	}
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
 * 48 bytes instead of 768, and with no palette quantization or c2p
 * pair-LUT rebuild anywhere in the loop. */
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
		 * quantization/pair-LUT already matches "data" (the current, still
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

/* Run through Supexec() : switch a Mega STE to 16MHz with the cache on. */
static void MegaSTE_SpeedUp(void)
{
	s_savedCpuSpeed = *MEGASTE_CPUCTL;
	*MEGASTE_CPUCTL = 0x03;	/* 16MHz + cache */
}

/* Run through Supexec() : put back what MegaSTE_SpeedUp() found. */
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

/**
 * Initialize the video driver.
 */
bool Video_Init(int screen_magnification, VideoScaleFilter filter)
{
	VARIABLE_NOT_USED(filter);
	VARIABLE_NOT_USED(screen_magnification);
	int i;

	s_framebuffer = calloc(1, SCREEN_WIDTH * (SCREEN_HEIGHT + 4));
	if (s_framebuffer == NULL) {
		Error("Failed to allocate %d bytes.\n", SCREEN_WIDTH * (SCREEN_HEIGHT + 4));
		return false;
	}

	(void)Cconws("Video_Init()\r\n");
	if(s_machine_type == MCH_UNKNOWN) Detect_Machine();

	if(s_machine_type == MCH_MEGA_STE && s_savedCpuSpeed < 0) {
		Supexec(MegaSTE_SpeedUp);
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
		/* set ST/STE 4bps video mode */
		s_savedMode = Getrez();
		s_savedLogBase = Logbase();
		s_savedPhysBase = Physbase();
		Setscreen(-1, -1, 0);	 /* set ST-Low resolution */
		/* set and backup system palette */
		for (i=0; i<16; i++) {
			s_paletteBackup[i] = Setcolor(i, ((s_palette4BitPC[i*4+0] << 5) & 0x0700) | ((s_palette4BitPC[i*4+1] << 1) & 0x0070) | ((s_palette4BitPC[i*4+2]>>3) & 0x007));
		}
		/* the mouse cursor is composited straight into the planar screen */
		s_curDirect = true;
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
	Supexec(install_ikbd_handler);
	return true;
}

/**
 * Uninitialize the video driver.
 */
void Video_Uninit(void)
{
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
		for (i=0; i<16; i++) {
			int oldColor = Setcolor(i, s_paletteBackup[i]);
			VARIABLE_NOT_USED(oldColor);
		}
		Setscreen(s_savedLogBase, s_savedPhysBase, s_savedMode);
	}
	Supexec(uninstall_ikbd_handler);
	if(s_savedCpuSpeed >= 0) {
		Supexec(MegaSTE_SpeedRestore);
		s_savedCpuSpeed = -1;
	}
	g_consoleActive = true;
	free(s_framebuffer);
	s_framebuffer = NULL;
}

void Video_SwitchFPSDisplay(uint8 key)
{
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

static uint16 s_curData[CURSOR_MAX_H][CURSOR_MAX_GROUPS * 4];
static uint16 s_curMask[CURSOR_MAX_H][CURSOR_MAX_GROUPS];
static uint16 s_curSave[CURSOR_MAX_H][CURSOR_MAX_GROUPS * 4];
/* Requested icon caches can be rebuilt before the old cursor moves. Keep
 * the actual on-screen pixels/mask independent of those cache lifetimes. */
static uint16 s_curDrawnData[CURSOR_MAX_H][CURSOR_MAX_GROUPS * 4];
static uint16 s_curDrawnMask[CURSOR_MAX_H][CURSOR_MAX_GROUPS];

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

bool Video_Atari_CursorDirect(void)
{
	return s_curDirect;
}

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
	 && s_paletteGeneration == s_curKeyPal) return false;

	s_curKeySprite = sprite;
	s_curKeyW = w;
	s_curKeyH = h;
	s_curKeyShift = shift;
	s_curKeyDx = dx;
	s_curKeyDy = dy;
	s_curKeyPal = s_paletteGeneration;
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
				uint8 pen = s_palette4BitMap[colour];

				mask[pos >> 4] |= bit;
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
static bool Video_Atari_CursorBuildPhase(CursorIcon *icon, uint16 phase, const uint8 *chunky, uint16 stride)
{
	uint16 groups = (uint16)((phase + icon->w + 0xf) >> 4);
	uint16 line, g, px;
	uint16 *data, *mask;

	icon->groups[phase] = groups;
	data = (uint16 *)malloc(sizeof(uint16) * (size_t)icon->h * groups * 4);
	mask = (uint16 *)malloc(sizeof(uint16) * (size_t)icon->h * groups);
	icon->data[phase] = data;
	icon->mask[phase] = mask;
	if (data == NULL || mask == NULL) return false;

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
				uint8 pen = s_palette4BitMap[colour];

				m[pos >> 4] |= bit;
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
			if (!Video_Atari_CursorBuildPhase(&s_curIcon[i], phase, box + minY * w + minX, w)) ok = false;
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

/* Movement, actual hiding and screen shifts restore this backup.
 * Ordinary drawing updates it synchronously instead. */
static void Video_Atari_CursorEraseFull(void)
{
	uint16 line, i;
	uint16 *p;

	if (!s_curDrawn) return;

	p = (uint16 *)(s_curDrawnBase + s_curDrawnY * (SCREEN_WIDTH >> 1)
	                             + (s_curDrawnGroup << 3));
	for (line = 0; line < s_curDrawnH; line++) {
		const uint16 *s = s_curSave[line];

		for (i = 0; i < (uint16)(s_curDrawnGroups << 2); i++) p[i] = s[i];
		p += SCREEN_WIDTH >> 2;	/* 80 words per scanline */
	}
	s_curDrawn = false;
}

/** Save the planar background and composite the cursor over it. */
static void Video_Atari_CursorDraw(uint8 *base)
{
	uint16 line, g, i;
	uint16 *p;

	if (s_curDrawn || !s_curVisible) return;
	if (s_curH == 0 || s_curGroups == 0) return;
	if (s_curDrawData == NULL || s_curDrawMask == NULL) return;

	p = (uint16 *)(base + s_curY * (SCREEN_WIDTH >> 1) + (s_curGroup << 3));
	for (line = 0; line < s_curH; line++) {
		const uint16 *d = s_curDrawData + (uint32)line * s_curDrawStride * 4;
		const uint16 *m = s_curDrawMask + (uint32)line * s_curDrawStride;
		uint16 *save = s_curSave[line];

		for (g = 0; g < s_curGroups; g++) {
			uint16 keep = (uint16)~m[g];

			for (i = (uint16)(g << 2); i < (uint16)((g << 2) + 4); i++) {
				uint16 w = p[i];

				save[i] = w;
				s_curDrawnData[line][i] = d[i];
				p[i] = (uint16)((w & keep) | d[i]);
			}
			s_curDrawnMask[line][g] = m[g];
		}
		p += SCREEN_WIDTH >> 2;
	}
	s_curDrawnBase = base;
	s_curDrawnY = s_curY;
	s_curDrawnH = s_curH;
	s_curDrawnGroup = s_curGroup;
	s_curDrawnGroups = s_curGroups;
	s_curDrawn = true;
}

static void Video_Atari_CursorSync(uint8 *base)
{
	uint16 line;
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
	same = s_curDrawn && s_curVisible && s_curDrawnBase == base &&
	       s_curDrawnY == s_curY && s_curDrawnH == s_curH &&
	       s_curDrawnGroup == s_curGroup && s_curDrawnGroups == s_curGroups;

	if (same && !s_curDirty) return;
	if (same) {
		for (line = 0; line < s_curH; line++) {
			if (memcmp(s_curDrawnData[line], s_curDrawData + (uint32)line * s_curDrawStride * 4,
			           s_curGroups * 4 * sizeof(uint16)) != 0 ||
			    memcmp(s_curDrawnMask[line], s_curDrawMask + (uint32)line * s_curDrawStride,
			           s_curGroups * sizeof(uint16)) != 0) {
				same = false;
				break;
			}
		}
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
static bool s_placeInvalid, s_placeVisible, s_placeDirty;
static int16 s_placeDrawnX, s_placeDrawnY;
static uint16 s_placeDrawnWidth, s_placeDrawnHeight;

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

static bool Video_Atari_PlanarOverlaysOverlap(uint8 *base, uint16 x, uint16 y,
                                             uint16 w, uint16 h)
{
	uint16 first = x >> 4, end = (x + w + 15) >> 4;

	/* Backups cover whole groups, including pixels outside an edge mask. */
	return Video_Atari_CursorRectOverlap(base, first, end, y, h) ||
	       Video_Atari_PlacementRectOverlap(base, first << 4, end << 4, y, h);
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

static int Video_Atari_CursorGroup(uint8 *base, uint16 y, uint16 group)
{
	if (!s_curDrawn || base != s_curDrawnBase ||
	    y < s_curDrawnY || y >= s_curDrawnY + s_curDrawnH ||
	    group < s_curDrawnGroup || group >= s_curDrawnGroup + s_curDrawnGroups) return -1;
	return group - s_curDrawnGroup;
}

static const uint16 *Video_Atari_CursorBackground(uint8 *base, uint16 y, uint16 group)
{
	int g = Video_Atari_CursorGroup(base, y, group);
	if (g >= 0) return &s_curSave[y - s_curDrawnY][g * 4];
	return (uint16 *)(base + (uint32)y * 160 + group * 8);
}

static void Video_Atari_CursorWriteGroup(uint8 *base, uint16 y, uint16 group, const uint16 words[4])
{
	uint16 *p = (uint16 *)(base + (uint32)y * 160 + group * 8);
	int g = Video_Atari_CursorGroup(base, y, group);
	uint16 plane;

	for (plane = 0; plane < 4; plane++) {
		uint16 w = words[plane];
		if (g >= 0) {
			uint16 line = y - s_curDrawnY;
			s_curSave[line][g * 4 + plane] = w;
			w = (uint16)((w & (uint16)~s_curDrawnMask[line][g]) |
			             s_curDrawnData[line][g * 4 + plane]);
		}
		p[plane] = w;
	}
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
	uint16 words[4], plane;

	for (plane = 0; plane < 4; plane++) {
		uint16 background = old[plane];
		if (block != NULL) {
			background = (uint16)((background & (uint16)~block->mask) |
			                      (block->saved[plane] & block->mask));
		}
		words[plane] = (uint16)((background & (uint16)~mask) | (pixels[plane] & mask));
		if (block != NULL) {
			block->saved[plane] = words[plane];
			words[plane] = (uint16)((words[plane] & (uint16)~block->mask) |
			                       ((s_placePen & (1u << plane)) ? block->mask : 0));
		}
	}
	Video_Atari_CursorWriteGroup(base, y, group, words);
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
				memcpy(words, base + (uint32)line * 160 + group * 8, sizeof(words));
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
		memcpy(words, base + (uint32)block->y * 160 + block->group * 8, sizeof(words));
		Video_Atari_PlanarMergeGroup(base, block->y, block->group, 0xffff, words);
	}
}

static void Video_Atari_PlacementCross(uint16 width, uint16 height)
{
	uint16 dx = width - 1, dy = height - 1;
	uint16 steps = dx > dy ? dx : dy;
	int16 error = steps / 2;
	uint16 x = 0, y = 0, i;

	/* Same midpoint stepping as GUI_DrawLine(), reflected for the other
	 * diagonal. Generate before clipping so the cross keeps its slope. */
	for (i = 0; i <= steps; i++) {
		uint16 mirror = dx - x;
		s_placeMask[y][x >> 4] |= 0x8000u >> (x & 15);
		s_placeMask[y][mirror >> 4] |= 0x8000u >> (mirror & 15);
		if (dx >= dy) {
			x++;
			error -= dy;
			if (error < 0) { error += dx; y++; }
		} else {
			y++;
			error -= dx;
			if (error < 0) { error += dy; x++; }
		}
	}
}

void Video_Atari_PlacementSet(int16 x, int16 y, uint16 width, uint16 height, bool invalid)
{
	uint16 line, group;

	if (!s_curDirect) return;
	if (width == 0 || width > PLACEMENT_MAX_GROUPS * 16 ||
	    height == 0 || height > PLACEMENT_MAX_H ||
	    (x & 15) != 0 || (width & 15) != 0 || (height & 15) != 0) {
		Warning("Invalid planar placement geometry: %hd,%hd %hux%hu\n", x, y, width, height);
		Video_Atari_PlacementHide();
		return;
	}
	if (width != s_placeWidth || height != s_placeHeight || invalid != s_placeInvalid) {
		memset(s_placeMask, 0, sizeof(s_placeMask));
		for (group = 0; group < width / 16; group++) {
			s_placeMask[0][group] = 0xffff;
			s_placeMask[height - 1][group] = 0xffff;
		}
		for (line = 1; line < height - 1; line++) {
			s_placeMask[line][0] |= 0x8000;
			s_placeMask[line][width / 16 - 1] |= 1;
		}
		if (invalid) Video_Atari_PlacementCross(width, height);
		s_placeWidth = width;
		s_placeHeight = height;
		s_placeInvalid = invalid;
		s_placeDirty = true;
	}
	if (!s_placeVisible || x != s_placeX || y != s_placeY) s_placeDirty = true;
	s_placeX = x;
	s_placeY = y;
	s_placeVisible = true;
}

static void Video_Atari_PlacementEnd(uint8 *base);

void Video_Atari_PlacementHide(void)
{
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

	for (i = 0; i < s_placeBlockCount; i++) {
		const PlacementBlock *block = &s_placeBlocks[i];
		const uint16 *p = Video_Atari_CursorBackground(s_placeDrawnBase, block->y, block->group);
		uint16 words[4];
		for (plane = 0; plane < 4; plane++) {
			words[plane] = (p[plane] & (uint16)~block->mask) | (block->saved[plane] & block->mask);
		}
		Video_Atari_CursorWriteGroup(s_placeDrawnBase, block->y, block->group, words);
	}
	s_placeBlockCount = 0;
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
			for (plane = 0; plane < 4; plane++) {
				block->saved[plane] = p[plane];
				words[plane] = (p[plane] & (uint16)~mask) | ((s_placePen & (1u << plane)) ? mask : 0);
			}
			Video_Atari_CursorWriteGroup(base, (uint16)y, (uint16)(x / 16), words);
		}
	}
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
 * black - exactly the state the following fade-in ramps up from. Under
 * write-through, getting this wrong is only a transient blemish rather
 * than a corruption: s_screen_needrepaint still re-converts everything
 * from the chunky shadow on a wide palette change.
 */

static bool s_presentMode = false;

static uint8 *Video_Atari_PlanarBase(void)
{
	return (uint8 *)Logbase() + s_center_image_offset;
}

/* Flat-colour planar fill. Unlike the c2p path this handles rectangles
 * that do not start/end on a 16 pixel group boundary, by masking the
 * partially covered groups. */
static void Video_Atari_PlanarFill(uint16 x, uint16 y, uint16 w, uint16 h, uint8 pen)
{
	uint8 *base = Video_Atari_PlanarBase();
	bool overlays = Video_Atari_PlanarOverlaysOverlap(base, x, y, w, h);
	uint16 first = (uint16)(x >> 4);
	uint16 last = (uint16)((x + w + 15) >> 4);	/* exclusive */
	uint16 *row = (uint16 *)(base + (uint32)y * ST_PLANAR_LINE_BYTES + first * 8);
	uint16 g, line, plane;

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
}

static void Video_Atari_PresentRun(const uint8 *src, uint16 srcStride,
                                   uint16 x, uint16 y, uint16 w, uint16 h)
{
	union { const uint8 *cp; void *p; } u;	/* c2p1x1_4_st takes a void* */
	uint8 *base = Video_Atari_PlanarBase();
	uint8 *dst = base + (uint32)y * ST_PLANAR_LINE_BYTES + (x >> 1);

	if (srcStride == SCREEN_WIDTH) {
		/* c2p1x1_4_st walks whole scanlines itself, with the chunky and
		 * planar strides hardcoded to 320/160 -- one call for the lot. */
		u.cp = src;
		c2p1x1_4_st(dst, u.p, w, h, s_palette4BitPairMap);
		Video_Atari_PlanarFinishRun(base, x, y, w, h);
	} else {
		/* A source whose rows are not 320 bytes apart (a WSA frame buffer,
		 * for instance) has to be handed over one line at a time. */
		uint16 line;

		for (line = 0; line < h; line++) {
			u.cp = src;
			c2p1x1_4_st(dst, u.p, w, 1, s_palette4BitPairMap);
			Video_Atari_PlanarFinishRun(base, x, (uint16)(y + line), w, 1);
			src += srcStride;
			dst += ST_PLANAR_LINE_BYTES;
		}
	}
}

/* Convert one partially covered 16 pixel group and merge it into what is
 * already on screen. Only source pixels inside [x0,x1) are read, so this
 * stays in bounds even when the source row is exactly as wide as the
 * rectangle (a WSA frame buffer, for instance). */
static void Video_Atari_PresentGroupMasked(const uint8 *srcRow, uint16 gx,
                                           uint16 x0, uint16 x1, uint8 *base, uint16 y,
                                           bool overlays)
{
	uint16 a = (x0 > gx) ? (uint16)(x0 - gx) : 0;
	uint16 b = (x1 < (uint16)(gx + 16)) ? (uint16)(x1 - gx) : 16;
	uint16 mask = (uint16)((0xFFFFu >> a) & (0xFFFFu << (16 - b)));
	uint16 pl[4];
	uint16 i;

	pl[0] = pl[1] = pl[2] = pl[3] = 0;

	for (i = a; i < b; i++) {
		uint8 pen = s_palette4BitMap[srcRow[gx + i - x0]];
		uint16 bit = (uint16)(0x8000u >> i);

		if (pen & 1) pl[0] |= bit;
		if (pen & 2) pl[1] |= bit;
		if (pen & 4) pl[2] |= bit;
		if (pen & 8) pl[3] |= bit;
	}

	if (overlays) {
		Video_Atari_PlanarMergeGroup(base, y, gx >> 4, mask, pl);
	} else {
		uint16 *dst = (uint16 *)(base + (uint32)y * ST_PLANAR_LINE_BYTES + (gx >> 1));
		Video_Atari_PlanarMergePlain(dst, mask, pl);
	}
}

/* Present a rectangle whose left edge and/or width are not multiples of
 * 16. The interior, which is group aligned, still goes through the fast
 * c2p; only the (at most two) partially covered edge groups take the
 * read-modify-write path above. */
static void Video_Atari_PresentRunMasked(const uint8 *src, uint16 srcStride,
                                         uint16 x, uint16 y, uint16 w, uint16 h)
{
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
	bool overlays = Video_Atari_PlanarOverlaysOverlap(base, x, y, w, h);
	uint16 line;

	if (lastFull >= firstFull) {
		const uint8 *fullSrc = src + (uint16)((firstFull << 4) - (int)x);

		if ((((uint32)fullSrc) & 1) || ((srcStride & 1) != 0 && h > 1)) {
			/* The fast c2p path needs a word-aligned source pointer.
			 * When the copy's source and destination x coordinates
			 * differ in parity (e.g. a map sprite placed at an odd
			 * pixel column), this alignment shift lands on an odd
			 * address that would fault _c2p1x1_4_st's word-wide
			 * pixel-pair reads. Fall back to the safe per-pixel merge
			 * for these groups instead (same primitive already used
			 * for the partial edge groups below). */
			const uint8 *mSrc = src;
			int g;

			for (line = 0; line < h; line++) {
				for (g = firstFull; g <= lastFull; g++) {
					Video_Atari_PresentGroupMasked(mSrc, (uint16)(g << 4), x, x1,
					                               base, (uint16)(y + line), overlays);
				}
				mSrc += srcStride;
			}
		} else {
			Video_Atari_PresentRun(fullSrc, srcStride,
			                       (uint16)(firstFull << 4), y,
			                       (uint16)((lastFull - firstFull + 1) << 4), h);
		}
	}

	if (!doLeft && !doRight) return;

	for (line = 0; line < h; line++) {
		if (doLeft) {
			Video_Atari_PresentGroupMasked(src, (uint16)(gLeft << 4), x, x1,
			                               base, (uint16)(y + line), overlays);
		}
		if (doRight) {
			Video_Atari_PresentGroupMasked(src, (uint16)(gRight << 4), x, x1,
			                               base, (uint16)(y + line), overlays);
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
	uint16 left, right, bytesPerLine;
	uint8 *base = Video_Atari_PlanarBase();
	uint8 *dst;

	if (buffer == NULL || width == 0 || height == 0) return false;
	if (x < 0 || y < 0) return false;
	if ((int)y + (int)height > SCREEN_HEIGHT) return false;

	left = (uint16)(x & ~0xf);
	right = (uint16)((x + width + 0xf) & ~0xf);
	if (right > SCREEN_WIDTH) right = SCREEN_WIDTH;
	bytesPerLine = (uint16)(((right - left) >> 4) << 3);

	dst = base + (uint32)y * ST_PLANAR_LINE_BYTES + (uint32)(left >> 4) * 8;

	{
		uint16 h = height;
		uint8 *d = dst;
		const uint8 *s = buffer;

		while (h-- != 0) {
			memcpy(d, s, bytesPerLine);
			d += ST_PLANAR_LINE_BYTES;
			s += bytesPerLine;
		}
	}
	Video_Atari_PlanarFinishRun(base, left, (uint16)y, (uint16)(right - left), height);

	GFX_Screen_ClearDirtyRect(left, (uint16)y, right, (uint16)(y + height));
	return true;
}

uint16 Video_Atari_GetPaletteGeneration(void)
{
	return s_paletteGeneration;
}

void Video_Atari_EncodePlanar(const uint8 *src, uint16 *pixels, uint16 width, uint16 height)
{
	assert(Video_Atari_CursorDirect() && src != NULL && pixels != NULL);
	assert(((uint32)src & 1) == 0 && height != 0 && height <= SCREEN_HEIGHT);
	assert(width != 0 && width <= SCREEN_WIDTH && (width & 15) == 0);
	if (width == SCREEN_WIDTH) {
		c2p1x1_4_st(pixels, src, width, height, s_palette4BitPairMap);
	} else {
		/* The assembly line loop has fixed 320-byte/160-byte strides. */
		while (height-- != 0) {
			c2p1x1_4_st(pixels, src, width, 1, s_palette4BitPairMap);
			src += width;
			pixels += width / 4;
		}
	}
}

void Video_Atari_PresentPlanarWindow(const uint16 *pixels, uint16 x, uint16 y,
                                    uint16 width, uint16 height)
{
	uint8 *base = Video_Atari_PlanarBase();
	uint16 right = x + width;
	uint16 first = x >> 4, last = (right - 1) >> 4;
	uint16 firstFull = (x + 15) >> 4, endFull = right >> 4;
	bool overlays;
	uint16 line;

	assert(Video_Atari_CursorDirect() && pixels != NULL && width != 0 && height != 0);
	assert((uint32)x + width <= SCREEN_WIDTH && (uint32)y + height <= SCREEN_HEIGHT);
	overlays = Video_Atari_PlanarOverlaysOverlap(base, x, y, width, height);

	if (endFull > firstFull) {
		for (line = 0; line < height; line++) {
			memcpy(base + (uint32)(y + line) * ST_PLANAR_LINE_BYTES + firstFull * 8,
			       pixels + (uint32)line * (SCREEN_WIDTH / 4) + firstFull * 4,
			       (endFull - firstFull) * 8);
		}
		Video_Atari_PlanarFinishRun(base, firstFull << 4, y, (endFull - firstFull) << 4, height);
	}

	for (line = 0; line < height; line++, pixels += SCREEN_WIDTH / 4) {
		if ((x & 15) != 0) {
			uint16 mask = 0xffffu >> (x & 15);
			uint16 *dst = (uint16 *)(base + (uint32)(y + line) * ST_PLANAR_LINE_BYTES + first * 8);
			if (first == last && (right & 15) != 0) mask &= 0xffffu << (16 - (right & 15));
			if (overlays) Video_Atari_PlanarMergeGroup(base, y + line, first, mask, pixels + first * 4);
			else Video_Atari_PlanarMergePlain(dst, mask, pixels + first * 4);
		}
		if ((right & 15) != 0 && ((x & 15) == 0 || first != last)) {
			uint16 mask = 0xffffu << (16 - (right & 15));
			uint16 *dst = (uint16 *)(base + (uint32)(y + line) * ST_PLANAR_LINE_BYTES + last * 8);
			if (overlays) Video_Atari_PlanarMergeGroup(base, y + line, last, mask, pixels + last * 4);
			else Video_Atari_PlanarMergePlain(dst, mask, pixels + last * 4);
		}
	}
	GFX_Screen_ClearDirtyRect(first << 4, y, (last + 1) << 4, y + height);
}

bool Video_Atari_PresentChunkyTransparent(const void *src, uint16 srcStride,
                                          int16 x, int16 y, uint16 width, uint16 height)
{
	uint16 left, right;

	if (src == NULL || width == 0 || height == 0) return false;
	if (x < 0 || y < 0) return false;
	if ((int)x + (int)width > SCREEN_WIDTH) return false;
	if ((int)y + (int)height > SCREEN_HEIGHT) return false;

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
	GFX_Screen_ClearDirtyRect(left, (uint16)y, right, (uint16)(y + height));

	return true;
}

bool Video_Atari_PresentActive(void)
{
	return s_presentMode;
}

uint16 *Video_Atari_CreateTileLookup(const uint8 *palette)
{
	uint8 pens[256];
	uint16 *lookup;
	unsigned hi, lo;

	if (!Video_Atari_CursorDirect()) return NULL;
	lookup = malloc(65536UL * sizeof(*lookup));
	if (lookup == NULL) {
		Warning("Planar tile decoding disabled: out of memory for c2p lookup\n");
		return NULL;
	}
	for (hi = 0; hi < 256; hi++) {
		pens[hi] = Palette_FindClosestColor(palette[hi * 3] & 0x3f,
		                                  palette[hi * 3 + 1] & 0x3f,
		                                  palette[hi * 3 + 2] & 0x3f);
	}
	for (hi = 0; hi < 256; hi++) {
		for (lo = 0; lo < 256; lo++) lookup[(hi << 8) | lo] = (pens[hi] << 8) | pens[lo];
	}
	return lookup;
}

bool Video_Atari_DecodePlanarTile(const uint8 *src, uint16 *pixels, const uint16 *lookup)
{
	uint8 *base = Video_Atari_PlanarBase();

	/* Decode with the gameplay palette even if a loading/mentat palette
	 * is currently displayed. Neither the active mapping nor registers change. */
	c2p1x1_4_st(base, src, 16, 16, lookup);
	Video_Atari_PlanarFinishRun(base, 0, 0, 16, 16);
	return Video_Atari_PresentSave(0, 0, 16, 16, (uint8 *)pixels);
}

void Video_Atari_DrawPlanarTile(const uint16 *pixels, const uint16 *masks, uint16 x, uint16 y)
{
	uint8 *base = Video_Atari_PlanarBase();
	bool overlays = Video_Atari_PlanarOverlaysOverlap(base, x, y, 16, 16);
	uint16 line;

	assert((x & 15) == 0 && x + 16 <= SCREEN_WIDTH && y + 16 <= SCREEN_HEIGHT);
	for (line = 0; line < 16; line++, pixels += 4) {
		uint16 mask = masks[line];
		uint16 *dst = (uint16 *)(base + (uint32)(y + line) * 160 + (x >> 1));
		if (mask == 0) continue;
		if (overlays) Video_Atari_PlanarMergeGroup(base, y + line, x >> 4, mask, pixels);
		else if (mask == 0xffff) Video_Atari_PlanarCopyGroup(dst, pixels);
		else Video_Atari_PlanarMergePlain(dst, mask, pixels);
	}
	GFX_Screen_ClearDirtyRect(x, y, x + 16, y + 16);
}

void Video_Atari_DrawPlanarTileFogged(const uint16 *pixels, const uint16 *masks,
                                    const uint16 *fogPixels, const uint16 *fogMasks,
                                    uint16 x, uint16 y)
{
	uint8 *base = Video_Atari_PlanarBase();
	bool overlays = Video_Atari_PlanarOverlaysOverlap(base, x, y, 16, 16);
	uint16 line;

	assert((x & 15) == 0 && x + 16 <= SCREEN_WIDTH && y + 16 <= SCREEN_HEIGHT);
	for (line = 0; line < 16; line++, pixels += 4, fogPixels += 4) {
		uint16 fogMask = fogMasks[line];
		uint16 mask = masks[line] | fogMask;
		uint16 combined[4];
		const uint16 *src = pixels;
		uint16 *dst = (uint16 *)(base + (uint32)(y + line) * 160 + (x >> 1));
		if (mask == 0) continue;
		if (fogMask == 0xffff) src = fogPixels;
		else if (fogMask != 0) {
			uint16 plane;
			for (plane = 0; plane < 4; plane++) {
				combined[plane] = (pixels[plane] & (uint16)~fogMask) | (fogPixels[plane] & fogMask);
			}
			src = combined;
		}
		if (overlays) Video_Atari_PlanarMergeGroup(base, y + line, x >> 4, mask, src);
		else if (mask == 0xffff) Video_Atari_PlanarCopyGroup(dst, src);
		else Video_Atari_PlanarMergePlain(dst, mask, src);
	}
	GFX_Screen_ClearDirtyRect(x, y, x + 16, y + 16);
}

void Video_Atari_PresentSprite(const uint8 *src, uint16 stride,
                              uint16 x, uint16 y, uint16 width, uint16 height,
                              const uint16 *masks)
{
	uint8 *base = Video_Atari_PlanarBase();
	uint16 pixels[12];
	uint16 groups = width >> 4;
	bool overlays = Video_Atari_PlanarOverlaysOverlap(base, x, y, width, height);
	uint16 line, group;

	assert((x & 15) == 0 && (width & 15) == 0 && width <= 48);
	assert(x + width <= 240 && y >= 40 && y + height <= SCREEN_HEIGHT);
	for (line = 0; line < height; line++, src += stride) {
		c2p1x1_4_st(pixels, src, width, 1, s_palette4BitPairMap);
		for (group = 0; group < groups; group++) {
			uint16 mask = *masks++;
			uint16 *dst = (uint16 *)(base + (uint32)(y + line) * 160 + (x >> 1) + group * 8);
			const uint16 *p = pixels + group * 4;
			if (mask == 0) continue;
			if (overlays) Video_Atari_PlanarMergeGroup(base, y + line, (x >> 4) + group, mask, p);
			else if (mask == 0xffff) Video_Atari_PlanarCopyGroup(dst, p);
			else Video_Atari_PlanarMergePlain(dst, mask, p);
		}
	}
	GFX_Screen_ClearDirtyRect(x, y, x + width, y + height);
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

	/* Presentation is write-through: the chunky SCREEN_0 shadow was kept
	 * up to date throughout the enclave, so it still describes the visible
	 * picture exactly. Nothing needs to be reset -- the normal c2p path
	 * can simply take over, and any leftover dirty state will re-convert
	 * from a buffer that agrees with the screen. */
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

	if (((x | (int16)width) & 0xf) != 0 || (((uint32)src) & 1) != 0 ||
	    ((srcStride & 1) != 0 && height > 1)) {
		/* A private, tightly packed source (not SCREEN_WIDTH strided)
		 * cannot be over-read outside [x, x+width): the masked
		 * read-modify-write path is the only safe option. */
		uint16 left = (uint16)(x & ~0xf);
		uint16 right = (uint16)((x + width + 0xf) & ~0xf);

		if (right > SCREEN_WIDTH) right = SCREEN_WIDTH;

		Video_Atari_PresentRunMasked((const uint8 *)src, srcStride,
		                             (uint16)x, (uint16)y, width, height);
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
 * (dx, dy) pixels, without touching the chunky shadow or running c2p, then
 * blank whatever the shift exposed (the source/destination bounding
 * rectangle outside the destination goes to black, it does not keep
 * showing the pre-shift picture until some later, unrelated redraw
 * happens to reach it).
 *
 * This is for the gameplay viewport scroll: it is always a whole number
 * of 16 pixel tiles in each direction, so x, width and dx are always a
 * multiple of 16 (one c2p group = one interleaved-plane word = exactly
 * one tile). That means the shift is a plain memmove of 8-byte group
 * chunks per scanline -- no bit-level shifting across word boundaries
 * is ever needed, unlike a general pixel-granular planar scroll would.
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
	/* Neither overlay may be copied as scene content by the memmove. */
	Video_Atari_CursorEraseFull();
	placementVisible = s_placeVisible;
	s_placeVisible = false;
	Video_Atari_PlacementEnd(base);
	bytes = width >> 1;	/* 8 bytes/group * (width>>4) groups == width>>1 */
	rows = height;

	src = base + (uint32)srcY * ST_PLANAR_LINE_BYTES + ((uint16)srcX >> 1);
	dst = base + (uint32)dstY * ST_PLANAR_LINE_BYTES + ((uint16)dstX >> 1);

	if (dstY > srcY) {
		/* Destination rows are below source rows: copy bottom row first
		 * so a lower destination row never clobbers a source row a
		 * higher iteration still needs to read. memmove() per row
		 * already handles horizontal overlap either way. */
		src += (uint32)(rows - 1) * ST_PLANAR_LINE_BYTES;
		dst += (uint32)(rows - 1) * ST_PLANAR_LINE_BYTES;
		while (rows-- != 0) {
			memmove(dst, src, bytes);
			src -= ST_PLANAR_LINE_BYTES;
			dst -= ST_PLANAR_LINE_BYTES;
		}
	} else {
		while (rows-- != 0) {
			memmove(dst, src, bytes);
			src += ST_PLANAR_LINE_BYTES;
			dst += ST_PLANAR_LINE_BYTES;
		}
	}

	/* The source/destination bounding rectangle is the scrolled viewport.
	 * Clear it minus the destination, including diagonal corners outside
	 * the source rectangle. The two exposed strips do not overlap. */
	if (dx != 0) {
		uint16 freeW = (uint16)((dx > 0) ? dx : -dx);
		int16 freeX = (int16)((dx > 0) ? x : (x + width + dx));

		Video_Atari_PlanarFill((uint16)freeX, (uint16)min(srcY, dstY),
		                      freeW, (uint16)(height + abs(dy)), 0);
	}
	if (dy != 0) {
		uint16 freeH = (uint16)((dy > 0) ? dy : -dy);
		int16 freeY = (int16)((dy > 0) ? y : (y + height + dy));

		Video_Atari_PlanarFill((uint16)dstX, (uint16)freeY, width, freeH, 0);
	}
	s_placeVisible = placementVisible;
	Video_Atari_PlacementEnd(base);
	Video_Atari_CursorSync(base);
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
static void Video_Atari_C2P_ConvertBlocks(uint8 *screen, uint8 *data, const uint32 *blocks, uint16 top, uint16 bottom)
{
	uint8 *base = screen - (uint32)top * ST_PLANAR_LINE_BYTES;
	uint32 sweepPixels = 0, sweepCalls = 0;
	uint16 y;
	uint16 runCount = 0;
	uint16 runLeft[10];	/* first pixel of the run */
	uint16 runWidth[10];	/* pixels in the run */

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

				c2p1x1_4_st(screen + (left >> 1), data + left, width, bandLines, s_palette4BitPairMap);
				Video_Atari_PlanarFinishRun(base, left, bandTop, width, bandLines);
			}
			sweepPixels += (uint32)bandWidth * bandLines;
			sweepCalls += runCount;
			Video_Atari_DirtySweepBand(mask, bandTop, y, bandWidth);
		}
		screen += (SCREEN_WIDTH >> 1) * bandLines;
		data += SCREEN_WIDTH * bandLines;
	}
	Video_Atari_DirtySweepRecord(DIRTY_SWEEP_VIEWPORT, sweepPixels, sweepCalls);
}
#endif

/**
 * Runs every tick to handle video updates.
 */
void Video_Tick(void)
{
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
	uint8 *screen = Logbase();
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

	if (s_presentMode) {
		/* Presentation already converted every rectangle it was handed and
		 * dropped the matching dirty blocks, so the pass below only has
		 * whatever was written to chunky SCREEN_0 behind its back left to
		 * do. Nothing is skipped: the shadow is maintained, so direct
		 * renderers that were never hooked still reach the screen. */
		Video_Atari_PlacementHide();
		Video_Atari_CursorHide();
	}

	if (s_curDirect) {
		if (g_selectionType != SELECTIONTYPE_PLACE) Video_Atari_PlacementHide();
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
				c2p1x1_4_st(screen, data, height*SCREEN_WIDTH, 1, s_palette4BitPairMap);
				Video_Atari_DirtySweepRecord(s_screen_needrepaint ? DIRTY_SWEEP_REPAINT : DIRTY_SWEEP_LEGACY,
				                            (uint32)height * SCREEN_WIDTH, 1);
				Video_Atari_PlanarFinishRun(frameBase, 0,
					(s_screen_needrepaint || area == NULL) ? 0 : area->top,
					SCREEN_WIDTH, (uint16)height);
			} else {
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
				uint16 y;
				uint32 sweepPixels = 0, sweepCalls = 0;
				/* 20 blocks per line allow 10 runs at most. */
				uint16 runCount = 0;
				uint16 runLeft[10];	/* first pixel of the run */
				uint16 runWidth[10];	/* pixels in the run */
#ifdef VIDEO_C2P_STATS
				/* DEBUG AID -- the accounting below deliberately keeps its
				 * running totals in locals and folds them into the global
				 * counters only once, after the loop. Profiling the first
				 * version of this instrumentation (opendune_dirty.txt) found
				 * it burning 360 cycles per converted run, 40% of
				 * Video_Tick(), as much as a c2p1x1_4_st call costs in fixed
				 * overhead: nine "ADD.L Dn,$absolute" counters are ~28
				 * cycles each on a 68000, and the region split added a
				 * 17-instruction compare chain. That is enough to distort
				 * the very measurements it exists to produce.
				 * Everything a mask contributes (total pixels, and its split
				 * either side of x=256) is the same for every line sharing
				 * that mask, so those sums are computed once while decoding
				 * and then added per line. The run loop itself carries no
				 * accounting at all. */
				uint32 cachedSpan = 0;
				uint32 cachedPixels = 0;	/* pixels converted for this mask */
				uint32 cachedBattfield = 0;	/* ...of which left of x=256 */
				uint32 cachedSidebar = 0;	/* ...of which right of x=256 */
				uint32 tickCalls = 0;
				uint32 tickRows = 0;
				uint32 tickPixels = 0;
				uint32 tickSpan = 0;
				uint32 tickTopBar = 0;
				uint32 tickBattfield = 0;
				uint32 tickSidebar = 0;
#endif

				for (y = area->top; y < area->bottom; ) {
					/* ENHANCEMENT -- convert each contiguous *run* of dirty
					 * blocks separately, instead of one call spanning from
					 * the first to the last dirty block of the line. That
					 * span includes every clean block sandwiched between two
					 * dirty ones, and measurements (VIDEO_C2P_STATS boxes in
					 * error.log) showed lines wasting 60-80% of their
					 * converted pixels that way, e.g. mask=04484 converting
					 * 208 px for 64 truly dirty ones.
					 * A c2p1x1_4_st call costs roughly 492 cycles of fixed
					 * overhead (316 in the callee, mostly its MOVEM register
					 * save/restore, plus ~176 pushing arguments here)
					 * against ~630 cycles per converted 16-px block, so
					 * skipping even a single clean block already pays for
					 * the extra call.
					 *
					 * ENHANCEMENT -- band batching. GFX_Screen_SetDirty_()
					 * ORs one and the same mask into *every* scanline of a
					 * box, so vertically adjacent lines carry identical
					 * masks: profiling measured ~10 consecutive lines per
					 * distinct mask. Gather that band first, then decode its
					 * mask once and hand each run to the assembly with the
					 * band's line count, so it converts the same horizontal
					 * run on every line of the band from a single call.
					 * That amortizes both the ~492 cycle call overhead and
					 * the mask decode over the whole band. Measured runs per
					 * line is only 1.08, so batching *runs* into one call
					 * would have saved almost nothing -- the lines are where
					 * the repetition is. */
					uint32 blocks = g_dirty_blocks[y];
					uint16 bandTop = y;
					uint16 bandLines;

					do {
						y++;
					} while (y < area->bottom && g_dirty_blocks[y] == blocks);
					bandLines = y - bandTop;

					if (blocks != 0) {
						uint32 rest = blocks;
						uint16 run;
						uint16 bandWidth = 0;

						runCount = 0;
#ifdef VIDEO_C2P_STATS
						cachedSpan = (uint32)
							((Video_LastDirtyBlock(blocks) - Video_FirstDirtyBlock(blocks)) << 4);
						cachedPixels = 0;
						cachedBattfield = 0;
						cachedSidebar = 0;
#endif
						while (rest != 0) {
							uint16 runStart = Video_FirstDirtyBlock(rest);
							uint16 runEnd = runStart + Video_FirstCleanBlock(rest >> runStart);

							runLeft[runCount] = runStart << 4;
							runWidth[runCount] = (runEnd - runStart) << 4;
							bandWidth += runWidth[runCount];
#ifdef VIDEO_C2P_STATS
							{
								uint16 runRight = runEnd << 4;
								uint16 battRight = (runRight < VIDEO_C2P_SIDEBAR_LEFT) ? runRight : VIDEO_C2P_SIDEBAR_LEFT;
								uint16 sideLeft = (runLeft[runCount] > VIDEO_C2P_SIDEBAR_LEFT) ? runLeft[runCount] : VIDEO_C2P_SIDEBAR_LEFT;

								cachedPixels += runWidth[runCount];
								if (battRight > runLeft[runCount]) cachedBattfield += (uint32)(battRight - runLeft[runCount]);
								if (runRight > sideLeft) cachedSidebar += (uint32)(runRight - sideLeft);
							}
#endif
							runCount++;

							rest &= ~(((uint32)1 << runEnd) - 1);
						}
#ifdef VIDEO_C2P_STATS
						/* everything a mask contributes is the same for
						 * every line of the band, so it is summed once here
						 * and scaled by the band height. The band may
						 * straddle the top bar boundary, so split it. */
						{
							uint32 topLines = 0;

							if (bandTop < VIDEO_C2P_TOPBAR_HEIGHT) {
								topLines = (uint32)((y < VIDEO_C2P_TOPBAR_HEIGHT ? y : VIDEO_C2P_TOPBAR_HEIGHT) - bandTop);
							}
							tickCalls += (uint32)runCount;
							tickRows += bandLines;
							tickSpan += cachedSpan * bandLines;
							tickPixels += cachedPixels * bandLines;
							tickTopBar += cachedPixels * topLines;
							tickBattfield += cachedBattfield * (bandLines - topLines);
							tickSidebar += cachedSidebar * (bandLines - topLines);
						}
#endif
						for (run = 0; run < runCount; run++) {
							left = runLeft[run];
							width = runWidth[run];
							c2p1x1_4_st(screen + (left >> 1), data + left, width, bandLines, s_palette4BitPairMap);
							Video_Atari_PlanarFinishRun(frameBase, (uint16)left, bandTop,
							                           (uint16)width, bandLines);
						}
						sweepPixels += (uint32)bandWidth * bandLines;
						sweepCalls += runCount;
					}
					screen += (SCREEN_WIDTH >> 1) * bandLines;
					data += SCREEN_WIDTH * bandLines;
				}
				Video_Atari_DirtySweepRecord(DIRTY_SWEEP_LEGACY, sweepPixels, sweepCalls);
#ifdef VIDEO_C2P_STATS
				s_statLineCalls += tickCalls;
				s_statTickCalls += tickCalls;
				s_statTickRows += tickRows;
				s_statLinePixels += tickPixels;
				s_statDirtyPixels += tickPixels;
				s_statTickPixels += tickPixels;
				s_statTickDirty += tickPixels;
				s_statSpanPixels += tickSpan;
				s_statTopBarPixels += tickTopBar;
				s_statBattlefieldPixels += tickBattfield;
				s_statSidebarPixels += tickSidebar;
#endif
#else
				screen += (left >> 1);
				data += left;
				c2p1x1_4_st(screen, data, width, height, s_palette4BitPairMap);
				Video_Atari_DirtySweepRecord(DIRTY_SWEEP_LEGACY, (uint32)width * height, 1);
				Video_Atari_PlanarFinishRun(frameBase, (uint16)left,
				                           area == NULL ? 0 : area->top, (uint16)width, (uint16)height);
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

			Video_Atari_C2P_ConvertBlocks(vpScreen, vpData, g_dirty_blocks_viewport, vpArea->top, vpArea->bottom);
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

		/* Quantization (Palette_FindClosestColor against the fixed 16-pen
		 * table) must always run for every changed index - a color shift
		 * can legitimately move an index to a different pen at any time.
		 * But Rebuild_Palette4BitPairMap() is expensive (O(256) word
		 * writes per changed index - see ATARI_PROFILE_FINDINGS.md /
		 * ATARI_PALETTE_ANIMATION_OPTIMIZATION.md) and is only actually
		 * needed for indices whose *pen assignment* changed as a result.
		 * Small, incremental animations (GUI_PaletteAnimate's repair/
		 * selection/windtrap color cycling) very often re-quantize to the
		 * *same* pen they already had (the RGB moved, but not far enough
		 * to cross into a different pen's territory) - in that case the
		 * chunky-pixel-to-pen mapping truly didn't change anywhere, and
		 * patching the pair-LUT would be a no-op. Track the actual
		 * sub-range of indices whose pen assignment changed and only
		 * patch that (possibly empty) range. */
		for (i = from; i < from + length; i++)
		{
			uint8 pen;

			red = *p++;
			green = *p++;
			blue = *p++;
			pen = Palette_FindClosestColor(red, green, blue);
			if (pen != s_palette4BitMap[i]) {
				s_palette4BitMap[i] = pen;
				if (changedFrom < 0) changedFrom = i;
				changedTo = i;
			}
		}
		if (changedFrom >= 0)
			Rebuild_Palette4BitPairMap(changedFrom, changedTo - changedFrom + 1);
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
		 * waste. Only force the repaint when a pen assignment really changed. */
		if (length >= 128 && changedFrom >= 0)
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
		Supexec(Video_ST_SetBase);
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
