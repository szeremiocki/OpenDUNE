/** @file src/audio/dsp_atari.c Atari DMA Sound implementation of the DSP. */

#include <mint/osbind.h>
#include <mint/ostruct.h>
#include <mint/cookie.h>
#include <string.h>

#include "types.h"
#include "../os/endian.h"
#include "../os/error.h"

#include "dsp.h"

extern void set_dma_sound(const void *buffer, uint32 len, uint32 mode);
extern void stop_dma_sound(void);	/* needs to be called in supervisor mode */
extern uint32 get_dma_status(void);	/* needs to be called in supervisor mode */

/* STE/TT/Falcon DMA Sound is able to play at :
 * 50066Hz 25033Hz 12517Hz 6258Hz
 * (6258Hz is not available on Falcon -- see the note further down about
 * this project currently being ST/STE-only, and what a future Falcon
 * port would need to reconsider here). */
#define DMASOUND_FREQ 12517
/*#define DMASOUND_FREQ 25033*/

/* All VOC samples are resampled to a single fixed target rate once, at
 * load time (see DSP_ConvertSample() below), instead of doing the
 * resample+sign-conversion on every single play. 6258Hz was chosen over
 * 12517Hz after measuring actual VOC sample rates in this game (a
 * -DDSP_ATARI_FREQ_STATS_ENABLE survey found real rates ranging ~4-14.7kHz,
 * dominated by 11.2-14.7kHz speech): 6258Hz keeps resampled+resident
 * voice data around ~0.8MB total instead of ~1.6MB at 12517Hz, which
 * matters a lot on stock ST/STE RAM sizes. This is a permanent choice,
 * not a runtime option; playback always uses the load-time conversion. */
#define DSP_ATARI_NO_RESAMPLE_ENABLE
#if defined(DSP_ATARI_NO_RESAMPLE_ENABLE)
#define DSP_ATARI_NO_RESAMPLE
#undef DMASOUND_FREQ
#define DMASOUND_FREQ 6258
#endif

/* Hardware playback-rate select for register $FFFF8921, must match
 * DMASOUND_FREQ above -- this is a SEPARATE setting from the frequency
 * DSP_ConvertSample() targets when building the buffer; getting the two out
 * of sync plays the buffer at the wrong speed regardless of how it was
 * built (0=6258Hz [not on Falcon], 1=12517Hz, 2=25033Hz, 3=50066Hz). */
#if DMASOUND_FREQ == 6258
#define DMASOUND_MODE 0
#elif DMASOUND_FREQ == 12517
#define DMASOUND_MODE 1
#elif DMASOUND_FREQ == 25033
#define DMASOUND_MODE 2
#elif DMASOUND_FREQ == 50066
#define DMASOUND_MODE 3
#else
#error "DMASOUND_FREQ must be one of 6258, 12517, 25033, 50066"
#endif

/* Sized for whatever DMASOUND_FREQ is currently set to: scaled from the
 * original hardcoded 64KB (which was sized for the old always-12517Hz
 * runtime resampler) so a lower target frequency gets a correspondingly
 * smaller buffer instead of wasting ST RAM. At 6258Hz this comes out to
 * ~31KB, matching the observed post-resample maximum VOC sample size
 * (measured with the DSP_ATARI_FREQ_STATS_ENABLE survey, see the
 * DMASOUND_FREQ comment above). Rounded up to a 4KB multiple. This is the
 * one and only size the buffer ever has: it is allocated once in DSP_Init()
 * and never resized. */
#define DMASOUND_BUFFER_SIZE	((((64UL*1024) * DMASOUND_FREQ / 12517) + 0x0FFF) & ~0x0FFFUL)

/* VOC files encode sample rate as a single byte "frequency divisor" (see
 * DSP_Play() below), not as a free Hz value, so DMASOUND_FREQ itself is
 * not always exactly representable; DMASOUND_VOC_DIVISOR is the divisor
 * byte that decodes (via the same 1000000/(256-divisor) formula) to the
 * closest frequency to DMASOUND_FREQ. For 6258Hz this is divisor 96,
 * which decodes back to 6250Hz -- the two are close enough that nothing
 * downstream needs to know they differ. */
