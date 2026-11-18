"""Check the real mono preparation code against a physical-pixel reference."""

import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tempfile
import unittest

from tools.test_dither_preparation import run_harness


ROOT = Path(__file__).resolve().parents[1]


class MonoPackerTest(unittest.TestCase):
    def test_packed_lookup_partial_updates(self):
        run_harness(r"""
#include <assert.h>
#include <string.h>
#include "atari_mono.h"
int main(void)
{
    AtariDitherLookup dither;
    AtariMonoPackedLookup lookup;
    for (unsigned y = 0; y < 4; y++)
        for (unsigned x = 0; x < 4; x++)
            for (unsigned c = 0; c < 256; c++)
                dither.pens[y][x][c] = ((c >> ((x + 4 * y) & 7)) ^ x ^ y) & 1;
    for (unsigned polarity = 0; polarity < 2; polarity++) {
        memset(&lookup, 0xa5, sizeof(lookup));
        Video_Atari_MonoPreparePackedLookup(&lookup, &dither, 17, 1, polarity);
        for (unsigned y = 0; y < 2; y++)
            for (unsigned x = 0; x < 2; x++)
                assert(lookup.cells[y][x][16] == 0xa5a5a5a5u &&
                    lookup.cells[y][x][18] == 0xa5a5a5a5u);
        Video_Atari_MonoPreparePackedLookup(&lookup, &dither, 0, 17, polarity);
        Video_Atari_MonoPreparePackedLookup(&lookup, &dither, 18, 238, polarity);
        for (unsigned y = 0; y < 2; y++)
            for (unsigned x = 0; x < 2; x++)
                for (unsigned c = 0; c < 256; c++) {
                    uint32 expected = 0;
                    for (unsigned dy = 0; dy < 2; dy++)
                        for (unsigned dx = 0; dx < 2; dx++)
                            expected |= (uint32)(dither.pens[y * 2 + dy][x * 2 + dx][c] ^ !polarity)
                                << ((1 - dy) * 16 + 1 - dx);
                    assert(lookup.cells[y][x][c] == expected);
                }
    }
    return 0;
}
""")

    def test_68000_opaque_row_pixels_bounds_and_abi(self):
        assembler = shutil.which("vasmm68k_mot")
        if assembler is None:
            self.skipTest("68000 execution requires vasm")
        try:
            import unicorn
            from unicorn import m68k_const as reg
        except ImportError:
            self.skipTest("68000 execution requires the optional unicorn package")
        assembly = (ROOT / "src/video/c2p1x1_8.s").read_text()
        assembly = assembly[assembly.index("_c2p1x1_1_st:"):]
        with tempfile.TemporaryDirectory(prefix="mono-row-68000-") as directory:
            source, binary = Path(directory) / "row.s", Path(directory) / "row.bin"
            source.write_text(assembly)
            subprocess.run([assembler, "-m68000", "-Fbin", "-quiet",
                            "-o", str(binary), str(source)], check=True)
            cpu = unicorn.Uc(unicorn.UC_ARCH_M68K, unicorn.UC_MODE_BIG_ENDIAN)
            cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_M68000)
            cpu.mem_map(0, 0x100000)
            cpu.mem_write(0x10000, binary.read_bytes())
            preserved = (reg.UC_M68K_REG_D2, reg.UC_M68K_REG_D3, reg.UC_M68K_REG_D4,
                         reg.UC_M68K_REG_D5, reg.UC_M68K_REG_D6, reg.UC_M68K_REG_D7,
                         reg.UC_M68K_REG_A2, reg.UC_M68K_REG_A3, reg.UC_M68K_REG_A4,
                         reg.UC_M68K_REG_A5, reg.UC_M68K_REG_A6)

            def white(colour, x, y):
                return ((colour >> ((x + y * 4) & 7)) ^ x ^ y) & 1

            for polarity in range(2):
                for oy in range(2):
                    for ox in range(2):
                        for lane in range(2):
                            table = []
                            for colour in range(256):
                                cell = sum((white(colour, ((ox + lane) & 1) * 2 + dx,
                                                  oy * 2 + dy) ^ (not polarity))
                                           << ((1 - dy) * 16 + 1 - dx)
                                           for dy in range(2) for dx in range(2))
                                table.append(cell)
                            cpu.mem_write(0x60000 + lane * 0x1000, struct.pack(">256I", *table))
                        for groups in (0, 1, 2, 40):
                            for seed in range(2):
                                width = groups * 8
                                # End at a mapped-page boundary; also test odd byte input.
                                src = 0x40000 - width - seed
                                pixels = bytes((i * 37 + seed) & 255 for i in range(width))
                                if pixels:
                                    cpu.mem_write(src, pixels)
                                cpu.mem_write(0x50000, b"\xa5" * 84)
                                cpu.mem_write(0x51000, b"\xa5" * 84)
                                expected = [bytearray(b"\xa5" * 84), bytearray(b"\xa5" * 84)]
                                for dy in range(2):
                                    for start in range(0, width, 8):
                                        word = 0
                                        for i, colour in enumerate(pixels[start:start + 8]):
                                            for dx in range(2):
                                                word = (word << 1) | (white(colour,
                                                    ((ox + start + i) & 1) * 2 + dx, oy * 2 + dy)
                                                    ^ (not polarity))
                                        expected[dy][2 + start // 4:4 + start // 4] = word.to_bytes(2, "big")
                                cpu.mem_write(0xf0000, struct.pack(">7I", 0x1f000, 0x50002, 0x51002,
                                                                  src, groups, 0x60000, 0x61000))
                                for index, register in enumerate(preserved):
                                    cpu.reg_write(register, 0x12345000 + index * 0x101)
                                cpu.reg_write(reg.UC_M68K_REG_A7, 0xf0000)

                                def check_read(cpu, access, address, size, value, data):
                                    if 0x30000 <= address < 0x41000:
                                        self.assertTrue(src <= address and address + size <= src + width)

                                def check_write(cpu, access, address, size, value, data):
                                    if 0x50000 <= address < 0x52000:
                                        start = 0x50002 if address < 0x51000 else 0x51002
                                        self.assertTrue(start <= address and address + size <= start + width // 4)

                                hook = cpu.hook_add(unicorn.UC_HOOK_MEM_READ, check_read)
                                writes = cpu.hook_add(unicorn.UC_HOOK_MEM_WRITE, check_write)
                                cpu.emu_start(0x10000, 0x1f000, count=100000)
                                cpu.hook_del(hook)
                                cpu.hook_del(writes)
                                self.assertEqual(cpu.reg_read(reg.UC_M68K_REG_PC), 0x1f000)
                                self.assertEqual(cpu.reg_read(reg.UC_M68K_REG_A7), 0xf0004)
                                for index, register in enumerate(preserved):
                                    self.assertEqual(cpu.reg_read(register), 0x12345000 + index * 0x101)
                                for dy, address in enumerate((0x50000, 0x51000)):
                                    self.assertEqual(cpu.mem_read(address, 84), expected[dy])

    def test_native_spans_masks_in_place_expansion_and_clipped_composition(self):
        run_harness(r"""
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "atari_mono.h"

static unsigned pixel(const uint16 *p, unsigned stride, unsigned x, unsigned y)
{
    return !!(p[y * stride + x / 16] & (0x8000u >> (x & 15)));
}
static void put(uint16 *p, unsigned stride, unsigned x, unsigned y, unsigned value)
{
    uint16 bit = 0x8000u >> (x & 15);
    uint16 *word = &p[y * stride + x / 16];
    *word = (*word & ~bit) | (value ? bit : 0);
}
static void check(unsigned width)
{
    unsigned height = 3, size = width / 4 * height, compactSize = width / 16 * height;
    uint16 pixels[size], masked[size], compact[compactSize], expanded[size + 2], separate[size];
    for (unsigned i = 0; i < size; i++) pixels[i] = 0xa39fu ^ (i * 1973u);
    for (unsigned i = 0; i < compactSize; i++) compact[i] = 0xa681u ^ (i * 971u);
    memcpy(masked, pixels, sizeof(pixels));
    memcpy(expanded + 1, compact, sizeof(compact));
    expanded[0] = expanded[size + 1] = 0xdead;
    Video_Atari_MonoMaskBitmap(masked, expanded + 1, expanded + 1, width, height);
    Video_Atari_MonoMaskBitmap(pixels, separate, compact, width, height);
    assert(!memcmp(pixels, masked, sizeof(pixels)));
    assert(!memcmp(separate, expanded + 1, sizeof(separate)));
    assert(expanded[0] == 0xdead && expanded[size + 1] == 0xdead);
    for (unsigned y = 0; y < height * 2; y++)
        for (unsigned x = 0; x < width * 2; x++) {
            unsigned opacity = !!(compact[y / 2 * (width / 16) + x / 32] &
                (0x8000u >> ((x / 2) & 15)));
            assert(pixel(expanded + 1, width / 8, x, y) == opacity);
            assert(!pixel(masked, width / 8, x, y) || opacity);
        }
    for (unsigned row = 0; row < height; row++)
        for (int x = -(int)width - 17; x <= (int)width + 17; x++) {
            uint16 words[4];
            unsigned expectedMask = 0, expectedOpaque = 0;
            Video_Atari_MonoReadSpan(masked, width / 4, row, x, words);
            for (unsigned i = 0; i < 16; i++) {
                int sx = x + (int)i;
                bool inside = sx >= 0 && sx < (int)width;
                bool opaque = inside && (compact[row * (width / 16) + sx / 16] &
                    (0x8000u >> (sx & 15)));
                if (inside) expectedOpaque |= 0x8000u >> i;
                if (opaque) expectedMask |= 0x8000u >> i;
                for (unsigned dy = 0; dy < 2; dy++)
                    for (unsigned dx = 0; dx < 2; dx++)
                        assert(pixel(words + dy * 2, 2, i * 2 + dx, 0) ==
                            (inside ? pixel(masked, width / 8, sx * 2 + dx, row * 2 + dy) : 0));
            }
            assert(Video_Atari_MonoReadMask(compact, width, row, x, false) == expectedMask);
            assert(Video_Atari_MonoReadMask(expanded + 1, width, row, x, true) == expectedMask);
            assert(Video_Atari_MonoReadMask(NULL, width, row, x, false) == expectedOpaque);
        }
    enum { DW = 48, DH = 7, DS = DW / 4 + 4, MS = DW / 16 + 1 };
    for (int y = -4; y <= DH + 1; y++)
        for (int x = -(int)width - 1; x <= DW + 1; x++)
            for (unsigned opaque = 0; opaque < 2; opaque++) {
                uint16 dst[DS * DH], expected[DS * DH], masks[MS * DH], wanted[MS * DH];
                for (unsigned i = 0; i < DS * DH; i++) dst[i] = expected[i] = 0x936fu ^ (i * 137u);
                for (unsigned i = 0; i < MS * DH; i++) masks[i] = wanted[i] = 0x0180u ^ (i * 71u);
                for (unsigned dy = 0; dy < DH; dy++)
                    for (unsigned dx = 0; dx < DW; dx++) {
                        int sx = (int)dx - x, sy = (int)dy - y;
                        if (sx < 0 || sx >= (int)width || sy < 0 || sy >= (int)height) continue;
                        if (!opaque && !(compact[sy * (width / 16) + sx / 16] &
                            (0x8000u >> (sx & 15)))) continue;
                        wanted[dy * MS + dx / 16] |= 0x8000u >> (dx & 15);
                        for (unsigned py = 0; py < 2; py++)
                            for (unsigned px = 0; px < 2; px++)
                                put(expected, DS / 2, dx * 2 + px, dy * 2 + py,
                                    pixel(pixels, width / 8, sx * 2 + px, sy * 2 + py));
                    }
                Video_Atari_MonoCompose(dst, DS, masks, MS, DW, DH,
                    pixels, opaque ? NULL : compact, width, height, x, y);
                assert(!memcmp(dst, expected, sizeof(dst)));
                assert(!memcmp(masks, wanted, sizeof(masks)));
            }
}
int main(void)
{
    check(16); check(32); check(64);
    return 0;
}
""")

    def test_native_words_masks_tails_and_source_anchoring(self):
        harness = r"""
#include <assert.h>
#include <stdlib.h>
#include "atari_mono.h"
#include "atari_dither_palette.h"

static void check_asset(const AtariDitherPattern patterns[256],
    const AtariMonoLookup *lookup, bool whiteIsOne, uint16 width, uint16 height,
    int16 originX, int16 originY, unsigned maskMode, unsigned padding)
{
    unsigned srcStride = width + padding, sourceWords = (width + 15u) / 16;
    unsigned srcMaskStride = sourceWords + padding;
    unsigned words = (width + 7u) / 8, stride = words + padding;
    size_t sourceBytes = (height - 1u) * srcStride + width;
    size_t sourceMaskWords = (height - 1u) * srcMaskStride + sourceWords;
    size_t outputWords = height * 2u * stride;
    uint8 *allocation = malloc(sourceBytes + 1), *src;
    uint16 *inputMask = malloc(sourceMaskWords * sizeof(*inputMask));
    uint16 *pixels = malloc((outputWords + 2) * sizeof(*pixels));
    uint16 *masks = malloc((outputWords + 2) * sizeof(*masks));
    AtariMonoSource source;
    AtariMonoBitmap target;

    assert(allocation && inputMask && pixels && masks);
    src = allocation + 1; /* Unaligned byte input, ending exactly at its allocation. */
    allocation[0] = 0x7d;
    for (size_t i = 0; i < sourceBytes; i++) src[i] = i * 37 + i / srcStride * 53;
    for (size_t i = 0; i < sourceMaskWords; i++)
        inputMask[i] = maskMode == 2 ? 0 : maskMode == 4 ? 0xffff :
            (uint16)(0xa681u ^ (i * 1973u));
    for (size_t i = 0; i < outputWords + 2; i++) pixels[i] = masks[i] = 0xa55a;
    source = (AtariMonoSource){
        src, maskMode >= 2 ? inputMask : NULL, width, height,
        srcStride, srcMaskStride, originX, originY
    };
    target = (AtariMonoBitmap){pixels + 1, maskMode ? masks + 1 : NULL, stride};
    Video_Atari_MonoPack(&source, lookup, &target);

    for (unsigned y = 0; y < height * 2u; y++) {
        for (unsigned word = 0; word < stride; word++) {
            uint16 expected = 0, expectedMask = 0;
            if (word < words) {
                for (unsigned bit = 0; bit < 16; bit++) {
                    unsigned x = word * 16 + bit, sx = x / 2, sy = y / 2;
                    unsigned px, py;
                    bool opaque, white;
                    if (sx >= width) continue;
                    opaque = maskMode < 2 ||
                        (inputMask[sy * srcMaskStride + sx / 16] & (0x8000u >> (sx % 16)));
                    if (!opaque) continue;
                    expectedMask |= 0x8000u >> bit;
                    px = (unsigned)((originX + (int)sx) * 2 + (int)(x % 2)) & 3;
                    py = (unsigned)((originY + (int)sy) * 2 + (int)(y % 2)) & 3;
                    white = patterns[src[sy * srcStride + sx]][py][px] != 0;
                    if (white == whiteIsOne) expected |= 0x8000u >> bit;
                }
                assert(pixels[1 + y * stride + word] == expected);
                if (maskMode) assert(masks[1 + y * stride + word] == expectedMask);
            } else {
                assert(pixels[1 + y * stride + word] == 0xa55a);
                assert(masks[1 + y * stride + word] == 0xa55a);
            }
        }
    }
    assert(allocation[0] == 0x7d);
    assert(pixels[0] == 0xa55a && pixels[outputWords + 1] == 0xa55a);
    assert(masks[0] == 0xa55a && masks[outputWords + 1] == 0xa55a);
    if (!maskMode)
        for (size_t i = 0; i < outputWords + 2; i++) assert(masks[i] == 0xa55a);
    free(allocation);
    free(inputMask);
    free(pixels);
    free(masks);
}

static unsigned pixel(const uint16 *bitmap, unsigned stride, unsigned x, unsigned y)
{
    return (bitmap[y * stride + x / 16] >> (15 - x % 16)) & 1;
}

static void check_crop(const AtariMonoLookup *lookup)
{
    uint8 src[29 * 5];
    uint16 full[4 * 10], crop[2 * 6];
    AtariMonoSource source = {src, NULL, 29, 5, 29, 0, -2, -3};
    AtariMonoBitmap target = {full, NULL, 4};

    for (unsigned i = 0; i < sizeof(src); i++) src[i] = i * 37;
    Video_Atari_MonoPack(&source, lookup, &target);
    source.pixels += 29 + 3;
    source.width = 15; source.height = 3;
    source.originX += 3; source.originY += 1;
    target.pixels = crop; target.stride = 2;
    Video_Atari_MonoPack(&source, lookup, &target);
    for (unsigned y = 0; y < 6; y++)
        for (unsigned x = 0; x < 30; x++)
            assert(pixel(crop, 2, x, y) == pixel(full, 4, x + 6, y + 2));
}

static void check_small_cells(const AtariMonoLookup *lookup, bool whiteIsOne)
{
    const uint8 src[] = {0, 255, 0};
    const uint16 inputMask[] = {0xe000};
    uint16 pixels[2], masks[2];
    AtariMonoSource source = {src, inputMask, 3, 1, 3, 1, 0, 0};
    AtariMonoBitmap target = {pixels, masks, 1};

    Video_Atari_MonoPack(&source, lookup, &target);
    assert(pixels[0] == (whiteIsOne ? 0x3000 : 0xcc00));
    assert(pixels[1] == pixels[0]);
    assert(masks[0] == 0xfc00 && masks[1] == 0xfc00);
}

int main(void)
{
    AtariDitherPattern synthetic[256];
    AtariMonoLookup lookup;
    const int16 origins[] = {-3, -2, 0, 1};
    const uint16 largeWidths[] = {63, 64, 65, 79, 80, 127, 128, 129, 255, 256, 257, 319, 320};

    for (unsigned c = 0; c < 256; c++)
        for (unsigned y = 0; y < 4; y++)
            for (unsigned x = 0; x < 4; x++)
                synthetic[c][y][x] = (c >> ((y * 4 + x) % 8)) & 1;
    for (unsigned palette = 0; palette < 2; palette++) {
        const AtariDitherPattern *patterns = palette ? s_paletteDitherMonoIBM : synthetic;
        for (unsigned polarity = 0; polarity < 2; polarity++) {
            Video_Atari_MonoPrepareLookup(&lookup, patterns, polarity);
            if (!palette) check_small_cells(&lookup, polarity);
            check_crop(&lookup);
            for (unsigned w = 1; w <= 40 + sizeof(largeWidths) / sizeof(*largeWidths); w++) {
                uint16 width = w <= 40 ? w : largeWidths[w - 41];
                for (unsigned height = 1; height <= 3; height += 2)
                    for (unsigned ox = 0; ox < 4; ox++)
                        for (unsigned oy = 0; oy < 4; oy++)
                            for (unsigned maskMode = 0; maskMode < 5; maskMode++)
                                check_asset(patterns, &lookup, polarity, width, height,
                                    origins[ox], origins[oy], maskMode, (w + ox + oy) % 4);
            }
            check_asset(patterns, &lookup, polarity, 320, 200, 1, 1, 3, 0);
        }
    }
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="mono-packer-") as directory:
            path, binary = Path(directory) / "test.c", Path(directory) / "test"
            path.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run(
                [*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", *flags,
                 "-I", str(ROOT / "include"), "-I", str(ROOT / "src/video"),
                 str(ROOT / "src/video/atari_mono.c"), str(path), "-o", str(binary)],
                check=True,
            )
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
