"""Exercise overlap-safe scrolling and its one-shot display-list barrier."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class PlanarScrollTest(unittest.TestCase):
    def test_retained_rectangle_copy_and_one_shot_barrier(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        production = "\n".join(function(video, name) for name in (
            "Video_Atari_BlitterStart", "Video_Atari_CompleteScroll", "Video_Atari_FinishScroll",
            "Video_Atari_BlitterSetup", "Video_Atari_BlitScroll",
            "Video_Atari_ShiftPlanar", "Video_Atari_DisplayExecute",
            "Video_Atari_ExecuteDisplayList", "Video_Atari_PlanarCopyGroup",
            "Video_Atari_PlanarMergePlain", "Video_Atari_PublishPlanarSpritePlain"))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "src/video/video.h"
#include "src/os/endian.h"
enum { SCREEN_WIDTH = 320, SCREEN_HEIGHT = 200, ST_PLANAR_LINE_BYTES = 160 };
enum { MCH_ST, MCH_STE, MCH_MEGA_STE, MCH_TT, MCH_FALCON };
static union { uint32 aligned; uint8 bytes[32000 + 512]; } screen;
static uint8 before[sizeof(screen.bytes)], expected[sizeof(screen.bytes)];
static uint8 *base;
#define s_planarBase base
static bool s_blitterDestinationWord;
static uint16 destinationHigh;
static int s_machine_type;
bool g_videoViewportBlitter, g_videoScrollPending;
bool g_videoAtariMono;
#define s_viewportBlitter g_videoViewportBlitter
static bool s_blitterTileSetup, s_placeVisible, s_curVisible;
static const uint16 *s_displayStream;
void (*g_videoTileCursorTail)(void);
static struct {
    const uint16 *pixels;
    uint16 *dst;
    const Video_Atari_SpriteBlitPlan *plan;
    uint16 height;
} s_planarBlit;
static struct {
    int16 sx, sy, dx, dy;
    uint16 first, middle, last, words, rows;
    uint32 source, destination;
    uint8 hop, op, skew, control;
} registers;
static unsigned launches, promotions, moves, supervisorCalls, placementCalls, cursorSyncs;
static unsigned executions, processed;
static unsigned takeoverPolls;
static bool erased, completed, originalPlacement, originalCursor, started;
static uint32 sourceLatch = 0xa39fbc71;
static bool prefetched;
static uint16 expectedRows, expectedWords, physicalStride;
static int direction;
static uint8 *sourceStart, *destinationStart;
static uintptr_t readPointer, writePointer;
static void advance(unsigned count);

static volatile uint8 *control(void) {
    if (registers.control & 0x80) {
        if (!started) {
            assert(registers.control == 0x80 && g_videoScrollPending);
            assert(erased && placementCalls >= 1);
            assert(!s_blitterTileSetup && launches == 0 && moves == 0);
            assert(registers.hop == 2 && registers.op == 3 && (registers.skew & 15) == 0);
            assert(registers.first == 0xffff && registers.middle == 0xffff &&
                   registers.last == 0xffff);
            assert(registers.words == expectedWords && registers.rows == expectedRows);
            assert(registers.sx == direction * 2 && registers.dx == direction * 2);
            assert(registers.sy == direction * (physicalStride - (expectedWords - 1) * 2));
            assert(registers.dy == registers.sy);
            uint32 last = direction < 0 ?
                (uint32)(expectedRows - 1) * physicalStride + (expectedWords - 1) * 2 : 0;
            readPointer = (uintptr_t)(sourceStart + last);
            writePointer = (uintptr_t)(destinationStart + last);
            assert((uintptr_t)s_planarBlit.pixels == readPointer);
            assert((uintptr_t)s_planarBlit.dst == writePointer);
            assert(registers.source == (uint32)readPointer);
            assert(registers.destination == (uint32)writePointer);
            started = true;
            launches++;
        } else if (registers.control == 0xc0) {
            assert(g_videoScrollPending);
            if (completed) {
                registers.control = 0;
                return &registers.control;
            }
            if (takeoverPolls++ < 2) return &registers.control;
            assert(promotions++ == 0);
            /* Promotion must keep the partially consumed addresses/counts. */
            assert(registers.source == (uint32)readPointer);
            assert(registers.destination == (uint32)writePointer);
            assert(registers.rows == expectedRows - processed / expectedWords);
            assert(registers.words == expectedWords - processed % expectedWords);
            advance(expectedRows * expectedWords);
        }
    }
    return &registers.control;
}
static void fetch_source(void) {
    unsigned row = processed / expectedWords;
    if (direction < 0) row = expectedRows - row - 1;
    uintptr_t rowStart = (uintptr_t)(sourceStart + row * physicalStride);
    uint16 value;
    assert(readPointer >= rowStart && readPointer + 2 <= rowStart + expectedWords * 2);
    memcpy(&value, (const void *)readPointer, 2);
    sourceLatch = registers.sx < 0 ? (sourceLatch >> 16) | ((uint32)value << 16) :
                                    (sourceLatch << 16) | value;
}
static void advance(unsigned count) {
    assert(started && !completed);
    for (unsigned i = 0; i < count && !completed; i++) {
        unsigned word = processed % expectedWords;
        if (word == 0 && !prefetched && (registers.skew & 0x80)) {
            fetch_source();
            readPointer += registers.sx;
            prefetched = true;
        }
        bool suppress = (registers.skew & 0x40) && word + 1 == expectedWords;
        if (suppress) {
            uint16 old;
            memcpy(&old, (const void *)writePointer, 2);
            sourceLatch = registers.sx < 0 ? (sourceLatch >> 16) | ((uint32)old << 16) :
                                            (sourceLatch << 16) | old;
        } else {
            fetch_source();
        }
        uint16 value;
        value = sourceLatch >> (registers.skew & 15);
        memcpy((void *)writePointer, &value, 2);
        if (suppress) {
            sourceLatch = registers.sx < 0 ? (sourceLatch >> 16) | ((uint32)value << 16) :
                                            (sourceLatch << 16) | value;
        } else {
            readPointer += word + 1 == expectedWords ||
                ((registers.skew & 0x40) && word + 2 == expectedWords) ?
                registers.sy : registers.sx;
        }
        writePointer += word + 1 == expectedWords ? registers.dy : registers.dx;
        processed++;
        if (processed % expectedWords == 0) prefetched = false;
        registers.rows = expectedRows - processed / expectedWords;
        registers.words = expectedWords - processed % expectedWords;
        if (processed == expectedRows * expectedWords) {
            registers.control = 0;
            completed = true;
        } else {
            registers.source = (uint32)readPointer;
            registers.destination = (uint32)writePointer;
        }
    }
}
#define BLITTER_CTRL (control())
#define BLITTER_SRC_XINC (&registers.sx)
#define BLITTER_SRC_YINC (&registers.sy)
#define BLITTER_DST_XINC (&registers.dx)
#define BLITTER_DST_YINC (&registers.dy)
#define BLITTER_ENDMASK1 (&registers.first)
#define BLITTER_ENDMASK2 (&registers.middle)
#define BLITTER_ENDMASK3 (&registers.last)
#define BLITTER_SRC_ADDR (&registers.source)
#define BLITTER_DST_ADDR (&registers.destination)
#define BLITTER_DST_ADDR_HIGH (&destinationHigh)
#define BLITTER_XCOUNT (&registers.words)
#define BLITTER_YCOUNT (&registers.rows)
#define BLITTER_HOP (&registers.hop)
#define BLITTER_OP (&registers.op)
#define BLITTER_SKEW (&registers.skew)
static void Atari_SupervisorExec(void (*callback)(void)) {
    supervisorCalls++;
    callback();
}
static uint8 *Video_Atari_PlanarBase(void) { return base; }
static void Video_Atari_CursorEraseFull(void) {
    Video_Atari_DisplayListFlush();
    erased = true;
}
static void Video_Atari_PlacementEnd(uint8 *pixels) {
    Video_Atari_DisplayListFlush();
    assert(pixels == base && erased);
    if (placementCalls++ == 0) assert(!s_placeVisible);
    else {
        assert(completed && s_placeVisible == originalPlacement);
        assert(placementCalls == 2 && originalPlacement);
    }
}
static void *counted_memmove(void *dst, const void *src, size_t bytes) {
    assert(!s_viewportBlitter && erased && placementCalls == 1);
    moves++;
    assert(moves <= expectedRows && bytes == expectedWords * 2u);
    void *result = memmove(dst, src, bytes);
    completed = moves == expectedRows;
    return result;
}
static void Video_Atari_CursorSync(uint8 *pixels) {
    Video_Atari_DisplayListFlush();
    assert(pixels == base && completed && placementCalls == 1u + originalPlacement);
    cursorSyncs++;
}
void Video_Atari_RestoreTileCursor(void) { assert(!g_videoScrollPending); }
uint16 endian_bswap16(uint16 value) { return __builtin_bswap16(value); }
uint32 endian_bswap32(uint32 value) { return __builtin_bswap32(value); }
void Error(const char *fmt, ...) { (void)fmt; abort(); }
static void Video_Atari_RunDisplayList(const uint16 *stream) {
    assert(!g_videoScrollPending && completed && !g_videoDisplayListActive);
    assert(*stream++ == HTOBE16(0x4e71));
    assert(*stream == HTOBE16(0x4e75));
    executions++;
}
#define memmove counted_memmove
/* PRODUCTION */
#undef memmove
#include "src/video/atari_display_list.c"
static void append(void) {
    *g_videoDisplayListNext++ = HTOBE16(0x4e71);
}
static void reset(unsigned offset) {
    assert(!g_videoScrollPending && !g_videoDisplayListActive);
    for (unsigned i = 0; i < sizeof(screen.bytes); i++)
        screen.bytes[i] = (uint8)((i * 73 + (i >> 7) * 19) ^ (i >> 3));
    memcpy(before, screen.bytes, sizeof(before));
    memcpy(expected, before, sizeof(expected));
    base = screen.bytes + offset;
    memset(&registers, 0xa5, sizeof(registers));
    registers.control = 0;
    destinationHigh = 0xdead;
    launches = promotions = moves = supervisorCalls = placementCalls = cursorSyncs = 0;
    executions = processed = takeoverPolls = 0;
    erased = completed = started = prefetched = false;
    s_blitterTileSetup = true;
    s_placeVisible = originalPlacement;
    s_curVisible = originalCursor;
}
static void prepare(unsigned offset, int x, int y, int w, int h, int dx, int dy) {
    reset(offset);
    unsigned divisor = g_videoAtariMono ? 4 : 2;
    physicalStride = g_videoAtariMono ? 80 : 160;
    sourceStart = base + y * 160 + x / divisor;
    destinationStart = base + (y + dy) * 160 + (x + dx) / divisor;
    expectedRows = g_videoAtariMono ? h * 2 : h;
    expectedWords = w / divisor / 2;
    direction = destinationStart > sourceStart ? -1 : 1;
    for (unsigned row = 0; row < expectedRows; row++)
        memcpy(expected + offset + (y + dy) * 160 + row * physicalStride + (x + dx) / divisor,
               before + offset + y * 160 + row * physicalStride + x / divisor, w / divisor);
}
static void check(unsigned offset, int x, int y, int w, int h, int dx, int dy) {
    prepare(offset, x, y, w, h, dx, dy);
    assert(Video_Atari_ShiftPlanar(x, y, w, h, dx, dy));
    if (s_viewportBlitter && !originalPlacement && !originalCursor) {
        assert(g_videoScrollPending && !completed && supervisorCalls == 1);
        control();
        Video_Atari_DisplayListBegin();
        append();
        assert(!executions && !promotions && g_videoScrollPending);
        advance(1 + expectedWords / 2);
        /* An early eviction or capacity flush completes the remaining copy. */
        Video_Atari_DisplayListFlush();
        assert(executions == 1 && !g_videoScrollPending && completed);
        unsigned calls = supervisorCalls;
        append();
        Video_Atari_DisplayListEnd();
        assert(executions == 2 && supervisorCalls == calls + 1);
    } else {
        assert(!g_videoScrollPending && completed);
    }
    assert(!memcmp(screen.bytes, expected, sizeof(expected)));
    assert(placementCalls == 1u + originalPlacement && cursorSyncs == originalCursor);
    assert(s_placeVisible == originalPlacement);
    assert(launches == (unsigned)s_viewportBlitter);
    assert(moves == (s_viewportBlitter ? 0u : expectedRows));
    assert(s_blitterTileSetup == !s_viewportBlitter);
}
static void check_barriers(void) {
    s_viewportBlitter = true;
    originalPlacement = originalCursor = false;
    s_machine_type = MCH_STE;
    for (unsigned wordOnly = 0; wordOnly < 2; wordOnly++)
    for (unsigned reverse = 0; reverse < 2; reverse++)
    for (unsigned scenario = 0; scenario < 6; scenario++) {
        s_blitterDestinationWord = wordOnly;
        int x = reverse ? 0 : 16, dx = reverse ? 16 : -16;
        prepare(0, x, 40, 224, 160, dx, 0);
        assert(Video_Atari_ShiftPlanar(x, 40, 224, 160, dx, 0));
        assert(g_videoScrollPending && !completed);
        control();
        advance(5);
        /* Construction can reuse the C argument scratch after launch. */
        assert(s_planarBlit.plan == NULL);
        s_planarBlit.pixels = NULL;
        s_planarBlit.dst = NULL;
        s_planarBlit.height = 0;
        if (scenario == 0) advance(expectedRows * expectedWords);
        if (scenario <= 2 || scenario == 4) Video_Atari_DisplayListBegin();
        if (scenario <= 1) {
            append();
            assert(g_videoScrollPending && !executions);
            Video_Atari_DisplayListEnd();
            assert(executions == 1);
        } else if (scenario <= 3) {
            /* CPU publication must wait even with an empty/inactive list. */
            uint16 pixels[4] = {0x1234, 0x5678, 0x9abc, 0xdef0}, mask = 0x0ff0;
            Video_Atari_PublishPlanarSpritePlain((uint16 *)(base + 40 * 160),
                                               pixels, &mask, 1, 1, 1);
            for (unsigned plane = 0; plane < 4; plane++) {
                uint16 value;
                memcpy(&value, expected + 40 * 160 + plane * 2, 2);
                value = (value & (uint16)~mask) | (pixels[plane] & mask);
                memcpy(expected + 40 * 160 + plane * 2, &value, 2);
            }
            assert(!executions);
            Video_Atari_DisplayListEnd();
        } else if (scenario == 4) {
            Video_Atari_DisplayListEnd();
            assert(!executions);
        } else {
            uint16 stream[2] = {HTOBE16(0x4e71), HTOBE16(0x4e75)};
            Video_Atari_ExecuteDisplayList(stream);
            assert(executions == 1);
        }
        assert(completed && !g_videoScrollPending && launches == 1);
        assert(destinationHigh == (wordOnly ? ((uint32)(size_t)base >> 16) : 0xdead));
        assert(promotions == (scenario == 0 ? 0u : 1u));
        assert(takeoverPolls == (scenario == 0 ? 0u : 3u));
        assert(!memcmp(screen.bytes, expected, sizeof(expected)));
        unsigned calls = supervisorCalls;
        Video_Atari_DisplayListFlush();
        Video_Atari_DisplayListFlush();
        assert(supervisorCalls == calls);
    }
    s_blitterDestinationWord = false;
}
int main(void) {
    for (unsigned mono = 0; mono < 2; mono++)
    for (unsigned mode = 0; mode < 2; mode++)
    for (unsigned offset = 0; offset <= 256; offset += 256)
    for (unsigned overlays = 0; overlays < 4; overlays++) {
        g_videoAtariMono = mono;
        s_viewportBlitter = mode;
        originalPlacement = overlays & 1;
        originalCursor = overlays & 2;
        s_machine_type = originalPlacement ? MCH_ST : MCH_STE;
        for (int dx = -224; dx <= 224; dx += 16)
        for (int dy = -144; dy <= 144; dy += 16) {
            if (!dx && !dy) continue;
            check(offset, dx < 0 ? -dx : 0, 40 + (dy < 0 ? -dy : 0),
                  240 - abs(dx), 160 - abs(dy), dx, dy);
        }
        s_machine_type = MCH_MEGA_STE;
        check(offset, 16, 0, 304, 199, -16, 1);
        check(offset, 0, 1, 304, 199, 16, -1);
        check(offset, 0, 0, 16, 1, 16, 199);
        check(offset, 16, 199, 16, 1, -16, -199);
        reset(offset);
        assert(Video_Atari_ShiftPlanar(0, 40, 240, 160, 0, 0));
        assert(!Video_Atari_ShiftPlanar(1, 40, 224, 160, 16, 0));
        assert(!Video_Atari_ShiftPlanar(0, 40, 240, 160, -16, 0));
        assert(!Video_Atari_ShiftPlanar(0, 40, 240, 160, 0, 1));
        assert(!Video_Atari_ShiftPlanar(0, 40, 0, 160, 16, 0));
        assert(!Video_Atari_ShiftPlanar(0, 40, 240, 0, 16, 0));
        s_machine_type = MCH_TT;
        assert(!Video_Atari_ShiftPlanar(0, 40, 224, 160, 16, 0));
        s_machine_type = MCH_FALCON;
        assert(!Video_Atari_ShiftPlanar(0, 40, 224, 160, 16, 0));
        assert(!erased && !launches && !moves && !placementCalls && !supervisorCalls);
        assert(!memcmp(screen.bytes, before, sizeof(before)));
    }
    g_videoAtariMono = false;
    check_barriers();
    Video_Atari_DisplayListFree();
    return 0;
}
"""
        harness = harness.replace("/* PRODUCTION */", production)
        with tempfile.TemporaryDirectory(prefix="planar-scroll-") as directory:
            source = Path(directory) / "scroll.c"
            binary = Path(directory) / "scroll"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("HOST_CC", "cc"))
            subprocess.run(
                compiler + ["-std=c17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                            "-DTOS", "-I" + str(ROOT), "-I" + str(ROOT / "include"),
                            "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
