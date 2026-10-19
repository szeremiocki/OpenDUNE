"""Check integer direction classification against the original division/scan."""

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TileDirectionTest(unittest.TestCase):
    def test_multiply_tree_equivalence(self):
        source = (ROOT / "src/tile.c").read_text()
        start = source.index("int8 Tile_GetDirection(tile32 from, tile32 to)")
        end = source.index("\n}\n", start) + 3
        production = source[start:end]
        scan_start = production.index("\ti = 0;")
        scan_end = production.index("\n\tif (!invert)", scan_start)
        scan = production[scan_start:scan_end]
        table = re.search(r"static const uint16 directions\[\] = \{.*?\n\t\};",
                          production, re.S).group()
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
typedef int8_t int8;
typedef int16_t int16;
typedef int32_t int32;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef struct { uint16 x, y; } tile32;
#define lengthof(array) (sizeof(array) / sizeof((array)[0]))
/* FUNCTIONS */
static uint16 tree_index(uint16 major, uint16 minor) {
    /* TABLE */
    const uint32 scaledMajor = (uint32)major << 8;
    uint16 i;
    /* SCAN */
    return i;
}
static const int32 originalDirections[] = {
    0x3FFF, 0x28BC, 0x145A, 0xD8E, 0xA27, 0x81B, 0x6BD, 0x5C3,
    0x506, 0x474, 0x3FE, 0x39D, 0x34B, 0x306, 0x2CB, 0x297,
    0x26A, 0x241, 0x21D, 0x1FC, 0x1DE, 0x1C3, 0x1AB, 0x194,
    0x17F, 0x16B, 0x159, 0x148, 0x137, 0x128, 0x11A, 0x10C
};
static uint16 reference_index(uint16 major, uint16 minor) {
    int32 gradient = minor == 0 ? 0x7fff : ((int32)major << 8) / minor;
    uint16 i;
    for (i = 0; i < lengthof(originalDirections); i++)
        if (originalDirections[i] <= gradient) break;
    return i;
}
static int8 reference_direction(tile32 from, tile32 to) {
    static const uint16 offsets[] = {0x40, 0x80, 0, 0xc0};
    int32 dx = to.x - from.x, dy = to.y - from.y;
    if (abs(dx) + abs(dy) > 8000) {
        dx /= 2;
        dy /= 2;
    }
    uint16 quadrant = 0;
    if (dy <= 0) { quadrant |= 2; dy = -dy; }
    if (dx < 0) { quadrant |= 1; dx = -dx; }
    bool invert = dx < dy;
    uint16 i = reference_index(invert ? dy : dx, invert ? dx : dy);
    if (!invert) i = 64 - i;
    if (quadrant == 0 || quadrant == 3) return (offsets[quadrant] + 64 - i) & 255;
    return (offsets[quadrant] + i) & 255;
}
static void check(tile32 from, tile32 to) {
    assert(Tile_GetDirection(from, to) == reference_direction(from, to));
}
int main(void) {
    for (unsigned major = 0; major <= 511; major++)
        for (unsigned minor = 0; minor <= major; minor++)
            assert(tree_index(major, minor) == reference_index(major, minor));
    /* Check both sides and equality at every reachable threshold boundary
     * for every minor magnitude possible after the original halving. */
    for (unsigned minor = 1; minor <= 32767; minor++) {
        for (unsigned i = 0; i < lengthof(originalDirections); i++) {
            uint32 boundary = (uint32)minor * originalDirections[i] / 256;
            for (int offset = -1; offset <= 1; offset++) {
                int32 major = (int32)boundary + offset;
                if (major < (int32)minor || major > 32767) continue;
                assert(tree_index(major, minor) == reference_index(major, minor));
            }
        }
        assert(tree_index(minor, minor) == reference_index(minor, minor));
        assert(tree_index(32767, minor) == reference_index(32767, minor));
        assert(tree_index(minor, 0) == 0);
    }
    tile32 centre = {32768, 32768};
    const int compass[8][2] = {
        {0, -256}, {256, -256}, {256, 0}, {256, 256},
        {0, 256}, {-256, 256}, {-256, 0}, {-256, -256}
    };
    for (unsigned i = 0; i < 8; i++)
        assert((uint8_t)Tile_GetDirection(centre,
            (tile32){centre.x + compass[i][0], centre.y + compass[i][1]}) == i * 32);
    assert(Tile_GetDirection(centre, centre) == 64);
    for (int dx = -256; dx <= 256; dx++) for (int dy = -256; dy <= 256; dy++)
        check(centre, (tile32){centre.x + dx, centre.y + dy});
    const int distances[] = {0, 1, 2, 15, 16, 255, 256, 3999, 4000,
                             4001, 7999, 8000, 8001, 16383, 16384, 32767};
    for (unsigned x = 0; x < lengthof(distances); x++)
        for (unsigned y = 0; y < lengthof(distances); y++)
            for (unsigned quadrant = 0; quadrant < 4; quadrant++) {
                int dx = quadrant & 1 ? -distances[x] : distances[x];
                int dy = quadrant & 2 ? -distances[y] : distances[y];
                check(centre, (tile32){centre.x + dx, centre.y + dy});
            }
    /* Halving can discard an odd component or turn it into zero. */
    for (int dx = 0; dx <= 8001; dx++)
        for (int sum = 7999; sum <= 8001; sum++)
            for (unsigned quadrant = 0; quadrant < 4; quadrant++) {
                int dy = sum - dx;
                int x = quadrant & 1 ? -dx : dx;
                int y = quadrant & 2 ? -dy : dy;
                check(centre, (tile32){centre.x + x, centre.y + y});
            }
    /* Exercise the full unsigned-coordinate range and varied gradients. */
    uint32_t state = 0x12345678;
    for (unsigned i = 0; i < 1000000; i++) {
        tile32 points[2];
        for (unsigned p = 0; p < 2; p++) {
            state = state * 1664525u + 1013904223u;
            points[p].x = state >> 16;
            state = state * 1664525u + 1013904223u;
            points[p].y = state >> 16;
        }
        check(points[0], points[1]);
        for (unsigned p = 0; p < 2; p++) {
            points[p].x &= 0x3fff;
            points[p].y &= 0x3fff;
        }
        check(points[0], points[1]);
    }
    return 0;
}
"""
        harness = harness.replace("/* FUNCTIONS */", production)
        harness = harness.replace("/* TABLE */", table)
        harness = harness.replace("/* SCAN */", scan)
        with tempfile.TemporaryDirectory(prefix="tile-direction-") as directory:
            c_file = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            c_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", str(c_file), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_68000_native_multiply(self):
        compiler = shutil.which("m68k-atari-mint-gcc")
        if compiler is None:
            self.skipTest("Atari cross-compiler unavailable")
        source = (ROOT / "src/tile.c").read_text()
        start = source.index("int8 Tile_GetDirection(tile32 from, tile32 to)")
        end = source.index("\n}\n", start) + 3
        production = source[start:end]
        harness = """
#include <stdbool.h>
#include <stdlib.h>
typedef signed char int8;
typedef unsigned short uint16;
typedef signed int int32;
typedef unsigned int uint32;
typedef struct { uint16 x, y; } tile32;
""" + production
        with tempfile.TemporaryDirectory(prefix="tile-direction-68000-") as directory:
            c_file = Path(directory) / "test.c"
            assembly = Path(directory) / "test.s"
            c_file.write_text(harness)
            subprocess.run([compiler, "-m68000", "-msoft-float", "-Ofast",
                            "-fno-split-paths", "-fomit-frame-pointer",
                            "-std=gnu17", "-S", str(c_file), "-o", str(assembly)],
                           check=True)
            generated = assembly.read_text()
            self.assertRegex(generated, r"\bmulu(?:\.w|w)?\b")
            self.assertNotRegex(generated, r"\b(?:jbsr|jsr|bsr|divu\w*|divs\w*)\b")
            self.assertNotRegex(generated, r"__(?:u?div|mul|u?mod)si3")


if __name__ == "__main__":
    unittest.main()
