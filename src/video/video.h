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
extern void Video_Atari_CursorBuild(const uint8 *chunky);
extern void Video_Atari_CursorHide(void);

/* Persistent, pre-shifted (all 16 sub-16px horizontal phases) bitplane cache
 * for every mouse cursor icon (MOUSE.SHP), built once at load time and once
 * more whenever the palette quantization changes -- never on the movement
 * hot path. See the "Cursor icon preload" section of video_atari.c. */
extern void Video_Atari_CursorPreloadIcons(void);
extern bool Video_Atari_CursorUseIcon(uint16 iconIndex, int16 left, int16 top);

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
 * on ST/STE the "shade" effect (halve every color's brightness, restore
 * later) never needs the 256-entry quantization/pair-LUT machinery either
 * - the 16 hardware pens can be halved/restored directly, instantly (no
 * ramp - the original effect is an immediate, one-shot palette swap, not
 * an animation). Outside of an active fade the 16 registers always sit at
 * their fixed catalog values (see Video_Atari_TryPaletteFadeUniform),
 * so this is always safe to call in matched shade(true)/shade(false) pairs. */
extern void Video_Atari_ShadeHwPalette(bool shade);
#endif /* TOS */

#endif /* VIDEO_VIDEO_H */
