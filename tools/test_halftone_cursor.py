"""Check resident halftone patterns across cursor and placement redraws."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function, inactive_display_list


ROOT = Path(__file__).resolve().parents[1]


class HalftoneCursorTest(unittest.TestCase):
    def test_pattern_residency_and_drawing(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        start = video.index("typedef struct PlacementTint {")
        end = video.index("static PlacementTint s_placeTint;", start)
        production = inactive_display_list() + video[start:end + len("static PlacementTint s_placeTint;")]
        production += "\n" + video[video.index("static const uint16 s_tileCursorPatterns"):
                                  video.index("static const uint16 *s_viewportFogWritable")]
        header = (ROOT / "src/video/video.h").read_text()
        production = header[header.index("typedef enum VideoAtariTileCursorShape"):
                            header.index("} VideoAtariTileCursorShape;") +
                            len("} VideoAtariTileCursorShape;")] + "\n" + production
        helper = function(video, "Video_Atari_SetHalftonePattern")
        helper = helper.replace("(volatile uint16 *)0xFFFF8A00UL", "halftoneRAM")
        helper = helper.replace("halftone[i] = pattern[i];",
                                "{ halftone[i] = pattern[i]; uploads++; }")
        production += "\n" + helper
        for name in ("Video_Atari_PlacementTintBlit", "Video_Atari_PlacementTint",
                     "Video_Atari_TileCursorFrame"):
            production += "\n" + function(video, name)
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int16_t int16;
#define ST_PLANAR_LINE_BYTES 160
#define Atari_SupervisorExec(callback) (callback)()
static bool s_viewportBlitter = true, s_blitterTileSetup;
static void (*g_videoTileCursorTail)(void);
static uint16 s_tileCursorCol, s_tileCursorTop;
static bool g_videoTileCursorRestored;
typedef struct Video_Atari_TileCursorBlit {
    uint8 *dst; const uint16 *pattern; const uint8 *operations;
} Video_Atari_TileCursorBlit;
static Video_Atari_TileCursorBlit g_videoTileCursorBlit;
static const uint16 *s_blitterHalftonePattern;
static uint16 halftoneRAM[16], screen[16000];
static unsigned uploads, launches;
static uint16 mask1, mask2, mask3, xcount, ycount;
static int16 xinc, yinc;
static uint32 destination;
static uint8 ctrl, hop, op, skew;
#define BLITTER_CTRL (&ctrl)
#define BLITTER_ENDMASK1 (&mask1)
#define BLITTER_ENDMASK2 (&mask2)
#define BLITTER_ENDMASK3 (&mask3)
#define BLITTER_DST_XINC (&xinc)
#define BLITTER_DST_YINC (&yinc)
#define BLITTER_XCOUNT (&xcount)
#define BLITTER_YCOUNT (&ycount)
#define BLITTER_HOP (&hop)
#define BLITTER_OP (&op)
#define BLITTER_SKEW (&skew)
#define BLITTER_DST_ADDR (&destination)
static uint16 g_tileCursorPen = 4, g_tileCursorTargetPen = 4;
static uint16 g_placementValidPlane = 1, g_placementInvalidPlane = 3;
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)(uintptr_t)0x100000; }
static void Video_Atari_BlitterStart(void) {
    assert(hop == 1 && skew == 0 && (op == 4 || op == 7));
    assert(mask1 == 0xffff && mask2 == 0xffff && mask3 == 0xffff);
    unsigned index = (destination - 0x100000) / 2;
    for (unsigned row = 0; row < ycount; row++)
    for (unsigned word = 0; word < xcount; word++) {
        assert(index < 16000);
        uint16 pattern = halftoneRAM[row & 15];
        if (op == 7) screen[index] |= pattern;
        else screen[index] &= (uint16)~pattern;
        index += (word + 1 == xcount ? yinc : xinc) / 2;
    }
    launches++;
    ctrl = 0;
}
static void Video_Atari_TileCursorTail(void) {
    const uint16 *pattern = g_videoTileCursorBlit.pattern;
    const uint8 *operations = g_videoTileCursorBlit.operations;
    uint8 *dst = g_videoTileCursorBlit.dst;
    if (s_blitterHalftonePattern != pattern) {
        memcpy(halftoneRAM,pattern,sizeof(halftoneRAM)); uploads += 16;
        s_blitterHalftonePattern = pattern;
    }
    mask1=mask2=mask3=0xffff; xinc=8; yinc=160; xcount=1; hop=1; skew=0;
    s_blitterTileSetup=false;
    for (unsigned p=0; p<4; p++) {
        op=operations[p]; destination=(uint32)(uintptr_t)dst+p*2; ycount=16;
        Video_Atari_BlitterStart();
    }
    hop=2;
    g_videoTileCursorRestored=true;
}
/* PRODUCTION */
static void cursor(unsigned col, unsigned row, VideoAtariTileCursorShape shape, unsigned expectedUploads) {
    unsigned before = launches;
    memset(screen, 0x5a, sizeof(screen));
    Video_Atari_TileCursorFrame(col, row, shape);
    assert(uploads == expectedUploads && launches == before + 4 && hop == 2);
    unsigned offset = (40 + row * 16) * 80 + col * 4;
    for (unsigned y = 0; y < 16; y++)
    for (unsigned p = 0; p < 4; p++) {
        uint16 pattern = halftoneRAM[y];
        uint16 pen = shape == TILE_CURSOR_TARGET ? g_tileCursorTargetPen : g_tileCursorPen;
        uint16 expected = pen & (1u << p) ? 0x5a5a | pattern :
                                                        0x5a5a & (uint16)~pattern;
        assert(screen[offset + y * 80 + p] == expected);
    }
}
static void placement(bool invalid, unsigned expectedUploads) {
    unsigned before = launches;
    memset(screen, 0x5a, sizeof(screen));
    Video_Atari_PlacementTint(32, 72, 32, 32, invalid);
    assert(uploads == expectedUploads && launches == before + 1 && hop == 2);
    unsigned plane = invalid ? g_placementInvalidPlane : g_placementValidPlane;
    for (unsigned y = 0; y < 32; y++)
    for (unsigned word = 0; word < 2; word++)
        assert(screen[(72 + y) * 80 + 8 + word * 4 + plane] ==
               (0x5a5a | (y & 1 ? 0x5555 : 0xaaaa)));
}
int main(void) {
    cursor(1, 1, false, 16);
    cursor(2, 2, false, 16);
    /* Source-only sprite/tile operations change controls, not halftone RAM. */
    hop = 2; op = 3; xinc = 2; yinc = 154; xcount = 4;
    cursor(3, 3, false, 16);
    cursor(3, 3, true, 32);
    g_tileCursorTargetPen = 15;
    cursor(4, 4, true, 32);
    placement(false, 48);
    placement(true, 48);
    cursor(5, 5, true, 64);
    cursor(5, 5, false, 80);
    s_blitterHalftonePattern = NULL;
    cursor(5, 5, false, 96);
    unsigned before = launches;
    Video_Atari_TileCursorFrame(15, 0, false);
    assert(uploads == 96 && launches == before);
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="halftone-cursor-") as directory:
            source, binary = Path(directory) / "check.c", Path(directory) / "check"
            source.write_text(harness.replace("/* PRODUCTION */", production))
            subprocess.run(["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
