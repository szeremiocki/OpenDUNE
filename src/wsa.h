/** @file src/wsa.h WSA definitions. */

#ifndef WSA_H
#define WSA_H

typedef enum WSAFrameFormat {
	WSA_FRAME_CHUNKY,
	WSA_FRAME_PLANAR
} WSAFrameFormat;

extern uint16 WSA_GetFrameCount(void *wsa);
extern WSAFrameFormat WSA_GetFrameFormat(void *wsa);
/* allowPlanar opts ST/STE callers into standalone PWS loading or preparation.
 * Continuation cache misses require WSA_PreparePlanarContinuation() afterwards.
 * Other platforms and opted-out callers retain original chunky playback. */
extern void *WSA_LoadFile(const char *filename, void *wsa, uint32 wsaSize, bool reserveDisplayFrame, bool allowPlanar);
extern void WSA_Unload(void *wsa);
/* Prepared SCREEN_0 frames publish directly; other targets defer native output
 * until WSA_PresentPlanar(), leaving composition to the caller. */
extern bool WSA_DisplayFrame(void *wsa, uint16 frameNext, uint16 posX, uint16 posY, Screen screenID);

#ifdef TOS
/* Prepare an independent, undecoded WSA matching this window. Keep its original
 * payload for fallback; the shared frame traversal then uses planar deltas. */
extern bool WSA_PreparePlanar(void *wsa, uint16 width, uint16 height);
extern bool WSA_IsContinuation(void *wsa);
/* A continuation cache miss needs the original final image of its source chain.
 * Filenames run from the independent segment through the immediate predecessor.
 * Source reconstruction is private; the saved recording is self-contained. */
extern bool WSA_PreparePlanarContinuation(void *wsa, const char *const *predecessors, uint16 count);
extern bool WSA_PresentPlanarRegion(void *wsa, uint16 x, uint16 y,
                                  uint16 left, uint16 top, uint16 width, uint16 height);
/* Publish pending groups, optionally compositing equally sized, group-aligned
 * planar overlay rows and one opacity word per group. */
extern bool WSA_PresentPlanar(void *wsa, uint16 x, uint16 y,
                             const uint16 *overlay, const uint16 *masks, bool force);
#endif

#endif /* WSA_H */
