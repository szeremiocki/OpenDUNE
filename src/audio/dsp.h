/** @file src/audio/dsp.h DSP definitions. */

#ifndef DSP_H
#define DSP_H

extern void DSP_Play(const uint8 *data);
extern void DSP_Stop(void);
extern uint8 DSP_GetStatus(void);
extern bool DSP_Init(void);
extern void DSP_Uninit(void);

#ifdef TOS
/* Atari DMA sound needs signed 8bit PCM at a fixed hardware rate, but VOC
 * files store unsigned 8bit PCM at whatever rate the original recording
 * used (found to vary from ~4kHz to ~14.7kHz across this game's samples).
 * Converting once at load time (see dsp_atari.c) avoids repeating both the
 * resampling and the sign conversion on every single play of an
 * already-loaded sample. Only implemented for the Atari DSP backend, so
 * only declared/called on TOS.
 *
 * The result is built in a shared ST RAM scratch buffer (since its size
 * can differ from the input) and is NOT written back into "data" -- the
 * caller must copy *outLength bytes out of the returned pointer into its
 * own (possibly reallocated) buffer before this function is called again
 * for another sample, and must ensure nothing is currently playing from
 * that scratch buffer (see Driver_Voice_Stop()) before calling this.
 *
 * filename is for -DDSP_ATARI_FREQ_STATS_ENABLE logging only; pass NULL
 * if not available (it is otherwise ignored).
 *
 * Returns the shared scratch buffer pointer; *outLength is set to 0 on
 * failure (e.g. ST RAM exhausted), in which case the returned pointer
 * must not be used.
 */
extern const uint8 *DSP_ConvertSample(const uint8 *data, uint32 length, uint32 *outLength, const char *filename);
#endif /* TOS */

#endif /* DSP_H */
