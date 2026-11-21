"""Exercise source-relative pattern sampling and its live ST-Low preparation boundary."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]

def backend_declarations(video):
    start = video.index("typedef struct AtariPlanarBackend {")
    end = "static const AtariPlanarBackend *s_planarBackend = &s_colourBackend;"
    return video[start:video.index(end, start) + len(end)] + "\n" + "\n".join(
        function(video, name) for name in (
            "Video_Atari_CopyColourRun", "Video_Atari_CopyMonoRun", "Video_Atari_ComposeColourTile",
            "Video_Atari_MonoPenWords", "Video_Atari_PaintColour", "Video_Atari_PaintMono"))


def colour_tile_compositor(video):
    return function(video, "Video_Atari_ComposeColourTile").replace(
        "static void Video_Atari_ComposeColourTile(", "void Video_Atari_ComposePlanarTile(", 1)


def surface_backend(video):
    return "\n".join(function(video, name) for name in (
        "Video_Atari_CopyColourRun", "Video_Atari_CopyMonoRun",
        "Video_Atari_PaintColour", "Video_Atari_PaintMono")) + r"""
static const struct {
    void (*paint)(uint16 *, uint16, uint16, uint16, uint16, uint16, const uint16 *, uint16, uint8, int16, int16);
    void (*copyRun)(uint8 *, uint16, const uint8 *, uint16, uint16, uint16);
    uint8 xShift;
} surfaceColour = {Video_Atari_PaintColour, Video_Atari_CopyColourRun, 1},
  surfaceMono = {Video_Atari_PaintMono, Video_Atari_CopyMonoRun, 2};
#define s_planarBackend (Video_Atari_Mono() ? &surfaceMono : &surfaceColour)
""" + "\n".join(function(video, name) for name in (
        "Video_Atari_PlanarOffset", "Video_Atari_PaintPlanar", "Video_Atari_CopyPlanar"))


def glyph_backend(video):
    header = (ROOT / "src/video/video.h").read_text()
    start = header.index("typedef struct VideoAtariGlyph {")
    end = header.index("} VideoAtariGlyphRun;", start) + len("} VideoAtariGlyphRun;")
    return "#ifndef VIDEO_VIDEO_H\n" + header[start:end] + "\n#endif\n" + "\n".join(
        function(video, name) for name in (
            "Video_Atari_GlyphValue", "Video_Atari_DrawColourGlyphs",
            "Video_Atari_DrawMonoGlyphs", "Video_Atari_DrawPlanarGlyphs"))


def run_harness(harness):
    with tempfile.TemporaryDirectory(prefix="dither-preparation-") as directory:
        source, binary = Path(directory) / "test.c", Path(directory) / "test"
        source.write_text(harness)
        compiler = shlex.split(os.environ.get("CC", "cc"))
        flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
        subprocess.run(
            [*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", *flags,
             "-I", str(ROOT / "include"), "-I", str(ROOT / "src/video"),
             str(ROOT / "src/video/atari_dither.c"), str(ROOT / "src/video/atari_mono.c"),
             str(source), "-o", str(binary)],
            check=True,
        )
        subprocess.run([str(binary)], check=True)


class DitherPreparationTest(unittest.TestCase):
    def test_all_phases_scaling_flips_crops_and_strides(self):
        run_harness(r"""
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "atari_dither.h"
#include "atari_dither_palette.h"

static void check(const AtariDitherPattern patterns[256], unsigned width, unsigned height,
    int originX, int originY, int stepX, int stepY, unsigned scale)
{
    unsigned srcStride = width + 3, dstStride = width * scale + 5;
    size_t inputBytes = (height - 1) * srcStride + width;
    size_t outputBytes = height * scale * dstStride;
    uint8 *allocation = malloc(inputBytes + 1), *out = malloc(outputBytes + 2);
    AtariDitherLookup lookup;
    AtariDitherSource source = {
        allocation + 1, width, height, srcStride, originX, originY, stepX, stepY
    };
    AtariDitherTarget target = {out + 1, dstStride, scale};

    assert(allocation && out);
    for (size_t i = 0; i <= inputBytes; i++) allocation[i] = i * 37 + i / srcStride * 53;
    memset(out, 0xa5, outputBytes + 2);
    Video_Atari_DitherPrepareLookup(&lookup, patterns);
    Video_Atari_PreparePens(&source, &lookup, &target);
    for (unsigned y = 0; y < height * scale; y++) {
        for (unsigned x = 0; x < dstStride; x++) {
            uint8 expected = 0xa5;
            if (x < width * scale) {
                unsigned sx = x / scale, sy = y / scale;
                unsigned dx = stepX < 0 ? scale - 1 - x % scale : x % scale;
                unsigned dy = stepY < 0 ? scale - 1 - y % scale : y % scale;
                unsigned px = (unsigned)((originX + (int)sx * stepX) * (int)scale + (int)dx) & 3;
                unsigned py = (unsigned)((originY + (int)sy * stepY) * (int)scale + (int)dy) & 3;
                expected = patterns[source.pixels[sy * srcStride + sx]][py][px];
            }
            assert(out[1 + y * dstStride + x] == expected);
        }
    }
    assert(out[0] == 0xa5 && out[outputBytes + 1] == 0xa5);
    free(allocation);
    free(out);
}

static void check_crop(const AtariDitherLookup *lookup, int stepX, int stepY, unsigned scale)
{
    uint8 src[29 * 7], full[58 * 14], crop[30 * 6];
    AtariDitherSource source = {src, 29, 7, 29, -3, 5, stepX, stepY};
    AtariDitherTarget target = {full, 29 * scale, scale};

    for (unsigned i = 0; i < sizeof(src); i++) src[i] = i * 37;
    Video_Atari_PreparePens(&source, lookup, &target);
    source.pixels += 29 + 3;
    source.width = 15; source.height = 3;
    source.originX += 3 * stepX; source.originY += stepY;
    target.pixels = crop; target.stride = 15 * scale;
    Video_Atari_PreparePens(&source, lookup, &target);
    for (unsigned y = 0; y < 3 * scale; y++)
        assert(!memcmp(crop + y * 15 * scale,
            full + (y + scale) * 29 * scale + 3 * scale, 15 * scale));
}

