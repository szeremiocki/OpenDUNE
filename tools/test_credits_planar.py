"""Check extracted planar credits rows against an independent pixel compositor."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class CreditsPlanarTest(unittest.TestCase):
    def test_rows_and_masks(self):
        source = (ROOT / "src/gui/gui.c").read_text()
        start = source.index("enum {\n\tCREDITS_CACHE_WIDTH")
        declarations = source[start:source.index("\nvoid GUI_InitCreditsCache", start)]
        declarations = declarations.replace("static uint16 s_creditsPlanarDisplayX, s_creditsPlanarDisplayY;\n", "")
        functions = []
        for name in ("GUI_BuildCreditsPlanarCache", "GUI_DrawCreditsPlanarRows",
                     "GUI_ComposeCreditsPlanar", "GUI_PresentCreditsPlanar"):
            extracted = function(source, name)
            if name == "GUI_DrawCreditsPlanarRows":
                extracted = extracted.replace("\n{", "\n{\n    digitCalls[position]++;", 1)
            functions.append(extracted)
        video = (ROOT / "src/video/video_atari.c").read_text()
        functions = [function(video, name) for name in
                     ("Video_Atari_PresentRestore", "Video_Atari_PresentRestoreStrided")] + functions
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
#define lengthof(a) (sizeof(a) / sizeof((a)[0]))
static uint8 mapping[256];
static unsigned encodes;
static unsigned digitCalls[6], publications, publishedBytes;
enum { SCREEN_WIDTH = 320, SCREEN_HEIGHT = 200, ST_PLANAR_LINE_BYTES = 160 };
static uint8 screen[32000], savedScreen[32000];
static uint32 dirty[200];
static bool overlay;
static uint8 *Video_Atari_PlanarBase(void) { return screen; }
static void Video_Atari_PlanarFinishRun(uint8 *base, uint16 x, uint16 y,
                                      uint16 width, uint16 height) {
    assert(base == screen && !(x & 15) && !(width & 15) && width);
    assert(x + width <= 320 && y + height <= 200);
    publications++;
    publishedBytes += width * height / 2;
    /* Observable post-copy overlay hook, in the last credits group. */
    if (overlay && x <= 304 && x + width > 304 && y <= 4 && y + height > 4)
        base[4 * 160 + 152] = 0x5a;
}
static void GFX_Screen_ClearDirtyRect(uint16 left, uint16 top, uint16 right, uint16 bottom) {
    for (unsigned y = top; y < bottom; y++)
        for (unsigned group = left / 16; group < right / 16; group++)
            dirty[y] &= ~(1u << group);
}
static bool Video_Atari_PresentRestoreStrided(int16, int16, uint16, uint16, const uint8 *, uint16);
#define Warning(...) assert(false)
static void Video_Atari_EncodePlanar(const uint8 *src, uint16 *dst, uint16 width, uint16 height) {
    unsigned y, x, p;
    encodes++;
    memset(dst, 0, width * height / 2);
    for (y = 0; y < height; y++) {
        for (x = 0; x < width; x++) {
            uint8 pen = mapping[src[y * width + x]];
            for (p = 0; p < 4; p++) {
                if (pen & (1u << p))
                    dst[y * (width / 4) + (x / 16) * 4 + p] |= 0x8000u >> (x & 15);
            }
        }
    }
}
/* PRODUCTION */
static uint16 storage[148], expected[144];
static uint8 logical[64 * 9];
static void pixel_reference(unsigned pos, unsigned lower, unsigned higher, int phase) {
    unsigned y, x, left = pos * 10 + 4;
    for (y = 0; y < 9; y++) {
        unsigned row, glyph;
        if (lower == higher) {
            if (y == 0) continue;
            row = y - 1;
            glyph = lower;
        } else {
            int lowerTop = (phase > 0 ? 1 : -7) - phase;
            int r = (int)y - lowerTop;
            assert(r >= 0 && r < 16);
            glyph = r < 8 ? lower : higher;
            row = (unsigned)r & 7;
        }
        for (x = 0; x < 8; x++)
            logical[y * 64 + left + x] = ((const uint8 *)s_creditsGlyphs[glyph])[row * 8 + x];
    }
}
static void compose(unsigned pos, unsigned lower, unsigned higher, int phase) {
    uint16 *dst = storage + 2;
    if (lower == higher) {
        GUI_DrawCreditsPlanarRows(dst, pos, lower, 0, 1, 8);
    } else {
        unsigned start = (phase + 7) & 7, count = 8 - start;
        GUI_DrawCreditsPlanarRows(dst, pos, lower, start, 0, count);
        GUI_DrawCreditsPlanarRows(dst, pos, higher, 0, count, 9 - count);
    }
    pixel_reference(pos, lower, higher, phase);
}
static void check(void) {
    unsigned before = encodes;
    Video_Atari_EncodePlanar(logical, expected, 64, 9);
    assert(encodes == before + 1);
    assert(!memcmp(storage + 2, expected, sizeof(expected)));
    assert(storage[0] == 0x1234 && storage[1] == 0x5678);
    assert(storage[146] == 0xabcd && storage[147] == 0xef01);
}
static void reset(void) {
    memcpy(storage + 2, s_creditsPlanarBackground, sizeof(s_creditsPlanarBackground));
    memcpy(logical, s_creditsBackground, sizeof(logical));
}
static unsigned glyph_for(char ch) { return ch == ' ' ? 0 : ch - '0' + 1; }
static void frame(const char *old, const char *new, int phase, bool force,
                  unsigned expectedGroups, unsigned expectedDigits) {
    unsigned before = encodes, x, y, pos;
    uint16 retained[144];
    memcpy(retained, s_creditsPlanarDisplay, sizeof(retained));
    memset(digitCalls, 0, sizeof(digitCalls));
    uint16 groups = GUI_ComposeCreditsPlanar(old, new, phase, force);
    assert(groups == expectedGroups && encodes == before);
    memcpy(logical, s_creditsBackground, sizeof(logical));
    for (pos = 0; pos < 6; pos++) {
        assert(digitCalls[pos] == ((expectedDigits & (1u << pos)) ?
               (old[pos] == new[pos] ? 1u : 2u) : 0u));
        pixel_reference(pos, glyph_for(old[pos]), glyph_for(new[pos]), phase);
    }
    Video_Atari_EncodePlanar(logical, expected, 64, 9);
    assert(!memcmp(s_creditsPlanarDisplay, expected, sizeof(expected)));
    for (y = 0; y < 9; y++)
        for (x = 0; x < 4; x++)
            if (!(groups & (1u << x)))
                assert(!memcmp(retained + y * 16 + x * 4,
                               s_creditsPlanarDisplay + y * 16 + x * 4, 8));
    memcpy(savedScreen, screen, sizeof(screen));
    for (y = 0; y < 200; y++) dirty[y] = 0xfffff;
    publications = publishedBytes = 0;
    GUI_PresentCreditsPlanar(groups, 256, 4);
    unsigned count = 0, runs = 0;
    for (x = 0; x < 4; x++) {
        if (groups & (1u << x)) {
            count++;
            if (x == 0 || !(groups & (1u << (x - 1)))) runs++;
        }
    }
    assert(publications == runs && publishedBytes == count * 72);
    for (y = 0; y < 200; y++) {
        assert(dirty[y] == (y >= 4 && y < 13 ? 0xfffff & ~((uint32)groups << 16) : 0xfffff));
        for (x = 0; x < 160; x++) {
            uint8 value = savedScreen[y * 160 + x];
            if (y >= 4 && y < 13 && x >= 128 && (groups & (1u << ((x - 128) / 8))))
                value = ((const uint8 *)s_creditsPlanarDisplay)[(y - 4) * 32 + x - 128];
            assert(screen[y * 160 + x] == value);
        }
    }
}
static void incremental(void) {
    memset(screen, 0xa5, sizeof(screen));
    frame(" 12345", " 12345", 0, true, 15, 63);
    frame(" 12346", " 12346", 0, false, 8, 32);
    frame(" 12346", " 12346", 3, false, 0, 0);
    for (int phase = 1; phase <= 7; phase++)
        frame(" 12346", " 12347", phase, false, 8, 32);
    frame(" 12347", " 12347", 0, false, 8, 32);
    for (int phase = -1; phase >= -7; phase--)
        frame(" 12346", " 12347", phase, false, 8, 32);
    frame(" 12346", " 12346", 0, false, 8, 32);
    /* Offset changes redraw rolling digits only; shared-group neighbors survive. */
    frame("    19", "    20", 0, true, 15, 63);
    for (int phase = 1; phase <= 7; phase++)
        frame("    19", "    20", phase, false, 12, 48);
    frame("    20", "    20", 0, false, 12, 48);
    for (int phase = -1; phase >= -7; phase--)
        frame("    19", "    20", phase, false, 12, 48);
    frame("    19", "    19", 0, false, 12, 48);
    frame(" 49999", " 49999", 0, true, 15, 63);
    frame(" 49999", " 59999", 1, false, 3, 2);
    frame(" 49999", " 59999", -1, false, 3, 2);
    frame(" 49999", " 49999", 0, false, 3, 2);
    frame("   999", "   999", 0, true, 15, 63);
    frame("   999", "  1000", 1, false, 14, 60);
    frame("   999", "  1000", -7, false, 14, 60);
    frame("   999", "   999", 0, false, 14, 60);
    frame("  9999", "  9999", 0, true, 15, 63);
    frame("  9999", " 10000", 1, false, 15, 62);
    frame(" 10000", " 10000", 0, false, 15, 62);
    frame(" 11001", " 11001", 0, false, 10, 36);
    assert(publications == 2);
    frame(" 11001", " 11001", 0, true, 15, 63);
    s_creditsPlanarDisplayReady = false; /* Re-entry after invalidation/fallback. */
    frame(" 11001", " 11001", 0, false, 15, 63);
    GUI_BuildCreditsPlanarCache(s_creditsPlanarPaletteGeneration);
    frame(" 11001", " 11001", 0, false, 15, 63);
}
static void publisher_contract(void) {
    uint8 packed[16];
    memset(packed, 0x33, sizeof(packed));
    publications = 0;
    assert(Video_Atari_PresentRestore(304, 4, 16, 2, packed));
    assert(publications == 1);
    assert(!memcmp(screen + 4 * 160 + 152, packed, 8));
    assert(!memcmp(screen + 5 * 160 + 152, packed + 8, 8));
    assert(Video_Atari_PresentRestore(305, 4, 1, 2, packed));
    assert(Video_Atari_PresentRestoreStrided(304, 4, UINT16_MAX, 1, packed, 8));
    /* Partial restore must invoke the same post-copy overlay hook. */
    overlay = true;
    assert(Video_Atari_PresentRestoreStrided(304, 4, 16, 1, packed, 32));
    assert(screen[4 * 160 + 152] == 0x5a);
    overlay = false;
    unsigned before = publications;
    memcpy(savedScreen, screen, sizeof(screen));
    assert(!Video_Atari_PresentRestoreStrided(304, 4, 16, 2, packed, 7));
    assert(!Video_Atari_PresentRestoreStrided(320, 4, 16, 2, packed, 32));
    assert(!Video_Atari_PresentRestoreStrided(-1, 4, 16, 2, packed, 32));
    assert(!Video_Atari_PresentRestoreStrided(304, 199, 16, 2, packed, 32));
    assert(!Video_Atari_PresentRestoreStrided(304, 4, 0, 2, packed, 32));
    assert(!Video_Atari_PresentRestoreStrided(304, 4, 16, 0, packed, 32));
    assert(!Video_Atari_PresentRestoreStrided(304, 4, 16, 2, NULL, 32));
    assert(publications == before && !memcmp(savedScreen, screen, sizeof(screen)));
}
int main(void) {
    unsigned pass, i, glyph, pos, low, high;
    int phase;
    s_creditsCacheReady = true;
    storage[0] = 0x1234; storage[1] = 0x5678;
    storage[146] = 0xabcd; storage[147] = 0xef01;
    for (i = 0; i < sizeof(s_creditsBackground); i++)
        ((uint8 *)s_creditsBackground)[i] = 1 + (i * 17) % 255;
    for (glyph = 0; glyph < 11; glyph++)
        for (i = 0; i < 64; i++) ((uint8 *)s_creditsGlyphs[glyph])[i] = 1 + (glyph * 43 + i * 7) % 255;
    for (pass = 0; pass < 3; pass++) {
        for (i = 0; i < 256; i++) mapping[i] = (i * (pass * 2 + 1) + pass * 3) & 15;
        encodes = 0;
        GUI_BuildCreditsPlanarCache(pass);
        assert(s_creditsCacheReady && s_creditsPlanarReady);
        assert(s_creditsPlanarPaletteGeneration == pass && encodes == 12);
        for (pos = 0; pos < 6; pos++)
            for (low = 0; low < 11; low++)
                for (high = 0; high < 11; high++)
                    for (phase = -7; phase <= 7; phase++) {
                        unsigned before;
                        if (phase == 0 && low != high) continue;
                        reset();
                        before = encodes;
                        compose(pos, low, high, phase);
                        assert(encodes == before);
                        check();
                    }
        for (phase = -7; phase <= 7; phase++) {
            reset();
            for (pos = 0; pos < 6; pos++) {
                low = pos == 0 ? 0 : 10;
                high = phase == 0 ? low : 1;
                compose(pos, low, high, phase);
            }
            check();
        }
        incremental();
    }
    publisher_contract();
    return 0;
}
"""
        harness = harness.replace("/* PRODUCTION */", declarations + "\n\n" + "\n\n".join(functions))
        with tempfile.TemporaryDirectory(prefix="credits-planar-") as directory:
            test = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            test.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(test), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
