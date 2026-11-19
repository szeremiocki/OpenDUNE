/** @file src/video/video.h Definitions of a video driver. */

#ifndef VIDEO_VIDEO_H
#define VIDEO_VIDEO_H

typedef enum VideoScaleFilter {
	FILTER_NEAREST_NEIGHBOR = 0,	/**<! Default */
	FILTER_SCALE2X,					/**<! see http://scale2x.sourceforge.net/ */
	FILTER_HQX						/**<! see https://code.google.com/p/hqx/ */
} VideoScaleFilter;

extern bool Video_Init(int screen_magnification, VideoScaleFilter filter);
extern void Video_Uninit(void);
extern void Video_Tick(void);
extern void Video_SetPalette(void *palette, int from, int length);
extern void Video_Mouse_SetPosition(uint16 x, uint16 y);
extern void Video_Mouse_SetRegion(uint16 minX, uint16 maxX, uint16 minY, uint16 maxY);
extern void Video_SetOffset(uint16 offset);
extern void * Video_GetFrameBuffer(uint16 size);

#ifdef TOS
#include "atari_dither.h"

/* Selected once from the existing ST/STE resolution, before asset loading. */
extern bool g_videoAtariMono;
#define Video_Atari_Mono() (g_videoAtariMono)
extern void Video_Atari_ExpandSpriteMasks(uint16 *pixels, uint16 *expanded,
	const uint16 *compact, uint16 width, uint16 height);
/* Private native surfaces use word strides per logical row in either layout.
 * Offset/copy X coordinates and copy width are multiples of 16. Copy sources
 * and destinations must not overlap. These operations never publish or drain. */
extern uint32 Video_Atari_PlanarOffset(uint16 stride, uint16 x, uint16 y);
extern void Video_Atari_CopyPlanar(uint16 *dst, uint16 dstStride, uint16 dstX, uint16 dstY,
	const uint16 *src, uint16 srcStride, uint16 srcX, uint16 srcY, uint16 width, uint16 height);
/* Paint a preclipped rectangle, preserving pixels outside compact logical masks.
 * NULL masks fills the rectangle. Masks start at the group containing x.
 * originX/Y are stable asset coordinates at (x,y), not screen coordinates.
 * Opacity updates and destination initialization remain the caller's policy. */
extern void Video_Atari_PaintPlanar(uint16 *dst, uint16 stride, uint16 x, uint16 y,
	uint16 width, uint16 height, const uint16 *masks, uint16 maskStride,
	uint8 pen, int16 originX, int16 originY);
/* Filled border; dst starts at its first logical row. Colours are logical
 * fill, bottom/right, top/left and corner indices. Requires width>=2,height>=3.
 * The colour bulk kernel requires vertically repeating margins in edge groups. */
extern void Video_Atari_DrawPlanarBorder(uint16 *dst, uint16 stride, uint16 x,
	uint16 width, uint16 height, const uint8 colours[4]);
typedef struct VideoAtariGlyph {
	const uint16 *masks;
	uint16 x;
} VideoAtariGlyph;

typedef struct VideoAtariGlyphValue {
	uint16 offset;
	uint8 colour;
} VideoAtariGlyphValue;

typedef struct VideoAtariGlyphRun {
	const VideoAtariGlyph *glyphs;
	const VideoAtariGlyphValue *values;
	uint16 count, valueCount, firstRow, rows;
} VideoAtariGlyphRun;

/* A shared layout of logical glyph masks, in overwrite order. Each value has
 * one mask per row; colours are original palette slots, zero is transparent.
 * Dither phase starts at each glyph's source origin, not its destination x.
 * The caller owns fit checks and optional compact-mask accumulation storage. */
extern void Video_Atari_DrawPlanarGlyphs(const VideoAtariGlyphRun *run,
	uint16 *dst, uint16 stride, uint16 *masks, uint16 maskStride);
/* Private transparent chunky merge, at most 32x32 logical source pixels.
 * Source byte zero is transparent; nonzero pixels may map to an opaque zero.
 * Geometry is preclipped to the target; source origin is (0,0). */