int main(void)
{
    AtariDitherPattern patterns[256];
    AtariDitherLookup lookup;
    const unsigned widths[] = {1, 3, 7, 8, 9, 15, 16, 17, 33, 320};

    for (unsigned c = 0; c < 256; c++)
        for (unsigned y = 0; y < 4; y++)
            for (unsigned x = 0; x < 4; x++) patterns[c][y][x] = (y * 4 + x) ^ (c & 15);
    Video_Atari_DitherPrepareLookup(&lookup, patterns);
    for (unsigned scale = 1; scale <= 2; scale++) {
        for (int stepX = -1; stepX <= 1; stepX += 2)
            for (int stepY = -1; stepY <= 1; stepY += 2) {
                check_crop(&lookup, stepX, stepY, scale);
                for (int oy = -3; oy <= 0; oy++)
                    for (int ox = -3; ox <= 0; ox++)
                        for (unsigned w = 0; w < sizeof(widths) / sizeof(*widths); w++)
                            check(patterns, widths[w], 5, ox, oy, stepX, stepY, scale);
            }
    }
    check(s_paletteDitherSTIBM, 256, 3, 1, -3, 1, 1, 1);
    check(s_paletteDitherMonoIBM, 256, 3, -1, 1, 1, 1, 2);
    return 0;
}
""")

    def test_building_classification_keeps_shared_and_nonbuilding_icons(self):
        classify = function((ROOT / "src/gfx.c").read_text(), "GFX_ClassifyPlanarBuildingTiles")
        run_harness(r"""
