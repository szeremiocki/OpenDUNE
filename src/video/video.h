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
#endif /* TOS */

#endif /* VIDEO_VIDEO_H */