extern void Video_Atari_BlitChunkyTransparent(uint16 *dst, uint16 stride, uint16 dstGroups,
	const uint8 *src, uint16 srcStride, uint16 width, uint16 height, uint16 x);
/* Group-aligned private row merge. Pointers select the first logical group;
 * native row strides retain the full surfaces. A zero mask stride repeats
 * the first compact mask row. No opacity accumulation or screen publication. */
extern void Video_Atari_MergePlanarRows(uint16 *dst, uint16 dstStride,
	const uint16 *src, uint16 srcStride, const uint16 *masks, uint16 maskStride,
	uint16 groups, uint16 height);
/* Shift a masked 16-pixel source into a 32-pixel private surface. Writes all
 * eight native words per logical row, including transparent zero padding. */
extern void Video_Atari_ShiftPlanarGroup(const uint16 *src, const uint16 *masks,
	uint16 height, uint16 shift, uint16 *dst);

/* Direct-to-planar mouse cursor, see src/video/video_atari.c.
 * On ST/STE the cursor is composited straight into the planar screen after
 * the chunky to planar conversion, so it never dirties SCREEN_0. */
#if defined(__m68k__)
extern bool g_videoAtariCursorDirect;
static inline bool Video_Atari_CursorDirect(void)
{
	return g_videoAtariCursorDirect;
}
#else
extern bool Video_Atari_CursorDirect(void);
#endif
extern bool Video_Atari_CursorPrepare(const void *sprite, uint16 x, uint16 y,
                                      uint16 w, uint16 h, int16 dx, int16 dy);
#define VIDEO_ATARI_CURSOR_MAX_WIDTH 96
#define VIDEO_ATARI_CURSOR_MAX_HEIGHT 64
extern void Video_Atari_CursorBuild(const uint8 *chunky, uint16 stride);
extern void Video_Atari_CursorHide(void);

/* Persistent, pre-shifted (all 16 sub-16px horizontal phases) bitplane cache
 * for every mouse cursor icon (MOUSE.SHP), built once at load time and once
 * more whenever the palette quantization changes -- never on the movement
 * hot path. See the "Cursor icon preload" section of video_atari.c. */
extern void Video_Atari_CursorPreloadIcons(void);
extern bool Video_Atari_CursorUseIcon(uint16 iconIndex, int16 left, int16 top);

typedef enum VideoAtariTileCursorShape {
	TILE_CURSOR_NORMAL,
	TILE_CURSOR_TARGET,
	TILE_CURSOR_SCROLL_UP,
	TILE_CURSOR_SCROLL_RIGHT,
	TILE_CURSOR_SCROLL_DOWN,
	TILE_CURSOR_SCROLL_LEFT
} VideoAtariTileCursorShape;

/* Grid-aligned placement preview, below the planar cursor and above the
 * scene. Coordinates are screen pixels; clipping is to the battlefield. */
extern void Video_Atari_PlacementTint(int16 x, int16 y, uint16 width, uint16 height, bool invalid);
extern void Video_Atari_TileCursorFrame(uint16 col, uint16 row, VideoAtariTileCursorShape shape);
extern void Video_Atari_PlacementCursor(bool hidden);
extern void Video_Atari_PlacementHide(void);

#ifdef VIEWPORT_DEBUG_DAMAGE
/* Reversible diagnostic overlays; Video_Tick keeps polling input only. */
extern void Video_Atari_DebugDamageBegin(const uint16 rows[10], bool accepted);
extern void Video_Atari_DebugDamageEnd(void);
#endif

