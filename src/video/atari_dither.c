/** @file src/video/atari_dither.c Shared phase-aware asset pen preparation. */

#include <assert.h>
#include <stddef.h>
#include "atari_dither.h"

void Video_Atari_DitherPrepareLookup(AtariDitherLookup *lookup,
	const AtariDitherPattern patterns[256])
{
	uint16 y, x, colour;

	assert(lookup != NULL && patterns != NULL);
	lookup->flat = true;
	for (y = 0; y < 4; y++) {
		for (x = 0; x < 4; x++) {
			for (colour = 0; colour < 256; colour++) {
				assert(patterns[colour][y][x] < 16);
				lookup->pens[y][x][colour] = patterns[colour][y][x];
				if (patterns[colour][y][x] != patterns[colour][0][0]) lookup->flat = false;
			}
		}
	}
}

void Video_Atari_DitherSetPen(AtariDitherLookup *lookup, uint8 colour, uint8 pen)
{
	uint16 y, x;

	assert(lookup != NULL && pen < 16);
	for (y = 0; y < 4; y++)
		for (x = 0; x < 4; x++) lookup->pens[y][x][colour] = pen;
}

void Video_Atari_PreparePens(const AtariDitherSource *source,
	const AtariDitherLookup *lookup, const AtariDitherTarget *target)
{
	uint16 row, x;
	uint8 scale, phaseY, advanceX, advanceY, dy;
	const uint8 *src;
	uint8 *output;

	assert(source != NULL && lookup != NULL && target != NULL);
	assert(source->pixels != NULL && target->pixels != NULL);
	assert(source->width != 0 && source->height != 0 && source->stride >= source->width);
	assert(source->stepX == 1 || source->stepX == -1);
	assert(source->stepY == 1 || source->stepY == -1);
	assert(target->scale == 1 || target->scale == 2);
	assert(target->stride >= (uint32)source->width * target->scale);
	scale = target->scale;
	phaseY = ((uint16)source->originY * scale) & 3;
	advanceX = (uint8)(source->stepX * scale) & 3;
	advanceY = (uint8)(source->stepY * scale) & 3;
	src = source->pixels;
	output = target->pixels;
	for (row = 0; row < source->height; row++) {
		if (row != 0) src += source->stride;
		for (dy = 0; dy < scale; dy++) {
			uint8 *dst;
			uint8 py = (phaseY + (source->stepY < 0 ? scale - 1 - dy : dy)) & 3;
			uint8 phaseX = ((uint16)source->originX * scale) & 3;

			if (row != 0 || dy != 0) output += target->stride;
			dst = output;
			if (scale == 1) {
				for (x = 0; x < source->width; x++) {
					*dst++ = lookup->pens[py][phaseX][src[x]];
					phaseX = (phaseX + advanceX) & 3;
				}
			} else {
				for (x = 0; x < source->width; x++) {
					uint8 left = source->stepX < 0 ? 1 : 0;
					*dst++ = lookup->pens[py][(phaseX + left) & 3][src[x]];
					*dst++ = lookup->pens[py][(phaseX + (left ^ 1)) & 3][src[x]];
					phaseX = (phaseX + advanceX) & 3;
				}
			}
		}
		phaseY = (phaseY + advanceY) & 3;
	}
}
