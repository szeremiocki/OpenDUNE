/** @file src/video/atari_mono.c Native monochrome packing and private asset composition. */

#include <assert.h>
#include <stddef.h>
#include <string.h>
#include "atari_mono.h"

#if defined(TOS) && defined(__m68k__)
extern void c2p1x1_1_st(uint16 *top, uint16 *bottom, const uint8 *src,
	uint32 groups, const uint32 *even, const uint32 *odd);
#else
static void c2p1x1_1_st(uint16 *top, uint16 *bottom, const uint8 *src,
	uint32 groups, const uint32 *even, const uint32 *odd)
{
	while (groups-- != 0) {
		uint16 x;
		uint32 cells = 0;
		for (x = 0; x < 8; x++)
			cells = (cells << 2) | ((x & 1) ? odd : even)[*src++];
		*top++ = cells >> 16;
		*bottom++ = cells;
	}
}
#endif

static uint16 Mono_ExpandOpacity(uint16 bits)
{
	bits = (bits | (bits << 4)) & 0x0f0f;
	bits = (bits | (bits << 2)) & 0x3333;
	bits = (bits | (bits << 1)) & 0x5555;
	return bits | (bits << 1);
}

void Video_Atari_MonoPreparePackedLookup(AtariMonoPackedLookup *lookup,
	const AtariDitherLookup *dither, uint16 first, uint16 count, bool whiteIsOne)
{
	uint16 y, x, colour;
	const uint32 invert = whiteIsOne ? 0 : 0x00030003UL;

	assert(lookup != NULL && dither != NULL && first + (uint32)count <= 256);
	for (y = 0; y < 2; y++) {
		for (x = 0; x < 2; x++) {
			for (colour = first; colour < first + count; colour++) {
				assert(dither->pens[y * 2][x * 2][colour] <= 1 &&
					dither->pens[y * 2][x * 2 + 1][colour] <= 1 &&
					dither->pens[y * 2 + 1][x * 2][colour] <= 1 &&
					dither->pens[y * 2 + 1][x * 2 + 1][colour] <= 1);
				lookup->cells[y][x][colour] =
					(((uint32)dither->pens[y * 2][x * 2][colour] << 17) |
					 ((uint32)dither->pens[y * 2][x * 2 + 1][colour] << 16) |
					 (dither->pens[y * 2 + 1][x * 2][colour] << 1) |
					 dither->pens[y * 2 + 1][x * 2 + 1][colour]) ^ invert;
			}
		}
	}
}

void Video_Atari_MonoPrepareLookup(AtariMonoLookup *lookup,
	const AtariDitherPattern patterns[256], bool whiteIsOne)
{
	uint16 y, x, colour;
	uint8 invert = whiteIsOne ? 0 : 15;

	assert(lookup != NULL && patterns != NULL);
	for (y = 0; y < 2; y++) {
		for (x = 0; x < 2; x++) {
			for (colour = 0; colour < 256; colour++) {
				const uint8 *top = &patterns[colour][y * 2][x * 2];
				const uint8 *bottom = &patterns[colour][y * 2 + 1][x * 2];
				assert(top[0] <= 1 && top[1] <= 1 && bottom[0] <= 1 && bottom[1] <= 1);
				lookup->cells[y][x][colour] =
					((top[0] << 3) | (top[1] << 2) | (bottom[0] << 1) | bottom[1]) ^ invert;
			}
		}
	}
}

void Video_Atari_MonoPackNative(const AtariDitherSource *source,
	const AtariMonoPackedLookup *lookup, uint16 *pixels, uint16 stride)
{
	uint16 row, words, full, tail;

	assert(source != NULL);
	assert(source->pixels != NULL && lookup != NULL && pixels != NULL);
	assert(source->width != 0 && source->height != 0 && source->stride >= source->width);
	assert(source->stepX == 1 || source->stepX == -1);
	assert(source->stepY == 1 || source->stepY == -1);
	words = ((source->width + 15u) & ~15u) / 8;
	full = source->width / 8;
	tail = source->width & 7;
	assert((stride & 1) == 0 && stride >= words * 2);
	for (row = 0; row < source->height; row++) {
		const uint8 *src = source->pixels + (size_t)row * source->stride;
		const uint32 *even = lookup->cells[(source->originY + row) & 1][(uint16)source->originX & 1];
		const uint32 *odd = lookup->cells[(source->originY + row) & 1][((uint16)source->originX & 1) ^ 1];
		uint16 *top = pixels + (size_t)row * stride;
		uint16 *bottom = top + stride / 2;
		uint16 x = full;

		/* Input memory is already flipped; reverse only each cell's physical rows/bits. */
		if (source->stepY < 0) {
			uint16 *swap = top;
			top = bottom;
			bottom = swap;
		}
		if (full != 0) c2p1x1_1_st(top, bottom, src, full, even, odd);
		if (tail != 0) {
			uint16 col, padding = 16 - tail * 2;
			uint32 cells = 0;
			for (col = 0; col < tail; col++)
				cells = (cells << 2) | ((col & 1) ? odd : even)[src[full * 8 + col]];
			top[x] = (uint16)(cells >> 16) << padding;
			bottom[x++] = (uint16)cells << padding;
		}
		for (; x < words; x++) top[x] = bottom[x] = 0;
		if (source->stepX < 0) {
			for (x = 0; x < words; x++) {
				top[x] = ((top[x] & 0xaaaau) >> 1) | ((top[x] & 0x5555u) << 1);
				bottom[x] = ((bottom[x] & 0xaaaau) >> 1) | ((bottom[x] & 0x5555u) << 1);
			}
		}
	}
}