/* Fast path for GUI_SetPaletteAnimated(): on ST/STE the expensive
 * full-screen fades in this game all have one endpoint that is a *uniform*
 * palette - every entry the same colour. Fades to/from all-black are the
 * common case (cutscene and house-selection fade in/out); the intro's
 * fade-to-white flash and the fade back out of it are the same shape with
 * a different intensity. For any such fade the 16 fixed hardware pens
 * never need to be re-quantized nor the 65536-entry c2p pair-LUT rebuilt
 * while the fade is in progress: a uniform logical palette means every
 * pixel shows the same colour regardless of which pen it maps to, so only
 * the actual RGB output of the 16 Setcolor() registers needs to ramp, in
 * 1-step (ST: 3 bit/channel) increments between that uniform intensity and
 * the pens' real catalog colours.
 * Returns true if it handled the whole fade (data[] is left equal to the
 * final palette[] and the caller does not need to do anything else), false
 * if neither endpoint is uniform and the caller must fall back to the
 * normal per-tick 256-entry software path. */
extern bool Video_Atari_TryPaletteFadeUniform(uint8 *data, const uint8 *palette, int16 ticksOfAnimation);

/* Fast path for ShadeScreen()/UnshadeScreen() (options-menu dim/restore):
 * on ST/STE the "shade" effect (subtract one intensity level, restore
 * later) never needs the 256-entry quantization/pair-LUT machinery either
 * - the 16 hardware pens can be dimmed/restored directly, instantly (no
 * ramp - the original effect is an immediate, one-shot palette swap, not
 * an animation). Outside of an active fade the 16 registers always sit at
 * their fixed catalog values (see Video_Atari_TryPaletteFadeUniform),
 * so this is always safe to call in matched shade(true)/shade(false) pairs. */
extern void Video_Atari_ShadeHwPalette(bool shade);

/* Direct chunky->planar presentation ("present mode"), see the section
 * comment in src/video/video_atari.c.
 *
 * Inside an enclave opened with Video_Atari_PresentEnter(), every
 * rectangle written to chunky SCREEN_0 is converted to the planar screen
 * at the moment it is written, and the dirty blocks it covered are
 * dropped, so Video_Tick()'s c2p pass has only what was written behind
 * present mode's back left to do.
 *
 * This is write-through: the chunky copy still happens. SCREEN_0 is an
 * XOR accumulator for WSA animations and is read back by several
 * renderers, so it must stay valid -- see ATARI_SCREEN0_PLANARIZATION.md.
 * What present mode buys is not skipping the chunky write but removing
 * the one-tick lag and the partially converted frames that go with it:
 * a picture appears atomically instead of being revealed by the next
 * c2p pass.
 *
 * Because c2p bakes pen numbers in, pixels converted under one
 * quantization keep it until something re-converts them. Calling
 * Video_Atari_PresentPalette() with the picture's real palette before
 * drawing avoids that entirely, and is invisible at the time: on ST/STE
 * the quantization and the 16 hardware colour registers are independent,
 * and the registers are still black -- exactly the state the following
 * fade-in ramps up from. Getting it wrong is no longer a correctness
 * problem, only a transient one, since the chunky shadow can always be
 * re-converted.
 *
 * Both submit functions return false when present mode is off or the
 * rectangle cannot be handled; the caller's chunky write happens either
 * way, so the fallback is simply to let Video_Tick() do the conversion.
 * Video_Atari_PresentChunky() handles any x and width, using a masked
 * read-modify-write for the edge groups that c2p1x1_4_st() -- which
 * converts whole 16 pixel groups only -- cannot write directly. */
extern bool Video_Atari_PresentEnter(void);
extern void Video_Atari_PresentLeave(void);
extern bool Video_Atari_PresentActive(void);
extern void Video_Atari_PresentPalette(const uint8 *palette);
extern void Video_Atari_PresentPaletteRange(const uint8 *palette, int from, int length);
extern bool Video_Atari_PresentChunky(const void *src, uint16 srcStride,
                                      int16 x, int16 y, uint16 width, uint16 height);
extern bool Video_Atari_PresentFill(int16 x, int16 y, uint16 width, uint16 height, uint8 colour);
/* Like Video_Atari_PresentChunky(), but a source byte of 0 leaves the
 * corresponding planar pixel untouched instead of drawing it -- i.e. 0 is
 * "transparent", not "colour 0". Used for glyph rendering, where the
 * source is a small private buffer (not SCREEN_0) built fresh per call, so
 * 0 reliably means "this pixel was not drawn". Every covered 16 pixel
 * group takes the masked merge path (there is no fast unmasked path: any
 * group may contain transparent pixels). */
