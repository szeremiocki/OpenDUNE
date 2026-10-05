"""Exercise stable, lazy planar tile slots and private cache conversion."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class PlanarTileLazyTest(unittest.TestCase):
    def test_68000_hot_lookup_inlining(self):
        tools = ("m68k-atari-mint-gcc", "m68k-atari-mint-nm")
        if any(shutil.which(tool) is None for tool in tools):
            self.skipTest("Atari compiler and nm required")
        with tempfile.TemporaryDirectory(prefix="tile-lookup-inline-") as directory:
            obj = Path(directory) / "gfx.o"
            subprocess.run([tools[0], "-m68000", "-msoft-float", "-Ofast",
                            "-fno-split-paths", "-fomit-frame-pointer", "-std=gnu17",
                            "-fno-strict-aliasing", "-DTOS", "-DNDEBUG",
                            "-I", str(ROOT / "include"),
                            "-I", str(ROOT / "objs/release"),
                            "-c", str(ROOT / "src/gfx.c"), "-o", str(obj)], check=True)
            symbols = subprocess.check_output([tools[1], str(obj)], text=True)
            self.assertIn(" T _GFX_DrawPlanarTile\n", symbols)
            self.assertIn(" T _GFX_DrawPlanarTileFogged\n", symbols)
            self.assertIn("_GFX_FillPlanarTile", symbols)
            self.assertNotIn("_GFX_GetPlanarTile", symbols)
            self.assertNotIn("_GFX_QueueViewportTile", symbols)

    def test_lazy_fills_and_stable_backgrounds(self):
        gfx = (ROOT / "src/gfx.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        state = gfx[gfx.index("static uint16 *s_planarTiles;"):
                    gfx.index("\nvoid GFX_FreePlanarTiles")]
        initialization = function(gfx, "GFX_InitPlanarTiles")
        self.assertNotIn("GFX_DrawTile(", initialization)
        self.assertNotIn("DecodePlanarTile(", initialization)
        self.assertNotIn("GFX_Screen_SetActive", initialization)
        decoder = function(video, "Video_Atari_DecodePlanarTile")
        self.assertNotIn("PlanarBase", decoder)
        self.assertNotIn("PresentSave", decoder)
        self.assertNotIn("memcpy", decoder)
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
#define HOUSE_MAX 6
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 200
#define TILES 389
static uint8 source[TILES * 128], palettes[32 * 16], table[TILES], rgb[256 * 3];
static uint8 sourceBefore[sizeof(source)], palettesBefore[sizeof(palettes)];
static uint8 *g_tilesPixels = source, *g_iconRPAL = palettes, *g_iconRTBL = table;
static uint16 s_tileWidth = 8, s_tileHeight = 16;
static uint8 s_tileByteSize = 128, s_tileMode;
static bool g_dune2_enhanced, direct = true;
static uint8 s_tilePens[256];
static uint16 s_tilePenPairMap[16 * 256], s_palette4BitPairMap[65536];
static unsigned allocations, failAllocation, warnings, mappings, conversions, publishes;
static unsigned slots, stridedCalls;
static const uint16 *lastPixels;
/* STATE */
static void *allocate(size_t n, bool zero) {
    if (++allocations == failAllocation) return NULL;
    void *p = malloc(n);
    if (p) memset(p, zero ? 0 : 0xa5, n);
    return p;
}
static void *test_malloc(size_t n) { return allocate(n, false); }
static void *test_calloc(size_t n, size_t size) { return allocate(n * size, true); }
#define malloc test_malloc
#define calloc test_calloc
static void Warning(const char *format, ...) { (void)format; warnings++; }
static void Debug(const char *format, ...) { (void)format; }
static bool Video_Atari_CursorDirect(void) { return direct; }
static uint8 Palette_FindClosestColor(uint8 r, uint8 g, uint8 b) {
    mappings++;
    return (r * 3 + g * 5 + b * 7) & 15;
}
static uint8 pen(uint8 colour) {
    const uint8 *p = rgb + colour * 3;
    return ((p[0] & 63) * 3 + (p[1] & 63) * 5 + (p[2] & 63) * 7) & 15;
}
static void encode(uint16 *dst, const uint8 *src, uint16 width, uint16 height,
                   const uint16 *lookup, unsigned srcStride, unsigned dstStride) {
    assert(width != 0 && !(width & 15) && !((uintptr_t)src & 1));
    if (lookup == s_tilePenPairMap)
        assert(dst == s_viewportFogPixels ||
               (dst >= s_planarTiles && dst + (height - 1) * dstStride / 2 + 4 <= s_planarTiles + slots * 64));
    conversions++;
    for (unsigned row = 0; row < height; row++, src += srcStride, dst += dstStride / 2) {
        memset(dst, 0, width / 2);
        for (unsigned x = 0; x < width; x += 2) {
            unsigned index = ((unsigned)src[x] << 8) | src[x + 1];
            if (lookup == s_tilePenPairMap) assert(index < 16 * 256);
            unsigned mapped = lookup[index];
            for (unsigned p = 0; p < 4; p++) {
                if ((mapped >> 8) & (1u << p)) dst[(x >> 4) * 4 + p] |= 0x8000u >> (x & 15);
                if (mapped & (1u << p)) dst[(x >> 4) * 4 + p] |= 0x4000u >> (x & 15);
            }
        }
    }
}
static void c2p1x1_4_st(uint16 *dst, const uint8 *src, uint16 width, uint16 height,
                       const uint16 *lookup) {
    assert(height == 1 || width == 320);
    encode(dst, src, width, height, lookup, 320, 160);
}
static void c2p1x1_4_st_strided(uint16 *dst, const uint8 *src, uint16 width, uint16 height,
                               const uint16 *lookup, uint32 srcStride, uint32 dstStride) {
    assert(height > 1 && srcStride >= width && !(srcStride & 1) && dstStride == width / 2);
    stridedCalls++;
    encode(dst, src, width, height, lookup, srcStride, dstStride);
}
static const uint16 *copy_source(const uint16 *p, const uint16 *m,
                                 const uint16 *f, const uint16 *fm) {
    bool ground = true, overlay = f != NULL;
    for (unsigned row = 0; row < 16; row++) {
        uint16 mask = fm ? fm[row] : 0;
        if ((m[row] | mask) != 0xffff) return NULL;
        if (f && mask) ground = false;
        if (mask != 0xffff) overlay = false;
    }
    return ground ? p : overlay ? f : NULL;
}
static void Video_Atari_DrawPlanarTile(const uint16 *p, const uint16 *m, uint16 x, uint16 y,
                                      const uint16 *copyPixels) {
    assert(p && m && x < 240 && y >= 40);
    assert(copyPixels == copy_source(p, m, NULL, NULL));
    lastPixels = p;
    publishes++;
}
static void Video_Atari_DrawPlanarTileFogged(const uint16 *p, const uint16 *m,
                                           const uint16 *f, const uint16 *fm, uint16 x, uint16 y,
                                           const uint16 *copyPixels) {
    assert(f && fm);
    assert(copyPixels == copy_source(p, m, f, fm) && x < 240 && y >= 40);
    lastPixels = p;
    publishes++;
}
/* VIDEO */
/* GFX */
static void initialize(void) {
    allocations = 0;
    unsigned before = conversions, beforePublishes = publishes, beforeMappings = mappings;
    GFX_InitPlanarTiles(sizeof(source), rgb);
    assert(GFX_PlanarTilesReady() && conversions == before && publishes == beforePublishes);
    assert(mappings == beforeMappings + 256);
    slots = 0;
    for (unsigned i = 0; i < TILES * 6; i++)
        if (s_planarTileIndex[i] >= slots) slots = s_planarTileIndex[i] + 1;
    for (unsigned i = 0; i < slots; i++) {
        assert(!s_planarTileReady[i]);
        for (unsigned word = 0; word < 64; word++) assert(s_planarTiles[i * 64 + word] == 0xa5a5);
    }
    for (unsigned i = 0; i < TILES * 16; i++) assert(s_planarTileMasks[i] == 0xa5a5);
}
static void check(unsigned tile, unsigned house) {
    unsigned index = s_planarTileIndex[house * TILES + tile];
    bool hit = s_planarTileReady[index] != 0;
    unsigned before = conversions;
    assert(GFX_GetPlanarTile(tile, house) == index);
    assert(conversions == before + (hit ? 0 : 1) && s_planarTileReady[index]);
    const uint8 *p = palettes + table[tile] * 16;
    uint16 allMask = 0xffff, anyMask = 0;
    for (unsigned line = 0; line < 16; line++) {
        uint16 expected[4] = {0}, mask = p[0] != 0 ? 0xffff : 0;
        for (unsigned x = 0; x < 16; x++) {
            unsigned packed = source[tile * 128 + line * 8 + x / 2];
            uint8 colour = p[(x & 1) ? packed & 15 : packed >> 4];
            if (colour) mask |= 0x8000u >> x;
            if ((colour & 0xf0) == 0x90 && (colour <= 0x96 || !g_dune2_enhanced))
                colour += house * 16;
            for (unsigned plane = 0; plane < 4; plane++)
                if (pen(colour) & (1u << plane)) expected[plane] |= 0x8000u >> x;
        }
        assert(s_planarTileMasks[tile * 16 + line] == mask);
        allMask &= mask; anyMask |= mask;
        assert(!memcmp(s_planarTiles + index * 64 + line * 4, expected, sizeof(expected)));
    }
    assert(s_planarTileReady[index] == (allMask == 0xffff ? PLANAR_TILE_OPAQUE :
                                        anyMask == 0 ? PLANAR_TILE_EMPTY : PLANAR_TILE_MIXED));
    assert(!memcmp(source, sourceBefore, sizeof(source)));
    assert(!memcmp(palettes, palettesBefore, sizeof(palettes)));
}
int main(void) {
    for (unsigned i = 0; i < sizeof(source); i++) source[i] = (i * 53 + i / 7) & 255;
    for (unsigned tile = 0; tile < TILES; tile++) table[tile] = tile % 32;
    for (unsigned p = 0; p < 32; p++) for (unsigned i = 0; i < 16; i++)
        palettes[p * 16 + i] = p < 2 ? i * 3 : 0x90 + i;
    palettes[0] = 1; palettes[3] = 0; /* Opaque logical colour 0. */
    palettes[16] = 0; palettes[19] = 0; /* Multiple transparent indices. */
    table[3] = table[33] = table[65] = 1;
    memset(source + 3 * 128, 0, 128); /* Entirely empty. */
    memset(source + 33 * 128, 0x11, 128); /* Opaque despite transparency-enabled palette. */
    memset(source + 65 * 128, 0x11, 128);
    memset(source + 65 * 128, 0, 8); /* Mixed, with one completely empty row. */
    for (unsigned i = 0; i < sizeof(rgb); i++) rgb[i] = (i * 11 + i / 13) & 255;
    rgb[0] = rgb[1] = rgb[2] = 0;
    memcpy(sourceBefore, source, sizeof(source));
    memcpy(palettesBefore, palettes, sizeof(palettes));
    for (unsigned enhanced = 0; enhanced < 2; enhanced++) {
        g_dune2_enhanced = enhanced != 0;
        initialize();
        unsigned fixedMappings = mappings;
        const unsigned classes[] = {3, 65, 33};
        for (unsigned ground = 0; ground < 3; ground++)
            for (unsigned overlay = 0; overlay < 3; overlay++)
                for (unsigned separate = 0; separate < 2; separate++) {
                    if (separate) {
                        GFX_DrawPlanarTile(classes[ground], 0, 40, 0);
                        GFX_DrawPlanarTile(classes[overlay], 0, 40, 0);
                    } else GFX_DrawPlanarTileFogged(classes[ground], classes[overlay], 0, 40, 0);
                }
        for (unsigned house = 0; house < 6; house++)
            assert(s_planarTileIndex[house * TILES] == s_planarTileIndex[0]);
        for (unsigned house = 1; house < 6; house++)
            assert(s_planarTileIndex[house * TILES + 2] != s_planarTileIndex[2]);
        /* Cache fills must ignore a currently displayed loading/fade palette. */
        memset(s_palette4BitPairMap, 0xff, sizeof(s_palette4BitPairMap));
        unsigned beforeFogConversions = conversions, beforeFogPublishes = publishes;
        assert(!s_viewportFogReady);
        GFX_DrawPlanarFogTile(0, 40);
        assert(s_viewportFogReady && conversions == beforeFogConversions + 1);
        for (unsigned word = 0; word < 64; word++)
            assert(s_viewportFogPixels[word] == (pen(12) & (1u << (word & 3)) ? 0xffff : 0));
        for (unsigned row = 0; row < 16; row++) assert(s_viewportFogMasks[row] == 0xffff);
        GFX_DrawPlanarFogTile(16, 40);
        assert(conversions == beforeFogConversions + 1 && publishes == beforeFogPublishes + 2);
        unsigned beforePublishes = publishes;
        const uint16 *cached[150][2], *cachedMasks[150][2];
        uint16 saved[150][128], savedMasks[150][32];
        for (unsigned cell = 0; cell < 150; cell++) {
            unsigned tile = cell * 13 % TILES, house = cell % 6;
            unsigned x = cell % 15 * 16, y = 40 + cell / 15 * 16;
            if (cell & 1) GFX_DrawPlanarTileFogged(tile, (tile + 1) % TILES, x, y, house);
            else {
                GFX_DrawPlanarTile(tile, x, y, house);
                GFX_DrawPlanarTile((tile + 2) % TILES, x, y, house);
            }
            unsigned overlay = (tile + ((cell & 1) ? 1 : 2)) % TILES;
            cached[cell][0] = s_planarTiles + s_planarTileIndex[house * TILES + tile] * 64;
            cached[cell][1] = s_planarTiles + s_planarTileIndex[house * TILES + overlay] * 64;
            cachedMasks[cell][0] = s_planarTileMasks + tile * 16;
            cachedMasks[cell][1] = s_planarTileMasks + overlay * 16;
            memcpy(saved[cell], cached[cell][0], 128);
            memcpy(saved[cell] + 64, cached[cell][1], 128);
            memcpy(savedMasks[cell], cachedMasks[cell][0], 32);
            memcpy(savedMasks[cell] + 16, cachedMasks[cell][1], 32);
        }
        assert(publishes == beforePublishes + 225);
        beforePublishes = publishes;
        /* Filling other slots must not relocate or overwrite existing assets. */
        for (unsigned tile = 0; tile < TILES; tile++) for (unsigned house = 0; house < 6; house++)
            check(tile, house);
        assert(publishes == beforePublishes && mappings == fixedMappings);
        for (unsigned cell = 0; cell < 150; cell++) {
            assert(!memcmp(saved[cell], cached[cell][0], 128));
            assert(!memcmp(saved[cell] + 64, cached[cell][1], 128));
            assert(!memcmp(savedMasks[cell], cachedMasks[cell][0], 32));
            assert(!memcmp(savedMasks[cell] + 16, cachedMasks[cell][1], 32));
        }
        unsigned beforeConversions = conversions;
        GFX_DrawPlanarTile(2, 0, 40, 5);
        assert(conversions == beforeConversions);
        assert(lastPixels == s_planarTiles + s_planarTileIndex[5 * TILES + 2] * 64);
        /* The ordinary shared encoder still consumes the active mapping. */
        uint8 chunky[32] = {0};
        uint16 pixels[8] = {0};
        Video_Atari_EncodePlanar(chunky, pixels, 16, 2);
        for (unsigned i = 0; i < 8; i++) assert(pixels[i] == 0xffff);
        GFX_FreePlanarTiles();
        assert(!s_planarTileReady && !s_viewportFogReady && !GFX_PlanarTilesReady());
    }
    for (unsigned failure = 1; failure <= 4; failure++) {
        allocations = 0; failAllocation = failure;
        unsigned beforeWarnings = warnings, beforeConversions = conversions;
        GFX_InitPlanarTiles(sizeof(source), rgb);
        assert(warnings == beforeWarnings + 1 && conversions == beforeConversions);
        assert(!s_planarTiles && !s_planarTileMasks && !s_planarTileIndex && !s_planarTileReady);
    }
    failAllocation = 0;
    /* Exercise compact sprite/window canvases and the unchanged full-width path. */
    union { uint32 aligned; uint8 bytes[320 * 200]; } canvas;
    uint16 planar[320 * 200 / 4 + 4], expected[320 * 200 / 4];
    for (unsigned i = 0; i < sizeof(canvas.bytes); i++) canvas.bytes[i] = i * 11 + i / 31;
    for (unsigned hi = 0; hi < 256; hi++) for (unsigned lo = 0; lo < 256; lo++)
        s_palette4BitPairMap[hi * 256 + lo] = ((hi & 15) << 8) | (lo & 15);
    const unsigned widths[] = {16, 32, 48, 64, 80, 160, 320};
    const unsigned heights[] = {1, 2, 16, 32, 64};
    for (unsigned w = 0; w < sizeof(widths) / sizeof(*widths); w++)
        for (unsigned h = 0; h < sizeof(heights) / sizeof(*heights); h++) {
            unsigned width = widths[w], height = heights[h], words = width * height / 4;
            memset(planar, 0xa5, sizeof(planar));
            memset(expected, 0, words * 2);
            for (unsigned row = 0; row < height; row++) for (unsigned x = 0; x < width; x++)
                for (unsigned p = 0; p < 4; p++) if (canvas.bytes[row * width + x] & (1u << p))
                    expected[row * width / 4 + (x >> 4) * 4 + p] |= 0x8000u >> (x & 15);
            unsigned before = conversions, beforeStrided = stridedCalls;
            Video_Atari_EncodePlanar(canvas.bytes, planar + 2, width, height);
            assert(conversions == before + 1);
            assert(stridedCalls == beforeStrided + (height > 1 && width != 320));
            assert(!memcmp(planar + 2, expected, words * 2));
            assert(planar[0] == 0xa5a5 && planar[1] == 0xa5a5 && planar[words + 2] == 0xa5a5);
        }
    /* A command panel converts straight from SCREEN_1 into a compact slot. */
    const uint8 *panel = canvas.bytes + 42 * 320 + 256;
    const unsigned panelWords = 64 * 82 / 4;
    memset(planar, 0xa5, sizeof(planar));
    memset(expected, 0, panelWords * 2);
    for (unsigned row = 0; row < 82; row++) for (unsigned x = 0; x < 64; x++)
        for (unsigned p = 0; p < 4; p++) if (panel[row * 320 + x] & (1u << p))
            expected[row * 16 + (x >> 4) * 4 + p] |= 0x8000u >> (x & 15);
    unsigned before = conversions, beforeStrided = stridedCalls;
    Video_Atari_EncodePlanarStrided(panel, 320, planar + 2, 64, 82);
    assert(conversions == before + 1 && stridedCalls == beforeStrided + 1);
    assert(!memcmp(planar + 2, expected, panelWords * 2));
    assert(planar[0] == 0xa5a5 && planar[1] == 0xa5a5 && planar[panelWords + 2] == 0xa5a5);
    initialize();
    GFX_DrawPlanarTile(2, 0, 40, 3);
    GFX_FreePlanarTiles();
    assert(!GFX_PlanarTilesReady());
    initialize(); /* Reload must make every stable slot cold again. */
    GFX_FreePlanarTiles();
    direct = false;
    GFX_InitPlanarTiles(sizeof(source), rgb);
    assert(!GFX_PlanarTilesReady());
    direct = true; s_tileMode = 4;
    GFX_InitPlanarTiles(sizeof(source), rgb);
    assert(!GFX_PlanarTilesReady());
    assert(stridedCalls != 0);
    return 0;
}
"""
        harness = harness.replace("/* STATE */", state)
        harness = harness.replace("/* VIDEO */", "\n".join(function(video, name) for name in (
            "Video_Atari_EncodePlanarWithLookup", "Video_Atari_EncodePlanar", "Video_Atari_EncodePlanarStrided",
            "Video_Atari_InitTileMapping", "Video_Atari_DecodePlanarTile")))
        harness = harness.replace("/* GFX */", "\n".join(function(gfx, name) for name in (
            "GFX_TileHouseColor", "GFX_FreePlanarTiles", "GFX_PlanarTilesReady",
            "GFX_FillPlanarTile", "GFX_GetPlanarTile",
            "GFX_DrawPlanarTile", "GFX_DrawPlanarTileFogged", "GFX_DrawPlanarFogTile",
            "GFX_InitPlanarTiles")))
        harness = harness.replace("((uint32)src & 1)", "((uintptr_t)src & 1)")
        with tempfile.TemporaryDirectory(prefix="planar-tile-lazy-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            *flags, str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