#define DMASOUND_VOC_DIVISOR ((uint8)(256 - ((1000000UL + DMASOUND_FREQ / 2) / DMASOUND_FREQ)))

static uint8 *s_stRamBuffer;
static uint32 s_stRamBufferSize;
static const uint8 *s_playingSample;

void DSP_Stop(void)
{
	Supexec(stop_dma_sound);
	s_playingSample = NULL;
}

void *DSP_AllocSample(uint32 length)
{
	void *sample = (void *)Mxalloc(length, MX_STRAM);
	if ((long)sample <= 0) {
		Warning("Failed to allocate %u bytes of ST RAM for voice sample.\n", length);
		return NULL;
	}
	return sample;
}

void DSP_FreeSample(void *sample)
{
	if (sample == NULL) return;
	if (sample == s_playingSample) DSP_Stop();
	Mfree(sample);
}

void DSP_Uninit(void)
{
	DSP_Stop();
	if (s_stRamBuffer != NULL) {
		Mfree(s_stRamBuffer);
		s_stRamBuffer = NULL;
	}
	s_stRamBufferSize = 0;
}

bool DSP_Init(void) 
{
	/* Get sound hardware with '_SND' cookie */
	long snd_cookie;
	if (Getcookie(C__SND, &snd_cookie) != C_FOUND)
		snd_cookie = 0;

	/* Check for DMA support */
	if (!(snd_cookie & 2)) {
		Warning("No Sound DMA detected\n");
		return false;
	}

	/* allocate ST RAM buffer for audio */
	s_stRamBufferSize = DMASOUND_BUFFER_SIZE;
	s_stRamBuffer = (uint8 *)Mxalloc(s_stRamBufferSize, MX_STRAM);
	if((long)s_stRamBuffer <= 0) {
		Error("Failed to allocate %u bytes of ST RAM for DMA sound.\n",
		      s_stRamBufferSize);
		s_stRamBufferSize = 0;
		s_stRamBuffer = NULL;
		return false;
	}
	return true;
}

/**
 * Check that "needed" bytes fit in s_stRamBuffer (the DMA-visible ST RAM
 * conversion scratch buffer).
 *
 * The buffer is allocated once, at DMASOUND_BUFFER_SIZE, in DSP_Init() and
 * never resized: that size is derived from DMASOUND_FREQ and already covers
 * the largest resampled sample in the game (see the DMASOUND_BUFFER_SIZE
 * comment above), and a compile-time assert ties it to READ_BUFFER_SIZE.
 * So this is now purely a guard against a corrupt/unexpected sample asking
 * for more than the buffer can hold - refusing it here keeps the overflow
 * from becoming heap corruption.
 */
static bool DSP_StRamBufferFits(uint32 needed)
{
	if (needed <= s_stRamBufferSize) return true;

	Error("DMA sound sample too large for ST RAM buffer. needed=%u have=%u\n",
	      needed, s_stRamBufferSize);
	return false;
}

/**
 * Convert a whole loaded VOC file to signed 8bit PCM already resampled to
 * DMASOUND_FREQ, once, at load time (see
 * Driver_Voice_LoadFile() in driver.c, the single choke point every VOC
 * load -- preloaded or ad-hoc -- goes through).
 *
 * The VOC container format is kept: odd-sized headers are padded to align
 * the first PCM payload, and sound blocks get an updated length and rate.
 * Odd PCM lengths get one signed-silence byte for an even DMA end address.
 * Non-sound-data blocks are copied verbatim. This mirrors the
 * Create Voice File header skip and block-type/length parsing in
 * DSP_Play() -- if that parsing ever changes, update both.
 *
 * The result is built in s_stRamBuffer, bounds-checked via
 * DSP_StRamBufferFits(), NOT in "data" itself, since the resampled size can differ
 * from the original (most samples in this game are >6258Hz and shrink,
 * but a few short low-rate sound effects are <6258Hz and grow). The
 * caller is expected to allocate its own ST RAM buffer and copy the
 * result out of s_stRamBuffer before the next call, since this scratch
 * buffer is shared/reused by every load and by non-preloaded speech -- the
 * caller MUST call Driver_Voice_Stop() first if a sample might currently
 * be playing from it (see Driver_Voice_LoadFile()).
 *
 * On failure (ST RAM exhausted), *outLength is set to 0 and "data" is left
 * untouched; the caller should treat this like a failed load.
 *
 * filename is only used for the optional -DDSP_ATARI_FREQ_STATS_ENABLE
 * survey below; pass NULL if not available.
 */
