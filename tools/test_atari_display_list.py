"""Check flat launch emission, viewport capacity control and CPU barriers."""

from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

from tools.test_unit_smoke_damage import run_harness
from tools.test_viewport_sprite_cache import function
from tools.test_dither_preparation import colour_tile_compositor

ROOT = Path(__file__).resolve().parents[1]


class DisplayListTest(unittest.TestCase):
    def test_cpu_cursor_handoff_with_an_active_display_list(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        start = viewport.index("\tif (planarViewport && s_tileCursorShown &&")
        handoff = viewport[start:viewport.index("\n\ts_viewportSpriteFilterActive = false;", start)]
        harness = r"""
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "types.h"
#include "src/video/video.h"
#include "src/os/endian.h"
bool g_videoViewportBlitter, g_videoScrollPending;
void (*g_videoTileCursorTail)(void);
static unsigned cpuFrames, nativeFrames, terrainWrites;
static bool planarViewport = true, s_tileCursorShown = true, damage = true;
static bool s_viewportSpriteFilterActive;
static uint16 s_tileCursorCol = 3, s_tileCursorRow = 2;
static VideoAtariTileCursorShape s_tileCursorShape = TILE_CURSOR_TARGET;
uint16 endian_bswap16(uint16 v) { return __builtin_bswap16(v); }
uint32 endian_bswap32(uint32 v) { return __builtin_bswap32(v); }
void Video_Atari_FinishScroll(void) { assert(false); }
static void native_cursor(void) { nativeFrames++; }
void Video_Atari_ExecuteDisplayList(const uint16 *stream)
{
    assert(!g_videoDisplayListActive && *stream++ == HTOBE16(0x4e71));
    terrainWrites++;
    if (*stream == HTOBE16(0x4eb9)) {
        uint32 address;
        memcpy(&address, stream + 1, sizeof(address));
        assert(BETOH32(address) == (uint32)(uintptr_t)native_cursor);
        native_cursor();
        stream += 3;
    }
    assert(*stream == HTOBE16(0x4e75));
}
#include "src/video/atari_display_list.c"
void Video_Atari_TileCursorFrame(uint16 col, uint16 row, VideoAtariTileCursorShape shape)
{
    assert(col == 3 && row == 2 && shape == TILE_CURSOR_TARGET);
    Video_Atari_DisplayListFlush();
    assert(!Video_Atari_DisplayListPending());
    cpuFrames++;
}
static bool GUI_Widget_Viewport_SpriteDamageRect(int16 l, int16 t, int16 r, int16 b, bool force)
{
    assert(l == 48 && t == 72 && r == 64 && b == 88 && force);
    return damage;
}
static void handoff(void)
{
/* HANDOFF */
}
int main(void)
{
    for (unsigned active = 0; active < 2; active++)
        for (unsigned native = 0; native < 2; native++)
            for (unsigned damaged = 0; damaged < 2; damaged++) {
                cpuFrames = nativeFrames = terrainWrites = 0;
                damage = damaged;
                g_videoViewportBlitter = active;
                g_videoTileCursorTail = native ? native_cursor : NULL;
                Video_Atari_DisplayListBegin();
                if (active) *g_videoDisplayListNext++ = HTOBE16(0x4e71);
                handoff();
                if (damaged && (!active || !native)) {
                    assert(cpuFrames == 1 && nativeFrames == 0);
                    assert(terrainWrites == active);
                } else assert(cpuFrames == 0 && nativeFrames == 0);
                Video_Atari_DisplayListEnd();
                assert(nativeFrames == (active && native && damaged));
                assert(terrainWrites == active);
            }
    Video_Atari_DisplayListFree();
    return 0;
}
"""
        run_harness(harness.replace("/* HANDOFF */", handoff))

    def test_native_cursor_tail_longword_store(self):
        compiler = shutil.which("m68k-atari-mint-gcc")
        if compiler is None:
            self.skipTest("m68k-atari-mint-gcc is unavailable")
        assembly = subprocess.check_output([
            compiler, "-m68000", "-msoft-float", "-Ofast", "-fno-split-paths",
            "-fomit-frame-pointer", "-std=gnu17", "-DNDEBUG", "-DTOS",
            "-I" + str(ROOT / "include"), "-S", "-o", "-",
            str(ROOT / "src/video/atari_display_list.c")], text=True)
        for name in ("_Video_Atari_QueueTileCursor",):
            start = assembly.index(name + ":")
            end = assembly.find("\n\t.even", start)
            self.assertGreater(end, start)
            body = assembly[start:end]
            self.assertNotIn("%d2", body, name)
            self.assertRegex(body, r"move\.l (?:%[da][01]|_g_videoTileCursorTail),2\(%a[01]\)")
            self.assertNotIn("jsr _memcpy", body, name)

    def test_arena_capacity_and_cpu_barrier(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        harness = r"""
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "src/video/video.h"
#include "src/os/endian.h"
bool g_videoViewportBlitter;
bool g_videoScrollPending;
void Video_Atari_FinishScroll(void) { assert(false); }
static unsigned executions, commands;
static uint16 screen[16000], source = 0x5678;
#undef Video_Atari_Mono
#define Video_Atari_Mono() false
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define Video_Atari_GroupWords() 4
#define Video_Atari_PlanarBase() ((uint8 *)screen)
#define Video_Atari_ViewportProtectionOverlap(...) false
#define Video_Atari_PresentProtectedSprite(p,m,...) ((void)(p), (void)(m), assert(false))
#define Video_Atari_PlanarOverlaysOverlap(...) false
#define Video_Atari_PresentPlanarSpriteOverlays(...) assert(false)
#define Video_Atari_PublishMonoSpriteRows(...) assert(false)
#define Video_Atari_PublishSpriteRows(...) assert(false)
#define GFX_Screen_ClearDirtyRect(...) ((void)0)
#define s_spriteHighlightEffect 0
uint16 endian_bswap16(uint16 v) { return (v >> 8) | (v << 8); }
uint32 endian_bswap32(uint32 v) { return __builtin_bswap32(v); }
void Error(const char *fmt, ...) { (void)fmt; abort(); }
void (*g_videoTileCursorTail)(void);
void Video_Atari_RestoreTileCursor(void) {}
void Video_Atari_ExecuteDisplayList(const uint16 *stream) {
    assert(!g_videoDisplayListActive);
    executions++;
    while (*stream != HTOBE16(0x4e75)) {
        assert(*stream++ == HTOBE16(0x4e71));
        commands++; screen[40 * 80] = source;
    }
}
#include "src/video/atari_display_list.c"
/* CPU */
static void append(void) {
    *g_videoDisplayListNext++ = HTOBE16(0x4e71);
}
int main(void) {
    Video_Atari_DisplayListBegin();
    assert(!g_videoDisplayListActive);
    Video_Atari_DisplayListCheck(2);
    g_videoViewportBlitter = true;
    Video_Atari_DisplayListBegin();
    uint16 *first = g_videoDisplayListNext;
    first[0] = 0xa55a;
    Video_Atari_DisplayListEnd();
    assert(!executions && first[0] == 0xa55a);
    Video_Atari_DisplayListBegin();
    Video_Atari_DisplayListCheck(VIDEO_ATARI_DISPLAY_LIST_BYTES - 2);
    for (unsigned i = 0; i < VIDEO_ATARI_DISPLAY_LIST_BYTES / 2 - 1; i++) append();
    assert(!executions && g_videoDisplayListNext == g_videoDisplayListLimit);
    Video_Atari_DisplayListCheck(2);
    assert(executions == 1 && commands == VIDEO_ATARI_DISPLAY_LIST_BYTES / 2 - 1 &&
           g_videoDisplayListNext == first);
    append();
    assert(executions == 1);
    uint16 pixels[4] = {0xabcd,1,2,3}, masks[1] = {0x00ff};
    Video_Atari_PresentPlanarSpriteStrided(pixels, masks, 16, 1, 0, 40, 16);
    assert(executions == 2 && screen[40 * 80] == 0x56cd);
    source = 0x1357; append();
    Video_Atari_DisplayListFlush(); /* eviction barrier precedes mutation */
    source = 0xffff;
    assert(screen[40 * 80] == 0x1357 && executions == 3);
    Video_Atari_DisplayListEnd();
    Video_Atari_DisplayListBegin();
    Video_Atari_DisplayListEnd();
    assert(executions == 3);
    Video_Atari_DisplayListFree();
    assert(!g_videoDisplayListNext && !g_videoDisplayListLimit);
    Video_Atari_DisplayListBegin();
    assert(g_videoDisplayListNext == first && !Video_Atari_DisplayListPending());
    append();
    Video_Atari_DisplayListFree();
    assert(executions == 4 && !g_videoDisplayListActive);
    return 0;
}
"""
        cpu = "\n".join(function(video, name) for name in (
            "Video_Atari_PlanarMergePlain", "Video_Atari_PlanarCopyGroup",
            "Video_Atari_PublishPlanarSpritePlain", "Video_Atari_PublishCompactSpriteRows",
            "Video_Atari_PresentPlanarSpriteStrided"))
        run_harness(harness.replace("/* CPU */", cpu))

    def test_unconditional_eviction_and_terrain_retag(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        gfx = (ROOT / "src/gfx.c").read_text()
        cache = function(gui, "GUI_ViewportPlanarSprite")
        start = cache.index("\t\tfor (i = 0; i < VIEWPORT_PLANAR_SPRITES;",
                            cache.index("if (!visible) return;"))
        choose = cache[start:cache.index("\n\t\tentry = victim;", start)]
        harness = r"""
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "src/video/video.h"
#include "src/os/endian.h"
bool g_videoViewportBlitter = true;
bool g_videoScrollPending;
bool g_videoAtariMono;
#include "src/video/atari_mono.c"
void Video_Atari_FinishScroll(void) { assert(false); }
static unsigned executions;
static const uint16 *queued;
static uint16 displayed;
uint16 endian_bswap16(uint16 v) { return (v >> 8) | (v << 8); }
uint32 endian_bswap32(uint32 v) { return __builtin_bswap32(v); }
void Error(const char *fmt, ...) { (void)fmt; abort(); }
void (*g_videoTileCursorTail)(void);
void Video_Atari_ExecuteDisplayList(const uint16 *stream) {
    assert(!g_videoDisplayListActive && *stream == HTOBE16(0x4e71));
    displayed = *queued; executions++;
}
#include "src/video/atari_display_list.c"
#define VIEWPORT_PLANAR_SPRITES 64
typedef struct {
    struct { uint32 main; } key;
    uint16 used, pixels;
} ViewportPlanarSprite;
static ViewportPlanarSprite s_viewportPlanarSprites[64];
static ViewportPlanarSprite *victim(void) {
    ViewportPlanarSprite *victim = NULL;
    uint16 i;
    /* VICTIM */
    return victim;
}
#define PLANAR_TILE_MIXED 1
#define PLANAR_TILE_EMPTY 2
#define PLANAR_TILE_OPAQUE 3
static uint16 indices[3] = {0,1,2}, *s_planarTileHouse[1] = {indices};
static uint16 tiles[192], tileMasks[48];
static uint16 *s_planarTiles = tiles, *s_planarTileMasks = tileMasks;
static uint8 ready[3] = {3,3,3}, *s_planarTileReady = ready;
static uint8 s_planarCompositeReady[160], s_planarRowSlot[64];
static uint32 s_planarCompositeTag[160];
static uint16 s_planarComposites[160][64], s_planarCompositeMasks[160][16];
static uint16 GFX_FillPlanarTile(uint16 tile, uint8 house, uint16 index) {
    (void)tile; (void)house; (void)index; assert(false); return 0;
}
/* TERRAIN */
static void append(const uint16 *source) {
    queued = source; *g_videoDisplayListNext++ = HTOBE16(0x4e71);
}
int main(void) {
    Video_Atari_DisplayListBegin();
    for (unsigned i=0; i<64; i++) {
        s_viewportPlanarSprites[i].key.main=i+1;
        s_viewportPlanarSprites[i].used=i+1;
        s_viewportPlanarSprites[i].pixels=0x1000+i;
    }
    append(&s_viewportPlanarSprites[63].pixels);
    assert(victim() == &s_viewportPlanarSprites[0]);
    assert(executions == 1 && displayed == 0x103f); /* victim need not be referenced */
    s_viewportPlanarSprites[0].key.main=0;
    append(&s_viewportPlanarSprites[63].pixels);
    assert(victim() == &s_viewportPlanarSprites[0] && executions == 1);
    Video_Atari_DisplayListFlush();
    for (unsigned i=0; i<192; i++) tiles[i]=0x1111*(i/64+1);
    for (unsigned i=0; i<48; i++) tileMasks[i]=0xffff;
    assert(GFX_PlanarCompositeSlot(0,1,0,0) == 0);
    append(s_planarComposites[0]);
    assert(GFX_PlanarCompositeSlot(0,1,0,0) == 0 && executions == 2);
    assert(GFX_PlanarCompositeSlot(0,2,0,0) == 0);
    assert(executions == 3 && displayed == 0x2222 && s_planarComposites[0][0] == 0x3333);
    Video_Atari_DisplayListEnd(); Video_Atari_DisplayListFree();
    return 0;
}
"""
        terrain = colour_tile_compositor((ROOT / "src/video/video_atari.c").read_text())
        terrain += "\n" + "\n".join(function(gfx, name) for name in (
            "GFX_ComposePlanarTile", "GFX_PlanarCompositeSlot"))
        run_harness(harness.replace("/* VICTIM */", choose).replace("/* TERRAIN */", terrain))

    def test_viewport_ownership_and_eviction_boundaries(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        gui = (ROOT / "src/gui/gui.c").read_text()
        gfx = (ROOT / "src/gfx.c").read_text()
        backend = (ROOT / "src/video/atari_display_list.c").read_text()
        runner = (ROOT / "src/video/atari_display_list_runner.s").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        draw = function(viewport, "GUI_Widget_Viewport_Draw")
        self.assertLess(draw.index("GUI_Widget_Viewport_DebugBegin"),
                        draw.index("Video_Atari_DisplayListBegin"))
        self.assertLess(draw.index("Video_Atari_QueueTileCursor"),
                        draw.index("Video_Atari_EndViewportProtection"))
        self.assertLess(draw.index("Video_Atari_EndViewportProtection"),
                        draw.index("GUI_DrawText_Planar"))
        self.assertLess(draw.index("GUI_DrawText_Planar"),
                        draw.index("Video_Atari_DisplayListEnd"))
        self.assertNotIn("g_videoTileCursorTail", function(backend, "Video_Atari_DisplayListFlush"))
        self.assertIn("Video_Atari_BeginViewportProtection(s_tileCursorShown,", draw)
        self.assertIn("DisplayListCheck(VIDEO_ATARI_DISPLAY_TILE_ROW_BYTES)",
                      function(viewport, "GUI_Widget_Viewport_RepairTiles"))
        cache = function(gui, "GUI_ViewportPlanarSprite")
        self.assertLess(cache.index("if (victim->key.main != 0) Video_Atari_DisplayListFlush()"),
                        cache.index("memset(entry->pixels"))
        composite = function(gfx, "GFX_PlanarCompositeSlot")
        self.assertLess(composite.index("Video_Atari_DisplayListFlush"),
                        composite.index("GFX_ComposePlanarTile"))
        for text, name in ((gui, "GUI_FreeViewportSpriteCache"), (gfx, "GFX_FreePlanarTiles")):
            body = function(text, name)
            self.assertLess(body.index("Video_Atari_DisplayListFlush"), body.index("free("))
        self.assertNotRegex(backend + runner, r"pinCount|s_pins|s_bottom|s_previous")
        self.assertNotIn("DisplayListFlush", runner)
        for name in ("Video_Atari_QueueMaskedBlit", "Video_Atari_QueueTintBlit",
                     "Video_Atari_PlacementTintBlit"):
            body = function(video, name)
            self.assertNotIn("DisplayListCheck", body)
            self.assertNotIn("DisplayListFlush", body)

    def test_native_flat_stream_and_pixels(self):
        try:
            import unicorn
            from unicorn import m68k_const as registers
        except ImportError:
            self.skipTest("Optional Unicorn CPU-only instruction execution required")
        tools = ("m68k-atari-mint-gcc", "m68k-atari-mint-ld", "m68k-atari-mint-nm",
                 "m68k-atari-mint-objcopy", "vasmm68k_mot")
        if any(shutil.which(tool) is None for tool in tools):
            self.skipTest("Atari cross compiler/assembler required")
        video = (ROOT / "src/video/video_atari.c").read_text()
        block = video[video.index("typedef struct PlanarBlit {"):
                      video.index("static PlanarBlit s_planarBlit;") + len("static PlanarBlit s_planarBlit;")]
        production = "\n".join(function(video, name) for name in (
            "Video_Atari_DisplayExecute", "Video_Atari_ExecuteDisplayList",
            "Video_Atari_BlitterDestinationFits", "Video_Atari_InitBlitterDestination",
            "Video_Atari_DisplayMoveLong", "Video_Atari_DisplayGeometry",
            "Video_Atari_DisplayPattern", "Video_Atari_DisplayPlane",
            "Video_Atari_QueueMaskedBlit", "Video_Atari_BuildSpriteBlitPlan",
            "Video_Atari_BuildSpriteBlitGeometry",
            "Video_Atari_CompileSpriteBlit", "Video_Atari_CompileSpriteBlitCode",
            "Video_Atari_QueueSpriteBlitCode", "Video_Atari_QueueSpriteBlitGeometry",
            "Video_Atari_ExecuteSpriteBlitCode", "Video_Atari_ExecuteSpriteBlitGeometry",
            "Video_Atari_BlitCompiledSprite", "Video_Atari_BlitterSetup", "Video_Atari_BlitterStart",
            "Video_Atari_BlitMaskedHighlight", "Video_Atari_SpriteWordOffset",
            "Video_Atari_PresentPlanarSpriteUnshifted",
            "Video_Atari_SetHalftonePattern",
            "Video_Atari_QueueTintBlit", "Video_Atari_PlacementTintBlit",
            "Video_Atari_PlacementTint"))
        production += "\n" + video[video.index("static const uint8 s_tileCursorOperations"):
                                  video.index("static const uint16 *s_viewportFogWritable")]
        macros = video[video.index("#define BLITTER_SRC_XINC"):video.index("#define BLITTER_SKEW")]
        macros += video[video.index("#define BLITTER_SKEW"):video.index("\n", video.index("#define BLITTER_SKEW"))]
        source = r"""
#include <assert.h>
#include <stddef.h>
#include "types.h"
#include "src/video/video.h"
#include "src/os/endian.h"
#define ST_PLANAR_LINE_BYTES 160
#define ATARI_SUPERVISOR_RESIDENT 1
enum { SCREEN_HEIGHT = 200 };
bool g_videoDisplayListActive, g_videoBlitterTileSetup;
bool g_videoScrollPending;
bool g_videoViewportBlitter, g_atariSupervisorResident;
bool g_videoAtariMono;
static uint16 s_spriteHighlightEffect;
static const struct { uint8 spriteYShift; bool blitterSpriteEffects; }
    testBackend[2] = {{0, true}, {1, false}};
#define s_planarBackend (&testBackend[g_videoAtariMono])
uint8 *g_videoPlanarBase;
#define s_planarBase g_videoPlanarBase
#define s_viewportBlitter g_videoViewportBlitter
static bool s_blitterDestinationWord;
extern void Video_Atari_ConfigureBlitterDestination(uint32 wordOnly, uint32 mono);
uint16 s_curViewportTiles[10];
uint16 *s_planarTileHouse[6], *s_planarTiles;
uint8 *s_planarTileReady;
uint32 restoredCursor;
void Video_Atari_RestoreTileCursor(void) {
    restoredCursor++;
}
uint16 *g_videoDisplayListNext, *g_videoDisplayListLimit;
#define s_blitterTileSetup g_videoBlitterTileSetup
const uint16 *g_videoBlitterHalftonePattern;
#define s_blitterHalftonePattern g_videoBlitterHalftonePattern
static const uint16 *s_displayStream;
#define Atari_SupervisorExec(callback) (callback)()
#define Video_Atari_PlanarBase() g_videoPlanarBase
#define Video_Atari_ViewportProtectionOverlap(...) false
#define Video_Atari_CursorRectOverlap(...) false
#define Video_Atari_PlacementRectOverlap(...) false
#define Video_Atari_PlanarOverlaysOverlap(...) false
static unsigned unexpectedFallback;
static bool s_monoWhiteIsOne, tintOverlap;
static uint16 g_placementInvalidPlane, g_placementValidPlane;
#undef Video_Atari_PlanarOverlaysOverlap
#define Video_Atari_PlanarOverlaysOverlap(...) tintOverlap
#define Video_Atari_MonoPenWords(...) (unexpectedFallback++)
#define Video_Atari_PlanarMergeGroup(...) (unexpectedFallback++)
void Video_Atari_DisplayListCheck(uint16 bytes) {
    if (g_videoDisplayListLimit - g_videoDisplayListNext < bytes / 2) unexpectedFallback++;
}
void Video_Atari_DisplayListFlush(void) { unexpectedFallback++; }
#define Video_Atari_PresentProtectedSprite(...) (unexpectedFallback++)
#define Video_Atari_RefreshViewportCursorUnshifted(...) (unexpectedFallback++)
#define Video_Atari_PublishSpriteRows(...) (unexpectedFallback++)
#define GFX_Screen_ClearDirtyRect(...) ((void)0)
extern void Video_Atari_RunDisplayList(const uint16 *stream);
void Video_Atari_FinishScroll(void) { assert(false); }
extern void Video_Atari_BlitPlaneCode(void);
typedef struct PlacementTint {
    uint8 *dst; const uint16 *pattern; uint16 words,height,pen;
} PlacementTint;
static PlacementTint s_placeTint;
Video_Atari_TileCursorBlit g_videoTileCursorBlit;
bool g_videoTileCursorRestored;
/* MACROS */
/* BLOCK */
/* FUNCTIONS */
bool TestDestination(uint32 base, bool enabled) {
    g_videoPlanarBase = (uint8 *)(size_t)base;
    g_videoViewportBlitter = enabled;
    Video_Atari_InitBlitterDestination();
    return s_blitterDestinationWord;
}
void TestPlan(Video_Atari_SpriteBlitPlan *out, uint16 sx, uint16 width, uint16 phase) {
    Video_Atari_BuildSpriteBlitPlan(out,32,sx,width,phase);
}
void TestMasked(const uint16 *pixels, const uint16 *masks, uint16 *dst,
    const Video_Atari_SpriteBlitPlan *plan, const Video_Atari_SpriteBlitCode *code,
    uint16 effect, bool protected, uint16 line, const uint16 *pattern) {
    s_planarBlit.pixels=pixels; s_planarBlit.masks=masks; s_planarBlit.dst=dst;
    s_planarBlit.plan=plan; s_planarBlit.code=code; s_planarBlit.height=4;
    s_planarBlit.writable=pattern; s_planarBlit.firstLine=line;
    s_spriteHighlightEffect=effect;
    Video_Atari_QueueMaskedBlit(protected);
}
void TestTint(uint16 *dst, const uint16 *pattern) {
    Video_Atari_SpriteBlitPlan plan = {8,8,0xffff,0xffff,0xffff,8,152,2,0};
    Video_Atari_QueueTintBlit(&plan, pattern, 0x0107, dst, 4);
}
void TestMonoTint(uint32 x, uint32 y, uint32 width, uint32 height, uint32 flags) {
    s_monoWhiteIsOne = (flags & 2) != 0;
    tintOverlap = (flags & 4) != 0;
    Video_Atari_PlacementTint(x, y, width, height, flags & 1);
}
void TestQueueSprite(const Video_Atari_SpriteBlitCode *code,
    const uint16 *pixels, const uint16 *masks, uint16 *dst, uint16 height,
    const Video_Atari_SpriteBlitPlan *plan, const Video_Atari_SpriteBlitGeometry *geometry) {
    if (geometry != NULL)
        Video_Atari_QueueSpriteBlitGeometry(code,pixels,masks,dst,height,geometry);
    else
        Video_Atari_QueueSpriteBlitCode(code,pixels,masks,dst,height,plan);
}
void TestHalftone(const uint16 *pattern) {
    Video_Atari_SetHalftonePattern(pattern);
}
void TestHighlight(uint16 effect) {
    s_spriteHighlightEffect=effect;
}
unsigned TestFallback(void) {
    return unexpectedFallback;
}
void TestCursorFrame(uint8 *dst, const uint16 *pattern, uint16 pen) {
    g_videoTileCursorBlit.dst=dst; g_videoTileCursorBlit.pattern=pattern;
    g_videoTileCursorBlit.operations=s_tileCursorOperations[pen];
    Video_Atari_TileCursorTail();
}
"""
        source = source.replace("/* MACROS */", macros).replace("/* BLOCK */", block)
        source = source.replace("/* FUNCTIONS */", production)
        with tempfile.TemporaryDirectory(prefix="flat-display-list-") as directory:
            directory = Path(directory)
            cfile, cobj = directory / "test.c", directory / "test.o"
            cfile.write_text(source)
            subprocess.run([tools[0], "-std=gnu17", "-m68000", "-msoft-float", "-fleading-underscore", "-O2", "-DNDEBUG", "-DTOS",
                            "-fomit-frame-pointer", "-I" + str(ROOT), "-I" + str(ROOT / "include"),
                            "-c", str(cfile), "-o", str(cobj)], check=True)
            objects = [cobj]
            for name in ("atari_display_list_runner", "atari_sprite_blit", "atari_viewport_tile"):
                obj = directory / (name + ".o")
                subprocess.run([tools[4], "-m68000", "-Faout", "-quiet", "-o", str(obj),
                                str(ROOT / "src/video" / (name + ".s"))], check=True)
                objects.append(obj)
            stub, obj = directory / "cpu.s", directory / "cpu.o"
            stub.write_text(" xdef _TestCPUCode\n_TestCPUCode:\n"
                            " move.l #$a5a55a5a,(a2)\n move.l #$01234567,d3\n"
                            " move.l #$dead0000,a5\n rts\n")
            subprocess.run([tools[4], "-m68000", "-Faout", "-quiet", "-o", str(obj), str(stub)], check=True)
            elf, binary = directory / "test.elf", directory / "test.bin"
            subprocess.run([tools[1], "-m", "m68kelf", "-Ttext", "0x10000", "-o", str(elf),
                            *map(str, objects), str(obj)], check=True)
            subprocess.run([tools[3], "-O", "binary", str(elf), str(binary)], check=True)
            table = subprocess.check_output([tools[2], "-n", str(elf)], text=True)
            symbols = {m[2]: int(m[1], 16) for m in
                       re.finditer(r"^([0-9a-f]+) [A-Za-z] (\S+)$", table, re.M)}
            cpu = unicorn.Uc(unicorn.UC_ARCH_M68K, unicorn.UC_MODE_BIG_ENDIAN)
            cpu.ctl_set_cpu_model(registers.UC_CPU_M68K_M68000)
            cpu.mem_map(0, 0x100000)
            cpu.mem_map(0xffff8000, 0x1000)
            cpu.mem_write(0x10000, binary.read_bytes())
            pending, latch = False, 0xa39fbc71

            def read(address, size):
                return int.from_bytes(cpu.mem_read(address, size), "big")

            def write(address, value, size):
                cpu.mem_write(address, (value & ((1 << (size * 8)) - 1)).to_bytes(size, "big"))

            def reg(name):
                return getattr(registers, "UC_M68K_REG_" + name)

            def call(name, args=(), inputs=None):
                sp = 0xf0000
                cpu.mem_write(sp, struct.pack(">" + "I" * (len(args) + 1), 0x1000, *args))
                cpu.reg_write(reg("A7"), sp)
                for key, value in (inputs or {}).items():
                    cpu.reg_write(reg(key), value)
                cpu.emu_start(symbols[name], 0x1000, count=100000)
                self.assertEqual(cpu.reg_read(reg("PC")), 0x1000, name)
                self.assertEqual(cpu.reg_read(reg("A7")), sp + 4, name)

            destination_writes, halftone_writes = [], []

            def mmio(cpu, access, address, size, value, data):
                nonlocal pending
                if 0xffff8a00 <= address < 0xffff8a20:
                    halftone_writes.append((address, size))
                if 0xffff8a32 <= address < 0xffff8a36:
                    destination_writes.append((address, size))
                if address == 0xffff8a3c and value & 0xf0 == 0xc0:
                    pending = True

            hardware_launches = []

            def complete():
                nonlocal pending, latch
                pending = False
                b = 0xffff8a00
                sx, sy, dx, dy = (struct.unpack(">h", cpu.mem_read(b + off, 2))[0]
                                  for off in (0x20, 0x22, 0x2e, 0x30))
                src, dst = read(b + 0x24, 4), read(b + 0x32, 4)
                words, rows = read(b + 0x36, 2), read(b + 0x38, 2)
                skew, hop, op, line = (read(b + off, 1) for off in (0x3d, 0x3a, 0x3b, 0x3c))
                hardware_launches.append((dst, words, rows, hop, op))
                self.assertIn(hop, (1, 2, 3))
                for y in range(rows):
                    if hop != 1 and skew & 0x80:
                        value = read(src, 2)
                        latch = ((latch >> 16) | value << 16) if sx < 0 else \
                            ((latch << 16) | value) & 0xffffffff
                        src += sx
                    for x in range(words):
                        old = read(dst, 2)
                        suppress = bool(skew & 0x40) and x + 1 == words
                        if hop == 1:
                            shifted = read(b + ((line + y) & 15) * 2, 2)
                        else:
                            value = old if suppress else read(src, 2)
                            latch = ((latch >> 16) | value << 16) if sx < 0 else \
                                ((latch << 16) | value) & 0xffffffff
                            shifted = (latch >> (skew & 15)) & 0xffff
                            if hop == 3:
                                shifted &= read(b + ((line + y) & 15) * 2, 2)
                        result = (old & shifted if op == 1 else shifted if op == 3 else
                                  old & ~shifted if op == 4 else old | shifted)
                        mask = read(b + (0x28 if x == 0 else 0x2c if x + 1 == words else 0x2a), 2)
                        write(dst, (old & ~mask) | (result & mask), 2)
                        if hop != 1:
                            if suppress:
                                value = read(dst, 2)
                                latch = ((latch >> 16) | value << 16) if sx < 0 else \
                                    ((latch << 16) | value) & 0xffffffff
                            else:
                                src += sy if x + 1 == words or (skew & 0x40 and x + 2 == words) else sx
                        dst += dy if x + 1 == words else dx
                write(b + 0x24, src, 4); write(b + 0x32, dst, 4)
                write(b + 0x38, 0, 2); write(b + 0x3c, 0, 1)

            def instruction(cpu, address, size, data):
                if pending:
                    complete()
                if read(address, 2) == 0x0838:
                    sp = cpu.reg_read(reg("A7"))
                    sr = cpu.reg_read(reg("SR"))
                    cpu.reg_write(reg("SR"), (sr & ~4) if read(0xffff8a3c, 1) & 0x80 else sr | 4)
                    cpu.reg_write(reg("A7"), sp)
                    cpu.reg_write(reg("PC"), address + 6)

            cpu.hook_add(unicorn.UC_HOOK_MEM_WRITE, mmio, begin=0xffff8a00, end=0xffff8a3f)
            cpu.hook_add(unicorn.UC_HOOK_CODE, instruction)
            configure = symbols["_Video_Atari_ConfigureBlitterDestination"]
            lea = configure + bytes(cpu.mem_read(configure, 100)).index(b"\x41\xfa")
            table = lea + 2 + struct.unpack(">h", cpu.mem_read(lea + 2, 2))[0]
            patches = tuple((read(table + i * 4, 4), opcode) for i, opcode in enumerate(
                (0x21ca, 0x21ca, 0x21c8, 0x21c8, 0x21c8, 0x21c8)))
            for base, enabled, word_only in (
                    (0, True, False), (0x40001, True, False),
                    (0x3f8000, True, True), (0x48260, True, True),
                    (0x48262, True, False), (0x49000, True, False),
                    (0x40000, False, False)):
                write(0xffff8a32, 0xdead1234, 4)
                before = len(destination_writes)
                call("_TestDestination", (base, int(enabled)))
                cpu.ctl_remove_cache(0x10000, 0x20000)
                self.assertEqual(cpu.reg_read(reg("D0")), word_only)
                self.assertEqual(read(0xffff8a32, 4),
                                 ((base >> 16) << 16 | 0x1234) if word_only else 0xdead1234)
                self.assertEqual(destination_writes[before:],
                                 [(0xffff8a32, 2)] if word_only else [])
                for address, opcode in patches:
                    self.assertEqual(read(address, 2),
                                     opcode | (0x1000 if word_only else 0))
                    self.assertEqual(read(address + 2, 2),
                                     0x8a34 if word_only else 0x8a32)
            background = bytes((i * 113 + 17) & 255 for i in range(160 * 16))
            pixels = b"".join(struct.pack(">H",
                (i * 137 + 0x369c) & ((i // 4 * 971 + 0xa39f) & 0xffff)) for i in range(32))
            masks = b"".join(struct.pack(">H", (i // 4 * 971 + 0xa39f) & 0xffff) for i in range(32))
            tile = bytes((i * 71 + 3) & 255 for i in range(128))
            masked_tile = bytes((i * 157 + 19) & 255 for i in range(128))
            tile_masks = (0, 0xffff, 0x8001, 0x0180, 0xf00f, 0xfc3f, 0x5555, 0xaaaa) * 2
            cpu.mem_write(0x54002, masked_tile)
            cpu.mem_write(0x55002, struct.pack(">16H", *tile_masks))
            pattern = [((i * 977) ^ 0xa39f) & 0xffff for i in range(16)]
            recipes = ((0,1,2,7),(3,1,2,0),(0,2,1,3),(4,1,2,3),(3,2,1,0),
                       (1,2,3,0),(0,1,2,8),(0,5,2,3),(0,1,6,3))
            cpu.mem_write(0x50000, pixels); cpu.mem_write(0x60000, masks); cpu.mem_write(0x52000, tile)
            for passes in range(256):
                call("_Video_Atari_CompileSpriteBlitCode", (0x20000, passes))
                pc, launches, nops = 0x20000, 0, 0
                lengths = {0x31fc:6, 0x47e8:4, 0x47e9:4, 0x47ea:4,
                           0x21c8:4, 0x21c9:4, 0x21ca:4, 0x21cb:4,
                           0x31c0:4, 0x11fc:6, 0x4e71:2}
                while read(pc, 2) != 0x4e75:
                    opcode = read(pc, 2)
                    self.assertIn(opcode, lengths)
                    if opcode == 0x11fc:
                        self.assertEqual(read(pc + 2, 2), 0xc0)
                        self.assertEqual(read(pc + 4, 2), 0x8a3c)
                        launches += 1
                        self.assertEqual(read(pc + 6, 2),
                                         0x4e75 if launches == bin(passes).count("1") else 0x4e71)
                    elif opcode == 0x4e71:
                        nops += 1
                    pc += lengths[opcode]
                    self.assertLess(pc, 0x20000 + 286)
                self.assertEqual(launches, bin(passes).count("1"))
                self.assertEqual(nops, max(0, launches - 1))
            call("_Video_Atari_CompileSpriteBlitCode", (0x20000, 255))
            for phase in range(16):
                word_only = bool(phase & 1)
                call("_TestDestination", (0x40000, int(word_only)))
                cpu.ctl_remove_cache(0x10000, 0x20000)
                call("_Video_Atari_CompileSpriteBlitCode", (0x20000, 255))
                cpu.ctl_remove_cache(0x20000, 0x20200)
                expected_destination = struct.pack(">HH",
                    0x31ca if word_only else 0x21ca, 0x8a34 if word_only else 0x8a32)
                self.assertIn(expected_destination, bytes(cpu.mem_read(0x20000, 286)))
                for sx in (0,1,15,16,31):
                    for effect in range(10):
                        protected, line = bool(effect & 1), (phase + sx) & 15
                        width = 32 - sx
                        expected = bytearray(background)
                        cpu.mem_write(0x40000, background)
                        cpu.mem_write(0x30020, struct.pack(">16H", *pattern))
                        write(symbols["_g_videoDisplayListNext"], 0x70000, 4)
                        write(symbols["_g_videoDisplayListLimit"], 0x7fffe, 4)
                        write(symbols["_g_videoDisplayListActive"], 1, 1)
                        call("_Video_Atari_QueueTile", (0x52000, 0x40000))
                        self.assertEqual(read(symbols["_g_videoDisplayListNext"], 4), 0x70012)
                        for y in range(16):
                            expected[y*160:y*160+8] = tile[y*8:y*8+8]
                        call("_TestPlan", (0x30000, sx, width, phase))
                        inputs = {"A0":0x50000 + sx//16*8, "A1":0x60000 + sx//16*8,
                                  "A2":0x40000, "A3":0x30000, "A4":0x20000, "D0":4, "D1":0x12345678}
                        call("_Video_Atari_QueueSpriteBlit", inputs=inputs)
                        self.assertEqual(read(symbols["_g_videoDisplayListNext"], 4), 0x70012 + 76)
                        for name in ("A0","A1","A2","A4","D0","D1"):
                            self.assertEqual(cpu.reg_read(reg(name)), inputs[name])
                        call("_Video_Atari_BuildSpriteBlitGeometry", (0x31000,32,sx,width))
                        geometry = 0x31000 + phase * 50
                        cached = bytes(cpu.mem_read(geometry,50))
                        before = read(symbols["_g_videoDisplayListNext"],4)
                        cached_inputs = dict(inputs, A3=geometry)
                        call("_Video_Atari_QueueSpriteGeometry", inputs=cached_inputs)
                        self.assertEqual(read(symbols["_g_videoDisplayListNext"],4)-before,36)
                        for name in ("A0","A1","A2","A3","A4","D0","D1"):
                            self.assertEqual(cpu.reg_read(reg(name)), cached_inputs[name])
                        cpu.ctl_remove_cache(0x31000,0x31320)

                        def reference(effect, protected):
                            for y in range(4):
                                for x in range(width):
                                    src = y*16 + (sx+x)//16*8
                                    sb, db = 0x8000 >> ((sx+x)&15), 0x8000 >> ((phase+x)&15)
                                    if not struct.unpack_from(">H",masks,src)[0] & sb: continue
                                    if protected and not pattern[(line+y)&15] & db: continue
                                    for p in range(4):
                                        select = recipes[effect-1][p] if effect else p
                                        colour = 0 if select == 8 else struct.unpack_from(
                                            ">H", pixels if select<4 else masks, src+(select%4)*2)[0]
                                        dst = y*160+(phase+x)//16*8+p*2
                                        old = struct.unpack_from(">H",expected,dst)[0]
                                        struct.pack_into(">H",expected,dst,(old&~db)|(db if colour&sb else 0))
                        reference(0,False)
                        before = read(symbols["_g_videoDisplayListNext"],4)
                        call("_TestMasked", (inputs["A0"],inputs["A1"],0x40000,0x30000,0x20000,
                                             effect,int(protected),line,0x30020))
                        launches = 7 if effect == 7 else 8
                        self.assertEqual(read(symbols["_g_videoDisplayListNext"],4)-before,
                                         48+(102 if protected else 0)+launches*30)
                        reference(effect,protected)
                        before = read(symbols["_g_videoDisplayListNext"],4)
                        call("_TestTint", (0x40282,0x30020))
                        self.assertEqual(read(symbols["_g_videoDisplayListNext"],4)-before,180)
                        for y in range(4):
                            for group in range(2):
                                dst=(y+4)*160+group*8+2
                                old=struct.unpack_from(">H",expected,dst)[0]
                                struct.pack_into(">H",expected,dst,old|pattern[y])
                        cpu.mem_write(0x30000, bytes(18)); cpu.mem_write(0x30020, bytes(32))
                        cursor = read(symbols["_g_videoDisplayListNext"],4)
                        cpu.mem_write(cursor, struct.pack(">HIHI",0x247c,0x40000,0x4eb9,symbols["_TestCPUCode"]))
                        write(symbols["_g_videoDisplayListNext"],cursor+12,4)
                        call("_Video_Atari_QueueTile",(0x52000,0x40000))
                        for y in range(16): expected[y*160:y*160+8]=tile[y*8:y*8+8]
                        cursor=read(symbols["_g_videoDisplayListNext"],4)
                        write(cursor,0x4e75,2); write(symbols["_g_videoDisplayListActive"],0,1)
                        saved={name:0x123400+i for i,name in enumerate(
                            ("D2","D3","D4","D5","D6","D7","A2","A3","A4","A5","A6"))}
                        cpu.ctl_remove_cache(0x70000,cursor+2)
                        before = len(destination_writes)
                        call("_Video_Atari_RunDisplayList",(0x70000,),saved)
                        self.assertEqual(read(symbols["_g_videoDisplayListNext"],4),cursor)
                        self.assertTrue(destination_writes[before:])
                        self.assertEqual(set(destination_writes[before:]),
                                         {(0xffff8a34, 2)} if word_only else {(0xffff8a32, 4)})
                        self.assertEqual(bytes(cpu.mem_read(0x40000,len(expected))),bytes(expected),
                                         (phase,sx,effect,protected))
                        self.assertEqual(bytes(cpu.mem_read(geometry,50)),cached)
                        for name,value in saved.items():
                            self.assertEqual(cpu.reg_read(reg(name)),value,name)

            # Immediate launchers never enqueue, even inside a construction phase.
            call("_TestPlan", (0x30000, 0, 16, 0))
            call("_Video_Atari_BuildSpriteBlitGeometry", (0x31000, 32, 0, 16))
            cpu.ctl_remove_cache(0x31000, 0x31320)
            expected = bytearray(background)
            for y in range(4):
                mask = struct.unpack_from(">H", masks, y*16)[0]
                for p in range(4):
                    offset = y*160+p*2
                    old = struct.unpack_from(">H", expected, offset)[0]
                    source = struct.unpack_from(">H", pixels, y*16+p*2)[0]
                    struct.pack_into(">H", expected, offset, (old & ~mask) | (source & mask))
            write(symbols["_g_videoDisplayListActive"], 1, 1)
            write(symbols["_g_videoDisplayListNext"], 0x70000, 4)
            for geometry in (False, True):
                cpu.mem_write(0x40000, background)
                call("_Video_Atari_BlitSpriteGeometry" if geometry else "_Video_Atari_BlitSpriteCode",
                     inputs={"A0":0x50000, "A1":0x60000, "A2":0x40000,
                             "A3":0x31000 if geometry else 0x30000, "A4":0x20000, "D0":4})
                self.assertEqual(read(symbols["_g_videoDisplayListNext"],4), 0x70000)
                self.assertEqual(bytes(cpu.mem_read(0x40000,len(expected))), bytes(expected))

                # Exercise the production C-to-register queue adapters and replay
                # without relying on the global phase flag to select an entry.
                cpu.mem_write(0x40000, background)
                launches = len(hardware_launches)
                call("_TestQueueSprite", (0x20000,0x50000,0x60000,0x40000,4,0x30000,
                                         0x31000 if geometry else 0))
                end = 0x70000 + (36 if geometry else 76)
                self.assertEqual(read(symbols["_g_videoDisplayListNext"],4), end)
                self.assertEqual(len(hardware_launches), launches)
                self.assertEqual(bytes(cpu.mem_read(0x40000,len(background))), background)
                write(end,0x4e75,2)
                cpu.ctl_remove_cache(0x70000,end+2)
                call("_Video_Atari_RunDisplayList", (0x70000,))
                self.assertEqual(read(symbols["_g_videoDisplayListNext"],4), end)
                self.assertEqual(bytes(cpu.mem_read(0x40000,len(expected))), bytes(expected))
                write(symbols["_g_videoDisplayListNext"],0x70000,4)

            for queued in (False, True):
                for resident in (False, True):
                    for geometry in (False, True):
                        write(symbols["_g_atariSupervisorResident"],int(resident),1)
                        write(symbols["_g_videoDisplayListActive"],int(queued),1)
                        write(symbols["_g_videoDisplayListNext"],0x70000,4)
                        call("_TestHighlight",(0,))
                        destination = read(symbols["_g_videoPlanarBase"],4) + 40*160
                        cpu.mem_write(destination,background)
                        launches = len(hardware_launches)
                        call("_Video_Atari_PresentPlanarSpriteUnshifted",
                             (0x50000,0x60000,32,0,16,4,0,40,0x31000 if geometry else 0,0x20000))
                        end = 0x70000 + ((36 if geometry else 76) if queued else 0)
                        self.assertEqual(read(symbols["_g_videoDisplayListNext"],4),end)
                        if queued:
                            self.assertEqual(len(hardware_launches),launches)
                            self.assertEqual(bytes(cpu.mem_read(destination,len(background))),background)
                            write(end,0x4e75,2)
                            cpu.ctl_remove_cache(0x70000,end+2)
                            call("_Video_Atari_RunDisplayList",(0x70000,))
                        self.assertEqual(bytes(cpu.mem_read(destination,len(expected))),bytes(expected))
            call("_TestFallback")
            self.assertEqual(cpu.reg_read(reg("D0")),0)
            write(symbols["_restoredCursor"],0,4)

            call("_TestDestination", (0x40000 - 40 * 160, 1))
            cpu.ctl_remove_cache(0x10000, 0x20000)
            write(symbols["_g_videoDisplayListNext"],0x70000,4)
            write(symbols["_g_videoDisplayListActive"],1,1)
            call("_TestPlan",(0x30000,0,16,0))
            for cell in range(16):
                call("_Video_Atari_QueueTile",(0x52000,0x40000))
                call("_TestMasked",(0x50000,0x60000,0x40000,0x30000,0x20000,0,1,0,0x30020))
            self.assertEqual(read(symbols["_g_videoDisplayListNext"],4)-0x70000,16*(390+18))
            write(symbols["_g_videoDisplayListNext"],0x70000,4)
            for cell in range(16):
                call("_Video_Atari_QueueMaskedTile",(0x54002,0x55002,0x40000))
                call("_TestMasked",(0x50000,0x60000,0x40000,0x30000,0x20000,0,1,0,0x30020))
            self.assertEqual(read(symbols["_g_videoDisplayListNext"],4)-0x70000,16*(390+24))
            write(symbols["_g_videoPlanarBase"],0x40000-40*160,4)
            write(symbols["_g_videoViewportBlitter"],1,1)
            write(symbols["_g_atariSupervisorResident"],1,1)
            write(symbols["_g_videoDisplayListNext"],0x70000,4)
            write(symbols["_g_videoScrollPending"],1,1)
            before_scroll = bytes(cpu.mem_read(0x40000, 2560))
            launches = len(hardware_launches)
            call("_GFX_QueueViewportPixelsFast",(0x52000,0,0),{"D2":0x12345678})
            self.assertEqual(cpu.reg_read(reg("D0")),1)
            self.assertEqual(cpu.reg_read(reg("D2")),0x12345678)
            self.assertEqual(read(symbols["_restoredCursor"],4),0)
            self.assertEqual(read(symbols["_g_videoDisplayListNext"],4),0x70012)
            self.assertEqual(len(hardware_launches),launches)
            self.assertEqual(bytes(cpu.mem_read(0x40000, 2560)),before_scroll)
            write(symbols["_g_videoScrollPending"],0,1)
            write(0x70012,0x4e75,2)
            cpu.ctl_remove_cache(0x70000,0x70014)
            call("_Video_Atari_RunDisplayList",(0x70000,))
            self.assertEqual(read(symbols["_g_videoDisplayListNext"],4),0x70012)
            for field, value, size in (("_g_videoViewportBlitter",0,1),
                                      ("_g_atariSupervisorResident",0,1),
                                      ("_s_curViewportTiles",1,2)):
                original = read(symbols[field],size)
                write(symbols[field],value,size)
                call("_GFX_QueueViewportPixelsFast",(0x52000,0,0),{"D2":0x12345678})
                self.assertEqual(cpu.reg_read(reg("D0")),0)
                self.assertEqual(cpu.reg_read(reg("D2")),0x12345678)
                self.assertEqual(read(symbols["_g_videoDisplayListNext"],4),0x70012)
                write(symbols[field],original,size)

            for base, word_only in ((0x48262, False), (0x48260, True)):
                call("_TestDestination", (base, 1))
                cpu.ctl_remove_cache(0x10000, 0x20000)
                destination = base + 184 * 160 + 19 * 8
                cpu.mem_write(destination, background)
                expected = bytearray(background)
                for y in range(16):
                    expected[y*160:y*160+8] = tile[y*8:y*8+8]
                before = len(destination_writes)
                write(symbols["_g_videoDisplayListNext"],0x70000,4)
                call("_GFX_QueueViewportPixelsFast", (0x52000, 19, 9), {"D2":0x12345678})
                self.assertEqual(cpu.reg_read(reg("D0")), 1)
                self.assertEqual(cpu.reg_read(reg("D2")), 0x12345678)
                self.assertEqual(destination_writes[before:],[])
                self.assertEqual(bytes(cpu.mem_read(destination,len(background))),background)
                write(0x70012,0x4e75,2)
                cpu.ctl_remove_cache(0x70000,0x70014)
                call("_Video_Atari_RunDisplayList",(0x70000,))
                self.assertEqual(destination_writes[before:],
                                 [(0xffff8a34, 2)] if word_only else [(0xffff8a32, 4)])
                self.assertEqual(read(0xffff8a32, 4), destination + 16 * 160)
                self.assertEqual(bytes(cpu.mem_read(destination, len(expected))), bytes(expected))

            saved = {name: 0x123400+i for i, name in enumerate(
                ("D2","D3","D4","D5","D6","D7","A2","A3","A4","A5","A6"))}
            patterns = (
                (0xf00f,0x8001,0x8001,0x8001,0,0,0,0,0,0,0,0,0x8001,0x8001,0x8001,0xf00f),
                (0xfc3f,0x8001,0x8001,0x8001,0x8001,0x8001,0,0x0180,
                 0x0180,0,0x8001,0x8001,0x8001,0x8001,0x8001,0xfc3f),
                tuple(pattern))
            for selection in range(32):
                pen, word_only = selection & 15, bool(selection & 16)
                call("_TestDestination", (0x40000, int(word_only)))
                cpu.ctl_remove_cache(0x10000, 0x20000)
                for pattern_index, cursor_pattern in enumerate(patterns):
                    cursor_pattern_address = 0x56000 + pattern_index * 32
                    cpu.mem_write(cursor_pattern_address, struct.pack(">16H", *cursor_pattern))
                    cpu.mem_write(0x40000, background)
                    expected = bytearray(background)
                    for y in range(16):
                        for p in range(4):
                            old = struct.unpack_from(">H", expected, y*160+p*2)[0]
                            value = (old & ~cursor_pattern[y]) | (
                                cursor_pattern[y] if pen & (1 << p) else 0)
                            struct.pack_into(">H", expected, y*160+p*2, value)
                    hardware_launches.clear()
                    write(symbols["_g_videoBlitterTileSetup"],1,1)
                    write(symbols["_g_videoTileCursorRestored"],0,1)
                    before = len(destination_writes)
                    call("_TestCursorFrame", (0x40000,cursor_pattern_address,pen), saved)
                    self.assertEqual(destination_writes[before:],
                                     [(0xffff8a34, 2)] * 4 if word_only else [(0xffff8a32, 4)] * 4)
                    self.assertEqual(bytes(cpu.mem_read(0x40000,len(expected))), bytes(expected))
                    self.assertEqual(bytes(cpu.mem_read(0xffff8a00,32)),
                                     struct.pack(">16H",*cursor_pattern))
                    self.assertEqual(hardware_launches, [
                        (0x40000+p*2,1,16,1,7 if pen & (1 << p) else 4) for p in range(4)])
                    self.assertEqual(read(symbols["_g_videoBlitterTileSetup"],1),0)
                    self.assertEqual(read(symbols["_g_videoTileCursorRestored"],1),1)
                    self.assertEqual(read(0xffff8a3a,1),2)
                    for name, value in saved.items():
                        self.assertEqual(cpu.reg_read(reg(name)),value,name)
                    # A queued opaque tile must reload geometry after the frame.
                    write(symbols["_g_videoDisplayListActive"],1,1)
                    write(symbols["_g_videoDisplayListNext"],0x70000,4)
                    call("_Video_Atari_QueueTile",(0x52000,0x40000))
                    before = read(symbols["_g_videoDisplayListNext"],4)
                    call("_Video_Atari_QueueMaskedTile",(0x54002,0x55002,0x40000),saved)
                    self.assertEqual(read(symbols["_g_videoDisplayListNext"],4)-before,24)
                    self.assertEqual(bytes(cpu.mem_read(0x40000,len(expected))),bytes(expected))
                    for name,value in saved.items():
                        self.assertEqual(cpu.reg_read(reg(name)),value,name)
                    call("_Video_Atari_QueueTile",(0x52000,0x40008))
                    end=read(symbols["_g_videoDisplayListNext"],4)
                    cpu.mem_write(end,struct.pack(">HI",0x4eb9,symbols["_Video_Atari_TileCursorTail"]))
                    write(symbols["_g_videoDisplayListNext"],end+6,4)
                    call("_Video_Atari_QueueMaskedRect",(0x54002,0x55002,0x40000,1,16),saved)
                    self.assertEqual(read(symbols["_g_videoDisplayListNext"],4)-end,6+32)
                    end=read(symbols["_g_videoDisplayListNext"],4)
                    write(end,0x4e75,2)
                    state = bytes(cpu.mem_read(symbols["_g_videoTileCursorBlit"],12))
                    write(symbols["_g_videoTileCursorRestored"],0,1)
                    write(symbols["_g_videoDisplayListActive"],0,1)
                    cpu.ctl_remove_cache(0x70000,end+2)
                    call("_Video_Atari_RunDisplayList",(0x70000,),saved)
                    self.assertEqual(bytes(cpu.mem_read(symbols["_g_videoTileCursorBlit"],12)),state)
                    self.assertEqual(read(symbols["_g_videoTileCursorRestored"],1),1)
                    for y in range(16):
                        for p in range(4):
                            old=struct.unpack_from(">H",tile,y*8+p*2)[0]
                            source=struct.unpack_from(">H",masked_tile,y*8+p*2)[0]
                            old=(old & ~tile_masks[y]) | (source & tile_masks[y])
                            value=(old & ~cursor_pattern[y]) | (
                                cursor_pattern[y] if pen & (1 << p) else 0)
                            value=(value & ~tile_masks[y]) | (source & tile_masks[y])
                            struct.pack_into(">H",expected,y*160+p*2,value)
                        expected[y*160+8:y*160+16]=tile[y*8:y*8+8]
                    self.assertEqual(bytes(cpu.mem_read(0x40000,len(expected))),bytes(expected))
                    for name,value in saved.items():
                        self.assertEqual(cpu.reg_read(reg(name)),value,name)

            def cursor_residency(pattern_address, pen, destination, upload_bytes):
                initial = bytes(background)
                expected = bytearray(initial)
                pattern = struct.unpack(">16H", cpu.mem_read(pattern_address, 32))
                for y in range(16):
                    for p in range(4):
                        old = struct.unpack_from(">H", expected, y*160+p*2)[0]
                        value = (old & ~pattern[y]) | (pattern[y] if pen & (1 << p) else 0)
                        struct.pack_into(">H", expected, y*160+p*2, value)
                cpu.mem_write(destination, initial)
                before = len(halftone_writes)
                call("_TestCursorFrame", (destination, pattern_address, pen), saved)
                self.assertEqual(sum(size for _, size in halftone_writes[before:]), upload_bytes)
                self.assertEqual(read(symbols["_g_videoBlitterHalftonePattern"], 4), pattern_address)
                self.assertEqual(bytes(cpu.mem_read(destination, len(expected))), bytes(expected))
                for name, value in saved.items():
                    self.assertEqual(cpu.reg_read(reg(name)), value, name)

            write(symbols["_g_videoBlitterHalftonePattern"], 0, 4)
            cursor_residency(0x56000, 4, 0x40000, 32)
            cursor_residency(0x56000, 15, 0x40008, 0)
            cursor_residency(0x56020, 15, 0x40000, 32)
            cursor_residency(0x56000, 4, 0x40000, 32)
            cursor_residency(0x56000, 4, 0x40000, 0)

            def begin_residency_list():
                write(symbols["_g_videoDisplayListNext"], 0x70000, 4)
                write(symbols["_g_videoDisplayListActive"], 1, 1)

            def finish_residency_list(upload_bytes):
                end = read(symbols["_g_videoDisplayListNext"], 4)
                cpu.mem_write(end, struct.pack(">HIH", 0x4eb9,
                    symbols["_Video_Atari_TileCursorTail"], 0x4e75))
                write(symbols["_g_videoDisplayListActive"], 0, 1)
                cpu.ctl_remove_cache(0x70000, end + 8)
                before = len(halftone_writes)
                call("_Video_Atari_ExecuteDisplayList", (0x70000,), saved)
                self.assertEqual(sum(size for _, size in halftone_writes[before:]), upload_bytes)
                self.assertEqual(read(symbols["_g_videoBlitterHalftonePattern"], 4), 0x56000)
                self.assertEqual(bytes(cpu.mem_read(0xffff8a00, 32)),
                                 bytes(cpu.mem_read(0x56000, 32)))

            # Source-only tiles/sprites and playback boundaries preserve the resident cursor pattern.
            call("_TestPlan", (0x30000, 0, 16, 0))
            begin_residency_list()
            call("_Video_Atari_QueueTile", (0x52000, 0x40000))
            call("_Video_Atari_QueueSpriteBlit", inputs={
                "A0":0x50000, "A1":0x60000, "A2":0x40000, "A3":0x30000,
                "A4":0x20000, "D0":4})
            finish_residency_list(0)
            cursor_residency(0x56000, 7, 0x40008, 0)
            begin_residency_list()
            finish_residency_list(0)

            # Queuing does not change residency; actual fog/tint playback invalidates it.
            cpu.mem_write(0x30020, bytes(cpu.mem_read(0x56020, 32)))
            for tint in (False, True):
                begin_residency_list()
                before = len(halftone_writes)
                if tint:
                    call("_TestTint", (0x40282, 0x30020))
                else:
                    call("_TestMasked", (0x50000, 0x60000, 0x40000, 0x30000,
                                         0x20000, 0, 1, 0, 0x30020))
                self.assertEqual(len(halftone_writes), before)
                self.assertEqual(read(symbols["_g_videoBlitterHalftonePattern"], 4), 0x56000)
                finish_residency_list(64)
                cursor_residency(0x56000, 4, 0x40000, 0)

            # Immediate C halftone writes share the native residency state.
            before = len(halftone_writes)
            call("_TestHalftone", (0x56000,))
            self.assertEqual(len(halftone_writes), before)
            call("_TestHalftone", (0x56020,))
            self.assertEqual(sum(size for _, size in halftone_writes[before:]), 32)
            cursor_residency(0x56000, 4, 0x40000, 32)

            # Variable-width CPU text uses its own masks and preserves BLITTER state.
            for groups in (1, 3, 5, 8, 20):
                for rows in (1, 6, 16, 32):
                    for fill in (0, 0xffff, None):
                        image = bytes((i * 157 + 19) & 255 for i in range(groups*rows*8))
                        opacity = tuple(fill if fill is not None else tile_masks[i % 16]
                                        for i in range(groups*rows))
                        packed = struct.pack(">" + "H"*len(opacity), *opacity)
                        initial = bytes((i * 113 + 17) & 255 for i in range(160*rows))
                        destination = 0x44002
                        cpu.mem_write(destination-2,b"\x13\x57"+initial+b"\x24\x68")
                        cpu.mem_write(0x58002,image); cpu.mem_write(0x62002,packed)
                        expected = bytearray(initial)
                        for y in range(rows):
                            for group in range(groups):
                                mask = opacity[y*groups+group]
                                for p in range(4):
                                    offset = y*160+group*8+p*2
                                    old = struct.unpack_from(">H",expected,offset)[0]
                                    source = struct.unpack_from(">H",image,(y*groups+group)*8+p*2)[0]
                                    struct.pack_into(">H",expected,offset,(old & ~mask) | (source & mask))
                        hardware = bytes(cpu.mem_read(0xffff8a00,64))
                        write(symbols["_g_videoBlitterTileSetup"],1,1)
                        hardware_launches.clear()
                        write(symbols["_g_videoDisplayListNext"],0x70000,4)
                        call("_Video_Atari_QueueMaskedRect",(0x58002,0x62002,destination,groups,rows),saved)
                        self.assertEqual(read(symbols["_g_videoDisplayListNext"],4),0x70020)
                        self.assertEqual(bytes(cpu.mem_read(destination,len(initial))),initial)
                        write(0x70020,0x4e75,2)
                        cpu.ctl_remove_cache(0x70000,0x70022)
                        call("_Video_Atari_RunDisplayList",(0x70000,),saved)
                        self.assertEqual(bytes(cpu.mem_read(destination,len(expected))),bytes(expected),
                                         (groups,rows,fill))
                        self.assertEqual(bytes(cpu.mem_read(destination-2,2)),b"\x13\x57")
                        self.assertEqual(bytes(cpu.mem_read(destination+len(expected),2)),b"\x24\x68")
                        self.assertEqual(bytes(cpu.mem_read(0xffff8a00,64)),hardware)
                        self.assertEqual(read(symbols["_g_videoBlitterTileSetup"],1),1)
                        self.assertEqual(hardware_launches,[])
                        self.assertEqual(bytes(cpu.mem_read(0x58002,len(image))),image)
                        self.assertEqual(bytes(cpu.mem_read(0x62002,len(packed))),packed)
                        for name,value in saved.items():
                            self.assertEqual(cpu.reg_read(reg(name)),value,name)

            write(symbols["_g_videoAtariMono"], 1, 1)
            write(symbols["_g_videoPlanarBase"], 0x40000, 4)
            write(symbols["_g_videoDisplayListActive"], 1, 1)
            write(symbols["_g_videoDisplayListLimit"], 0x70200, 4)
            for x, y, w, h in ((3, 45, 3, 3), (7, 45, 19, 3), (232, 38, 16, 5)):
                for flags in range(4):
                    start_x, end_x = max(0, x) * 2, min(240, x + w) * 2
                    start_y, end_y = max(40, y) * 2, (y + h) * 2
                    address = 0x40000 + (start_y - 1) * 80
                    original = bytes((i * 111 + 37) & 255 for i in range((end_y - start_y + 2) * 80))
                    expected = bytearray(original)
                    value = bool(flags & 1) != bool(flags & 2)
                    for py in range(start_y, end_y):
                        for px in range(start_x, end_x):
                            if ((px // 2) ^ ((py - start_y) // 2)) & 1:
                                continue
                            index = (py - start_y + 1) * 80 + px // 8
                            bit = 0x80 >> (px & 7)
                            expected[index] = expected[index] | bit if value else expected[index] & ~bit
                    cpu.mem_write(address, original)
                    write(symbols["_g_videoDisplayListNext"], 0x70000, 4)
                    call("_TestMonoTint", (x, y, w, h, flags))
                    end = read(symbols["_g_videoDisplayListNext"], 4)
                    self.assertEqual(end - 0x70000, 180)
                    self.assertEqual(bytes(cpu.mem_read(address, len(original))), original)
                    write(end, 0x4e75, 2)
                    cpu.ctl_remove_cache(0x70000, end + 2)
                    hardware_launches.clear()
                    call("_Video_Atari_RunDisplayList", (0x70000,))
                    self.assertEqual(len(hardware_launches), 1)
                    self.assertEqual(bytes(cpu.mem_read(address, len(original))), expected)

            # CPU-only playback needs no BLITTER hardware state or backend selection.
            for destination in (0x40002, 0x48072):
                for mask_rows in ((0,) * 16, (0xffff,) * 16, tile_masks):
                    cpu.mem_write(destination-2, b"\x13\x57" + background + b"\x24\x68")
                    cpu.mem_write(0x55002, struct.pack(">16H", *mask_rows))
                    expected = bytearray(background)
                    for y in range(16):
                        for p in range(4):
                            old = struct.unpack_from(">H",expected,y*160+p*2)[0]
                            source = struct.unpack_from(">H",masked_tile,y*8+p*2)[0]
                            struct.pack_into(">H",expected,y*160+p*2,
                                             (old & ~mask_rows[y]) | (source & mask_rows[y]))
                    write(symbols["_g_videoViewportBlitter"],0,1)
                    write(symbols["_g_videoBlitterTileSetup"],1,1)
                    hardware = bytes(cpu.mem_read(0xffff8a00,64))
                    hardware_launches.clear()
                    write(symbols["_g_videoDisplayListNext"],0x70000,4)
                    call("_Video_Atari_QueueMaskedTile",(0x54002,0x55002,destination),saved)
                    end = read(symbols["_g_videoDisplayListNext"],4)
                    cpu.mem_write(end,b"\x4e\x75")
                    cpu.ctl_remove_cache(0x70000,end+2)
                    call("_Video_Atari_RunDisplayList",(0x70000,),saved)
                    self.assertEqual(bytes(cpu.mem_read(destination,len(expected))),bytes(expected))
                    self.assertEqual(bytes(cpu.mem_read(destination-2,2)),b"\x13\x57")
                    self.assertEqual(bytes(cpu.mem_read(destination+len(expected),2)),b"\x24\x68")
                    self.assertEqual(bytes(cpu.mem_read(0xffff8a00,64)),hardware)
                    self.assertEqual(read(symbols["_g_videoBlitterTileSetup"],1),1)
                    self.assertEqual(hardware_launches,[])
                    self.assertEqual(bytes(cpu.mem_read(0x54002,128)),masked_tile)
                    self.assertEqual(bytes(cpu.mem_read(0x55002,32)),struct.pack(">16H",*mask_rows))
                    for name,value in saved.items():
                        self.assertEqual(cpu.reg_read(reg(name)),value,name)

            # The same executable emits one-plane mono tiles and sprite recipes.
            write(symbols["_g_videoAtariMono"], 1, 1)
            call("_TestHighlight", (0,))
            mono_masks = bytearray(64)
            for y in range(8):
                for x in range(64):
                    if (x // 2 + y // 2) % 5:
                        mono_masks[y * 8 + x // 8] |= 0x80 >> (x & 7)
            mono_pixels = bytes(((i * 137 + 0x39) & 255) & mask
                                for i, mask in enumerate(mono_masks))
            cpu.mem_write(0x50000, mono_pixels)
            cpu.mem_write(0x60000, bytes(mono_masks))
            initial = bytes((i * 113 + 17) & 255 for i in range(32000))
            for base, word_only in ((0x48262, False), (0x48260, True)):
                call("_TestDestination", (base, 1))
                cpu.ctl_remove_cache(0x10000, 0x20000)
                self.assertEqual(cpu.reg_read(reg("D0")), word_only)
                call("_Video_Atari_CompileSpriteBlitCode", (0x20000, 0x11))
                cpu.ctl_remove_cache(0x20000, 0x20200)
                cpu.mem_write(base, initial)
                write(symbols["_g_videoBlitterTileSetup"], 0, 1)
                write(symbols["_g_videoDisplayListActive"], 1, 1)
                write(symbols["_g_videoDisplayListNext"], 0x70000, 4)
                call("_Video_Atari_QueueTile", (0x52000, base + 40 * 160))
                write(0x70012, 0x4e75, 2)
                cpu.ctl_remove_cache(0x70000, 0x70014)
                hardware_launches.clear()
                call("_Video_Atari_RunDisplayList", (0x70000,))
                expected = bytearray(initial)
                for y in range(32):
                    off = 40 * 160 + y * 80
                    expected[off:off + 4] = tile[y * 4:y * 4 + 4]
                self.assertEqual(bytes(cpu.mem_read(base, 32000)), bytes(expected))
                self.assertEqual(hardware_launches, [(base + 40 * 160, 2, 32, 2, 3)])
                before = read(symbols["_g_videoDisplayListNext"], 4)
                call("_GFX_QueueViewportPixelsFast", (0x52000, 0, 0))
                self.assertEqual(cpu.reg_read(reg("D0")), 0)
                self.assertEqual(read(symbols["_g_videoDisplayListNext"], 4), before)
                for sx in (*range(8), 8, 15, 16, 23, 31):
                    for width in dict.fromkeys((1, min(8, 32 - sx), 32 - sx)):
                        call("_Video_Atari_BuildSpriteBlitGeometry", (0x31000, 32, sx, width))
                        cpu.ctl_remove_cache(0x31000, 0x31320)
                        for phase in range(16):
                            x, y = 64 + phase, 40
                            expected = bytearray(initial)
                            for py in range(8):
                                for px in range(width * 2):
                                    source = sx * 2 + px
                                    sb = 0x80 >> (source & 7)
                                    src = py * 8 + source // 8
                                    if not mono_masks[src] & sb:
                                        continue
                                    dx = x * 2 + px
                                    off = (y * 2 + py) * 80 + dx // 8
                                    bit = 0x80 >> (dx & 7)
                                    expected[off] = (expected[off] & ~bit) | (
                                        bit if mono_pixels[src] & sb else 0)
                            for queued, cached in ((True, False), (True, True), (False, True)):
                                cpu.mem_write(base, initial)
                                write(symbols["_g_videoDisplayListActive"], int(queued), 1)
                                write(symbols["_g_videoDisplayListNext"], 0x70000, 4)
                                call("_Video_Atari_PresentPlanarSpriteUnshifted",
                                     (0x50000, 0x60000, 32, sx, width, 4, x, y,
                                      0x31000 + phase * 50 if cached else 0, 0x20000))
                                if queued:
                                    end = read(symbols["_g_videoDisplayListNext"], 4)
                                    write(end, 0x4e75, 2)
                                    cpu.ctl_remove_cache(0x70000, end + 2)
                                    call("_Video_Atari_RunDisplayList", (0x70000,))
                                self.assertEqual(bytes(cpu.mem_read(base, 32000)), bytes(expected),
                                                 (word_only, sx, width, phase, queued, cached))
            call("_TestFallback")
            self.assertEqual(cpu.reg_read(reg("D0")), 0)


if __name__ == "__main__":
    unittest.main()
