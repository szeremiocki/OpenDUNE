"""Focused tests for the monochrome palette/asset proposal generator."""

import itertools
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from tools.preview_mono_palette import (
    ROOT, build_data, closest_pen, decode_tiles, pack_pattern, quadrant, read_st_palette,
    render_dither_header, render_header,
)


class MonoPaletteTest(unittest.TestCase):
    def test_only_active_catalogue_is_read(self):
        palette = ",".join(f"MAKE_PC_COLOR({i * 16},0,0)" for i in range(16))
        source = "const uint8 s_palette4BitPC[16*4] = {" + palette
        source += "/* MAKE_PC_COLOR(255,255,255) */};"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "palette.c"
            path.write_text(source)
            self.assertEqual(read_st_palette(path), [(i * 16, 0, 0) for i in range(16)])

    def test_lookup_matches_actual_c_matcher(self):
        colours = read_st_palette(ROOT / "src/video/video_atari.c")
        values = (0, 3, 4, 7, 8, 31, 32, 63)
        samples = list(itertools.product(values, repeat=3))
        samples += [(i % 64, (i // 4) % 64, 63 - i % 64) for i in range(256)]
        source = (ROOT / "src/video/video_atari.c").read_text()
        matcher = source[source.index("static inline uint8 Palette_FindClosestColor("):]
        matcher = matcher.split("\n}\n", 1)[0] + "\n}\n"
        catalogue = ",".join(str(c >> 2) for rgb in colours for c in (*rgb, 0))
        inputs = ",".join("{" + ",".join(map(str, rgb)) + "}" for rgb in samples)
        harness = r"""
#include <stdint.h>
#include <stdio.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
static uint16 s_SquareTable[256];
static const uint8 s_palette4BitPC[64] = { CATALOGUE };
MATCHER
int main(void) {
    const uint8 samples[][3] = { INPUTS };
    for (unsigned i = 0; i < 256; i++) s_SquareTable[i] = i * i;
    for (unsigned i = 0; i < sizeof(samples) / sizeof(samples[0]); i++)
        putchar(Palette_FindClosestColor(samples[i][0], samples[i][1], samples[i][2]));
    return 0;
}
"""
        harness = harness.replace("CATALOGUE", catalogue).replace("MATCHER", matcher)
        harness = harness.replace("INPUTS", inputs)
        with tempfile.TemporaryDirectory() as directory:
            path, binary = Path(directory) / "matcher.c", Path(directory) / "matcher"
            path.write_text(harness)
            subprocess.run(
                ["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", str(path), "-o", str(binary)],
                check=True,
            )
            result = subprocess.run([str(binary)], check=True, capture_output=True).stdout
        self.assertEqual(list(result), [closest_pen(rgb, colours) for rgb in samples])

    def test_matcher_ties_masking_and_channel_weights(self):
        colours = [(0, 0, 0), (32, 0, 0)] + [(252, 252, 252)] * 14
        self.assertEqual(closest_pen((4, 0, 0), colours), 0)
        self.assertEqual(closest_pen((7, 3, 3), colours), 0)
        self.assertEqual(closest_pen((8, 0, 0), colours), 1)
        colours = [(16, 0, 0), (0, 16, 0)] + [(252, 252, 252)] * 14
        self.assertEqual(closest_pen((0, 0, 0), colours), 0)

    def test_quadrants_and_white_coverage(self):
        rows = ("1000", "0100", "0010", "0000")
        self.assertEqual(pack_pattern(rows), 0x8420)
        self.assertEqual(
            [[quadrant(rows, x, y) for x in range(2)] for y in range(2)],
            [[9, 0], [0, 8]],
        )
        self.assertEqual(quadrant(rows, 3, 3), 8)
        colours = read_st_palette(ROOT / "src/video/video_atari.c")
        data = build_data(colours, bytes(c % 64 for c in range(768)), "fixture.pak")
        for pen in data["pens"]:
            self.assertLessEqual(abs((pen["white"] - pen["whiteBias"]) / 16 - pen["luma"]), 1 / 32)
        self.assertEqual(len(set(pen["mask"] for pen in data["pens"])), 16)

    def test_perceptual_adjustments_preserve_mapping_and_quadrant_consistency(self):
        colours = read_st_palette(ROOT / "src/video/video_atari.c")
        palette = bytes(c % 64 for c in range(768))
        data = build_data(colours, palette, "fixture.pak")
        self.assertEqual([pen["index"] for pen in data["pens"] if pen["whiteBias"]], [2, 3, 5])
        for index, baseline, white in ((2, 3, 5), (3, 3, 5), (5, 5, 4)):
            pen = data["pens"][index]
            self.assertEqual((pen["lumaWhite"], pen["white"]), (baseline, white))
            self.assertEqual(
                sum(value.bit_count() for row in pen["quadrants"] for value in row), white,
            )
        self.assertEqual(data["mapping"], [
            closest_pen(palette[i:i + 3], colours) for i in range(0, 768, 3)
        ])

    def test_tile_palette_expansion_preserves_zero_as_a_colour(self):
        def chunk(name, data):
            return name + struct.pack(">I", len(data)) + data + b"\0" * (len(data) & 1)

        payload = b"ICON" + chunk(b"SINF", b"\1\1\3\4")
        payload += chunk(b"SSET", struct.pack("<HIH", 0, 32, 0) + b"\x10" * 32)
        payload += chunk(b"RPAL", bytes([0, 42] + [0] * 14)) + chunk(b"RTBL", b"\0")
        width, height, tiles = decode_tiles(b"FORM" + struct.pack(">I", len(payload)) + payload)
        self.assertEqual((width, height), (8, 8))
        self.assertEqual(tiles, [[42, 0] * 32])

    def test_generated_c_tables_match_preview_for_every_index_and_phase(self):
        colours = read_st_palette(ROOT / "src/video/video_atari.c")
        data = build_data(colours, bytes(c % 64 for c in range(768)), "fixture.pak")
        harness = r"""
#include <stdio.h>
#include "atari_mono_palette.h"
#include "atari_mono_palette.h"
#include "atari_dither_palette.h"
#include "atari_dither_palette.h"
_Static_assert(sizeof(s_paletteMonoIBM) == 512, "Direct IBM table must be 512 bytes");
_Static_assert(sizeof(AtariDitherPattern) == 16, "Shared pattern must contain 16 byte pens");
_Static_assert(sizeof(s_paletteDitherSTIBM) == 4096, "ST pattern table must be 4096 bytes");
_Static_assert(sizeof(s_paletteDitherMonoIBM) == 4096, "Mono pattern table must be 4096 bytes");
static void emit(uint16 pattern) {
    putchar(pattern >> 8);
    putchar(pattern & 255);
}
int main(void) {
    for (unsigned i = 0; i < 16; i++) emit(s_paletteMonoST[i]);
    for (unsigned i = 0; i < 256; i++) emit(s_paletteMonoIBM[i]);
    if (fwrite(s_paletteDitherSTIBM, 1, sizeof(s_paletteDitherSTIBM), stdout)
            != sizeof(s_paletteDitherSTIBM)) return 1;
    if (fwrite(s_paletteDitherMonoIBM, 1, sizeof(s_paletteDitherMonoIBM), stdout)
            != sizeof(s_paletteDitherMonoIBM)) return 1;
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as directory:
            path, binary = Path(directory) / "tables.c", Path(directory) / "tables"
            (Path(directory) / "atari_mono_palette.h").write_text(render_header(data))
            (Path(directory) / "atari_dither_palette.h").write_text(render_dither_header(data))
            path.write_text(harness)
            subprocess.run(
                ["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                 "-I", str(ROOT / "include"), "-I", str(ROOT / "src/video"),
                 str(path), "-o", str(binary)],
                check=True,
            )
            result = subprocess.run([str(binary)], check=True, capture_output=True).stdout
        expected = [pen["mask"] for pen in data["pens"]]
        expected += [data["pens"][pen]["mask"] for pen in data["mapping"]]
        packed = b"".join(struct.pack(">H", pattern) for pattern in expected)
        st = bytes(pen for pen in data["mapping"] for _ in range(16))
        mono = bytes(
            (data["pens"][pen]["mask"] >> shift) & 1
            for pen in data["mapping"] for shift in range(15, -1, -1)
        )
        self.assertEqual(result, packed + st + mono)


if __name__ == "__main__":
    unittest.main()