const uint8 *DSP_ConvertSample(const uint8 *data, uint32 length, uint32 *outLength, const char *filename)
{
	const uint8 *end = data + length;
	const uint8 *p = data;
	uint16 headerSize;
	uint32 written;

	VARIABLE_NOT_USED(filename);

	*outLength = 0;

	if (length < 26) return NULL;

	headerSize = READ_LE_UINT16(p + 20);
	if (headerSize < 26 || headerSize >= length || headerSize == 0xffff) return NULL;
	written = (headerSize + 1u) & ~1u;
	if (!DSP_StRamBufferFits(written)) return NULL;
	memcpy(s_stRamBuffer, p, headerSize);
	if (written != headerSize) s_stRamBuffer[headerSize] = 0;
	WRITE_LE_UINT16(s_stRamBuffer + 20, written);
	p += headerSize;

	while (p < end) {
		uint8 blockType = *p;
		uint32 blockLen;

		/* see DSP_Play() for the full Block Type list; 0x00
		 * (Terminator) ends the sample, copy it and stop. */
		if (blockType == 0) {
			if (!DSP_StRamBufferFits(written + 1)) { *outLength = 0; return NULL; }
			s_stRamBuffer[written++] = 0;
			break;
		}

		/* Malformed/truncated data: not even a full 4-byte block
		 * header (1 type + 3 length bytes) left before "end". Bail
		 * out rather than reading blockLen from out-of-bounds bytes
		 * -- this previously produced a garbage blockLen (observed
		 * as a bogus ~16MB "needed" size reaching
		 * DSP_StRamBufferFits()) that could corrupt the heap. */
		if ((uint32)(end - p) < 4) { *outLength = 0; return NULL; }

		blockLen = p[1] | (p[2] << 8) | (p[3] << 16);
		if (blockLen > (uint32)(end - p) - 4) blockLen = (uint32)(end - p) - 4;

		if (blockType != 1) {
			/* Not sound data -- copy the block verbatim. */
			uint32 total = 4 + blockLen;
			if (!DSP_StRamBufferFits(written + total)) { *outLength = 0; return NULL; }
			memcpy(s_stRamBuffer + written, p, total);
			written += total;
			p += total;
			continue;
		}

		{
			/* Block Type 1 (Sound data): byte 0 frequency divisor,
			 * byte 1 codec id (0 = "8bits unsigned PCM"), rest is
			 * audio data. Guard against a too-short/clamped block
			 * (blockLen < 2, e.g. truncated data) which would
			 * otherwise underflow "payloadLen" below. */
			uint8 codecId;
			uint32 freq;
			uint32 payloadLen;
			const uint8 *src;
			uint8 *dst;
			uint8 *w;
			uint32 i, j;
			uint32 paddedLength;

			if (blockLen < 2) { *outLength = 0; return NULL; }

			codecId = p[5];
			freq = 1000000UL / (256 - p[4]);
			payloadLen = blockLen - 2;
			src = p + 6;

			if (codecId != 0) Warning("Unsupported VOC codec 0x%02x\n", (int)codecId);


#if defined(DSP_ATARI_FREQ_STATS_ENABLE)
			/* DEBUG AID -- log each VOC's actual source sample
			 * rate to error.log. Used once to survey real-world
			 * frequency variability across this game's samples
			 * (result: ~4-14.7kHz, see the DMASOUND_FREQ comment
			 * above); off by default, kept only in case source
			 * data/assumptions ever need re-checking. Build with
			 * -DDSP_ATARI_FREQ_STATS_ENABLE to enable. */
			Error("FREQSTATS %s freq=%luHz len=%lu\n",
			      (filename != NULL) ? filename : "?",
			      (unsigned long)freq, (unsigned long)payloadLen);
#endif

			/* Reserve ceil(resampled length), rounded to an even DMA length. */
			paddedLength = ((payloadLen * DMASOUND_FREQ + freq - 1) / freq + 1) & ~1u;
			if (!DSP_StRamBufferFits(written + 6 + paddedLength)) {
				*outLength = 0;
				return NULL;
			}

			dst = s_stRamBuffer + written;
			dst[4] = DMASOUND_VOC_DIVISOR;
			dst[5] = codecId;

			w = dst + 6;
			for (i = 1, j = 0; i <= payloadLen; i++) {
				uint8 sample = *src++ ^ 0x80;
				while (j < i * DMASOUND_FREQ) {
					*w++ = sample;
					j += freq;
				}
			}

			{
				uint32 newPayloadLen = (uint32)(w - (dst + 6));
				uint32 newBlockLen;
				if ((newPayloadLen & 1) != 0) {
					*w = 0;
					newPayloadLen++;
				}
				newBlockLen = newPayloadLen + 2;
				dst[0] = 1;
				dst[1] = newBlockLen & 0xFF;
				dst[2] = (newBlockLen >> 8) & 0xFF;
				dst[3] = (newBlockLen >> 16) & 0xFF;
				written += 4 + newBlockLen;
			}
		}

		p += 4 + blockLen;
	}

	*outLength = written;
	return s_stRamBuffer;
}


