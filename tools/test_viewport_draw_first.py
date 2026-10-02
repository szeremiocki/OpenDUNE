"""Compare draw-first restoration against the existing terrain-first renderer."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class ViewportDrawFirstTest(unittest.TestCase):
    def test_equivalence_and_protected_pixels(self):
        gfx = (ROOT / "src/gfx.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        state = gfx[gfx.index("static uint16 *s_planarTiles;"):
                    gfx.index("\nvoid GFX_ViewportBeginRestore")]
        gate = re.search(r"restoreBackground = .*?;", viewport, re.S).group()
        self.assertLess(viewport.index("GFX_ViewportBeginRestore();"),
                        viewport.index("GFX_DrawPlanarTileFogged(t->groundTileID"))
        self.assertLess(viewport.index("/* draw air units */"),
                        viewport.index("GFX_ViewportEndRestore();"))
        self.assertLess(viewport.index("GFX_ViewportEndRestore();"),
                        viewport.index("if (g_changedTilesCount != 0"))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
#define HOUSE_MAX 6
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 200
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
static uint16 visible[16000], underlay[16000], overlayPixels[16000], overlayMasks[4000];
static uint16 initial[16000], expected[16000], expectedUnderlay[16000], beforeRestore[16000];
static uint16 spritePixels[640], spriteMasks[160], fallbackMasks[96];
static uint8 fallbackPixels[48 * 32];
static uint16 s_palette4BitPairMap[1];
static bool overlays;
static unsigned writes, clears, conversions;
/* STATE */
void GFX_ViewportSpriteMasks(const uint16 *masks, uint16 stride,
                             uint16 first, uint16 end, uint16 top, uint16 bottom);
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)visible; }
static bool Video_Atari_PlanarOverlaysOverlap(uint8 *base, uint16 x, uint16 y,
                                           uint16 width, uint16 height) {
    assert(base == (uint8 *)visible && !(x & 15) && !(width & 15));
    assert(x + width <= 240 && y >= 40 && y + height <= 200);
    return overlays;
}
static void GFX_Screen_ClearDirtyRect(uint16 l, uint16 t, uint16 r, uint16 b) {
    assert(!(l & 15) && !(r & 15) && l < r && r <= 240 && t >= 40 && t < b && b <= 200);
    clears++;
}
/* MERGE */
static void Video_Atari_PlanarMergeGroup(uint8 *base, uint16 y, uint16 group,
                                       uint16 mask, const uint16 pixels[4]) {
    assert(base == (uint8 *)visible && overlays);
    unsigned index = y * 80 + group * 4;
    uint16 overlay = overlayMasks[y * 20 + group];
    Video_Atari_PlanarMergePlain(underlay + index, mask, pixels);
    for (unsigned p = 0; p < 4; p++)
        visible[index + p] = (underlay[index + p] & (uint16)~overlay) |
                            (overlayPixels[index + p] & overlay);
    writes++;
}
static void c2p1x1_4_st(uint16 *dst, const uint8 *src, uint16 width, uint16 height,
                       const uint16 *lookup) {
    assert(height == 1 && lookup == s_palette4BitPairMap);
    conversions++;
    memset(dst, 0, width / 2);
    for (unsigned x = 0; x < width; x++) for (unsigned p = 0; p < 4; p++)
        if (src[x] & (1u << p)) dst[(x >> 4) * 4 + p] |= 0x8000u >> (x & 15);
}
/* VIDEO */
static uint16 GFX_GetPlanarTile(uint16 tileID, uint8 houseID) {
    return s_planarTileIndex[(uint32)houseID * s_planarTileCount + tileID];
}
/* GFX */
static bool eligible(bool planarViewport, bool forceRedraw, bool hasScrolled,
                     void *g_unitSelected, uint16 g_dirtyViewportCount) {
    bool restoreBackground;
    /* GATE */
    return restoreBackground;
}
static void reset_screen(void) {
    memcpy(visible, initial, sizeof(visible));
    memcpy(underlay, initial, sizeof(underlay));
    if (overlays) for (unsigned i = 0; i < 4000; i++) for (unsigned p = 0; p < 4; p++)
        visible[i * 4 + p] = (visible[i * 4 + p] & (uint16)~overlayMasks[i]) |
                            (overlayPixels[i * 4 + p] & overlayMasks[i]);
}
static void terrain(unsigned frame) {
    for (unsigned cell = 0; cell < 150; cell++) {
        if ((frame & 1) && (cell * 7 + frame) % 4 != 0) continue;
        unsigned x = (cell % 15) * 16, y = 40 + (cell / 15) * 16;
        unsigned tile = 1 + (cell + frame) % 3, house = (cell + frame) % 6;
        if (cell % 3 == 0) GFX_DrawPlanarTileFogged(tile, 5, x, y, house);
        else {
            GFX_DrawPlanarTile(tile, x, y, house);
            if (cell % 3 == 1) GFX_DrawPlanarTile(4, x, y, house);
        }
    }
}
static void sprite(unsigned width, int x, int y, unsigned phase) {
    unsigned groups = width / 16;
    for (unsigned row = 0; row < 32; row++) for (unsigned group = 0; group < groups; group++) {
        unsigned index = row * groups + group;
        spriteMasks[index] = (row + phase) % 5 == 0 ? 0 :
                             (row + phase) % 5 == 1 ? 0xffff : 0x3c69u >> ((group + phase) & 3);
        for (unsigned p = 0; p < 4; p++)
            spritePixels[index * 4 + p] = (p + group + phase) % 4 == 0 ? 0 : index * 197 + p * 439;
    }
    Video_Atari_PresentPlanarSprite(spritePixels, spriteMasks, width, 32, x, y);
}
static void sprites(unsigned frame) {
    sprite(80, -32 + (frame % 4) * 16, 25 + frame % 17, frame);
    sprite(48, 48, 67 + frame % 11, frame + 1);
    sprite(32, 64, 74 + frame % 11, frame + 2);
    sprite(64, 208 + (frame % 3) * 16, 179 + frame % 23, frame + 3);
    /* Exercise the uncached sprite publisher as well as cached composites. */
    Video_Atari_PresentSprite(fallbackPixels, 48, 96, 87, 48, 32, fallbackMasks);
}
int main(void) {
    s_planarTileCount = 6;
    s_planarTiles = malloc(6 * 6 * 64 * sizeof(*s_planarTiles));
    s_planarTileMasks = malloc(6 * 16 * sizeof(*s_planarTileMasks));
    s_planarTileIndex = malloc(6 * 6 * sizeof(*s_planarTileIndex));
    assert(s_planarTiles && s_planarTileMasks && s_planarTileIndex);
    for (unsigned house = 0; house < 6; house++) for (unsigned tile = 0; tile < 6; tile++) {
        unsigned index = house * 6 + tile;
        s_planarTileIndex[index] = index;
        for (unsigned i = 0; i < 64; i++)
            s_planarTiles[index * 64 + i] = tile == 2 ? 0 : index * 311 + i * 139;
    }
    for (unsigned tile = 0; tile < 6; tile++) for (unsigned row = 0; row < 16; row++) {
        s_planarTileMasks[tile * 16 + row] = tile < 4 ? 0xffff :
            tile == 4 ? (uint16)(0x59a3u << (row & 3)) :
            row % 3 == 0 ? 0xffff : row % 3 == 1 ? 0 : 0x7e38;
    }
    for (unsigned i = 0; i < 16000; i++) {
        initial[i] = i * 137 + 41;
        overlayPixels[i] = i % 4 == 2 ? 0xffff : 0;
    }
    /* Cursor and placement backups include complete affected groups. */
    for (unsigned row = 74; row < 95; row++) {
        overlayMasks[row * 20 + 4] = 0xe731;
        overlayMasks[row * 20 + 5] = 0x1f88;
    }
    for (unsigned i = 0; i < sizeof(fallbackPixels); i++) fallbackPixels[i] = i % 5 == 0 ? 0 : i & 15;
    for (unsigned i = 0; i < 96; i++) fallbackMasks[i] = i % 4 == 0 ? 0xffff : 0xb76d;
    for (unsigned mode = 0; mode < 2; mode++) for (unsigned frame = 0; frame < 40; frame++) {
        overlays = mode != 0;
        reset_screen();
        terrain(frame);
        sprites(frame);
        memcpy(expected, visible, sizeof(expected));
        memcpy(expectedUnderlay, underlay, sizeof(expectedUnderlay));
        reset_screen();
        uint16 beforeQueue[16000];
        memcpy(beforeQueue, visible, sizeof(beforeQueue));
        unsigned oldWrites = writes, oldClears = clears, oldConversions = conversions;
        GFX_ViewportBeginRestore();
        terrain(frame);
        assert(!memcmp(visible, beforeQueue, sizeof(visible)));
        assert(writes == oldWrites && clears == oldClears && conversions == oldConversions);
        assert(s_viewportRestoreCount == (frame & 1 ? 37 + (frame % 4 == 1) : 150));
        sprites(frame);
        memcpy(beforeRestore, overlays ? underlay : visible, sizeof(beforeRestore));
        uint16 protectedMasks[150][16];
        for (unsigned cell = 0; cell < 150; cell++)
            memcpy(protectedMasks[cell], s_viewportTileRestore[cell].coverage, sizeof(protectedMasks[cell]));
        GFX_ViewportEndRestore();
        assert(!s_viewportRestoreActive && s_viewportRestoreCount == 0);
        assert(!memcmp(visible, expected, sizeof(visible)));
        if (overlays) assert(!memcmp(underlay, expectedUnderlay, sizeof(underlay)));
        for (unsigned cell = 0; cell < 150; cell++) {
            assert(s_viewportTileRestore[cell].pixels == NULL);
            for (unsigned row = 0; row < 16; row++) for (unsigned p = 0; p < 4; p++) {
                unsigned index = (40 + cell / 15 * 16 + row) * 80 + (cell % 15) * 4 + p;
                const uint16 *after = overlays ? underlay : visible;
                assert(((after[index] ^ beforeRestore[index]) & protectedMasks[cell][row]) == 0);
            }
        }
    }
    for (unsigned flags = 0; flags < 32; flags++) {
        bool want = (flags & 1) && !(flags & 6) && (flags & 8) && (flags & 16);
        assert(eligible(flags & 1, flags & 2, flags & 4, flags & 8 ? visible : NULL, flags & 16) == want);
    }
    unsigned oldWrites = writes;
    GFX_ViewportBeginRestore();
    GFX_DrawPlanarTile(1, 0, 40, 0);
    GFX_FreePlanarTiles();
    assert(!s_viewportRestoreActive && !s_viewportRestoreCount && !s_planarTiles);
    assert(writes == oldWrites);
    GFX_ViewportBeginRestore();
    GFX_ViewportEndRestore();
    assert(writes == oldWrites);
    return 0;
}
"""
        harness = harness.replace("/* STATE */", state)
        harness = harness.replace("/* MERGE */", function(video, "Video_Atari_PlanarMergePlain"))
        harness = harness.replace("/* VIDEO */", "\n".join(function(video, name) for name in (
            "Video_Atari_PlanarCopyGroup", "Video_Atari_DrawPlanarTile",
            "Video_Atari_DrawPlanarTileFogged", "Video_Atari_RestorePlanarTile",
            "Video_Atari_PresentSprite", "Video_Atari_PresentPlanarSprite")))
        harness = harness.replace("/* GFX */", "\n".join(function(gfx, name) for name in (
            "GFX_ViewportBeginRestore", "GFX_QueueViewportTile", "GFX_ViewportSpriteMasks",
            "GFX_ViewportEndRestore", "GFX_DrawPlanarTile", "GFX_DrawPlanarTileFogged",
            "GFX_FreePlanarTiles")))
        harness = harness.replace("/* GATE */", gate)
        with tempfile.TemporaryDirectory(prefix="viewport-draw-first-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