void Video_Atari_MonoPack(const AtariMonoSource *source,
	const AtariMonoLookup *lookup, const AtariMonoBitmap *target)
{
	uint16 row;

	assert(source != NULL && lookup != NULL && target != NULL);
	assert(source->pixels != NULL && target->pixels != NULL);
	assert(source->width != 0 && source->height != 0);
	assert(source->pixelStride >= source->width);
	assert(target->stride >= (source->width + 7u) / 8);
	assert(source->opacity == NULL || (target->opacity != NULL &&
		source->opacityStride >= (source->width + 15u) / 16));

	for (row = 0; row < source->height; row++) {
		const uint8 *src = source->pixels + (size_t)row * source->pixelStride;
		const uint16 *opacity = source->opacity == NULL ? NULL :
			source->opacity + (size_t)row * source->opacityStride;
		const uint8 *even = lookup->cells[(source->originY + row) & 1][(uint16)source->originX & 1];
		const uint8 *odd = lookup->cells[(source->originY + row) & 1][((uint16)source->originX & 1) ^ 1];
		uint16 *top = target->pixels + (size_t)row * 2 * target->stride;
		uint16 *bottom = top + target->stride;
		uint16 *mask = target->opacity == NULL ? NULL :
			target->opacity + (size_t)row * 2 * target->stride;
		uint16 x = 0;

		while (x < source->width) {
			uint16 count = source->width - x, col, upper = 0, lower = 0;
			uint16 padding, valid;
			if (count > 8) count = 8;
			padding = 16 - count * 2;
			for (col = 0; col < count; col++) {
				uint8 cell = (col & 1 ? odd : even)[src[x + col]];
				upper = (upper << 2) | (cell >> 2);
				lower = (lower << 2) | (cell & 3);
			}
			valid = (uint16)(0xffffu << padding);
			if (opacity != NULL) {
				uint16 bits = (opacity[x >> 4] >> (8 - (x & 8))) & 0xff;
				valid &= Mono_ExpandOpacity(bits);
			}
			*top++ = (uint16)(upper << padding) & valid;
			*bottom++ = (uint16)(lower << padding) & valid;
			if (mask != NULL) {
				mask[0] = mask[target->stride] = valid;
				mask++;
			}
			x += count;
		}
	}
}

void Video_Atari_MonoPackPens(const uint8 *pens, uint16 *pixels,
	uint16 width, uint16 height, uint16 srcStride, uint16 dstStride, bool whiteIsOne)
{
	uint16 row;
	assert(pens != NULL && pixels != NULL && width != 0 && height != 0);
	assert(srcStride >= width && dstStride >= (width + 15u) / 16);
	for (row = 0; row < height; row++) {
		uint16 x;
		memset(pixels, 0, dstStride * sizeof(*pixels));
		for (x = 0; x < width; x++) {
			assert(pens[x] <= 1);
			if ((pens[x] != 0) == whiteIsOne) pixels[x >> 4] |= 0x8000u >> (x & 15);
		}
		pens += srcStride;
		pixels += dstStride;
	}
}

void Video_Atari_MonoReadGroup(const uint16 *pixels, uint16 stride,
	uint16 row, uint16 group, uint16 words[4])
{
	const uint16 *p = pixels + (size_t)row * stride + group * 2;
	words[0] = p[0]; words[1] = p[1];
	words[2] = p[stride / 2]; words[3] = p[stride / 2 + 1];
}

void Video_Atari_MonoWriteGroup(uint16 *pixels, uint16 stride,
	uint16 row, uint16 group, const uint16 words[4])
{
	uint16 *p = pixels + (size_t)row * stride + group * 2;
	p[0] = words[0]; p[1] = words[1];
	p[stride / 2] = words[2]; p[stride / 2 + 1] = words[3];
}

void Video_Atari_MonoMaskWords(uint16 mask, uint16 words[4])
{
	words[0] = words[2] = Mono_ExpandOpacity(mask >> 8);
	words[1] = words[3] = Mono_ExpandOpacity(mask & 255);
}

