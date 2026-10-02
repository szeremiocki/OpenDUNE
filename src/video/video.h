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
/* Direct-to-planar mouse cursor, see src/video/video_atari.c.
 * On ST/STE the cursor is composited straight into the planar screen after
 * the chunky to planar conversion, so it never dirties SCREEN_0. */
extern bool Video_Atari_CursorDirect(void);
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

/* Grid-aligned placement preview, below the planar cursor and above the
 * scene. Coordinates are screen pixels; clipping is to the battlefield. */
extern void Video_Atari_PlacementSet(int16 x, int16 y, uint16 width, uint16 height, bool invalid);
extern void Video_Atari_PlacementHide(void);

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
/* Encode tightly packed, word-aligned chunky rows with the current mapping.
 * Width must be a multiple of 16. The full-width window API below retains
 * screen x coordinates, with masked edges and cursor-aware presentation. */
extern uint16 Video_Atari_GetPaletteGeneration(void);
extern void Video_Atari_EncodePlanar(const uint8 *src, uint16 *pixels, uint16 width, uint16 height);
extern void Video_Atari_PresentPlanarWindow(const uint16 *pixels, uint16 x, uint16 y,
                                           uint16 width, uint16 height);

/* Shift a rectangle of the planar screen in place; see the definition in
 * video_atari.c for the full contract (group-aligned geometry only,
 * ST/STE only, independent of present mode). Used by the gameplay
 * viewport scroll to avoid re-running c2p on pixels that only moved.
 * The source/destination bounding rectangle is the viewport being moved.
 * Its area outside the destination is cleared to black, including the
 * extra exposed corners of diagonal shifts. */
extern bool Video_Atari_ShiftPlanar(int16 x, int16 y, uint16 width, uint16 height, int16 dx, int16 dy);
/* Fixed gameplay tile decoding uses a temporary lookup, without changing
 * a currently displayed UI palette. Tiles are 16x16; source stride is 320.
 * Sprite canvases are group-aligned, at most 48 pixels wide, with explicit
 * opacity masks so an opaque logical colour 0 remains opaque. */
extern uint16 *Video_Atari_CreateTileLookup(const uint8 *palette);
extern bool Video_Atari_DecodePlanarTile(const uint8 *src, uint16 *pixels, const uint16 *lookup);
extern void Video_Atari_DrawPlanarTile(const uint16 *pixels, const uint16 *masks, uint16 x, uint16 y);
/* Fog-covered ground never reaches the screen: merge both cached images
 * before the single destination write, preserving overlay backgrounds. */
extern void Video_Atari_DrawPlanarTileFogged(const uint16 *pixels, const uint16 *masks,
                                          const uint16 *fogPixels, const uint16 *fogMasks,
                                          uint16 x, uint16 y);
extern void Video_Atari_PresentSprite(const uint8 *src, uint16 stride,
                                     uint16 x, uint16 y, uint16 width, uint16 height,
                                     const uint16 *masks);
/* Merge a cached component into private planar pixels/masks at any X phase.
 * Both row widths are group-aligned; transparent right padding is clipped. */
extern void Video_Atari_ComposePlanarSprite(uint16 *dstPixels, uint16 *dstMasks,
                                          uint16 dstWidth, uint16 dstHeight,
                                          const uint16 *pixels, const uint16 *masks,
                                          uint16 width, uint16 height, uint16 x, uint16 y);
/* Prealigned/flipped frames or layered units, up to 80x64; width and X
 * are multiples of 16. Clipping preserves cursor/placement backgrounds. */
extern void Video_Atari_PresentPlanarSprite(const uint16 *pixels, const uint16 *masks,
                                          uint16 width, uint16 height, int16 x, int16 y);
#endif /* TOS */

#endif /* VIDEO_VIDEO_H */