extern bool Video_Atari_PresentChunkyTransparent(const void *src, uint16 srcStride,
                                      int16 x, int16 y, uint16 width, uint16 height);

/* Save/restore the raw planar bytes of a (16px-group-aligned) rectangle
 * verbatim -- see the definitions in video_atari.c for the full contract.
 * Used by GFX_CopyToBuffer()/GFX_CopyFromBuffer() on ST/STE, where the
 * planar screen -- not any chunky buffer -- is the only thing guaranteed
 * to match what is actually visible. */
extern bool Video_Atari_PresentSave(int16 x, int16 y, uint16 width, uint16 height, uint8 *buffer);
extern bool Video_Atari_PresentRestore(int16 x, int16 y, uint16 width, uint16 height, const uint8 *buffer);
/* Restore group-aligned source rows with an explicit byte stride, at least
 * the rounded/clipped row width. Zero retains the packed restore layout.
 * The buffer points to the first published group, not the start of its row. */
extern bool Video_Atari_PresentRestoreStrided(int16 x, int16 y, uint16 width, uint16 height,
                                            const uint8 *buffer, uint16 srcStride);
/* Compatibility asset encoders: current palette, source origin (0,0), steps
 * (+1,+1). Existing callers supply group-aligned widths and compact output.
 * Use PreparePlanar below for explicit source phases and partial widths.
 * These prepare private assets, not destination-screen rectangles. */
extern uint16 Video_Atari_GetPaletteGeneration(void);
extern uint8 Video_Atari_GetPalettePen(uint8 colour);
extern void Video_Atari_EncodePlanar(const uint8 *src, uint16 *pixels, uint16 width, uint16 height);
/* As above, reading source rows with an explicit byte stride. */
extern void Video_Atari_EncodePlanarStrided(const uint8 *src, uint16 srcStride,
                                           uint16 *pixels, uint16 width, uint16 height);
typedef struct VideoAtariPlanarCacheInfo {
	const char *extension;
	uint32 format;
} VideoAtariPlanarCacheInfo;

/* Stable disk identity; hardware brightness does not affect prepared pixels.
 * The mapping hash covers all phases of the original slots in colours[32]. */
extern void Video_Atari_GetPlanarCacheInfo(VideoAtariPlanarCacheInfo *info);
extern uint32 Video_Atari_PlanarMappingHash(const uint8 colours[32]);
/* Native transitions use logical group skip/count pairs, four opaque words
 * per changed group, and a zero/zero terminator. Runs never cross a logical
 * row. NULL output measures bytes. Replay reports changed logical groups. */
extern uint32 Video_Atari_EncodePlanarDelta(uint16 *dst, const uint16 *previous,
	const uint16 *next, uint16 groups, uint16 height);
extern void Video_Atari_ApplyPlanarDelta(uint16 *pixels, const uint16 *delta,
	uint16 groups, uint32 *dirty);
/* Phase-aware private asset preparation for the startup-selected ST backend.
 * NULL lookup selects the active palette's constant-pen baseline. Explicit
 * lookups select an asset policy, not a destination-screen phase.
 * Output has ceil(width/16)*4 words per logical row: four planes in ST-Low,
 * or two consecutive physical one-plane rows in ST-High. Right padding is zero.
 * Opacity remains owned by the caller. Source limits are 320x200, with no
 * source alignment requirement. Does not publish pixels or alter caches. */
extern void Video_Atari_PreparePlanar(const AtariDitherSource *source,
	const AtariDitherLookup *lookup, uint16 *pixels);
extern void Video_Atari_PrepareUnitPlanar(const AtariDitherSource *source, uint16 *pixels);
extern void Video_Atari_PresentPlanarWindow(const uint16 *pixels, uint16 x, uint16 y,
                                           uint16 width, uint16 height);
