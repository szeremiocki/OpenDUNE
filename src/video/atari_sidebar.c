/** @file src/video/atari_sidebar.c Prepared sidebar BLITTER commands, independent of viewport kernels. */

#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "types.h"
#include "video.h"
#include "atari_mono.h"
#include "atari_sidebar.h"
#include "../os/common.h"
#include "../os/endian.h"

extern bool g_videoBlitterTileSetup;
extern void Video_Atari_SidebarHealthCode(void);

static uint16 *Sidebar_Long(uint16 *out, uint16 opcode, uint32 value, uint16 address)
{
	*out++ = HTOBE16(opcode);
	*out++ = HTOBE16(value >> 16);
	*out++ = HTOBE16(value);
	*out++ = HTOBE16(address);
	return out;
}

static uint16 *Sidebar_Word(uint16 *out, uint16 opcode, uint16 value, uint16 address)
{
	*out++ = HTOBE16(opcode);
	*out++ = HTOBE16(value);
	*out++ = HTOBE16(address);
	return out;
}

static uint16 *Sidebar_Launch(uint16 *out, const uint16 *source, uint16 plane, uint16 height)
{
	out = Sidebar_Long(out, 0x21fc, (uint32)(uintptr_t)source, 0x8a24);
	if (plane != 0) {
		*out++ = HTOBE16(0x43e8); /* lea plane(a0),a1 */
		*out++ = HTOBE16(plane * 2);
	}
	*out++ = HTOBE16(plane == 0 ? 0x21c8 : 0x21c9);
	*out++ = HTOBE16(0x8a32);
	out = Sidebar_Word(out, 0x31fc, height, 0x8a38);
	out = Sidebar_Word(out, 0x11fc, 0xc0, 0x8a3c);
	*out++ = HTOBE16(0x4e71);
	return out;
}

static uint16 *Sidebar_Interleaved(uint16 *out, uint16 width)
{
	out = Sidebar_Long(out, 0x21fc, 0x00020002, 0x8a20);
	out = Sidebar_Long(out, 0x21fc, 0xffffffff, 0x8a28);
	out = Sidebar_Long(out, 0x21fc, 0xffff0002, 0x8a2c);
	out = Sidebar_Word(out, 0x31fc, Video_Atari_Mono() ? 82 - width / 4 : 162 - width / 2, 0x8a30);
	out = Sidebar_Word(out, 0x31fc, Video_Atari_Mono() ? width / 8 : width / 4, 0x8a36);
	return Sidebar_Word(out, 0x11fc, 0, 0x8a3d);
}