void Video_Atari_MonoComposeTile(const uint16 *pixels, const uint16 *masks,
	const uint16 *overlay, const uint16 *overlayMasks, uint16 *result, uint16 *resultMasks)
{
	uint16 row, word;

	for (row = 0; row < 16; row++) {
		uint16 mask = masks[row], overlayMask = overlay == NULL ? 0 : overlayMasks[row];
		uint16 opacity[4], overlayOpacity[4];
		Video_Atari_MonoMaskWords(mask, opacity);
		if (overlay != NULL) Video_Atari_MonoMaskWords(overlayMask, overlayOpacity);
		resultMasks[row] = mask | overlayMask;
		for (word = 0; word < 4; word++) {
			uint16 value = pixels[row * 4 + word] & opacity[word];
			if (overlay != NULL) value = (value & ~overlayOpacity[word]) | (overlay[row * 4 + word] & overlayOpacity[word]);
			result[row * 4 + word] = value;
		}
	}
}

void Video_Atari_MonoMergeWords(uint16 dst[4], const uint16 pixels[4], uint16 mask)
{
	uint16 expanded[4], i;
	Video_Atari_MonoMaskWords(mask, expanded);
	for (i = 0; i < 4; i++) dst[i] = (dst[i] & ~expanded[i]) | (pixels[i] & expanded[i]);
}

static uint16 Mono_ReadWord(const uint16 *row, uint16 words, int16 bit)
{
	uint16 index, shift, result;
	if (bit <= -16 || bit >= words * 16) return 0;
	if (bit < 0) return row[0] >> -bit;
	index = bit >> 4;
	shift = bit & 15;
	result = row[index] << shift;
	if (shift != 0 && index + 1 < words) result |= row[index + 1] >> (16 - shift);
	return result;
}

void Video_Atari_MonoReadSpan(const uint16 *pixels, uint16 stride,
	uint16 row, int16 x, uint16 words[4])
{
	const uint16 *top = pixels + (size_t)row * stride;
	uint16 i;
	for (i = 0; i < 4; i++)
		words[i] = Mono_ReadWord(top + (i / 2) * (stride / 2), stride / 2,
			x * 2 + (i & 1) * 16);
}

uint16 Video_Atari_MonoReadMask(const uint16 *masks, uint16 width,
	uint16 row, int16 x, bool expanded)
{
	uint16 i, mask = 0;
	if (masks == NULL) {
		for (i = 0; i < 16; i++) if (x + (int)i >= 0 && x + i < width) mask |= 0x8000u >> i;
	} else if (!expanded) {
		mask = Mono_ReadWord(masks + (size_t)row * (width / 16), width / 16, x);
	} else {
		uint16 words[4];
		Video_Atari_MonoReadSpan(masks, width / 4, row, x, words);
		for (i = 0; i < 16; i++)
			if (words[i / 8] & (0x8000u >> ((i & 7) * 2))) mask |= 0x8000u >> i;
	}
	return mask;
}

void Video_Atari_MonoMaskBitmap(uint16 *pixels, uint16 *expanded,
	const uint16 *compact, uint16 width, uint16 height)
{
	uint16 row = height;
	assert(pixels != NULL && compact != NULL && width != 0 && (width & 15) == 0);
	/* Reverse traversal also permits expanding compact masks in place. */
	while (row-- != 0) {
		uint16 group = width / 16;
		while (group-- != 0) {
			uint16 words[4], opacity[4], i;
			Video_Atari_MonoMaskWords(compact[row * (width / 16) + group], opacity);
			Video_Atari_MonoReadGroup(pixels, width / 4, row, group, words);
			for (i = 0; i < 4; i++) words[i] &= opacity[i];
			Video_Atari_MonoWriteGroup(pixels, width / 4, row, group, words);
			if (expanded != NULL)
				Video_Atari_MonoWriteGroup(expanded, width / 4, row, group, opacity);
		}
	}
}

void Video_Atari_MonoCompose(uint16 *dst, uint16 dstStride,
	uint16 *dstMasks, uint16 dstMaskStride, uint16 dstWidth, uint16 dstHeight,
	const uint16 *pixels, const uint16 *masks, uint16 width, uint16 height, int16 x, int16 y)
{
	int row, group, first = x >= 0 ? x / 16 : -((15 - x) / 16);
	int end = ((int)x + width + 15) / 16;
	assert((width & 15) == 0 && (dstWidth & 15) == 0 && dstStride >= dstWidth / 4);
	if (first < 0) first = 0;
	if (end > dstWidth / 16) end = dstWidth / 16;
	for (row = 0; row < height; row++) {
		if (y + row < 0 || y + row >= dstHeight) continue;
		for (group = first; group < end; group++) {
			int16 sx = group * 16 - x;
			uint16 src[4], old[4], mask = Video_Atari_MonoReadMask(masks, width, row, sx, false);
			if (mask == 0) continue;
			Video_Atari_MonoReadSpan(pixels, width / 4, row, sx, src);
			Video_Atari_MonoReadGroup(dst, dstStride, y + row, group, old);
			Video_Atari_MonoMergeWords(old, src, mask);
			Video_Atari_MonoWriteGroup(dst, dstStride, y + row, group, old);
			if (dstMasks != NULL) dstMasks[(y + row) * dstMaskStride + group] |= mask;
		}
	}
}