/* Compact planar rows; X is group aligned, a partial right group is masked. */
extern bool Video_Atari_PresentPlanarRect(const uint16 *pixels, uint16 srcStride,
                                         uint16 x, uint16 y, uint16 width, uint16 height);
extern bool Video_Atari_PresentPlanarSubRect(const uint16 *pixels, uint16 srcStride, uint16 srcX,
                                            uint16 x, uint16 y, uint16 width, uint16 height);

/* Shift a rectangle of the planar screen in place; see the definition in
 * video_atari.c for the full contract (group-aligned geometry only,
 * ST/STE only, independent of present mode). Used by the gameplay
 * viewport scroll to avoid re-running c2p on pixels that only moved.
 * The caller reconstructs exposed tiles; they are not cleared here.
 * With viewport BLiTTER enabled, the copy can remain pending until the
 * next display-list flush or immediate screen access. */
extern bool Video_Atari_ShiftPlanar(int16 x, int16 y, uint16 width, uint16 height, int16 dx, int16 dy);
extern bool g_videoScrollPending;
extern void Video_Atari_FinishScroll(void);
/* Freeze the IBM.PAL mapping at tile load, without changing the UI palette.
 * Decode packed 16x16 tiles directly into private planar cache storage.
 * The 16-entry source palette contains house-adjusted logical indices.
 * Sprite canvases are group-aligned, at most 48 pixels wide, with explicit
 * opacity masks so an opaque logical colour 0 remains opaque. */
extern void Video_Atari_InitTileMapping(const uint8 *palette);
extern void Video_Atari_DecodePlanarTile(const uint8 *src, const uint8 *palette, uint16 *pixels);
extern void Video_Atari_DecodePlanarBuildingTile(const uint8 *src, const uint8 *palette, uint16 *pixels);
/* Compose private native 16x16 tiles, overwriting all 64 pixel words and
 * 16 compact opacity words. No output initialization is required.
 * overlay and overlayMasks must either both be present or both be NULL. */
extern void Video_Atari_ComposePlanarTile(const uint16 *pixels, const uint16 *masks,
	const uint16 *overlay, const uint16 *overlayMasks, uint16 *result, uint16 *resultMasks);
/* copyPixels is NULL or a ground/overlay source proven fully opaque by
 * cached tile mask classifications. */
extern bool Video_Atari_QueueViewportTile(const uint16 *pixels, uint16 col, uint16 row);
extern void Video_Atari_DrawPlanarTile(const uint16 *pixels, const uint16 *masks, uint16 x, uint16 y,
                                      const uint16 *copyPixels);
extern void Video_Atari_ResetViewportProtection(void);
extern void Video_Atari_SetViewportFog(uint16 col, uint16 row, const uint16 *writable);
extern void Video_Atari_BeginViewportProtection(bool cursor, uint16 col, uint16 row, VideoAtariTileCursorShape shape);
extern void Video_Atari_EndViewportProtection(void);
extern void Video_Atari_PresentSprite(const uint8 *src, uint16 stride,
                                     uint16 x, uint16 y, uint16 width, uint16 height,
                                     const uint16 *masks);
/* Merge a cached component into private planar pixels/masks at any X phase.
 * Both row widths are group-aligned; transparent right padding is clipped. */
extern void Video_Atari_ComposePlanarSprite(uint16 *dstPixels, uint16 *dstMasks,
                                          uint16 dstWidth, uint16 dstHeight,
                                          const uint16 *pixels, const uint16 *masks,
                                          uint16 width, uint16 height, uint16 x, uint16 y);
/* Signed placement with clipping on all edges, for conditionally cropped canvases. */
extern void Video_Atari_ComposePlanarSpriteClipped(uint16 *dstPixels, uint16 *dstMasks,
                                                 uint16 dstWidth, uint16 dstHeight,
                                                 const uint16 *pixels, const uint16 *masks,
                                                 uint16 width, uint16 height, int16 x, int16 y);