#include <assert.h>
#include "types.h"
#include "../sprites.h"
static uint16 map[] = {
    [ICM_ICONGROUP_ROCK_CRATERS] = 27,
    [ICM_ICONGROUP_HOUSE_PALACE] = 32,
    [27] = 2, 33, 108, 125, 143,
    [32] = 210, 125, 143, 354, 388, 389, 0xffff
};
uint16 *g_iconMap = map;
static uint16 s_planarTileCount = 389;
static uint8 s_planarBuildingTiles[64];
static bool mono;
#define Video_Atari_Mono() (mono)
static bool GFX_PlanarTilesReady(void) { return true; }
static unsigned warnings;
static void Warning(const char *text, ...) { assert(text != 0); warnings++; }
""" + classify + r"""
int main(void)
{
    unsigned words = sizeof(map) / sizeof(*map);
    GFX_ClassifyPlanarBuildingTiles(words);
    assert(s_planarBuildingTiles[210 / 8] == 0);
    mono = true;
    GFX_ClassifyPlanarBuildingTiles(32);
    assert(warnings == 1 && s_planarBuildingTiles[210 / 8] == 0);
    GFX_ClassifyPlanarBuildingTiles(words);
    for (unsigned id = 0; id < 512; id++)
        assert(((s_planarBuildingTiles[id / 8] & (1u << (id & 7))) != 0) ==
            (id == 210 || id == 354 || id == 388));
    return 0;
}
""")

    def test_terrain_artwork_substitutions_preserve_masks_and_donor_tiles(self):
        gfx = (ROOT / "src/gfx.c").read_text()
        prepare = "\n".join(function(gfx, name) for name in (
            "GFX_InitPlanarRockArtwork", "GFX_InitPlanarSandArtwork", "GFX_FillPlanarTile"))
        run_harness(r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "../sprites.h"
enum { PLANAR_TILE_MIXED = 1, PLANAR_TILE_EMPTY, PLANAR_TILE_OPAQUE };
static uint16 map[97];
uint16 *g_iconMap = map;
static uint16 s_planarTileCount = 4;
static uint16 s_planarRockTile = 0xffff, s_planarRockArtwork;
static uint16 s_planarSandTile = 0xffff, s_planarSandArtwork;
static uint8 s_planarBuildingTiles[64], s_planarTileReady[4];
static uint16 s_planarTiles[4 * 64], s_planarTileMasks[4 * 16];
static uint8 tileData[4 * 128], palettes[32], paletteIndices[4];
uint8 *g_tilesPixels = tileData, *g_iconRPAL = palettes, *g_iconRTBL = paletteIndices;
static uint16 s_tileByteSize = 128;
static bool mono, reduced;
static const uint8 *decodedSource;
static uint8 decodedColour, decodedBackground;
static unsigned warnings;
#define Video_Atari_Mono() (mono)
static bool GFX_PlanarTilesReady(void) { return true; }
static void Warning(const char *text, ...) { assert(text != 0); warnings++; }
static uint8 GFX_TileHouseColor(uint8 colour, uint8 house)
{
    return colour + house;
}
static void Video_Atari_DecodePlanarTile(const uint8 *src, const uint8 *pal, uint16 *dst)
{
    reduced = false;
    decodedSource = src;
    decodedColour = pal[1];
    decodedBackground = pal[2];
    *dst = decodedColour;
}
static void Video_Atari_DecodePlanarBuildingTile(const uint8 *src, const uint8 *pal, uint16 *dst)
{
    assert(mono);
    Video_Atari_DecodePlanarTile(src, pal, dst);
    reduced = true;
}
""" + prepare + r"""
int main(void)
{
    map[ICM_ICONGROUP_LANDSCAPE] = 32;
    map[32 + 16] = 1;
    map[32 + 48] = 2;
    map[32] = 3;
    map[32 + 64] = 2;
    g_iconRTBL[2] = 1;
    g_iconRPAL[1] = 24;
    g_iconRPAL[17] = 98;
    memset(tileData, 0x11, sizeof(tileData));
    GFX_InitPlanarRockArtwork(96);
    GFX_FillPlanarTile(1, 1, 1);
    assert(!reduced && decodedSource == g_tilesPixels + 128 && decodedColour == 25);
    mono = true;
    GFX_InitPlanarRockArtwork(80);
    assert(warnings == 1 && s_planarRockTile == 0xffff);
    GFX_InitPlanarRockArtwork(96);
    GFX_FillPlanarTile(1, 1, 1);
    assert(reduced && decodedSource == g_tilesPixels + 256 && decodedColour == 98);
    assert(s_planarTileReady[1] == PLANAR_TILE_OPAQUE);
    assert(s_planarTileMasks[16] == 0xffff && s_planarTileMasks[31] == 0xffff);
    GFX_FillPlanarTile(2, 0, 2);
    assert(!reduced && decodedSource == g_tilesPixels + 256 && decodedColour == 98);
    g_tilesPixels[128] = 0x01;
    GFX_FillPlanarTile(1, 0, 1);
    assert(!reduced && decodedSource == g_tilesPixels + 128 && decodedColour == 24);
    assert(s_planarTileReady[1] == PLANAR_TILE_MIXED && s_planarTileMasks[16] == 0x7fff);

    g_iconRPAL[17] = 218;
    g_iconRPAL[18] = 90;
    GFX_InitPlanarSandArtwork(97);
    GFX_FillPlanarTile(3, 0, 3);
    assert(decodedSource == g_tilesPixels + 384 && decodedColour == 24);
    mono = false;
    GFX_InitPlanarSandArtwork(96);
    assert(warnings == 2 && s_planarSandTile == 0xffff);
    GFX_InitPlanarSandArtwork(97);
    GFX_FillPlanarTile(3, 0, 3);
    assert(decodedSource == g_tilesPixels + 256 && decodedColour == 88 && decodedBackground == 90);
    assert(s_planarTileReady[3] == PLANAR_TILE_OPAQUE && s_planarTileMasks[48] == 0xffff);
    GFX_FillPlanarTile(2, 0, 2);
    assert(decodedSource == g_tilesPixels + 256 && decodedColour == 218 && decodedBackground == 90);
    g_tilesPixels[384] = 0x01;
    GFX_FillPlanarTile(3, 0, 3);
    assert(decodedSource == g_tilesPixels + 384 && decodedColour == 24);
    assert(s_planarTileReady[3] == PLANAR_TILE_MIXED && s_planarTileMasks[48] == 0x7fff);
    return 0;
}
""")

    def test_st_backend_palette_updates_bands_padding_and_composition(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        production = "\n".join(function(video, name) for name in (
            "Video_Atari_MonoCoverage", "Video_Atari_SetMonoCoverage", "Video_Atari_ReducedMonoCoverage",
            "Video_Atari_SetPackedMonoCoverage",
            "Video_Atari_PrepareUnitPlanar",
            "Rebuild_Palette4BitPairMap", "Video_Atari_EncodePlanarWithLookup",
            "Video_Atari_InitPenPairMap", "Video_Atari_PreparePlanar",
            "Video_Atari_PrepareColour", "Video_Atari_PrepareMonoCustom",
            "Video_Atari_PrepareMono", "Video_Atari_ConvertColour", "Video_Atari_ColourReadGroup",
            "Video_Atari_EncodePlanar", "Video_Atari_EncodePlanarStrided",
            "Video_Atari_InitTileMapping", "Video_Atari_DecodePlanarTile", "Video_Atari_DecodePlanarBuildingTile",
            "Video_Atari_PlanarMergePlain", "Video_Atari_ComposePlanarSprite",
            "Video_Atari_ComposePlanarTile",
            "Video_Atari_PlanarOffset", "Video_Atari_CopyPlanar", "Video_Atari_PaintPlanar",
            "Video_Atari_MergePlanarRows", "Video_Atari_ShiftPlanarGroup",
            "Video_FirstDirtyBlock", "Video_FirstCleanBlock",
            "Video_Atari_ConvertRun",
            "Video_Atari_C2P_ConvertBlocks",
        ))
        harness = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "atari_dither.h"
#include "atari_mono.h"
#include "atari_mono_palette.h"
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 200
#define ST_PLANAR_LINE_BYTES 160
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
typedef enum { DIRTY_SWEEP_LEGACY, DIRTY_SWEEP_VIEWPORT, DIRTY_SWEEP_REPAINT } DirtySweepKind;
static const uint8 s_nibbleFirstSet[16] = {4,0,1,0,2,0,1,0,3,0,1,0,2,0,1,0};
#ifdef VIDEO_C2P_STATS
#define VIDEO_C2P_TOPBAR_HEIGHT 40
#define VIDEO_C2P_SIDEBAR_LEFT 256
static uint32 s_statLineCalls, s_statTickCalls, s_statTickRows, s_statLinePixels;
static uint32 s_statDirtyPixels, s_statTickPixels, s_statTickDirty, s_statSpanPixels;
static uint32 s_statTopBarPixels, s_statBattlefieldPixels, s_statSidebarPixels;
static uint16 Video_LastDirtyBlock(uint32 mask) { return 32 - __builtin_clz(mask); }
#endif
static unsigned nativeCalls, sweepCalls, sweepPixels;
static DirtySweepKind sweepKind;
static void Video_Atari_DisplayListFlush(void) {}
static void Video_Atari_PlanarFinishRun(uint8 *base, uint16 x, uint16 y, uint16 w, uint16 h)
{ (void)base; assert(!(x & 15) && !(w & 15) && y + h <= 200); nativeCalls++; }
static void Video_Atari_DirtySweepRecord(DirtySweepKind kind, uint32 pixels, uint32 calls)
{ sweepKind = kind; sweepPixels = pixels; sweepCalls = calls; }
static void Video_Atari_DirtySweepBand(uint32 mask, uint16 top, uint16 bottom, uint16 width)
{ assert(mask && top < bottom && width <= 320); }
static bool mono, s_monoWhiteIsOne;
#define Video_Atari_Mono() mono
static uint8 s_palette4BitMap[256], s_paletteMonoCoverage[256];
static uint16 s_palette4BitPairMap[65536], s_penPairMap[4096];
static AtariDitherLookup s_palette4BitDither = {.flat = true}, s_tileDither = {.flat = true};
static AtariMonoPackedLookup s_paletteMonoPacked, s_tileMonoPacked, s_unitMonoPacked, s_buildingMonoPacked;
static bool s_penPairMapReady;
static unsigned mappedEncodes, penEncodes;
/* BACKEND */
static bool Video_Atari_CursorDirect(void) { return true; }
static uint8 Palette_FindClosestColor(uint8 r, uint8 g, uint8 b)
{ return (r * 3 + g * 5 + b * 7) & 15; }
static void Video_Atari_ExpandTileNibbles(const uint8 *src, const uint8 *palette, uint8 *dst)
{
    for (unsigned i = 0; i < 128; i++) {
        *dst++ = palette[src[i] >> 4];
        *dst++ = palette[src[i] & 15];
    }
}
static void encode(uint16 *dst, const uint8 *src, unsigned width, unsigned height,
    const uint16 *lookup, unsigned srcStride, unsigned dstStride)
{
    assert(lookup == s_penPairMap || lookup == s_palette4BitPairMap);
    if (lookup == s_penPairMap) penEncodes++; else mappedEncodes++;
    for (unsigned y = 0; y < height; y++) {
        memset(dst + y * dstStride / 2, 0, width / 2);
        for (unsigned x = 0; x < width; x += 2) {
            unsigned index = (src[y * srcStride + x] << 8) | src[y * srcStride + x + 1];
            assert(lookup != s_penPairMap || index < 4096);
            unsigned pair = lookup[index];
            for (unsigned p = 0; p < 4; p++) {
                uint16 *word = &dst[y * dstStride / 2 + (x / 16) * 4 + p];
                if ((pair >> 8) & (1u << p)) *word |= 0x8000u >> (x & 15);
                if (pair & (1u << p)) *word |= 0x4000u >> (x & 15);
            }
        }
    }
}
static void c2p1x1_4_st(uint16 *dst, const uint8 *src, unsigned w, unsigned h, const uint16 *map)
{ encode(dst, src, w, h, map, 320, 160); }
static void c2p1x1_4_st_strided(uint16 *dst, const uint8 *src, unsigned w, unsigned h,
    const uint16 *map, unsigned ss, unsigned ds)
{ encode(dst, src, w, h, map, ss, ds); }
/* PRODUCTION */
enum { PLANAR_TILE_MIXED = 1, PLANAR_TILE_EMPTY, PLANAR_TILE_OPAQUE };
/* TILE COMPOSITOR */
static uint8 pixel(const uint16 *pixels, unsigned width, unsigned x, unsigned y)
{
    uint8 pen = 0;
    for (unsigned p = 0; p < 4; p++)
        pen |= ((pixels[y * width / 4 + (x / 16) * 4 + p] >> (15 - (x & 15))) & 1) << p;
    return pen;
}
static void check_private_surfaces(void)
{
    const unsigned widths[] = {1, 7, 16, 17, 47, 64};
    uint16 out[24 * 10 + 2], expected[24 * 10 + 2], masks[5 * 4], source[20 * 10];
    for (unsigned mode = 0; mode < 2; mode++)
    for (unsigned polarity = 0; polarity < 2; polarity++) {
        mono = mode;
        s_planarBackend = mode ? &s_monoBackend : &s_colourBackend;
        s_monoWhiteIsOne = polarity;
        for (unsigned pen = 0; pen < 16; pen++)
        for (unsigned x = 0; x < 32; x++)
        for (unsigned wi = 0; wi < sizeof(widths) / sizeof(*widths); wi++)
        for (unsigned masked = 0; masked < 2; masked++) {
            unsigned width = widths[wi], scale = mode ? 2 : 1;
            for (unsigned i = 0; i < sizeof(out) / sizeof(*out); i++)
                out[i] = expected[i] = 0xa39fu ^ (i * 1973u);
            for (unsigned i = 0; i < sizeof(masks) / sizeof(*masks); i++)
                masks[i] = i & 1 ? 0x8001u ^ (i * 311u) : 0xffff;
            for (unsigned row = 0; row < 4; row++)
            for (unsigned col = 0; col < width; col++) {
                if (masked && !(masks[row * 5 + (x + col) / 16 - x / 16] &
                                (0x8000u >> ((x + col) & 15)))) continue;
                for (unsigned dy = 0; dy < scale; dy++)
                for (unsigned dx = 0; dx < scale; dx++) {
                    if (mode) {
                        unsigned px = ((col - 3) * 2 + dx) & 3;
                        unsigned py = ((row + 1) * 2 + dy) & 3;
                        unsigned bit = 0x8000u >> (((x + col) * 2 + dx) & 15);
                        unsigned offset = 1 + ((row + 2) * 2 + dy) * 12 +
                                          ((x + col) * 2 + dx) / 16;
                        bool set = ((s_paletteMonoST[pen] >> (15 - py * 4 - px)) & 1) ^ !polarity;
                        expected[offset] = (expected[offset] & ~bit) | (set ? bit : 0);
                    } else {
                        unsigned bit = 0x8000u >> ((x + col) & 15);
                        for (unsigned plane = 0; plane < 4; plane++) {
                            unsigned offset = 1 + (row + 2) * 24 + (x + col) / 16 * 4 + plane;
                            expected[offset] = (expected[offset] & ~bit) | ((pen & (1u << plane)) ? bit : 0);
                        }
                    }
                }
            }
            Video_Atari_PaintPlanar(out + 1, 24, x, 2, width, 4,
                masked ? masks : NULL, 5, pen, -3, 1);
            if (memcmp(out, expected, sizeof(out)))
                fprintf(stderr, "paint mode=%u polarity=%u pen=%u x=%u width=%u masked=%u\n",
                        mode, polarity, pen, x, width, masked);
            assert(!memcmp(out, expected, sizeof(out)));
        }
        for (unsigned i = 0; i < sizeof(source) / sizeof(*source); i++) source[i] = i * 7919u;
        for (unsigned dstX = 0; dstX < 48; dstX += 16)
        for (unsigned srcX = 0; srcX < 48; srcX += 16) {
            for (unsigned i = 0; i < sizeof(out) / sizeof(*out); i++) out[i] = expected[i] = 0x5ca7u;
            for (unsigned row = 0; row < 3 * (mode ? 2u : 1u); row++)
            for (unsigned col = 0; col < 32 * (mode ? 2u : 1u); col++) {
                if (mode) {
                    unsigned bit = 0x8000u >> ((dstX * 2 + col) & 15);
                    unsigned offset = 1 + (4 + row) * 12 + (dstX * 2 + col) / 16;
                    bool set = !!(source[(2 + row) * 10 + (srcX * 2 + col) / 16] &
                                  (0x8000u >> ((srcX * 2 + col) & 15)));
                    expected[offset] = (expected[offset] & ~bit) | (set ? bit : 0);
                } else {
                    unsigned bit = 0x8000u >> ((dstX + col) & 15);
                    for (unsigned plane = 0; plane < 4; plane++) {
                        unsigned offset = 1 + (2 + row) * 24 + (dstX + col) / 16 * 4 + plane;
                        bool set = !!(source[(1 + row) * 20 + (srcX + col) / 16 * 4 + plane] &
                                      (0x8000u >> ((srcX + col) & 15)));
                        expected[offset] = (expected[offset] & ~bit) | (set ? bit : 0);
                    }
                }
            }
            Video_Atari_CopyPlanar(out + 1, 24, dstX, 2, source, 20, srcX, 1, 32, 3);
            if (memcmp(out, expected, sizeof(out)))
                fprintf(stderr, "copy mode=%u polarity=%u dstX=%u srcX=%u\n", mode, polarity, dstX, srcX);
            assert(!memcmp(out, expected, sizeof(out)));
        }
        for (unsigned shift = 0; shift < 16; shift++) {
            uint16 shifted[34], wanted[34] = {0};
            const uint16 opacity[4] = {0, 0xffff, 0x8001, 0x3ff0};
            unsigned scale = mode ? 2 : 1;
            memset(shifted, 0xa5, sizeof(shifted));
            wanted[0] = wanted[33] = 0xa5a5;
            for (unsigned row = 0; row < 4 * scale; row++)
            for (unsigned col = shift * scale; col < (shift + 16) * scale; col++) {
                unsigned sx = col - shift * scale;
                if (!(opacity[row / scale] & (0x8000u >> (sx / scale)))) continue;
                if (mode) {
                    if (source[row * 2 + sx / 16] & (0x8000u >> (sx & 15)))
                        wanted[1 + row * 4 + col / 16] |= 0x8000u >> (col & 15);
                } else {
                    unsigned pen = pixel(source, 16, sx, row);
                    for (unsigned plane = 0; plane < 4; plane++)
                        if (pen & (1u << plane))
                            wanted[1 + row * 8 + col / 16 * 4 + plane] |= 0x8000u >> (col & 15);
                }
            }
            Video_Atari_ShiftPlanarGroup(source, opacity, 4, shift, shifted + 1);
            if (memcmp(shifted, wanted, sizeof(shifted)))
                fprintf(stderr, "shift mode=%u shift=%u\n", mode, shift);
            assert(!memcmp(shifted, wanted, sizeof(shifted)));
        }
        for (unsigned maskStride = 0; maskStride <= 5; maskStride += 5) {
            for (unsigned i = 0; i < sizeof(out) / sizeof(*out); i++) out[i] = expected[i] = 0x5ca7u;
            for (unsigned row = 0; row < 3; row++)
            for (unsigned col = 0; col < 32; col++) {
                unsigned scale = mode ? 2 : 1;
                if (!(masks[row * maskStride + col / 16] & (0x8000u >> (col & 15)))) continue;
                for (unsigned dy = 0; dy < scale; dy++)
                for (unsigned dx = 0; dx < scale; dx++) {
                    if (mode) {
                        unsigned tx = (32 + col) * 2 + dx, ty = (2 + row) * 2 + dy;
                        unsigned sx = (16 + col) * 2 + dx, sy = (1 + row) * 2 + dy;
                        unsigned bit = 0x8000u >> (tx & 15), offset = 1 + ty * 12 + tx / 16;
                        bool set = !!(source[sy * 10 + sx / 16] & (0x8000u >> (sx & 15)));
                        expected[offset] = (expected[offset] & ~bit) | (set ? bit : 0);
                    } else {
                        unsigned pen = pixel(source, 80, 16 + col, 1 + row), bit = 0x8000u >> (col & 15);
                        for (unsigned plane = 0; plane < 4; plane++) {
                            unsigned offset = 1 + (2 + row) * 24 + (32 + col) / 16 * 4 + plane;
                            expected[offset] = (expected[offset] & ~bit) | ((pen & (1u << plane)) ? bit : 0);
                        }
                    }
                }
            }
            Video_Atari_MergePlanarRows(out + 1 + Video_Atari_PlanarOffset(24, 32, 2), 24,
                source + Video_Atari_PlanarOffset(20, 16, 1), 20, masks, maskStride, 2, 3);
            assert(!memcmp(out, expected, sizeof(out)));
        }
    }
    mono = false;
    s_planarBackend = &s_colourBackend;
}
static void check_tile_composition(void)
{
    uint16 base[64], overlay[64], masks[16], overlayMasks[16];
    uint16 savedBase[64], savedOverlay[64], savedMasks[16], savedOverlayMasks[16];
    const uint16 patterns[] = {0, 0xffff, 0xaaaa, 0x5555, 0x8001, 0x00ff, 0xff00, 0x3ff0};
    for (unsigned mode = 0; mode < 2; mode++)
    for (unsigned zero = 0; zero < 2; zero++)
    for (unsigned a = 0; a < 24; a++)
    for (unsigned b = 0; b < 25; b++) {
        uint16 out[66], outMasks[18], expected[64] = {0};
        unsigned maskAnd = 0xffff, maskOr = 0;
        s_planarBackend = mode ? &s_monoBackend : &s_colourBackend;
        for (unsigned i = 0; i < 64; i++) {
            base[i] = zero ? 0 : 0xa39fu ^ (i * 1973u);
            overlay[i] = zero ? 0 : 0x5ca7u ^ (i * 7919u);
        }
        for (unsigned y = 0; y < 16; y++) {
            uint32 m = a < 8 ? patterns[a] : 0x8000u >> (a - 8);
            uint32 o = b < 8 ? patterns[b] : b < 24 ? 0x8000u >> (b - 8) : 0;
            masks[y] = (m << y) | (m >> (16 - y));
            overlayMasks[y] = (o << y) | (o >> (16 - y));
        }
        memcpy(savedBase, base, sizeof(base));
        memcpy(savedOverlay, overlay, sizeof(overlay));
        memcpy(savedMasks, masks, sizeof(masks));
        memcpy(savedOverlayMasks, overlayMasks, sizeof(overlayMasks));
        unsigned scale = mode ? 2 : 1;
        for (unsigned y = 0; y < 16 * scale; y++)
        for (unsigned x = 0; x < 16 * scale; x++) {
            unsigned bit = 0x8000u >> (x / scale);
            const uint16 *source = overlayMasks[y / scale] & bit ? overlay :
                masks[y / scale] & bit ? base : NULL;
            if (source == NULL) continue;
            if (mode) {
                if (source[y * 2 + x / 16] & (0x8000u >> (x & 15)))
                    expected[y * 2 + x / 16] |= 0x8000u >> (x & 15);
            } else {
                unsigned pen = pixel(source, 16, x, y);
                for (unsigned plane = 0; plane < 4; plane++)
                    if (pen & (1u << plane)) expected[y * 4 + plane] |= bit;
            }
        }
        for (unsigned seed = 0; seed < 2; seed++) {
            memset(out, seed ? 0xa5 : 0x5a, sizeof(out));
            memset(outMasks, seed ? 0x3c : 0xc3, sizeof(outMasks));
            uint8 classification = GFX_ComposePlanarTile(base, masks,
                b == 24 ? NULL : overlay, b == 24 ? NULL : overlayMasks,
                out + 1, outMasks + 1);
            for (unsigned y = 0; y < 16; y++) {
                unsigned mask = masks[y] | overlayMasks[y];
                assert(outMasks[1 + y] == mask);
                maskAnd &= mask; maskOr |= mask;
            }
            assert(classification == (maskAnd == 0xffff ? PLANAR_TILE_OPAQUE :
                maskOr == 0 ? PLANAR_TILE_EMPTY : PLANAR_TILE_MIXED));
            assert(!memcmp(out + 1, expected, sizeof(expected)));
            assert(out[0] == (seed ? 0xa5a5 : 0x5a5a) && out[65] == out[0]);
            assert(outMasks[0] == (seed ? 0x3c3c : 0xc3c3) && outMasks[17] == outMasks[0]);
            assert(!memcmp(base, savedBase, sizeof(base)));
            assert(!memcmp(overlay, savedOverlay, sizeof(overlay)));
            assert(!memcmp(masks, savedMasks, sizeof(masks)));
            assert(!memcmp(overlayMasks, savedOverlayMasks, sizeof(overlayMasks)));
        }
    }
    s_planarBackend = &s_colourBackend;
}
static void check(const AtariDitherPattern patterns[256], const AtariDitherLookup *lookup,
    unsigned width, unsigned height, int ox, int oy, int stepX, int stepY)
{
    unsigned stride = width + 3, outputWidth = (width + 15) & ~15;
    size_t inputBytes = (height - 1) * stride + width, words = outputWidth / 4 * height;
    uint8 *allocation = malloc(inputBytes + 1);
    uint16 *out = malloc((words + 2) * sizeof(*out));
    AtariDitherSource source = {allocation + 1, width, height, stride, ox, oy, stepX, stepY};

    assert(allocation && out);
    for (size_t i = 0; i <= inputBytes; i++) allocation[i] = i * 37 + i / stride * 53;
    for (size_t i = 0; i < words + 2; i++) out[i] = 0xa55a;
    Video_Atari_PreparePlanar(&source, lookup, out + 1);
    unsigned scale = mono ? 2 : 1;
    for (unsigned y = 0; y < height * scale; y++)
        for (unsigned x = 0; x < outputWidth * scale; x++) {
            uint8 expected = 0;
            if (x < width * scale) {
                uint8 colour = source.pixels[y / scale * stride + x / scale];
                unsigned px = (unsigned)((ox + (int)(x / scale) * stepX) * (int)scale +
                    (stepX > 0 ? (int)(x % scale) : (int)(scale - 1 - x % scale))) & 3;
                unsigned py = (unsigned)((oy + (int)(y / scale) * stepY) * (int)scale +
                    (stepY > 0 ? (int)(y % scale) : (int)(scale - 1 - y % scale))) & 3;
                expected = lookup ? patterns[colour][py][px] :
                    s_palette4BitDither.pens[py][px][colour];
                if (mono) expected ^= !s_monoWhiteIsOne;
            }
            unsigned actual = mono ?
                !!(out[1 + y * (outputWidth / 8) + x / 16] & (0x8000u >> (x & 15))) :
                pixel(out + 1, outputWidth, x, y);
            assert(actual == expected);
        }
    assert(out[0] == 0xa55a && out[words + 1] == 0xa55a);
    free(allocation);
    free(out);
}
static void check_composition(const AtariDitherPattern patterns[256], const AtariDitherLookup *lookup)
{
    uint8 src[16 * 3];
    uint16 component[4 * 3], masks[3] = {0xffff, 0x9999, 0xffff};
    AtariDitherSource source = {src, 16, 3, 16, 1, -3, 1, 1};
    for (unsigned i = 0; i < sizeof(src); i++) src[i] = i * 37;
    Video_Atari_PreparePlanar(&source, lookup, component);
    for (unsigned offset = 1; offset <= 15; offset++) {
        uint16 composite[8 * 5] = {0}, compositeMasks[2 * 5] = {0};
        Video_Atari_ComposePlanarSprite(composite, compositeMasks, 32, 5,
            component, masks, 16, 3, offset, 1);
        for (unsigned y = 0; y < 5; y++)
            for (unsigned x = 0; x < 32; x++) {
                uint8 expected = 0;
                bool visible = false;
                if (y >= 1 && y < 4 && x >= offset && x < offset + 16) {
                    unsigned sx = x - offset, sy = y - 1;
                    visible = (masks[sy] & (0x8000u >> sx)) != 0;
                    if (visible) expected = patterns[src[sy * 16 + sx]][(sy + 1) & 3][(sx + 1) & 3];
                }
                assert(pixel(composite, 32, x, y) == expected);
                assert(!!(compositeMasks[y * 2 + x / 16] & (0x8000u >> (x & 15))) == visible);
            }
    }
}
static void check_fused_colour(void)
{
    const unsigned widths[] = {16, 32, 320};
    union { uint32 align; uint8 bytes[336 * 3]; } sourcePixels;
    AtariDitherLookup saved = s_palette4BitDither;
    uint16 out[242];
    for (unsigned i = 0; i < sizeof(sourcePixels.bytes); i++) sourcePixels.bytes[i] = i * 37 + i / 336;
    for (unsigned policy = 0; policy < 3; policy++) {
        s_palette4BitDither = saved;
        if (policy == 1) {
            for (unsigned c = 0; c < 256; c++)
                for (unsigned y = 0; y < 4; y++)
                    for (unsigned x = 0; x < 4; x++)
                        s_palette4BitDither.pens[y][x][c] = (c + y * 4 + x) & 15;
            s_palette4BitDither.flat = false;
        } else if (policy == 2) {
            for (unsigned c = 0; c < 256; c++)
                Video_Atari_DitherSetPen(&s_palette4BitDither, c, (c * 3) & 15);
        }
        for (unsigned wi = 0; wi < sizeof(widths) / sizeof(*widths); wi++) {
            unsigned width = widths[wi], words = width / 4 * 3;
            AtariDitherSource source = {sourcePixels.bytes, width, 3, width + 16, -3, 32767, -1, -1};
            unsigned mapped = mappedEncodes, pens = penEncodes;
            for (unsigned i = 0; i < sizeof(out) / sizeof(*out); i++) out[i] = 0xa55a;
            Video_Atari_PreparePlanar(&source, NULL, out + 1);
            assert(mappedEncodes - mapped == (policy == 0 ? 1u : 0u));
            assert(penEncodes - pens == (policy == 0 ? 0u : 1u));
            for (unsigned row = 0; row < 3; row++)
                for (unsigned col = 0; col < width; col++) {
                    unsigned colour = sourcePixels.bytes[row * source.stride + col];
                    unsigned py = (32767u - row) & 3, px = (0u - 3 - col) & 3;
                    assert(pixel(out + 1, width, col, row) == s_palette4BitDither.pens[py][px][colour]);
                }
            assert(out[0] == 0xa55a);
            for (unsigned i = 1 + words; i < sizeof(out) / sizeof(*out); i++) assert(out[i] == 0xa55a);
        }
    }
    s_palette4BitDither = saved;
}
static void check_tiles(void)
{
    uint8 rgb[256 * 3], colours[16], src[128];
    uint16 baseline[64], after[64];
    for (unsigned i = 0; i < sizeof(rgb); i++) rgb[i] = i * 19;
    for (unsigned i = 0; i < 16; i++) colours[i] = i * 17;
    for (unsigned i = 0; i < 128; i++) src[i] = i * 37;
    Video_Atari_InitTileMapping(rgb);
    Video_Atari_DecodePlanarTile(src, colours, baseline);
    for (unsigned y = 0; y < 16; y++)
        for (unsigned x = 0; x < 16; x++) {
            unsigned pair = src[y * 8 + x / 2];
            unsigned colour = colours[(x & 1) ? pair & 15 : pair >> 4];
            const uint8 *p = rgb + colour * 3;
            assert(pixel(baseline, 16, x, y) ==
                Palette_FindClosestColor(p[0] & 63, p[1] & 63, p[2] & 63));
        }
    memset(s_palette4BitMap, 15, sizeof(s_palette4BitMap));
    Rebuild_Palette4BitPairMap(0, 256);
    Video_Atari_DecodePlanarTile(src, colours, after);
    assert(!memcmp(baseline, after, sizeof(baseline)));
    /* A nonconstant tile policy must see IBM indices, not prequantized pens. */
    s_tileDither.flat = false;
    for (unsigned c = 0; c < 256; c++)
        for (unsigned y = 0; y < 4; y++)
            for (unsigned x = 0; x < 4; x++)
                s_tileDither.pens[y][x][c] = (c ^ (y * 4 + x)) & 15;
    Video_Atari_DecodePlanarTile(src, colours, after);
    for (unsigned y = 0; y < 16; y++)
        for (unsigned x = 0; x < 16; x++) {
            unsigned pair = src[y * 8 + x / 2];
            unsigned colour = colours[(x & 1) ? pair & 15 : pair >> 4];
            assert(pixel(after, 16, x, y) == ((colour ^ ((y & 3) * 4 + (x & 3))) & 15));
        }
    /* Compatibility wrappers select the active UI palette, not the tile one. */
    uint8 chunky[16 * 3] = {0};
    uint16 compact[12], strided[8];
    Video_Atari_EncodePlanar(chunky, compact, 16, 3);
    Video_Atari_EncodePlanarStrided(chunky + 16, 16, strided, 16, 2);
    for (unsigned i = 0; i < 12; i++) assert(compact[i] == 0xffff);
    for (unsigned i = 0; i < 8; i++) assert(strided[i] == compact[i + 4]);
}
static void check_sweeps(void)
{
    uint8 src[64000];
    uint32 blocks[200], before[200];
    uint16 guarded[16002], *screen = guarded + 1;
    for (unsigned i = 0; i < sizeof(src); i++) src[i] = i * 37 + i / 320 * 13;
    for (unsigned mode = 0; mode < 2; mode++)
        for (unsigned polarity = 0; polarity < 2; polarity++)
            for (unsigned variant = 0; variant < 2; variant++) {
                unsigned top = variant ? 7 : 136;
                mono = mode; s_monoWhiteIsOne = polarity;
                s_planarBackend = mode ? &s_monoBackend : &s_colourBackend;
                Rebuild_Palette4BitPairMap(0, 256);
                for (unsigned i = 0; i < 16002; i++) guarded[i] = 0xa39fu;
                for (unsigned y = 0; y < 200; y++)
                    blocks[y] = variant ? (y >= 7 && y < 18 ? 0x55555 :
                        y >= 19 && y < 22 ? 0x80003 : y >= 23 ? 0xfffff : 0) :
                        y >= 136 ? 0xf0000 : 0;
                memcpy(before, blocks, sizeof(before));
                nativeCalls = sweepCalls = sweepPixels = 0;
#ifdef VIDEO_C2P_STATS
                s_statLineCalls = s_statTickCalls = s_statTickRows = s_statLinePixels = 0;
                s_statDirtyPixels = s_statTickPixels = s_statTickDirty = s_statSpanPixels = 0;
                s_statTopBarPixels = s_statBattlefieldPixels = s_statSidebarPixels = 0;
#endif
                Video_Atari_C2P_ConvertBlocks((uint8 *)screen + top * 160, src + top * 320,
                    blocks, top, 200, variant ? DIRTY_SWEEP_LEGACY : DIRTY_SWEEP_VIEWPORT);
                assert(nativeCalls == (variant ? 13 : 1));
                assert(sweepCalls == nativeCalls && sweepPixels == (variant ? 58544 : 4096));
                assert(sweepKind == (variant ? DIRTY_SWEEP_LEGACY : DIRTY_SWEEP_VIEWPORT));
                assert(!memcmp(before, blocks, sizeof(before)));
                assert(guarded[0] == 0xa39fu && guarded[16001] == 0xa39fu);
#ifdef VIDEO_C2P_STATS
                unsigned wantRows = 0, wantSpan = 0, wantTop = 0, wantBattle = 0, wantSide = 0;
                for (unsigned y = 0; y < 200; y++) {
                    unsigned first = 20, last = 0;
                    for (unsigned col = 0; col < 20; col++)
                        if (blocks[y] & (1u << col)) {
                            if (first == 20) first = col;
                            last = col + 1;
                            if (y < 40) wantTop += 16;
                            else if (col < 16) wantBattle += 16;
                            else wantSide += 16;
                        }
                    if (last) { wantRows++; wantSpan += (last - first) * 16; }
                }
                assert(s_statLineCalls == (variant ? sweepCalls : 0));
                assert(s_statTickCalls == s_statLineCalls);
                assert(s_statTickRows == (variant ? wantRows : 0));
                assert(s_statSpanPixels == (variant ? wantSpan : 0));
                assert(s_statLinePixels == (variant ? sweepPixels : 0));
                assert(s_statDirtyPixels == s_statLinePixels && s_statTickPixels == s_statLinePixels);
                assert(s_statTickDirty == s_statLinePixels);
                assert(s_statTopBarPixels == (variant ? wantTop : 0));
                assert(s_statBattlefieldPixels == (variant ? wantBattle : 0));
                assert(s_statSidebarPixels == (variant ? wantSide : 0));
#endif
                for (unsigned y = 0; y < 200; y++)
                    for (unsigned x = 0; x < 320; x++) {
                        uint8 colour = src[y * 320 + x];
                        bool dirty = (blocks[y] & (1u << (x / 16))) != 0;
                        if (!mode) {
                            unsigned original = 0;
                            for (unsigned p = 0; p < 4; p++)
                                original |= ((0xa39fu >> (15 - (x & 15))) & 1) << p;
                            assert(pixel(screen, 320, x, y) ==
                                (dirty ? s_palette4BitMap[colour] : original));
                        } else {
                            for (unsigned dy = 0; dy < 2; dy++)
                                for (unsigned dx = 0; dx < 2; dx++) {
                                    unsigned px = x * 2 + dx, py = y * 2 + dy;
                                    unsigned actual = (screen[py * 40 + px / 16] >> (15 - (px & 15))) & 1;
                                    unsigned expected = dirty ?
                                        s_palette4BitDither.pens[py & 3][px & 3][colour] ^ !polarity :
                                        (0xa39fu >> (15 - (px & 15))) & 1;
                                    assert(actual == expected);
                                }
                        }
                    }
            }
}
static void check_unit_contrast(void)
{
    uint8 indices[32];
    uint16 pixels[8], normal[8];
    const uint8 sourceCoverage[] = {0, 2, 3, 5, 6, 8, 9, 16};
    const unsigned coverage[] = {0, 4, 8, 12};
    for (unsigned c = 0; c < 8; c++) {
        indices[c * 2] = indices[c * 2 + 1] = sourceCoverage[c];
        indices[16 + c * 2] = indices[16 + c * 2 + 1] = sourceCoverage[c];
    }
    const AtariDitherSource source = {indices, 16, 2, 16, 0, 0, 1, 1};
    Video_Atari_PrepareUnitPlanar(&source, pixels);
    Video_Atari_PreparePlanar(&source, NULL, normal);
    for (unsigned c = 0; c < 8; c++) {
        unsigned normalWhite = 0;
        for (unsigned y = 0; y < 4; y++)
            for (unsigned x = c * 4; x < (c + 1) * 4; x++) {
                unsigned bit = 0x8000u >> (x & 15), offset = y * 2 + x / 16;
                unsigned phase = 15 - y * 4 - (x & 3);
                bool white = ((pixels[offset] & bit) != 0) == s_monoWhiteIsOne;
                assert(white == ((s_paletteMonoLuma[coverage[c / 2]] & (1u << phase)) != 0));
                normalWhite += ((normal[offset] & bit) != 0) == s_monoWhiteIsOne;
            }
        assert(normalWhite == sourceCoverage[c]);
    }
}
static void check_frozen_mono_tiles(void)
{
    uint8 rgb[768], colours[16], src[128];
    uint16 baseline[64], building[64], after[64];
    const uint8 sourceLevels[16] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16};
    const uint8 buildingLevels[16] = {0, 0, 0, 4, 4, 4, 8, 8, 8, 12, 12, 12, 12, 12, 12, 12};
    for (unsigned i = 0; i < sizeof(rgb); i++) rgb[i] = i * 19;
    for (unsigned i = 0; i < 16; i++) {
        colours[i] = i * 17;
        uint8 grey = (sourceLevels[i] * 63 + 8) / 16;
        memset(rgb + colours[i] * 3, grey, 3);
    }
    for (unsigned i = 0; i < sizeof(src); i++) src[i] = i * 37;
    Video_Atari_InitTileMapping(rgb);
    Video_Atari_DecodePlanarTile(src, colours, baseline);
    Video_Atari_DecodePlanarBuildingTile(src, colours, building);
    for (unsigned y = 0; y < 32; y++)
        for (unsigned x = 0; x < 32; x++) {
            unsigned pair = src[y / 2 * 8 + x / 4];
            unsigned nibble = (x & 2) ? pair & 15 : pair >> 4;
            unsigned coverage = sourceLevels[nibble];
            unsigned bit = 15 - (y & 3) * 4 - (x & 3);
            unsigned expected = ((s_paletteMonoLuma[coverage] >> bit) & 1) ^ !s_monoWhiteIsOne;
            assert(((baseline[y * 2 + x / 16] >> (15 - (x & 15))) & 1) == expected);
            unsigned reduced = buildingLevels[nibble];
            expected = ((s_paletteMonoLuma[reduced] >> bit) & 1) ^ !s_monoWhiteIsOne;
            assert(((building[y * 2 + x / 16] >> (15 - (x & 15))) & 1) == expected);
        }
    for (unsigned c = 0; c < 256; c++) s_paletteMonoCoverage[c] = 16 - s_paletteMonoCoverage[c];
    Rebuild_Palette4BitPairMap(0, 256);
    Video_Atari_DecodePlanarTile(src, colours, after);
    assert(!memcmp(baseline, after, sizeof(baseline)));
    Video_Atari_DecodePlanarBuildingTile(src, colours, after);
    assert(!memcmp(building, after, sizeof(building)));
}
int main(void)
{
    AtariDitherPattern patterns[256];
    AtariDitherLookup lookup;
    const unsigned widths[] = {1, 5, 8, 9, 15, 16, 17, 31, 32, 63, 64, 319, 320};
    check_private_surfaces();
    check_tile_composition();
    for (unsigned c = 0; c < 256; c++) {
        s_palette4BitMap[c] = (c * 7) & 15;
        for (unsigned y = 0; y < 4; y++)
            for (unsigned x = 0; x < 4; x++) patterns[c][y][x] = (y * 4 + x) ^ (c & 15);
    }
    Video_Atari_DitherPrepareLookup(&lookup, patterns);
    Rebuild_Palette4BitPairMap(0, 256);
    check_fused_colour();
    s_tileDither = s_palette4BitDither;
    for (unsigned stage = 0; stage < 3; stage++) {
        if (stage == 1) {
            s_palette4BitMap[17] = 3;
            Rebuild_Palette4BitPairMap(17, 1);
        } else if (stage == 2) {
            for (unsigned c = 0; c < 128; c++) s_palette4BitMap[c] = (c * 3) & 15;
            Rebuild_Palette4BitPairMap(0, 128);
        }
        for (unsigned hi = 0; hi < 256; hi++)
            for (unsigned lo = 0; lo < 256; lo++)
                assert(s_palette4BitPairMap[hi * 256 + lo] ==
                    (s_palette4BitMap[hi] << 8 | s_palette4BitMap[lo]));
        for (unsigned w = 0; w < sizeof(widths) / sizeof(*widths); w++) {
            check(patterns, NULL, widths[w], 67, -3, 32767, 1, 1);
            for (int oy = -3; oy <= 0; oy++)
                for (int ox = -3; ox <= 0; ox++)
                    check(patterns, &lookup, widths[w], 67, ox, oy, -1, -1);
        }
        /* Palette updates must not overwrite independently frozen tile policies. */
        for (unsigned c = 0; c < 256; c++)
            for (unsigned y = 0; y < 4; y++)
                for (unsigned x = 0; x < 4; x++)
                    assert(s_tileDither.pens[y][x][c] == ((c * 7) & 15));
    }
    check(patterns, &lookup, 320, 200, -32768, 32767, -1, 1);
    check_composition(patterns, &lookup);
    check_tiles();
    mono = true;
    s_planarBackend = &s_monoBackend;
    for (unsigned c = 0; c < 256; c++)
        for (unsigned y = 0; y < 4; y++)
            for (unsigned x = 0; x < 4; x++)
                patterns[c][y][x] = ((c >> ((x + y * 4) & 7)) ^ x ^ (y >> 1)) & 1;
    Video_Atari_DitherPrepareLookup(&lookup, patterns);
    for (unsigned polarity = 0; polarity < 2; polarity++) {
        s_monoWhiteIsOne = polarity;
        for (unsigned c = 0; c < 256; c++) s_paletteMonoCoverage[c] = c % 17;
        Rebuild_Palette4BitPairMap(0, 256);
        check_unit_contrast();
        for (unsigned w = 0; w < sizeof(widths) / sizeof(*widths); w++) {
            check(patterns, NULL, widths[w], 67, -3, 32767, 1, 1);
            for (int stepY = -1; stepY <= 1; stepY += 2)
                for (int stepX = -1; stepX <= 1; stepX += 2)
                    for (int oy = -3; oy <= 0; oy++)
                        for (int ox = -3; ox <= 0; ox++)
                            check(patterns, &lookup, widths[w], 67, ox, oy, stepX, stepY);
        }
        check(patterns, &lookup, 320, 200, -32768, 32767, -1, 1);
        check_frozen_mono_tiles();
    }
    check_sweeps();
    return 0;
}
"""
        harness = harness.replace("/* BACKEND */", backend_declarations(video)).replace(
            "/* PRODUCTION */", production).replace(
            "/* TILE COMPOSITOR */", function((ROOT / "src/gfx.c").read_text(), "GFX_ComposePlanarTile")
        ).replace("((uint32)src & 1)", "((uintptr_t)src & 1)")
        run_harness(harness)
        run_harness("#define VIDEO_C2P_STATS\n" + harness)


if __name__ == "__main__":
    unittest.main()