size_t Video_Atari_CompileSidebarBlit(VideoAtariSidebarBlit *code,
    const uint16 *pixels, const uint16 *masks, uint16 sourceWidth,
    uint16 width, uint16 height, uint16 phase)
{
	uint16 *out = code->words;
	uint16 words = (phase + width + 15) >> 4;
	uint16 first = 0xffffu >> phase, last = 0xffffu << (15 - ((phase + width - 1) & 15));
	uint16 sourceWords = (width + 15) >> 4;
	bool suppress = sourceWords < words;
	uint16 pass, plane;

	assert(sourceWidth != 0 && (sourceWidth & 15) == 0 && width != 0 && width <= sourceWidth);
	assert(height != 0 && phase < 16);
	*out++ = HTOBE16(0x4239); /* Invalidate the shared BLITTER register residency at playback. */
	*out++ = HTOBE16((uint32)(uintptr_t)&g_videoBlitterTileSetup >> 16);
	*out++ = HTOBE16((uint32)(uintptr_t)&g_videoBlitterTileSetup);
	if (Video_Atari_Mono() && (phase != 0 || width != sourceWidth)) {
		uint16 physicalPhase = (phase * 2) & 15;
		words = (physicalPhase + width * 2 + 15) / 16;
		sourceWords = (width * 2 + 15) / 16;
		suppress = sourceWords < words;
		first = 0xffffu >> physicalPhase;
		last = 0xffffu << (15 - ((physicalPhase + width * 2 - 1) & 15));
		if (phase >= 8) {
			*out++ = HTOBE16(0x41e8); /* lea 2(a0),a0 */
			*out++ = HTOBE16(2);
		}
		out = Sidebar_Long(out, 0x21fc, ((uint32)2 << 16) |
			(uint16)(sourceWidth / 4 - (words - 1) * 2 + (suppress ? 2 : 0)), 0x8a20);
		out = Sidebar_Long(out, 0x21fc, ((uint32)(words == 1 ? first & last : first) << 16) | 0xffff, 0x8a28);
		out = Sidebar_Long(out, 0x21fc, ((uint32)last << 16) | 2, 0x8a2c);
		out = Sidebar_Word(out, 0x31fc, 80 - (words - 1) * 2, 0x8a30);
		out = Sidebar_Word(out, 0x31fc, words, 0x8a36);
		out = Sidebar_Word(out, 0x11fc, physicalPhase | (suppress ? 0x40 : 0), 0x8a3d);
		for (pass = 0; pass < (masks == NULL ? 1 : 2); pass++) {
			out = Sidebar_Word(out, 0x31fc, masks == NULL ? 0x0203 : pass == 0 ? 0x0204 : 0x0207, 0x8a3a);
			out = Sidebar_Launch(out, masks != NULL && pass == 0 ? masks : pixels, 0, height * 2);
		}
	} else if (masks == NULL && phase == 0 && width == sourceWidth) {
		out = Sidebar_Interleaved(out, width);
		out = Sidebar_Word(out, 0x31fc, 0x0203, 0x8a3a);
		out = Sidebar_Launch(out, pixels, 0, Video_Atari_Mono() ? height * 2 : height);
	} else {
		uint16 set[4] = {0}, clear[4] = {0};
		uint16 group, groups = sourceWidth / 16 * height;

		for (group = 0; masks != NULL && group < groups; group++) {
			for (plane = 0; plane < 4; plane++) {
				uint16 opacity = masks[group * 4 + plane], colour = pixels[group * 4 + plane];
				set[plane] |= colour & opacity;
				clear[plane] |= (uint16)~colour & opacity;
			}
		}
		if (masks != NULL && phase == 0 && width == sourceWidth) {
			out = Sidebar_Interleaved(out, width);
			for (pass = 0; pass < 2; pass++) {
				const uint16 *needed = pass == 0 ? clear : set;
				if ((needed[0] | needed[1] | needed[2] | needed[3]) == 0) continue;
				out = Sidebar_Word(out, 0x31fc, pass == 0 ? 0x0204 : 0x0207, 0x8a3a);
				out = Sidebar_Launch(out, pass == 0 ? masks : pixels, 0, Video_Atari_Mono() ? height * 2 : height);
			}
		} else {
			out = Sidebar_Long(out, 0x21fc,
			    ((uint32)8 << 16) | (uint16)(sourceWidth / 2 - (words - 1) * 8 + (suppress ? 8 : 0)), 0x8a20);
			out = Sidebar_Long(out, 0x21fc,
			    ((uint32)(words == 1 ? first & last : first) << 16) | 0xffff, 0x8a28);
			out = Sidebar_Long(out, 0x21fc, ((uint32)last << 16) | 8, 0x8a2c);
			out = Sidebar_Word(out, 0x31fc, 160 - (words - 1) * 8, 0x8a30);
			out = Sidebar_Word(out, 0x31fc, words, 0x8a36);
			out = Sidebar_Word(out, 0x11fc, phase | (suppress ? 0x40 : 0), 0x8a3d);
			for (pass = 0; pass < (masks == NULL ? 1 : 2); pass++) {
				out = Sidebar_Word(out, 0x31fc,
				    masks == NULL ? 0x0203 : (pass == 0 ? 0x0204 : 0x0207), 0x8a3a);
				for (plane = 0; plane < 4; plane++) {
					if (masks != NULL && (pass == 0 ? clear[plane] : set[plane]) == 0) continue;
					out = Sidebar_Launch(out, (masks != NULL && pass == 0 ? masks : pixels) + plane, plane, height);
				}
			}
		}
	}
	*out++ = HTOBE16(0x4e75);
	assert(out <= code->words + lengthof(code->words));
	return (out - code->words) * sizeof(*out);
}

void Video_Atari_QueueSidebarBlit(const uint16 *code, uint16 *dst)
{
	uint16 *out;
	uint32 address;

	assert(g_videoDisplayListActive);
	Video_Atari_DisplayListCheck(12);
	out = g_videoDisplayListNext;
	*out++ = HTOBE16(0x207c); /* movea.l #destination,a0 */
	address = HTOBE32((uint32)(uintptr_t)dst);
	memcpy(out, &address, sizeof(address));
	out += 2;
	*out++ = HTOBE16(0x4eb9);
	address = HTOBE32((uint32)(uintptr_t)code);
	memcpy(out, &address, sizeof(address));
	g_videoDisplayListNext = out + 2;
}