extern void Video_Atari_BlitPlanarSprite(uint16 *dst, uint16 dstStride, uint16 dstGroups,
                                         const uint16 *pixels, const uint16 *masks,
                                         uint16 width, uint16 height, int16 x);
/* Live planar screen, row stride in words. Begin restores a cursor drawn over the rectangle and
 * returns the group containing x at row y; End drops the c2p dirty state of the rectangle. */
#define VIDEO_ATARI_LIVE_STRIDE 80
extern uint16 *Video_Atari_LiveBegin(uint16 x, uint16 y, uint16 width, uint16 height);
extern void Video_Atari_LiveEnd(uint16 x, uint16 y, uint16 width, uint16 height);
/* Prealigned/flipped frames or layered units, up to 80x64; width and X
 * are multiples of 16. Clipping preserves cursor/placement backgrounds. */
extern void Video_Atari_PresentPlanarSprite(const uint16 *pixels, const uint16 *masks,
                                          uint16 width, uint16 height, int16 x, int16 y);
/* Aligned UI text, using only its own packed masks, not battlefield fog.
 * Referenced pixels/masks must stay unchanged until the next display-list drain. */
extern void Video_Atari_PresentPlanarText(const uint16 *pixels, const uint16 *masks,
                                        uint16 width, uint16 height, uint16 x, uint16 y);
/* Source pointers select the first group; sourceWidth retains the full
 * cached row width when publishing a clipped portion. */
extern void Video_Atari_PresentPlanarSpriteStrided(const uint16 *pixels, const uint16 *masks,
                                                 uint16 width, uint16 height, int16 x, int16 y,
                                                 uint16 sourceWidth);
extern bool g_videoViewportBlitter;
#define Video_Atari_ViewportBlitter() (g_videoViewportBlitter)
extern bool g_videoDisplayListActive;
extern uint16 *g_videoDisplayListNext, *g_videoDisplayListLimit;
/* Native tail reads these frame-stable pointers at offsets 0/4/8 on TOS. */
typedef struct Video_Atari_TileCursorBlit {
	uint8 *dst;
	const uint16 *pattern;
	const uint8 *operations;
} Video_Atari_TileCursorBlit;
extern Video_Atari_TileCursorBlit g_videoTileCursorBlit;
extern bool g_videoTileCursorRestored;
extern void Video_Atari_TileCursorTail(void);
extern void (*g_videoTileCursorTail)(void);
extern void Video_Atari_RestoreTileCursor(void);
extern bool Video_Atari_DisplayListPending(void);
/* A <=48x48 cached sprite covers at most 4x4 cells, including phase edges.
 * Each cell needs at most 390 launch bytes and one 24-byte tile repair. */
enum {
	VIDEO_ATARI_DISPLAY_LIST_BYTES = 16384,
	VIDEO_ATARI_DISPLAY_SPRITE_BYTES = 16 * (390 + 24),
	VIDEO_ATARI_DISPLAY_TILE_ROW_BYTES = 15 * 24,
	VIDEO_ATARI_DISPLAY_TINT_BYTES = 180,
	VIDEO_ATARI_DISPLAY_TEXT_BYTES = 32,
	VIDEO_ATARI_DISPLAY_CURSOR_BYTES = 6
};
extern void Video_Atari_DisplayListBegin(void);
extern void Video_Atari_DisplayListCheck(uint16 bytes);
extern void Video_Atari_DisplayListFlush(void);
extern void Video_Atari_DisplayListEnd(void);
extern void Video_Atari_DisplayListFree(void);
extern void Video_Atari_ExecuteDisplayList(const uint16 *stream);
extern void Video_Atari_QueueTile(const uint16 *pixels, uint16 *dst);
/* Cached pixels and masks must remain unchanged until the next drain. */
extern void Video_Atari_QueueMaskedTile(const uint16 *pixels, const uint16 *masks, uint16 *dst);
extern void Video_Atari_QueueMaskedRect(const uint16 *pixels, const uint16 *masks, uint16 *dst,
                                      uint16 groups, uint16 rows);
