/* ATARI Falcon / TT Video Driver */

#include <string.h>
#include <stdlib.h>

#include <mint/sysbind.h>
#include <mint/osbind.h>
#include <mint/ostruct.h>
#include <mint/falcon.h>
#include <mint/cookie.h>

#include "types.h"
#include "video.h"
#include "video_fps.h"
#include "../gfx.h"
#include "../input/input.h"
#include "../input/mouse.h"
#include "../os/error.h"

/* ATARI IKBD doc : https://www.kernel.org/doc/Documentation/input/atarikbd.txt
 * see  */
extern void install_ikbd_handler(void);
extern void uninstall_ikbd_handler(void);

/* chunky to planar routine : */
extern void c2p1x1_8_falcon(void * planar, void * chunky, uint32 count);
extern void c2p1x1_8_tt(void * planar, void * chunky, uint32 count);
extern void c2p1x1_8_tt_partial(void * planar, void * chunky, uint32 count);
extern void c2p1x1_4_st(void * planar, void * chunky, uint32 count, void * pal);

/* switch FPS display */
extern void Video_SwitchFPSDisplay(uint8 key);

/* Chunky buffer. What a shame that the TT030 and Falcon030 have no
 * chunky 256 colors mode, that would spare us expensive chunky to planar
 * conversion. */
static uint8 * s_framebuffer = NULL;

/* offset to center the 320x200 image in 320x240 display */
static uint32 s_center_image_offset = 0;

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
static uint32 s_statDirtyPixels = 0;	/* pixels really dirty (popcount based) */
static uint32 s_statForcedRepaints = 0;	/* s_screen_needrepaint forced full frames */
static uint32 s_statForcedPixels = 0;	/* pixels converted by forced repaints */
static uint32 s_statTickPixels = 0;	/* pixels converted by the current tick */
static uint32 s_statTickDirty = 0;	/* really dirty pixels of the current tick */
static uint32 s_statTickLines = 0;	/* line branch calls of the current tick */
static uint32 s_statPeakTickPx = 0;	/* worst single tick of this period */
static uint32 s_statSpikes = 0;		/* ticks above the stutter threshold */
#ifdef VIDEO_C2P_STATS_VERBOSE
static uint32 s_statSpikesLogged = 0;
static uint32 s_statLogged = 0;		/* boxes logged during this period */
#endif

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
			Warning("c2p SPIKE tick: %lu px in %lu lines, dirty %lu px, waste %lu px (%lu%%), ~%lu ms\n",
			        (unsigned long)s_statTickPixels,
			        (unsigned long)s_statTickLines,
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
	Warning("  converted %lu px, really dirty %lu px, waste %lu px (%lu%%)\n",
	        (unsigned long)total, (unsigned long)s_statDirtyPixels,
	        (unsigned long)(total - s_statDirtyPixels),
	        (unsigned long)(total != 0 ? ((total - s_statDirtyPixels) * 100) / total : 0));
	Warning("  peak tick %lu px (~%lu ms), %lu spikes >=%u px, avg %lu px/converting tick\n",
	        (unsigned long)s_statPeakTickPx,
	        (unsigned long)(s_statPeakTickPx * 41 / 8000),
	        (unsigned long)s_statSpikes, VIDEO_C2P_STATS_TICK_PX,
	        (unsigned long)(s_statConverts != 0 ? total / s_statConverts : 0));
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
	s_statDirtyPixels = 0;
	s_statForcedRepaints = 0;
	s_statForcedPixels = 0;
	s_statPeakTickPx = 0;
	s_statSpikes = 0;
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
	MAKE_PC_COLOR(20,12,28), MAKE_PC_COLOR(68,36,52), MAKE_PC_COLOR(48,52,109),	MAKE_PC_COLOR(78,74,78),
	MAKE_PC_COLOR(133,76,48), MAKE_PC_COLOR(52,101,36), MAKE_PC_COLOR(208,70,72), MAKE_PC_COLOR(117,113,97),
	MAKE_PC_COLOR(89,125,206), MAKE_PC_COLOR(210,125,44), MAKE_PC_COLOR(133,149,161), MAKE_PC_COLOR(109,170,44),
	MAKE_PC_COLOR(210,170,153), MAKE_PC_COLOR(109,194,202), MAKE_PC_COLOR(218,212,94), MAKE_PC_COLOR(222,238,214)
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
	}
}

