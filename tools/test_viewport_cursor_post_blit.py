"""Compare immediate cursor repair with independent scene compositing."""

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import blitter_model, function


ROOT = Path(__file__).resolve().parents[1]


class ViewportCursorPostBlitTest(unittest.TestCase):
    def test_68000_plain_loop_has_no_stack_spills(self):
        compiler, objdump = "m68k-atari-mint-gcc", "m68k-atari-mint-objdump"
        if shutil.which(compiler) is None or shutil.which(objdump) is None:
            self.skipTest("Atari compiler and objdump required")
        with tempfile.TemporaryDirectory(prefix="viewport-plain-loop-") as directory:
            obj = Path(directory) / "video.o"
            subprocess.run([compiler, "-m68000", "-msoft-float", "-Ofast",
                            "-fno-split-paths", "-fomit-frame-pointer", "-std=gnu17",
                            "-fno-strict-aliasing", "-DTOS", "-DNDEBUG",
                            "-DATARI_SUPERVISOR_RESIDENT=1",
                            "-I", str(ROOT / "include"), "-I", str(ROOT / "objs/release"),
                            "-c", str(ROOT / "src/video/video_atari.c"), "-o", str(obj)],
                           check=True)
            assembly = subprocess.check_output([objdump, "-d", str(obj)], text=True)
            body = re.search(
                r"<_Video_Atari_PublishPlanarSpritePlain>:\n(.*?)(?=\n[0-9a-f]+ <_|\Z)",
                assembly, re.S).group(1)
            start = re.search(r"\bmovew\s+%a[0-6]@\+,%d[0-7]", body).start()
            end = re.search(r"\bmoveml\s+%sp@\+", body[start:]).start() + start
            loop = body[start:end]
            self.assertNotIn("%sp@", loop)
            self.assertRegex(loop, r"\bcmp(?:a)?l\s+%[ad]\d,%[ad]\d")
            self.assertNotIn("jsr", loop)

    def test_pixels_backups_and_movement(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        block = video[video.index("typedef struct PlacementBlock"):
                      video.index("} PlacementBlock;") + len("} PlacementBlock;")]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int16_t int16;
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 200
/* CURSOR LIMITS */
#define CURSOR_MAX_H VIDEO_ATARI_CURSOR_MAX_HEIGHT
#define CURSOR_MAX_GROUPS (VIDEO_ATARI_CURSOR_MAX_WIDTH / 16)
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
/* BLOCK */
static uint16 visible[16000], scene[16000], expected[16000], withoutCursor[16000];
static bool s_curDrawn;
static uint8 *s_curDrawnBase, *s_placeDrawnBase;
static uint16 s_curDrawnY, s_curDrawnH, s_curDrawnGroup, s_curDrawnGroups;
static uint16 s_curSave[CURSOR_MAX_H][CURSOR_MAX_GROUPS * 4];
static uint16 s_curDrawnData[CURSOR_MAX_H][CURSOR_MAX_GROUPS * 4];
static uint16 s_curDrawnMask[CURSOR_MAX_H][CURSOR_MAX_GROUPS];
static uint16 s_curViewportTiles[10], s_placeViewportTiles[10];
static PlacementBlock s_placeBlocks[144];
static uint16 s_placeBlockCount, s_placeDrawnWidth, s_placeDrawnHeight;
static int16 s_placeDrawnX, s_placeDrawnY;
static uint8 s_placePen = 5;
static uint16 tile[64], fog[64], tileMasks[16], fogMasks[16];
static uint16 sprite[640], spriteMasks[160], lookup[1];
static uint8 chunky[64 * 32];
#define s_palette4BitPairMap lookup
static unsigned mergeCalls, repairCalls;
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)visible; }
static void GFX_Screen_ClearDirtyRect(uint16 l, uint16 t, uint16 r, uint16 b) {
    assert(!(l & 15) && !(r & 15) && l < r && r <= 320 && t < b && b <= 200);
}
static void c2p1x1_4_st(uint16 *dst, const uint8 *src, uint16 width, uint16 height,
                       const uint16 *map) {
    assert(height == 1 && map == lookup);
    memset(dst, 0, width / 2);
    for (unsigned x = 0; x < width; x++) for (unsigned p = 0; p < 4; p++)
        if (src[x] & (1u << p)) dst[x / 16 * 4 + p] |= 0x8000u >> (x & 15);
}
/* VIDEO */
static void composite(void) {
    memcpy(withoutCursor, scene, sizeof(scene));
    for (unsigned b = 0; b < s_placeBlockCount; b++) {
        PlacementBlock *block = s_placeBlocks + b;
        unsigned i = block->y * 80 + block->group * 4;
        for (unsigned p = 0; p < 4; p++)
            withoutCursor[i + p] = (withoutCursor[i + p] & (uint16)~block->mask) |
                (s_placePen & (1u << p) ? block->mask : 0);
    }
    memcpy(expected, withoutCursor, sizeof(expected));
    if (!s_curDrawn) return;
    for (unsigned row = 0; row < s_curDrawnH; row++)
        for (unsigned group = 0; group < s_curDrawnGroups; group++) {
            unsigned i = (s_curDrawnY + row) * 80 + (s_curDrawnGroup + group) * 4;
            uint16 mask = s_curDrawnMask[row][group];
            for (unsigned p = 0; p < 4; p++)
                expected[i + p] = (expected[i + p] & (uint16)~mask) |
                    (s_curDrawnData[row][group * 4 + p] & mask);
        }
}
static void check(void) {
    composite();
    assert(!memcmp(visible, expected, sizeof(expected)));
    if (s_curDrawn) for (unsigned row = 0; row < s_curDrawnH; row++)
        for (unsigned group = 0; group < s_curDrawnGroups; group++) {
            unsigned i = (s_curDrawnY + row) * 80 + (s_curDrawnGroup + group) * 4;
            assert(!memcmp(s_curSave[row] + group * 4, withoutCursor + i, 8));
        }
    for (unsigned b = 0; b < s_placeBlockCount; b++) {
        PlacementBlock *block = s_placeBlocks + b;
        assert(!memcmp(block->saved, scene + block->y * 80 + block->group * 4, 8));
    }
}
static void reset(unsigned cursorGroup, unsigned cursorY, unsigned groups, bool placement) {
    mergeCalls = repairCalls = 0;
    s_curDrawn = true; s_curDrawnBase = (uint8 *)visible;
    s_curDrawnGroup = cursorGroup; s_curDrawnY = cursorY;
    s_curDrawnGroups = groups; s_curDrawnH = 24;
    for (unsigned i = 0; i < 16000; i++) scene[i] = i * 137 + 41;
    s_placeBlockCount = 0; s_placeDrawnBase = (uint8 *)visible;
    s_placeDrawnX = 64; s_placeDrawnY = 74;
    s_placeDrawnWidth = 32; s_placeDrawnHeight = 12;
    if (placement) for (unsigned row = 74; row < 86; row++)
        for (unsigned group = 4; group < 6; group++) {
            PlacementBlock *b = s_placeBlocks + s_placeBlockCount++;
            b->y = row; b->group = group; b->mask = row % 3 ? 0x38a1 : 0xffff;
            memcpy(b->saved, scene + row * 80 + group * 4, 8);
        }
    for (unsigned row = 0; row < s_curDrawnH; row++)
        for (unsigned group = 0; group < groups; group++) {
            uint16 mask = row % 4 == 0 ? 0 : row % 4 == 1 ? 0xffff : 0x39a1 >> group;
            s_curDrawnMask[row][group] = mask;
            for (unsigned p = 0; p < 4; p++)
                s_curDrawnData[row][group * 4 + p] = p == 1 ? 0 : mask;
        }
    composite();
    memcpy(visible, expected, sizeof(visible));
    for (unsigned row = 0; row < s_curDrawnH; row++)
        memcpy(s_curSave[row], withoutCursor + (cursorY + row) * 80 + cursorGroup * 4, groups * 8);
    Video_Atari_MarkViewportTiles(s_curViewportTiles, cursorGroup * 16, cursorY, groups * 16, 24);
    Video_Atari_MarkViewportTiles(s_placeViewportTiles, placement ? 64 : 0, 74,
                                placement ? 32 : 0, 12);
}
static void reference_tile(unsigned kind, unsigned x, unsigned y) {
    for (unsigned row = 0; row < 16; row++) {
        uint16 fm = kind == 2 ? fogMasks[row] : kind == 3 ? 0xffff : 0;
        uint16 mask = kind == 0 ? 0xffff : tileMasks[row] | fm;
        for (unsigned p = 0; p < 4; p++) {
            unsigned i = (y + row) * 80 + x / 16 * 4 + p;
            uint16 pixels = (tile[row * 4 + p] & (uint16)~fm) | (fog[row * 4 + p] & fm);
            scene[i] = (scene[i] & (uint16)~mask) | (pixels & mask);
        }
    }
}
static void reference_sprite(bool fallback, int x, int y, unsigned width) {
    for (unsigned row = 0; row < 32; row++) for (unsigned col = 0; col < width; col++) {
        int dx = x + col, dy = y + row;
        if (dx < 0 || dx >= 240 || dy < 40 || dy >= 200) continue;
        uint16 bit = 0x8000u >> (col & 15), dest = 0x8000u >> (dx & 15);
        unsigned group = row * (width / 16) + col / 16;
        if (!(spriteMasks[group] & bit)) continue;
        for (unsigned p = 0; p < 4; p++) {
            unsigned i = dy * 80 + dx / 16 * 4 + p;
            bool colour = fallback ? (chunky[row * 64 + col] & (1u << p)) != 0 :
                (sprite[group * 4 + p] & bit) != 0;
            scene[i] = (scene[i] & (uint16)~dest) | (colour ? dest : 0);
        }
    }
}
int main(void) {
    for (unsigned i = 0; i < 64; i++) { tile[i] = i * 237; fog[i] = i * 139; }
    for (unsigned row = 0; row < 16; row++) {
        tileMasks[row] = row % 4 == 0 ? 0 : row % 4 == 1 ? 0xffff : 0x59a3;
        fogMasks[row] = row % 3 == 0 ? 0 : row % 3 == 1 ? 0x0ec0 : 0xffff;
    }
    for (unsigned i = 0; i < 160; i++) {
        spriteMasks[i] = i % 5 == 0 ? 0 : i % 5 == 1 ? 0xffff : 0x39e7;
        for (unsigned p = 0; p < 4; p++)
            sprite[i * 4 + p] = (i * 311 + p * 971) & spriteMasks[i];
    }
    /* An opaque hardware pen-0 pixel must clear both screen and backup. */
    spriteMasks[51] |= 0x0400;
    for (unsigned p = 0; p < 4; p++) sprite[51 * 4 + p] &= (uint16)~0x0400;
    for (unsigned i = 0; i < sizeof(chunky); i++) chunky[i] = (i * 7 + i / 31) & 15;
    const unsigned positions[][3] = {{4, 74, 2}, {3, 64, 3}, {14, 32, 2}, {4, 8, 2}, {15, 74, 2}};
    for (unsigned place = 0; place < 2; place++) for (unsigned pos = 0; pos < 5; pos++)
        for (unsigned kind = 0; kind < 4; kind++) {
            reset(positions[pos][0], positions[pos][1], positions[pos][2], place);
            unsigned x = pos == 4 ? 240 : pos == 2 ? 224 : 64;
            unsigned y = pos == 3 ? 16 : pos == 2 ? 40 : 72;
            reference_tile(kind, x, y);
            if (kind < 2) Video_Atari_DrawPlanarTile(tile, tileMasks, x, y, kind == 0 ? tile : NULL);
            else Video_Atari_DrawPlanarTileFogged(tile, tileMasks, fog, fogMasks, x, y,
                                                kind == 3 ? fog : NULL);
            check();
            if (!place && pos < 3) assert(mergeCalls == 0);
            if (pos == 0 && !place) assert(repairCalls == 1);
            if (pos == 0 && place) assert(mergeCalls > 0 && repairCalls == 0);
            if (pos >= 3) assert(mergeCalls > 0 && repairCalls == 0);
            Video_Atari_CursorEraseFull();
            assert(!memcmp(visible, withoutCursor, sizeof(visible)));
        }
    const int spritePositions[][2] = {{48, 67}, {-16, 25}, {208, 179}};
    for (unsigned place = 0; place < 2; place++) for (unsigned pos = 0; pos < 3; pos++)
        for (unsigned fallback = 0; fallback < 2; fallback++) {
            if (fallback && pos != 0) continue;
            reset(pos == 2 ? 14 : pos == 1 ? 0 : 4,
                  pos == 2 ? 176 : pos == 1 ? 32 : 74, 2, place);
            int x = fallback ? 48 : spritePositions[pos][0], y = fallback ? 67 : spritePositions[pos][1];
            unsigned width = fallback ? 48 : 80;
            reference_sprite(fallback, x, y, width);
            if (fallback) Video_Atari_PresentSprite(chunky, 64, x, y, width, 32, spriteMasks);
            else Video_Atari_PresentPlanarSprite(sprite, spriteMasks, width, 32, x, y);
            check();
            if (!place) assert(!mergeCalls && repairCalls == 1);
            if (place && pos == 0) assert(mergeCalls > 0 && !repairCalls);
            Video_Atari_CursorEraseFull();
            assert(!memcmp(visible, withoutCursor, sizeof(visible)));
        }
    /* Tile portions retain full source strides and repair overlay backups
     * after every publication, including clipped viewport edges. */
    for (unsigned place = 0; place < 2; place++) for (unsigned pos = 0; pos < 3; pos++) {
        reset(pos == 2 ? 14 : pos == 1 ? 0 : 4,
              pos == 2 ? 176 : pos == 1 ? 32 : 74, 2, place);
        int x = spritePositions[pos][0], y = spritePositions[pos][1];
        for (unsigned col = 0; col < 5; col++) {
            int dx = x + col * 16;
            if (dx < 0 || dx >= 240) continue;
            int top = y < 40 ? 40 : y, bottom = y + 32 > 200 ? 200 : y + 32;
            for (int row = top; row < bottom; ) {
                int end = 40 + ((row - 40) / 16 + 1) * 16;
                if (end > bottom) end = bottom;
                unsigned offset = (row - y) * 5 + col;
                for (int line = row; line < end; line++) {
                    unsigned source = (line - y) * 5 + col;
                    for (unsigned plane = 0; plane < 4; plane++) {
                        unsigned dest = line * 80 + dx / 16 * 4 + plane;
                        scene[dest] = (scene[dest] & (uint16)~spriteMasks[source]) |
                                      (sprite[source * 4 + plane] & spriteMasks[source]);
                    }
                }
                Video_Atari_PresentPlanarSpriteStrided(sprite + offset * 4, spriteMasks + offset,
                                                      16, end - row, dx, row, 80);
                check();
                row = end;
            }
        }
        Video_Atari_CursorEraseFull();
        assert(!memcmp(visible, withoutCursor, sizeof(visible)));
    }
    /* Adjacent publications repair only their own tile, then compose a sprite. */
    reset(4, 74, 3, false);
    for (unsigned x = 64; x <= 80; x += 16) {
        reference_tile(1, x, 72);
        Video_Atari_DrawPlanarTile(tile, tileMasks, x, 72, NULL);
        check();
    }
    reference_sprite(false, 48, 67, 80);
    Video_Atari_PresentPlanarSprite(sprite, spriteMasks, 80, 32, 48, 67);
    check();
    assert(repairCalls == 3 && !mergeCalls);
    Video_Atari_CursorEraseFull();
    assert(!memcmp(visible, withoutCursor, sizeof(visible)));
    reference_tile(0, 64, 72);
    Video_Atari_DrawPlanarTile(tile, tileMasks, 64, 72, tile);
    check();
    assert(repairCalls == 3 && !mergeCalls);
    /* Unshifted publication retains cursor and placement backups for every
     * phase, including edge-clipped single-word shifts and repeated draws. */
    uint16 expandedMasks[640];
    for (unsigned i = 0; i < 160; i++) for (unsigned p = 0; p < 4; p++)
        expandedMasks[i * 4 + p] = spriteMasks[i];
    for (unsigned place = 0; place < 2; place++) for (unsigned phase = 0; phase < 16; phase++) {
        reset(4, 74, 2, place);
        s_viewportBlitter = true;
        unsigned launches = blitterLaunches;
        unsigned sourceX = 16 + ((16 - phase) & 15), width = 16 - phase;
        for (unsigned repeat = 0; repeat < 2; repeat++) {
            for (unsigned row = 0; row < 12; row++) for (unsigned col = 0; col < width; col++) {
                unsigned source = row * 5 + (sourceX + col) / 16;
                uint16 sb = 0x8000u >> ((sourceX + col) & 15), db = 0x8000u >> (phase + col);
                if (!(spriteMasks[source] & sb)) continue;
                for (unsigned p = 0; p < 4; p++) {
                    unsigned dest = (74 + row) * 80 + 4 * 4 + p;
                    scene[dest] = (scene[dest] & (uint16)~db) |
                                  (sprite[source * 4 + p] & sb ? db : 0);
                }
            }
            Video_Atari_PresentPlanarSpriteUnshifted(sprite, expandedMasks, 80, sourceX,
                                                    width, 12, 64 + phase, 74, NULL);
            check();
        }
        assert(!blitterLocks && (place ? mergeCalls != 0 : mergeCalls == 0));
        assert(blitterLaunches == launches + (place ? 0 : 16));
        if (!place) assert(repairCalls == 2);
        Video_Atari_CursorEraseFull();
        assert(!memcmp(visible, withoutCursor, sizeof(visible)));
    }
    /* Full-word backup footprints matter at every viewport clipping edge,
     * including publications confined to one row or one destination word. */
    const unsigned clips[][6] = {
        {13, 0, 40, 67, 25, 0},
        {0, 224, 40, 16, 25, 14},
        {0, 65, 40, 31, 1, 4},
        {0, 65, 191, 31, 9, 4},
        {13, 79, 74, 1, 12, 4}
    };
    for (unsigned c = 0; c < sizeof(clips) / sizeof(clips[0]); c++) {
        unsigned sourceX = clips[c][0], x = clips[c][1], y = clips[c][2];
        unsigned width = clips[c][3], height = clips[c][4];
        reset(clips[c][5], y < 176 ? y : 176, 2, false);
        unsigned launches = blitterLaunches;
        for (unsigned repeat = 0; repeat < 2; repeat++) {
            for (unsigned row = 0; row < height; row++) for (unsigned col = 0; col < width; col++) {
                unsigned source = row * 5 + (sourceX + col) / 16;
                uint16 sb = 0x8000u >> ((sourceX + col) & 15);
                uint16 db = 0x8000u >> ((x + col) & 15);
                if (!(spriteMasks[source] & sb)) continue;
                for (unsigned p = 0; p < 4; p++) {
                    unsigned dest = (y + row) * 80 + ((x + col) / 16) * 4 + p;
                    scene[dest] = (scene[dest] & (uint16)~db) | (sprite[source * 4 + p] & sb ? db : 0);
                }
            }
            Video_Atari_PresentPlanarSpriteUnshifted(sprite, expandedMasks, 80, sourceX,
                                                    width, height, x, y, NULL);
            check();
        }
        assert(blitterLaunches == launches + 16 && !mergeCalls && repairCalls == 2);
        Video_Atari_CursorEraseFull();
        assert(!memcmp(visible, withoutCursor, sizeof(visible)));
    }
    /* Opaque terrain keeps the existing cache but uses one hardware copy. */
    reset(10, 74, 2, false);
    unsigned launches = blitterLaunches;
    reference_tile(0, 64, 72);
    Video_Atari_DrawPlanarTile(tile, tileMasks, 64, 72, tile);
    check();
    assert(blitterLaunches == launches + 1);
    unsigned setups = blitterSetups;
    reference_tile(0, 80, 72);
    Video_Atari_DrawPlanarTile(tile, tileMasks, 80, 72, tile);
    check();
    assert(blitterLaunches == launches + 2 && blitterSetups == setups);
    /* A whole sprite changes mode; the following tile must restore its setup. */
    reference_sprite(false, 49, 106, 80);
    Video_Atari_PresentPlanarSpriteUnshifted(sprite, expandedMasks, 80, 0, 80, 32, 49, 106, NULL);
    check();
    assert(blitterLaunches == launches + 10 && blitterSetups == setups + 1);
    reference_tile(0, 96, 72);
    Video_Atari_DrawPlanarTile(tile, tileMasks, 96, 72, tile);
    check();
    assert(blitterLaunches == launches + 11 && blitterSetups == setups + 2);
    /* Whole-sprite hardware writes refresh cursor backups; placement retains
     * the CPU fallback. Repeated publications must not save cursor pixels. */
    Video_Atari_SpriteBlitPlan plans[16];
    Video_Atari_BuildSpriteBlitPlans(plans, 80, 80);
    for (unsigned place = 0; place < 2; place++) for (unsigned phase = 0; phase < 16; phase++) {
        reset(4, 74, 2, place);
        launches = blitterLaunches;
        for (unsigned repeat = 0; repeat < 2; repeat++) {
            reference_sprite(false, 48 + phase, 67, 80);
            unsigned builds = blitterPlanBuilds;
            Video_Atari_PresentPlanarSpriteUnshifted(sprite, expandedMasks, 80, 0, 80, 32,
                                                    48 + phase, 67, &plans[phase]);
            assert(blitterPlanBuilds == builds);
            check();
        }
        assert(blitterLaunches == launches + (place ? 0 : 16));
        assert(place ? mergeCalls != 0 : mergeCalls == 0);
        if (!place) assert(repairCalls == 2);
        Video_Atari_CursorEraseFull();
        assert(!memcmp(visible, withoutCursor, sizeof(visible)));
    }
    return 0;
}
"""
        names = (
            "Video_Atari_MarkViewportTiles", "Video_Atari_CursorEraseFull",
            "Video_Atari_CursorRectOverlap", "Video_Atari_PlacementRectOverlap",
            "Video_Atari_PlanarOverlaysOverlap", "Video_Atari_TileOverlaysOverlap",
            "Video_Atari_PlanarMergePlain", "Video_Atari_PlanarCopyGroup",
            "Video_Atari_CursorGroup", "Video_Atari_CursorBackground",
            "Video_Atari_CursorWriteGroup", "Video_Atari_PlacementBlock",
            "Video_Atari_PlanarMergeGroup", "Video_Atari_RefreshViewportCursor",
            "Video_Atari_PublishViewportCursorRect", "Video_Atari_DrawPlanarTileFoggedCursor",
            "Video_Atari_PresentSpriteCursor",
            "Video_Atari_PresentPlanarSpriteOverlays",
            "Video_Atari_PublishPlanarSpritePlain",
            "Video_Atari_DrawPlanarTile", "Video_Atari_DrawPlanarTileFogged",
            "Video_Atari_PresentSprite", "Video_Atari_PresentPlanarSpriteStrided",
            "Video_Atari_PresentPlanarSprite",
        )
        production = []
        for name in names:
            if name == "Video_Atari_DrawPlanarTile":
                production.append(blitter_model(video, tiles=True))
            text = function(video, name)
            if name in ("Video_Atari_PlanarMergeGroup", "Video_Atari_RefreshViewportCursor"):
                counter = "mergeCalls" if name.endswith("MergeGroup") else "repairCalls"
                text = text.replace("\n{", "\n{\n    " + counter + "++;", 1)
            production.append(text)
        limits = "\n".join(line for line in (ROOT / "src/video/video.h").read_text().splitlines()
                           if line.startswith(("#define VIDEO_ATARI_CURSOR_MAX_WIDTH",
                                               "#define VIDEO_ATARI_CURSOR_MAX_HEIGHT")))
        harness = harness.replace("/* CURSOR LIMITS */", limits)
        harness = harness.replace("/* BLOCK */", block).replace("/* VIDEO */", "\n".join(production))
        with tempfile.TemporaryDirectory(prefix="viewport-post-blit-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            *flags, str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
