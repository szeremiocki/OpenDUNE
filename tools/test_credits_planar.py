"""Check extracted planar credits rows against an independent pixel compositor."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CreditsPlanarTest(unittest.TestCase):
    def test_rows_and_masks(self):
        source = (ROOT / "src/gui/gui.c").read_text()
        start = source.index("enum {\n\tCREDITS_CACHE_WIDTH")
        declarations = source[start:source.index("\nvoid GUI_InitCreditsCache", start)]
        functions = []
        for name in ("GUI_BuildCreditsPlanarCache", "GUI_DrawCreditsPlanarRows"):
            start = source.index("static void " + name + "(")
            functions.append(source[start:source.index("\n}", start) + 2])
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
#define lengthof(a) (sizeof(a) / sizeof((a)[0]))
static uint8 mapping[256];
static unsigned encodes;
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
    }
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
