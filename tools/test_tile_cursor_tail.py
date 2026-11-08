"""Exercise production cursor tails, drain boundaries and mode isolation."""

from pathlib import Path
import unittest

from tools.test_unit_smoke_damage import run_harness
from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class TileCursorTailTest(unittest.TestCase):
    def test_drains_immediate_writes_and_stable_state(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        gfx = (ROOT / "src/gfx.c").read_text()
        state = video[video.index("static const uint16 s_tileCursorPatterns"):
                      video.index("/* Battlefield tile cursor:")]
        placement = video[video.index("typedef struct PlacementBlock"):
                          video.index("} PlacementBlock;") + len("} PlacementBlock;")]
        tint = video[video.index("typedef struct PlacementTint"):
                     video.index("static PlacementTint s_placeTint;") +
                     len("static PlacementTint s_placeTint;")]
        helpers = "\n".join(function(video, name) for name in (
            "Video_Atari_CursorRectOverlap", "Video_Atari_PlacementRectOverlap",
            "Video_Atari_PlanarOverlaysOverlap", "Video_Atari_CursorGroup",
            "Video_Atari_CursorBackground", "Video_Atari_CursorWriteGroup",
            "Video_Atari_PlacementBlock", "Video_Atari_PlanarMergeGroup",
            "Video_Atari_PlanarCopyGroup", "Video_Atari_PlanarMergePlain",
            "Video_Atari_TileOverlaysOverlap"))
        production = placement + tint + "\n" + helpers + "\n" + state
        production += "\n" + function(video, "Video_Atari_TileCursorFrame")
        production += "\n" + "\n".join(function(video, name) for name in (
            "Video_Atari_RestoreTileCursor",
            "Video_Atari_BlitTile",
            "Video_Atari_PublishViewportCursorRect", "Video_Atari_DrawPlanarTile"))
        production += "\n" + function(gfx, "GFX_ComposePlanarTile")
        production += "\n" + function(gfx, "GFX_DrawPlanarSelectionTile")
        harness = r"""
#include <assert.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "src/gfx.h"
#include "src/house.h"
#include "src/video/video.h"
#include "src/os/endian.h"
#define ST_PLANAR_LINE_BYTES 160
#define lengthof(a) (sizeof(a)/sizeof((a)[0]))
#define CURSOR_MAX_H 48
#define CURSOR_MAX_GROUPS 5
#define Atari_SupervisorExec(callback) (callback)()
#define s_viewportBlitter g_videoViewportBlitter
bool g_videoViewportBlitter = true, g_screenViewportPlanar = true;
static uint16 screen[16000], tile[64], expected[64];
static bool s_curDrawn;
static uint8 *s_curDrawnBase, *s_placeDrawnBase;
static uint16 s_curDrawnY, s_curDrawnH, s_curDrawnGroup, s_curDrawnGroups;
static uint16 s_curSave[CURSOR_MAX_H][CURSOR_MAX_GROUPS * 4];
static uint16 s_curDrawnData[CURSOR_MAX_H][CURSOR_MAX_GROUPS * 4];
static uint16 s_curDrawnMask[CURSOR_MAX_H][CURSOR_MAX_GROUPS];
static uint16 s_placeBlockCount, s_placeDrawnWidth, s_placeDrawnHeight;
static uint16 s_curViewportTiles[10], s_placeViewportTiles[10];
static int16 s_placeDrawnX, s_placeDrawnY;
static uint8 s_placePen;
static const uint16 *s_blitterHalftonePattern;
static bool s_blitterTileSetup;
static uint16 g_tileCursorPen = 4, g_tileCursorTargetPen = 15;
enum { PLANAR_TILE_MIXED = 1, PLANAR_TILE_EMPTY, PLANAR_TILE_OPAQUE };
static uint16 selectionPixels[128], selectionMasks[32];
static uint16 *s_planarTiles = selectionPixels, *s_planarTileMasks = selectionMasks;
static uint16 s_planarTileCount = 2;
static struct {
    uint32 tiles; uint16 style; bool opaque; uint16 pixels[64], masks[16];
} s_selectionTiles[9];
static uint16 GFX_GetPlanarTile(uint16 id, uint8 house) { (void)house; return id; }
static void GFX_PreparePlanarFogTile(void) { assert(false); }
static uint16 *s_viewportFogPixels, *s_viewportFogMasks;
static unsigned executions, frameLaunches, tails, sceneWrites;
static unsigned immediateTiles;
static struct { const uint16 *pixels; uint16 *dst; } s_planarBlit;
static const uint16 *queuedPixels, *queuedMasks;
static uint16 *queuedDst;
void Video_Atari_QueueMaskedTile(const uint16 *pixels, const uint16 *masks, uint16 *dst) {
    queuedPixels = pixels; queuedMasks = masks; queuedDst = dst;
    *g_videoDisplayListNext++ = HTOBE16(0x4e70);
    for (unsigned i = 0; i < 11; i++) *g_videoDisplayListNext++ = 0;
}
void Video_Atari_QueueTile(const uint16 *pixels, uint16 *dst) {
    queuedPixels = pixels; queuedMasks = NULL; queuedDst = dst;
    *g_videoDisplayListNext++ = HTOBE16(0x4e72);
    for (unsigned i = 0; i < 8; i++) *g_videoDisplayListNext++ = 0;
}
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)screen; }
void Video_Atari_TileCursorTail(void) {
    const uint16 *pattern = g_videoTileCursorBlit.pattern;
    const uint8 *operations = g_videoTileCursorBlit.operations;
    uint8 *destination = g_videoTileCursorBlit.dst;
    s_blitterTileSetup = false;
    for (unsigned p = 0; p < 4; p++) {
        for (unsigned row = 0; row < 16; row++) {
            uint16 *dst = (uint16 *)(destination + row*160) + p;
            if (operations[p] == 7) *dst |= pattern[row];
            else { assert(operations[p] == 4); *dst &= (uint16)~pattern[row]; }
        }
        frameLaunches++;
    }
    g_videoTileCursorRestored = true;
}
uint16 endian_bswap16(uint16 v) { return (v >> 8) | (v << 8); }
uint32 endian_bswap32(uint32 v) { return __builtin_bswap32(v); }
void Error(const char *fmt, ...) { (void)fmt; abort(); }
void GFX_Screen_ClearDirtyRect_(uint16 l, uint16 t, uint16 r, uint16 b) {
    (void)l; (void)t; (void)r; (void)b;
}
void Video_Atari_EndViewportProtection(void);
static void Video_Atari_BlitOpaque(void) {
    assert(!g_videoDisplayListActive);
    immediateTiles++;
    for (unsigned y = 0; y < 16; y++)
        memcpy(s_planarBlit.dst+y*80,s_planarBlit.pixels+y*4,8);
}
static void Video_Atari_RefreshViewportCursor(uint8 *base, uint16 first, uint16 end,
    uint16 top, uint16 bottom, const uint16 *masks, uint16 stride);
/* PLACEMENT STATE */
/* PRODUCTION */
#include "src/video/atari_display_list.c"
static void Video_Atari_RefreshViewportCursor(uint8 *base, uint16 first, uint16 end,
    uint16 top, uint16 bottom, const uint16 *masks, uint16 stride) {
    assert(first == 4 && end == 5 && top == 72 && bottom == 88 && stride == 1);
    for (unsigned y = 0; y < 16; y++) {
        assert(masks[y] == 0xffff);
        memcpy(s_curSave[y],screen+(72+y)*80+16,8);
        Video_Atari_CursorWriteGroup(base,72+y,4,s_curSave[y]);
    }
}
static bool queuedCursorTile = true;
void Video_Atari_ExecuteDisplayList(const uint16 *stream) {
    assert(!g_videoDisplayListActive);
    s_blitterHalftonePattern = NULL;
    executions++;
    while (true) {
        uint16 opcode = BETOH16(*stream++);
        if (opcode == 0x4e75) break;
        if (opcode == 0x4e71) {
            if (queuedCursorTile) for (unsigned y = 0; y < 16; y++)
                memcpy(screen + (72+y)*80 + 4*4, tile + y*4, 8);
            sceneWrites++;
        } else if (opcode == 0x4e70 || opcode == 0x4e72) {
            stream += opcode == 0x4e70 ? 11 : 8;
            for (unsigned y = 0; y < 16; y++) for (unsigned p = 0; p < 4; p++) {
                uint16 mask = queuedMasks == NULL ? 0xffff : queuedMasks[y];
                queuedDst[y*80+p] = (queuedDst[y*80+p] & (uint16)~mask) |
                                   (queuedPixels[y*4+p] & mask);
            }
        } else {
            assert(opcode == 0x4eb9);
            uint32 address = (uint32)BETOH16(stream[0]) << 16 | BETOH16(stream[1]);
            assert(address == (uint32)(size_t)Video_Atari_TileCursorTail);
            stream += 2;
            tails++;
            Video_Atari_TileCursorTail();
        }
    }
}
static void append(void) {
    *g_videoDisplayListNext++ = HTOBE16(0x4e71);
}
static void checkFrame(const uint16 *pattern, uint16 pen, bool pointer) {
    for (unsigned y = 0; y < 16; y++) for (unsigned p = 0; p < 4; p++) {
        uint16 value = (tile[y*4+p] & (uint16)~pattern[y]) |
                        ((pen & (1u << p)) ? pattern[y] : 0);
        expected[y*4+p] = value;
        if (pointer) {
            assert(s_curSave[y][p] == value);
            value = (value & (uint16)~s_curDrawnMask[y][0]) | s_curDrawnData[y][p];
        }
        assert(screen[(72+y)*80 + 16+p] == value);
    }
}
static void writeScene(bool pointer) {
    static uint16 masks[16]; for (unsigned y = 0; y < 16; y++) masks[y] = 0xffff;
    assert(pointer == s_curDrawn);
    s_curViewportTiles[2] = pointer ? 1u << 4 : 0;
    Video_Atari_DrawPlanarTile(tile,masks,64,72,NULL);
}
int main(void) {
    for (unsigned i = 0; i < 64; i++) tile[i] = i*137+41;
    Video_Atari_BeginViewportProtection(true,4,2,false);
    assert(g_videoTileCursorTail == Video_Atari_TileCursorTail);
    assert((uint16 *)g_videoTileCursorBlit.dst == screen + 72*80 + 16);
    Video_Atari_TileCursorBlit retainedFrame = g_videoTileCursorBlit;
    assert(!g_videoTileCursorTiles[2]);
    assert(!Video_Atari_ViewportProtectionOverlap(64,72,16,16));
    Video_Atari_DisplayListBegin();
    s_placeTint.dst = (uint8 *)screen;
    s_placeTint.pattern = tile;
    s_placeTint.pen = 7;
    PlacementTint retainedTint = s_placeTint;
    Video_Atari_DisplayListFlush();
    assert(!executions && !tails && !frameLaunches);
    queuedCursorTile = false;
    g_tileCursorPen = 7; /* the current tail keeps its prepared pen */
    append(); Video_Atari_DisplayListFlush();
    assert(executions == 1 && !tails && !frameLaunches);
    Video_Atari_DisplayListCheck(VIDEO_ATARI_DISPLAY_CURSOR_BYTES);
    Video_Atari_QueueTileCursor(); Video_Atari_DisplayListFlush();
    assert(executions == 2 && tails == 1 && frameLaunches == 4);
    for (unsigned y = 0; y < 16; y++) for (unsigned p = 0; p < 4; p++)
        assert(screen[(72+y)*80+16+p] == (p == 2 ? s_tileCursorPatterns[0][y] : 0));
    g_tileCursorPen = 4;
    queuedCursorTile = true;
    append();
    Video_Atari_DisplayListFlush(); /* occupied cache eviction */
    assert(tails == 1 && frameLaunches == 4);
    assert(!memcmp(&s_placeTint,&retainedTint,sizeof(retainedTint)));
    for (unsigned y = 0; y < 16; y++)
        assert(!memcmp(screen+(72+y)*80+16,tile+y*4,8));
    append(); Video_Atari_DisplayListFlush(); /* another drain in the same frame */
    assert(tails == 1 && frameLaunches == 4);
    append(); Video_Atari_QueueTileCursor(); Video_Atari_DisplayListEnd();
    assert(tails == 2 && frameLaunches == 8);
    checkFrame(s_tileCursorPatterns[0],4,false);
    assert(!memcmp(&g_videoTileCursorBlit,&retainedFrame,sizeof(retainedFrame)));
    Video_Atari_TileCursorFrame(4,2,false); /* no duplicate final redraw */
    assert(frameLaunches == 8);
    Video_Atari_EndViewportProtection();
    assert(!g_videoTileCursorTail);

    Video_Atari_BeginViewportProtection(true,4,2,true);
    s_blitterTileSetup = true;
    s_blitterHalftonePattern = tile;
    writeScene(false); /* immediate writer before list construction */
    assert(frameLaunches == 12 && !s_blitterTileSetup);
    assert(s_blitterHalftonePattern == NULL);
    checkFrame(s_tileCursorPatterns[1],15,false);
    Video_Atari_DisplayListBegin();
    uint16 retainedScreen[16000]; memcpy(retainedScreen, screen, sizeof(screen));
    writeScene(false); /* active list: no screen write or immediate cursor repair */
    assert(frameLaunches == 12 && Video_Atari_DisplayListPending());
    assert(g_videoDisplayListNext - g_videoDisplayListLimit + 32767 == 12);
    assert(!memcmp(retainedScreen, screen, sizeof(screen)));
    Video_Atari_DisplayListCheck(65534);
    assert(frameLaunches == 12);
    for (unsigned i = 0; i < 32767; i++) *g_videoDisplayListNext++ = HTOBE16(0x4e71);
    Video_Atari_DisplayListCheck(6); /* full payload drains before explicit cursor */
    assert(tails == 2 && frameLaunches == 12 && !Video_Atari_DisplayListPending());
    writeScene(false);
    assert(frameLaunches == 12); /* queued until the explicit final cursor */
    Video_Atari_QueueTileCursor();
    Video_Atari_DisplayListEnd(); Video_Atari_EndViewportProtection();
    assert(frameLaunches == 16);

    /* Classic-pointer publication stays backup-aware with tile mode inactive. */
    s_curDrawn = true; s_curDrawnBase = (uint8 *)screen;
    s_curDrawnY = 72; s_curDrawnH = 16; s_curDrawnGroup = 4; s_curDrawnGroups = 1;
    for (unsigned y = 0; y < 16; y++) {
        s_curDrawnMask[y][0] = y & 1 ? 0x81f0 : 0x000f;
        for (unsigned p = 0; p < 4; p++)
            s_curDrawnData[y][p] = p == 1 ? s_curDrawnMask[y][0] : 0;
        memcpy(s_curSave[y],tile+y*4,8);
        Video_Atari_CursorWriteGroup((uint8 *)screen,72+y,4,tile+y*4);
    }
    writeScene(true);
    assert(frameLaunches == 16 && !g_videoTileCursorTail);
    for (unsigned y = 0; y < 16; y++) for (unsigned p = 0; p < 4; p++) {
        assert(s_curSave[y][p] == tile[y*4+p]);
        assert(screen[(72+y)*80+16+p] ==
               ((tile[y*4+p] & (uint16)~s_curDrawnMask[y][0]) | s_curDrawnData[y][p]));
    }
    s_curDrawn = false; s_curViewportTiles[2] = 0;

    for (unsigned y = 0; y < 16; y++) memcpy(screen+(72+y)*80+16,tile+y*4,8);
    Video_Atari_BeginViewportProtection(true,5,3,true);
    retainedFrame = g_videoTileCursorBlit;
    Video_Atari_TileCursorFrame(0,0,false); /* standalone draw preserves pending tail */
    assert(!memcmp(&g_videoTileCursorBlit,&retainedFrame,sizeof(retainedFrame)));
    assert(!g_videoTileCursorRestored);
    unsigned before = frameLaunches;
    Video_Atari_TileCursorFrame(5,3,true);
    assert(frameLaunches == before + 4);
    uint16 opaqueMasks[16]; for (unsigned y = 0; y < 16; y++) opaqueMasks[y] = 0xffff;
    Video_Atari_DrawPlanarTile(tile,opaqueMasks,16,72,NULL); /* unrelated immediate write */
    assert(frameLaunches == before + 8);
    Video_Atari_TileCursorFrame(5,3,true);
    assert(frameLaunches == before + 8);
    for (unsigned y = 0; y < 16; y++)
        assert(!memcmp(screen+(72+y)*80+16,tile+y*4,8)); /* old frame is gone */
    Video_Atari_EndViewportProtection();

    before = frameLaunches;
    unsigned previousTails = tails;
    Video_Atari_BeginViewportProtection(false,4,2,false);
    Video_Atari_DisplayListBegin();
    append(); Video_Atari_DisplayListEnd();
    assert(tails == previousTails && frameLaunches == before);
    Video_Atari_EndViewportProtection();

    Video_Atari_BeginViewportProtection(true,14,9,true);
    for (unsigned y = 184; y < 200; y++) {
        screen[y*80+55] = 0x1357; screen[y*80+60] = 0x2468;
    }
    Video_Atari_DisplayListBegin();
    queuedCursorTile = false;
    append(); Video_Atari_QueueTileCursor(); Video_Atari_DisplayListEnd();
    for (unsigned y = 184; y < 200; y++) {
        assert(screen[y*80+55] == 0x1357 && screen[y*80+60] == 0x2468);
        for (unsigned p = 0; p < 4; p++)
            assert(screen[y*80+56+p] == s_tileCursorPatterns[1][y-184]);
    }
    Video_Atari_EndViewportProtection();

    uint16 fog[16]; for (unsigned y = 0; y < 16; y++) fog[y] = 0xa55a;
    Video_Atari_SetViewportFog(4,2,fog);
    Video_Atari_BeginViewportProtection(true,4,2,false);
    assert(Video_Atari_ViewportProtectionOverlap(64,72,16,16));
    assert(Video_Atari_ViewportWritable(4,2) == fog); /* no cursor bits in fog mask */
    Video_Atari_EndViewportProtection();
    g_videoViewportBlitter = false;
    Video_Atari_BeginViewportProtection(true,4,2,false);
    assert(!g_videoTileCursorTail && g_videoTileCursorTiles[2] == (1u << 4));
    for (unsigned y = 0; y < 16; y++)
        assert(s_tileCursorFogWritable[y] == (fog[y] & (uint16)~s_tileCursorPatterns[0][y]));
    Video_Atari_EndViewportProtection();
    Video_Atari_ResetViewportProtection();

    /* Cache construction is offscreen; replacing a queued slot drains first. */
    g_videoViewportBlitter = true;
    for (unsigned y = 0; y < 16; y++) {
        selectionMasks[y] = selectionMasks[16+y] = 0x0180;
        for (unsigned p = 0; p < 4; p++) {
            selectionPixels[y*4+p] = 0x1357 + y + p;
            selectionPixels[64+y*4+p] = 0x2468 + y + p;
        }
    }
    Video_Atari_BeginViewportProtection(true,4,2,false);
    Video_Atari_DisplayListBegin();
    memcpy(retainedScreen,screen,sizeof(screen));
    before = frameLaunches;
    GFX_DrawPlanarSelectionTile(0,0,64,72,0,GFX_SELECTION_LEFT,15);
    assert(frameLaunches == before && !memcmp(retainedScreen,screen,sizeof(screen)));
    assert(queuedPixels == s_selectionTiles[0].pixels && queuedMasks == s_selectionTiles[0].masks);
    uint16 firstPixels[64], firstMasks[16];
    memcpy(firstPixels,queuedPixels,sizeof(firstPixels)); memcpy(firstMasks,queuedMasks,sizeof(firstMasks));
    GFX_DrawPlanarSelectionTile(1,0,64,72,0,GFX_SELECTION_LEFT,15);
    assert(frameLaunches == before); /* old slot executed without an implicit cursor */
    for (unsigned y = 0; y < 16; y++) for (unsigned p = 0; p < 4; p++) {
        uint16 old = retainedScreen[(72+y)*80+16+p];
        uint16 value = (old & (uint16)~firstMasks[y]) | (firstPixels[y*4+p] & firstMasks[y]);
        assert(screen[(72+y)*80+16+p] == value);
    }
    Video_Atari_QueueTileCursor(); Video_Atari_DisplayListEnd();
    assert(frameLaunches == before+4);
    for (unsigned y = 0; y < 16; y++) for (unsigned p = 0; p < 4; p++) {
        uint16 old = retainedScreen[(72+y)*80+16+p], mask = s_selectionTiles[0].masks[y];
        uint16 value = (old & (uint16)~mask) | (s_selectionTiles[0].pixels[y*4+p] & mask);
        value = (value & (uint16)~s_tileCursorPatterns[0][y]) |
                (p == 2 ? s_tileCursorPatterns[0][y] : 0);
        assert(screen[(72+y)*80+16+p] == value);
    }
    Video_Atari_EndViewportProtection();
    /* Actual capture case: opaque selected tiles enqueue without cursor repair. */
    for (unsigned i = 0; i < 32; i++) selectionMasks[i] = 0xffff;
    Video_Atari_BeginViewportProtection(true,4,2,false);
    Video_Atari_DisplayListBegin();
    s_planarBlit.pixels = tile; s_planarBlit.dst = screen;
    memcpy(retainedScreen,screen,sizeof(screen));
    before = frameLaunches;
    unsigned oldExecutions = executions;
    GFX_DrawPlanarSelectionTile(0,0,64,72,0,GFX_SELECTION_LEFT,15);
    assert(s_selectionTiles[0].opaque && queuedMasks == NULL);
    assert(frameLaunches == before && executions == oldExecutions && !immediateTiles);
    assert(s_planarBlit.pixels == tile && s_planarBlit.dst == screen);
    assert(!memcmp(retainedScreen,screen,sizeof(screen)));
    uint16 *begin = g_videoDisplayListNext - 9;
    GFX_DrawPlanarSelectionTile(1,0,64,72,0,GFX_SELECTION_LEFT,15);
    assert(frameLaunches == before && executions == oldExecutions+1);
    assert(g_videoDisplayListNext == begin+9);
    Video_Atari_QueueTileCursor(); Video_Atari_DisplayListEnd();
    assert(frameLaunches == before+4 && !immediateTiles);
    for (unsigned y = 0; y < 16; y++) for (unsigned p = 0; p < 4; p++) {
        uint16 value = s_selectionTiles[0].pixels[y*4+p];
        value = (value & (uint16)~s_tileCursorPatterns[0][y]) |
                (p == 2 ? s_tileCursorPatterns[0][y] : 0);
        assert(screen[(72+y)*80+16+p] == value);
    }
    before = frameLaunches;
    GFX_DrawPlanarSelectionTile(1,0,64,72,0,GFX_SELECTION_LEFT,15);
    assert(immediateTiles == 1 && frameLaunches == before+4);
    Video_Atari_EndViewportProtection();
    Video_Atari_DisplayListFree();
    return 0;
}
"""
        harness = harness.replace("/* PLACEMENT STATE */",
                                  placement + "\nstatic PlacementBlock s_placeBlocks[144];")
        production = production[len(placement):]
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_tile_cursor_excludes_pointer_and_placement(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        state = viewport[viewport.index("static bool s_tileCursorShown"):
                         viewport.index("/* Runs before the dirty scan")]
        production = function(video, "Video_Atari_PlacementCursor")
        production += "\n" + function(viewport, "GUI_Widget_Viewport_PlacementDirty")
        production += "\n" + state
        production += "\n" + function(viewport, "GUI_Widget_Viewport_PlacementPrepare")
        harness = r"""
#include <assert.h>
#include "types.h"
#include "src/tile.h"
#define SELECTIONTYPE_PLACE 1
static bool s_curSuppress, s_curDrawn = true, s_curDirty;
static uint16 s_curDrawnGroup = 4, s_curDrawnY = 72, s_curDrawnH = 16;
static bool s_placeTintShown, s_placeTintInvalid;
static int16 s_placeTintX, s_placeTintY, s_placeTintW, s_placeTintH;
static uint16 g_tileCursor = 1, g_mouseDisabled, g_mouseX = 64, g_mouseY = 72;
static uint16 g_cursorSpriteID, g_viewportPosition;
static uint16 g_selectionType, g_selectionRectanglePosition, g_minimapPosition;
static uint16 g_selectionWidth = 1, g_selectionHeight = 1, g_selectionState = 1;
static unsigned erases, repairs;
static uint16 repaired[16];
static void Video_Atari_CursorEraseFull(void) { erases++; s_curDrawn = false; }
static void Map_Update(uint16 tile, uint16 type, bool ignoreInvisible) {
    assert(type == 0 && ignoreInvisible && repairs < 16);
    repaired[repairs++] = tile;
}
/* PRODUCTION */
static void prepare(void) {
    GUI_Widget_Viewport_TileCursorPrepare(GUI_Widget_Viewport_PlacementPrepare());
}
int main(void) {
    prepare();
    assert(s_tileCursorShown && GUI_Widget_Viewport_TileCursorActive());
    assert(s_curSuppress && !s_curDrawn && s_curDirty && erases == 1);
    assert(repairs == 1 && repaired[0] == Tile_PackXY(4,2));
    prepare(); assert(repairs == 1); /* no unnecessary terrain damage */
    g_mouseX = 80; prepare();
    assert(repairs == 3 && repaired[1] == Tile_PackXY(4,2) &&
           repaired[2] == Tile_PackXY(5,2)); /* repair old and new tiles */
    g_selectionType = SELECTIONTYPE_PLACE; prepare();
    assert(!s_tileCursorShown && s_placeTintShown && s_curSuppress);
    g_selectionType = 0; prepare();
    assert(s_tileCursorShown && !s_placeTintShown && s_curSuppress);
    g_mouseX = 250; prepare();
    assert(!s_tileCursorShown && !GUI_Widget_Viewport_TileCursorActive() && !s_curSuppress);
    g_mouseX = 64;
    for (g_cursorSpriteID = 1; g_cursorSpriteID <= 4; g_cursorSpriteID++) {
        prepare(); assert(!s_tileCursorShown && !s_curSuppress);
    }
    prepare(); assert(s_tileCursorShown && s_tileCursorTarget && s_curSuppress);
    g_mouseDisabled = 1; prepare();
    assert(!s_tileCursorShown && !s_curSuppress);
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))


if __name__ == "__main__":
    unittest.main()