typedef struct MonoSidebarHealth {
	uint16 *dst;
	uint16 pixels[7 * 8], masks[7 * 2];
} MonoSidebarHealth;

static void Sidebar_MonoHealth(const void *parameters)
{
	const MonoSidebarHealth *health = parameters;
	Video_Atari_MonoCompose(health->dst, VIDEO_ATARI_LIVE_STRIDE, NULL, 0, 32, 7,
		health->pixels, health->masks, 32, 7, 0, 0);
}

void Video_Atari_QueueSidebarHealth(uint16 *dst, uint16 width, uint8 foreground, uint8 background)
{
	uint32 patterns[4] = {0}, address, fill;
	uint16 *out, plane;

	assert(g_videoDisplayListActive && width <= 24 && foreground < 16 && background < 16);
	if (Video_Atari_Mono()) {
		MonoSidebarHealth *health = Video_Atari_QueueSidebarCPU(Sidebar_MonoHealth, sizeof(*health));
		uint16 row, group;
		uint32 logicalFill = width == 0 ? 0 : ((1UL << width) - 1) << (27 - width);
		health->dst = dst;
		for (row = 0; row < 7; row++) {
			for (group = 0; group < 2; group++) {
				uint16 words[4], fg[4], mask = group == 0 ? 0x07ff : 0xfff8;
				Video_Atari_MonoPenWords(background, group * 16 - 5, row, words);
				Video_Atari_MonoPenWords(foreground, group * 16 - 5, row, fg);
				Video_Atari_MonoMergeWords(words, fg, logicalFill >> (group == 0 ? 16 : 0));
				Video_Atari_MonoWriteGroup(health->pixels, 8, row, group, words);
				health->masks[row * 2 + group] = mask;
			}
		}
		return;
	}
	fill = ((1UL << width) - 1) << (27 - width);
	for (plane = 0; plane < 4; plane++) {
		const uint16 shift = (plane & 1) == 0 ? 16 : 0;
		const uint32 bits = ((foreground & (1 << plane)) ? fill : 0) |
		    ((background & (1 << plane)) ? 0x07fffff8UL & ~fill : 0);
		patterns[plane >> 1] |= (bits >> 16) << shift;
		patterns[2 + (plane >> 1)] |= (bits & 0xffff) << shift;
	}
	Video_Atari_DisplayListCheck(36);
	out = g_videoDisplayListNext;
	*out++ = HTOBE16(0x207c);
	address = HTOBE32((uint32)(uintptr_t)dst);
	memcpy(out, &address, sizeof(address));
	out += 2;
	for (plane = 0; plane < 4; plane++) {
		*out++ = HTOBE16(0x203c | (plane << 9));
		address = HTOBE32(patterns[plane]);
		memcpy(out, &address, sizeof(address));
		out += 2;
	}
	*out++ = HTOBE16(0x4eb9);
	address = HTOBE32((uint32)(uintptr_t)Video_Atari_SidebarHealthCode);
	memcpy(out, &address, sizeof(address));
	g_videoDisplayListNext = out + 2;
}

void *Video_Atari_QueueSidebarCPU(void (*code)(const void *), size_t bytes)
{
	uint16 *out, *data;
	uint32 address;
	size_t padded = (bytes + 1) & ~(size_t)1;

	assert(g_videoDisplayListActive && bytes <= INT16_MAX - 20);
	Video_Atari_DisplayListCheck(18 + padded);
	out = g_videoDisplayListNext;
	data = out + 9;
	*out++ = HTOBE16(0x2f3c); /* move.l #parameters,-(sp) */
	address = HTOBE32((uint32)(uintptr_t)data);
	memcpy(out, &address, sizeof(address));
	out += 2;
	*out++ = HTOBE16(0x4eb9);
	address = HTOBE32((uint32)(uintptr_t)code);
	memcpy(out, &address, sizeof(address));
	out += 2;
	*out++ = HTOBE16(0x588f); /* addq.l #4,sp */
	*out++ = HTOBE16(0x6000); /* Skip the immutable parameters on return. */
	*out++ = HTOBE16(2 + padded);
	if (padded != bytes) ((uint8 *)data)[bytes] = 0;
	g_videoDisplayListNext = data + padded / 2;
	return data;
}