static uint32 s_fps_chars[5];

static void Video_Atari_DrawChar(uint8 * screen, uint16 x, uint8 digit)
{
	static const uint8 fontdigits[10] = {0167,044,0135,0155,056,0153,0173,045,0177,0157};
	static const uint8 fonttestsegments[15] = {03,01,05, 02,0,04, 032,010,054, 020,0,040, 0120,0100,0140};
	uint8 segments = fontdigits[digit];
	int i, line;
	uint32 pixels = 0;

	(void)screen;

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

/**
 * Runs every tick to handle video updates.
 */
void Video_Tick(void)
{
	uint8 *data = GFX_Screen_Get_ByIndex(SCREEN_0);
	uint8 *screen = Logbase();
	screen += s_center_image_offset;

	/* send mouse event */
	if(s_mouse_state_changed) {
		s_mouse_state_changed = false;
		Mouse_EventHandler(s_mouse_x, s_mouse_y,
		                   s_mouse_left_btn, s_mouse_right_btn);
	}

	if (s_showFPS) {
		memset(s_fps_chars, 0, sizeof(s_fps_chars));
		Video_ShowFPS_2(screen, 320, Video_Atari_DrawChar);
	}

	if (GFX_Screen_IsDirty(SCREEN_0) || s_screen_needrepaint) {
		struct dirty_area * area;
		int height = SCREEN_HEIGHT;
#ifdef VIDEO_C2P_STATS
		s_statTickPixels = 0;
		s_statTickDirty = 0;
		s_statTickLines = 0;
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
				return;
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
			data += (s_screenOffset << 2);
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
#ifdef VIDEO_C2P_STATS
				if (s_screen_needrepaint) {
					/* Legitimate: a palette change of >=128 entries
					 * (fade/transition) invalidates every pixel's pen,
					 * so the whole screen really is stale. Counted
					 * separately and kept out of the waste figures. */
					s_statForcedRepaints++;
					s_statForcedPixels += (uint32)height * SCREEN_WIDTH;
				} else {
					s_statSnapCalls++;
					s_statSnapPixels += (uint32)height * SCREEN_WIDTH;
					Video_C2PStats_Box("snap", area->top, area->bottom, 0,
					                   (uint32)height * SCREEN_WIDTH,
					                   Video_C2PStats_CountDirty(area->top, area->bottom), 0);
				}
#endif
				c2p1x1_4_st(screen, data, height*SCREEN_WIDTH, s_palette4BitPairMap);
			} else {
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
				uint16 y;
				for (y = area->top; y < area->bottom; y++) {
					if (g_dirty_blocks[y] != 0) {
						uint32 blocks = g_dirty_blocks[y];
						left = Video_FirstDirtyBlock(blocks) << 4;
						width = (Video_LastDirtyBlock(blocks) << 4) - left;
#ifdef VIDEO_C2P_STATS
						s_statLineCalls++;
						s_statTickLines++;
						s_statLinePixels += (uint32)width;
						Video_C2PStats_Box("line", y, y + 1, left, (uint32)width,
						                   (uint32)Video_CountDirtyBlocks(g_dirty_blocks[y]) << 4,
						                   g_dirty_blocks[y]);
#endif
						c2p1x1_4_st(screen + (left >> 1), data + left, width, s_palette4BitPairMap);
					}
					screen += SCREEN_WIDTH >> 1;
					data += SCREEN_WIDTH;
				}
#else
				screen += (left >> 1);
				data += left;
				while(height > 0) {
					c2p1x1_4_st(screen, data, width, s_palette4BitPairMap);
					screen += SCREEN_WIDTH >> 1;
					data += SCREEN_WIDTH;
					height--;
				}
#endif
			}
		}

		GFX_Screen_SetClean(SCREEN_0);
#ifdef VIDEO_C2P_STATS
		Video_C2PStats_EndTick();
#endif
		s_screen_needrepaint = false;
	}

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
			screenwords += (320-32)/4;
			for (line = 0; line < 5; line++) {
				for (plane = 0; plane < 4; plane++)
				{
					screenwords[plane] = (uint16)(s_fps_chars[line] >> 16);
					screenwords[plane+4] = (uint16)s_fps_chars[line];
				}
				screenwords += 320/4;
			}
		}
	}

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