void DSP_Play(const uint8 *data)
{
	uint32 len;
	const uint8 *sample = data;

	/* skip Create Voice File header */
	data += READ_LE_UINT16(data + 20);

	/* first byte is Block Type :
	 * 0x00: Terminator
	 * 0x01: Sound data
	 * 0x02: Sound data continuation
	 * 0x03: Silence
	 * 0x04: Marker
	 * 0x05: Text
	 * 0x06: Repeat start
	 * 0x07: Repeat end
	 * 0x08: Extra info
	 * 0x09: Sound data (New format) */
	if (*data != 1) return;

	/* next 3 bytes are block size (not including the 1 block type and
	 * size 4 bytes) */
	len = data[1] | (data[2] << 8) | (data[3] << 16);
	/* Sanity-check before the "-= 2" below: a corrupt/garbage buffer
	 * (e.g. one whose real contents were clobbered by an overflowing
	 * caller) can otherwise yield a nonsense multi-megabyte length, or
	 * underflow to ~4GB when len < 2. No converted sample can exceed
	 * the conversion scratch limit. */
	if (len < 2 || len - 2 > DMASOUND_BUFFER_SIZE) {
		Warning("DSP_Play: implausible VOC block length %lu, ignoring sample\n",
		        (unsigned long)len);
		return;
	}
	len -= 2;
	data += 4;
	/* byte  0    frequency divisor
	 * byte  1    codec id : 0 is "8bits unsigned PCM"
	 * bytes 2..n audio data */
	if (data[0] != DMASOUND_VOC_DIVISOR || data[1] != 0 ||
	    ((unsigned long)(data + 2) & 1) != 0 || (len & 1) != 0) {
		Warning("DSP_Play: sample is not DMA-ready (rate=%u codec=%u length=%u).\n",
		        (unsigned)data[0], (unsigned)data[1], len);
		return;
	}
	if (len == 0) return;

	/* All TOS callers use retained ST RAM or the ST RAM conversion scratch.
	 * Neither source may be freed/overwritten until DMA has stopped. */
	set_dma_sound(data + 2, len, DMASOUND_MODE);
	s_playingSample = sample;
}

/**
 * Should return 2 if playing sound, 0 if not
 */
uint8 DSP_GetStatus(void)
{
	uint8 status = (uint8)Supexec(get_dma_status);
	Debug("DSP_GetStatus() status = %02x : %s\n",
	      status, (status != 0) ? "Playing" : "Stopped");
	return (status != 0) ? 2 : 0;
}
