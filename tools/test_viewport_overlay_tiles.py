"""Check drawn overlay tile masks and CPU publication against rectangle gates."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class ViewportOverlayTilesTest(unittest.TestCase):
    def test_geometry_lifecycle_and_cpu_backups(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        names = (
            "Video_Atari_MarkViewportTiles", "Video_Atari_CursorHide",
            "Video_Atari_CursorEraseFull", "Video_Atari_CursorDraw", "Video_Atari_CursorSync",
            "Video_Atari_CursorRectOverlap", "Video_Atari_PlacementRectOverlap",
            "Video_Atari_TileOverlaysOverlap", "Video_Atari_PlanarMergePlain",
            "Video_Atari_PlanarCopyGroup", "Video_Atari_CursorGroup",
            "Video_Atari_CursorBackground", "Video_Atari_CursorWriteGroup",
            "Video_Atari_PlacementBlock", "Video_Atari_PlanarMergeGroup",
            "Video_Atari_PlacementEnd", "Video_Atari_PlacementHide",
            "Video_Atari_DrawPlanarTile", "Video_Atari_DrawPlanarTileFogged",
        )
        generic = function(video, "Video_Atari_PlanarOverlaysOverlap").replace(
            "Video_Atari_PlanarOverlaysOverlap(", "rectangle_overlap(")
        functions = "\n".join(function(video, name) for name in names)
        legacy = "\n".join(
            function(video, name).replace(name + "(", "legacy_" + name + "(").replace(
                "Video_Atari_TileOverlaysOverlap(base, x, y)",
                "rectangle_overlap(base, x, y, 16, 16)")
            for name in ("Video_Atari_DrawPlanarTile", "Video_Atari_DrawPlanarTileFogged")
        )
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
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 200
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
static uint16 screen[16000], expected[16000], expectedClean[16000];
static uint16 cursorPixels[64 * 6 * 4], cursorMasks[64 * 6];
static uint16 s_curSave[64][24], s_curDrawnData[64][24], s_curDrawnMask[64][6];
static uint16 expectedSave[64][24];
static uint16 s_curViewportTiles[10], s_placeViewportTiles[10];
static bool s_curVisible, s_curDrawn, s_curDirty;
static uint8 *s_curDrawnBase;
static uint16 s_curY, s_curH, s_curGroup, s_curGroups, s_curDrawStride;
static uint16 s_curDrawnY, s_curDrawnH, s_curDrawnGroup, s_curDrawnGroups;
static const uint16 *s_curDrawData, *s_curDrawMask;
static const void *s_curKeySprite;
static uint16 s_curSelectedIcon, s_curKeyPal, s_paletteGeneration;
static unsigned g_mouseHiddenDepth, g_mouseLock;
static void GUI_Mouse_Hide(void) { assert(false); }
static void GUI_Mouse_Show(void) { assert(false); }
typedef struct PlacementBlock { uint16 y, group, mask, saved[4]; } PlacementBlock;
static PlacementBlock s_placeBlocks[48 * 3], expectedBlocks[48 * 3];
static uint16 s_placeMask[48][3], s_placeBlockCount, s_placeWidth, s_placeHeight;
static uint16 s_placeDrawnWidth, s_placeDrawnHeight;
static int16 s_placeX, s_placeY, s_placeDrawnX, s_placeDrawnY;
static bool s_placeVisible, s_placeDirty;
static uint8 *s_placeDrawnBase;
static uint8 s_placePen, s_palette4BitMap[256];
static unsigned clears, rectangleChecks;
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)screen; }
static void GFX_Screen_ClearDirtyRect(uint16 x, uint16 y, uint16 r, uint16 b) {
    assert(x < r && y < b && r <= 320 && b <= 200); clears++;
}
static bool Video_Atari_PlanarOverlaysOverlap(uint8 *base, uint16 x, uint16 y,
                                            uint16 w, uint16 h);
static bool rectangle_overlap(uint8 *base, uint16 x, uint16 y, uint16 w, uint16 h);
/* FUNCTIONS */
/* GENERIC */
static bool Video_Atari_PlanarOverlaysOverlap(uint8 *base, uint16 x, uint16 y,
                                            uint16 w, uint16 h) {
    rectangleChecks++;
    return rectangle_overlap(base, x, y, w, h);
}
/* LEGACY */
static void check_all_tiles(void) {
    unsigned before = rectangleChecks;
    for (unsigned row = 0; row < 10; row++) for (unsigned col = 0; col < 15; col++) {
        unsigned x = col * 16, y = 40 + row * 16;
        assert(Video_Atari_TileOverlaysOverlap((uint8 *)screen, x, y) ==
               rectangle_overlap((uint8 *)screen, x, y, 16, 16));
    }
    assert(rectangleChecks == before);
}
static void check_zero(const uint16 tiles[10]) {
    for (unsigned row = 0; row < 10; row++) assert(tiles[row] == 0);
}
static void geometry(void) {
    int xs[] = {-96, -1, 0, 15, 16, 224, 239, 240, 320};
    int ys[] = {-64, 0, 39, 40, 55, 56, 199, 200, 256};
    unsigned widths[] = {0, 1, 16, 48, 96}, heights[] = {0, 1, 16, 48, 64};
    uint16 tiles[10];
    assert(sizeof(s_curViewportTiles) + sizeof(s_placeViewportTiles) == 40);
    for (unsigned x = 0; x < 9; x++) for (unsigned y = 0; y < 9; y++)
        for (unsigned w = 0; w < 5; w++) for (unsigned h = 0; h < 5; h++) {
            Video_Atari_MarkViewportTiles(tiles, xs[x], ys[y], widths[w], heights[h]);
            for (unsigned row = 0; row < 10; row++) {
                assert(!(tiles[row] & 0x8000));
                for (unsigned col = 0; col < 15; col++) {
                    int left = col * 16, top = 40 + row * 16;
                    bool overlaps = widths[w] && heights[h] &&
                        left < xs[x] + (int)widths[w] && left + 16 > xs[x] &&
                        top < ys[y] + (int)heights[h] && top + 16 > ys[y];
                    assert(((tiles[row] >> col) & 1) == overlaps);
                }
            }
        }
}
static void cursor_lifecycle(void) {
    unsigned ys[] = {0, 39, 40, 55, 56, 183, 199};
    unsigned groups[] = {0, 3, 14, 15, 19};
    s_curDrawData = cursorPixels; s_curDrawMask = cursorMasks;
    for (unsigned size = 0; size < 2; size++)
        for (unsigned y = 0; y < 7; y++) for (unsigned g = 0; g < 5; g++) {
        s_curY = ys[y]; s_curH = min(size ? 64 : 17, 200 - s_curY);
        s_curGroup = groups[g]; s_curGroups = min(size ? 6 : 2, 20 - s_curGroup);
        s_curDrawStride = s_curGroups; s_curVisible = true;
        Video_Atari_CursorDraw((uint8 *)screen);
        assert(s_curDrawn); check_all_tiles();
        uint16 drawn[10];
        memcpy(drawn, s_curViewportTiles, sizeof(drawn));
        s_curY = 0; s_curGroup = 19; s_curGroups = s_curDrawStride = 1; s_curDirty = true;
        Video_Atari_CursorDraw((uint8 *)screen);
        assert(!memcmp(drawn, s_curViewportTiles, sizeof(drawn)));
        Video_Atari_CursorSync((uint8 *)screen);
        assert(s_curDrawn); check_zero(s_curViewportTiles); check_all_tiles();
        Video_Atari_CursorEraseFull();
        s_curY = ys[y]; s_curH = min(size ? 64 : 17, 200 - s_curY);
        s_curGroup = groups[g]; s_curGroups = min(size ? 6 : 2, 20 - s_curGroup);
        s_curDrawStride = s_curGroups;
        Video_Atari_CursorDraw((uint8 *)screen);
        assert(!memcmp(drawn, s_curViewportTiles, sizeof(drawn)));
        Video_Atari_CursorHide();
        assert(!memcmp(drawn, s_curViewportTiles, sizeof(drawn)));
        check_all_tiles();
        Video_Atari_CursorSync((uint8 *)screen);
        assert(!s_curDrawn);
        check_zero(s_curViewportTiles); check_all_tiles();
        Video_Atari_CursorDraw((uint8 *)screen);
        assert(!s_curDrawn);
    }
}
static void configure_placement(int x, int y) {
    s_placeX = x; s_placeY = y; s_placeWidth = s_placeHeight = 48;
    memset(s_placeMask, 0, sizeof(s_placeMask));
    for (unsigned row = 0; row < 48; row++) for (unsigned col = 0; col < 3; col++)
        s_placeMask[row][col] = row == 0 || row == 47 ? 0xffff :
                               col == 0 ? 0x8000 : col == 2 ? 1 : 0;
    s_placeVisible = s_placeDirty = true;
    Video_Atari_PlacementEnd((uint8 *)screen);
}
static void placement_lifecycle(void) {
    int xs[] = {-32, -16, 0, 48, 224, 240}, ys[] = {0, 24, 40, 56, 184, 200};
    for (unsigned x = 0; x < 6; x++) for (unsigned y = 0; y < 6; y++) {
        configure_placement(xs[x], ys[y]); check_all_tiles();
        uint16 drawn[10];
        memcpy(drawn, s_placeViewportTiles, sizeof(drawn));
        s_placeX = 240; s_placeY = 200; s_placeDirty = true;
        assert(!memcmp(drawn, s_placeViewportTiles, sizeof(drawn)));
        Video_Atari_PlacementEnd((uint8 *)screen);
        assert(!s_placeBlockCount); check_zero(s_placeViewportTiles);
        Video_Atari_PlacementHide(); check_all_tiles();
    }
}
static void scene(unsigned overlays) {
    assert(!s_curDrawn && !s_placeBlockCount);
    for (unsigned i = 0; i < 16000; i++) screen[i] = i * 137 + 41;
    memset(s_curSave, 0, sizeof(s_curSave)); memset(s_placeBlocks, 0, sizeof(s_placeBlocks));
    s_placeVisible = false; s_curVisible = false;
    if (overlays & 2) configure_placement(64, 72);
    if (overlays & 1) {
        s_curY = 80; s_curH = 17; s_curGroup = 4; s_curGroups = s_curDrawStride = 2;
        for (unsigned row = 0; row < 17; row++) for (unsigned col = 0; col < 2; col++) {
            unsigned i = row * 2 + col;
            cursorMasks[i] = row % 3 ? 0x8001 : 0;
            for (unsigned plane = 0; plane < 4; plane++)
                cursorPixels[i * 4 + plane] = plane == 1 ? cursorMasks[i] : 0;
        }
        s_curDrawData = cursorPixels; s_curDrawMask = cursorMasks; s_curVisible = true;
        Video_Atari_CursorDraw((uint8 *)screen);
    }
    check_all_tiles();
}
static void cpu_publication(void) {
    uint16 pixels[64], fog[64], masks[16], fogMasks[16];
    for (unsigned kind = 0; kind < 2; kind++) for (unsigned mode = 0; mode < 4; mode++)
            for (unsigned overlays = 0; overlays < 4; overlays++)
                for (unsigned legacy = 0; legacy < 2; legacy++) {
                    scene(overlays);
                    for (unsigned row = 0; row < 16; row++) {
                        masks[row] = mode == 2 ? 0x71e3 : 0xffff;
                        fogMasks[row] = mode == 2 ? 0xffff : mode == 3 ? 0x3e71 : 0;
                        for (unsigned p = 0; p < 4; p++) {
                            pixels[row * 4 + p] = mode == 1 ? 0 : row * 317 + p * 137;
                            fog[row * 4 + p] = row * 937 + p * 71;
                        }
                    }
                    const uint16 *copy = mode < 2 ? pixels :
                                         mode == 2 && kind != 0 ? fog : NULL;
                    clears = rectangleChecks = 0;
                    if (kind == 0) {
                        if (legacy) legacy_Video_Atari_DrawPlanarTile(pixels, masks, 64, 72, copy);
                        else Video_Atari_DrawPlanarTile(pixels, masks, 64, 72, copy);
                    } else {
                        if (legacy) legacy_Video_Atari_DrawPlanarTileFogged(
                            pixels, masks, fog, fogMasks, 64, 72, copy);
                        else Video_Atari_DrawPlanarTileFogged(pixels, masks, fog, fogMasks, 64, 72, copy);
                    }
                    assert(clears == 1 && rectangleChecks == 0);
                    if (!legacy) {
                        memcpy(expected, screen, sizeof(expected));
                        memcpy(expectedSave, s_curSave, sizeof(expectedSave));
                        memcpy(expectedBlocks, s_placeBlocks, sizeof(expectedBlocks));
                    } else {
                        assert(!memcmp(expected, screen, sizeof(expected)));
                        assert(!memcmp(expectedSave, s_curSave, sizeof(expectedSave)));
                        assert(!memcmp(expectedBlocks, s_placeBlocks, sizeof(expectedBlocks)));
                    }
                    uint16 placement[10];
                    memcpy(placement, s_placeViewportTiles, sizeof(placement));
                    Video_Atari_CursorEraseFull();
                    check_zero(s_curViewportTiles);
                    assert(!memcmp(placement, s_placeViewportTiles, sizeof(placement)));
                    Video_Atari_PlacementHide();
                    check_zero(s_placeViewportTiles);
                    if (!legacy) memcpy(expectedClean, screen, sizeof(expectedClean));
                    else assert(!memcmp(expectedClean, screen, sizeof(expectedClean)));
                }
}
static void fallback(void) {
    scene(3);
    unsigned xy[][2] = {{240, 40}, {0, 0}, {64, 80}, {64, 50}};
    for (unsigned i = 0; i < 4; i++) {
        unsigned before = rectangleChecks;
        assert(Video_Atari_TileOverlaysOverlap((uint8 *)screen, xy[i][0], xy[i][1]) ==
               rectangle_overlap((uint8 *)screen, xy[i][0], xy[i][1], 16, 16));
        assert(rectangleChecks == before + 1);
    }
    Video_Atari_PlacementHide();
    assert(s_curDrawn); check_zero(s_placeViewportTiles); check_all_tiles();
    Video_Atari_CursorEraseFull(); check_all_tiles();
}
int main(void) {
    s_palette4BitMap[255] = 3;
    geometry(); cursor_lifecycle(); placement_lifecycle(); cpu_publication(); fallback();
    return 0;
}
"""
        harness = harness.replace("/* FUNCTIONS */", functions).replace("/* GENERIC */", generic)
        harness = harness.replace("/* LEGACY */", legacy)
        with tempfile.TemporaryDirectory(prefix="viewport-overlay-tiles-") as directory:
            cfile, binary = Path(directory) / "test.c", Path(directory) / "test"
            cfile.write_text(harness)
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run(["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            *flags, str(cfile), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