extern void Video_Atari_QueueTileCursor(void);
typedef struct Video_Atari_SpriteBlitPlan {
	/* Hardware order for paired longword writes in atari_sprite_blit.s. */
	int16 sourceXinc, sourceYinc;
	uint16 firstMask, middleMask, lastMask;
	int16 destinationXinc, destinationYinc;
	uint16 words;
	uint8 skew;
} Video_Atari_SpriteBlitPlan;
/* Sixteen destination phases of the full, horizontally unclipped image.
 * sourceWidth retains the group-aligned canvas stride; sourceX/width
 * delimit the opaque horizontal bounds within that canvas. */
extern void Video_Atari_BuildSpriteBlitPlans(Video_Atari_SpriteBlitPlan plans[16],
                                           uint16 sourceWidth, uint16 sourceX, uint16 width);
/* Bits 0-3 enable opacity clears; bits 4-7 enable colour ORs.
 * Classify the final image with one compact opacity word per four plane words. */
extern uint8 Video_Atari_BuildSpriteBlitRecipe(const uint16 *pixels, const uint16 *masks,
                                              uint16 groups);
extern bool Video_Atari_UnitOutlineEnabled(void);
extern void Video_Atari_OutlineUnit(uint16 *pixels, const uint16 *masks, uint16 width, uint16 height);
/* At most eight 17-word launches, two 3-word HOP/OP writes, and RTS.
 * Executable words are big-endian, including in host-side cache tests. */
#define VIDEO_ATARI_SPRITE_BLIT_CODE_WORDS (8 * 17 + 2 * 3 + 1)
typedef struct Video_Atari_SpriteBlitCode {
	uint16 words[VIDEO_ATARI_SPRITE_BLIT_CODE_WORDS];
	uint8 passes;
} Video_Atari_SpriteBlitCode;
/* Geometry writes, tile-setup invalidation, then JMP (a4) to the plane recipe. */
#define VIDEO_ATARI_SPRITE_BLIT_GEOMETRY_WORDS 25
typedef struct Video_Atari_SpriteBlitGeometry {
	uint16 words[VIDEO_ATARI_SPRITE_BLIT_GEOMETRY_WORDS];
} Video_Atari_SpriteBlitGeometry;
extern void Video_Atari_BuildSpriteBlitGeometry(Video_Atari_SpriteBlitGeometry geometry[16],
                                              uint16 sourceWidth, uint16 sourceX, uint16 width);
extern void Video_Atari_CompileSpriteBlitCode(Video_Atari_SpriteBlitCode *code, uint8 passes);
/* Visible rectangle of an unshifted composite, up to 80x64. Masks expand
 * opacity into the native bitmap layout; pixel bits outside opacity are zero.
 * sourceX and x are pixel offsets. geometry is NULL for calculated geometry,
 * or matching full-image phase code; vertical clipping is OK. */
extern void Video_Atari_PresentPlanarSpriteUnshifted(const uint16 *pixels, const uint16 *masks,
                                                   uint16 sourceWidth, uint16 sourceX,
                                                   uint16 width, uint16 height, uint16 x, uint16 y,
                                                   const Video_Atari_SpriteBlitGeometry *geometry,
                                                   const Video_Atari_SpriteBlitCode *code);
/* Target-highlight IDs, implemented by the native backend without a palette remap.
 * effect 0 is off, 1..VIDEO_ATARI_HIGHLIGHT_EFFECTS select a native effect. */
#define VIDEO_ATARI_HIGHLIGHT_EFFECTS 9
/* Applies to the following Video_Atari_PresentPlanarSprite*() calls; 0 resets. */
extern void Video_Atari_SetSpriteHighlight(uint16 effect);
/* Recolours `groups` native 16-logical-pixel groups without changing opacity. */
extern void Video_Atari_HighlightPixels(uint16 *dst, const uint16 *pixels, const uint16 *masks,
                                        uint16 groups, uint16 effect);
#endif /* TOS */

#endif /* VIDEO_VIDEO_H */
