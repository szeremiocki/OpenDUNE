"""Check countdown direction scanning against the original linear loop."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TileDirectionTest(unittest.TestCase):
    def test_countdown_equivalence(self):
        source = (ROOT / "src/tile.c").read_text()
        start = source.index("int8 Tile_GetDirection(tile32 from, tile32 to)")
        end = source.index("\n}\n", start) + 3
        production = source[start:end]
        scan_start = production.index("\tconst int32 *p = directions;")
        scan_end = production.index("\n\tif (!invert)", scan_start)
        scan = production[scan_start:scan_end]
        original_scan = """
    for (i = 0; i < lengthof(directions); i++) {
        if (directions[i] <= gradient) break;
    }
"""
        reference = production.replace("Tile_GetDirection(", "reference_direction(", 1)
        reference = reference.replace(scan, original_scan)
        table = re.search(r"static const int32 directions\[\] = \{.*?\n\t\};",
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
typedef struct { uint16 x, y; } tile32;
#define lengthof(array) (sizeof(array) / sizeof((array)[0]))
/* FUNCTIONS */
static uint16 scan_direction(int32 gradient) {
    /* TABLE */
    uint16 i;
    /* SCAN */
    return i;
}
static uint16 reference_scan(int32 gradient) {
    /* TABLE */
    uint16 i;
    /* ORIGINAL SCAN */
    return i;
}
static void check(tile32 from, tile32 to) {
    assert(Tile_GetDirection(from, to) == reference_direction(from, to));
}
int main(void) {
    for (int32 gradient = -1; gradient <= 65536; gradient++)
        assert(scan_direction(gradient) == reference_scan(gradient));
    assert(scan_direction(INT32_MAX) == 0);
    assert(scan_direction(INT32_MIN) == 32);
    assert(scan_direction(0x3fff) == 0);
    assert(scan_direction(0x10c) == 31);
    assert(scan_direction(0x10b) == 32);
    tile32 centre = {32768, 32768};
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
    /* Exercise the full unsigned-coordinate range and varied gradients. */
    uint32_t state = 0x12345678;
    for (unsigned i = 0; i < 100000; i++) {
        tile32 points[2];
        for (unsigned p = 0; p < 2; p++) {
            state = state * 1664525u + 1013904223u;
            points[p].x = state >> 16;
            state = state * 1664525u + 1013904223u;
            points[p].y = state >> 16;
        }
        check(points[0], points[1]);
    }
    return 0;
}
"""
        harness = harness.replace("/* FUNCTIONS */", production + "\n" + reference)
        harness = harness.replace("/* TABLE */", table)
        harness = harness.replace("/* SCAN */", scan)
        harness = harness.replace("/* ORIGINAL SCAN */", original_scan)
        with tempfile.TemporaryDirectory(prefix="tile-direction-") as directory:
            c_file = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            c_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", str(c_file), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
