"""Exercise shared WSA traversal with original and prepared planar payloads."""

import os
from pathlib import Path
import shlex
import struct
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


def archive_wsas(path):
    data = path.read_bytes()
    entries = []
    position = 0
    while True:
        offset = struct.unpack_from("<I", data, position)[0]
        position += 4
        if offset == 0:
            break
        end = data.index(0, position)
        entries.append((data[position:end].decode("ascii"), offset))
        position = end + 1
    return {name: data[start:entries[i + 1][1] if i + 1 < len(entries) else len(data)]
            for i, (name, start) in enumerate(entries) if name.upper().endswith(".WSA")}


def encode_wsa(width, height, commands):
    blocks = []
    for command in commands:
        block = b"".join(bytes([128 | len(command[i:i + 63])]) + command[i:i + 63]
                         for i in range(0, len(command), 63)) + b"\x80"
        blocks.append(block)
    offsets = [10 + 4 * (len(commands) + 1)]
    for block in blocks:
        offsets.append(offsets[-1] + len(block))
    workspace = max(max(map(len, commands)), max(map(len, blocks))) + 35
    return (struct.pack("<5H", 3, width, height, workspace, 0) +
            struct.pack("<5I", *offsets) + b"".join(blocks))


def fixture():
    width, height = 24, 3
    first = bytes([0, width * height, 31, 128, 0, 0])
    second = bytes([0x8F, 0, 4, 3, 128, 0, 0])
    third = bytes([128, 70, 0, 1, 8, 128, 0, 0])
    closing = bytearray(width * height)
    closing[15:19] = bytes([3] * 4)
    closing[70] = 8
    closing = bytes([len(closing)]) + closing + bytes([128, 0, 0])
    return encode_wsa(width, height, [first, second, third, closing])


def intro_fixture():
    width, height = 304, 120
    end = b"\x80\x00\x00"
    first = bytearray()
    remaining = width * height
    while remaining:
        count = min(remaining, 0x3fff)
        first += b"\x80" + struct.pack("<H", 0xc000 | count) + b"\x1f"
        remaining -= count

    def delta(changes):
        command = bytearray()
        position = 0
        for pixel, value in sorted(changes.items()):
            skip = pixel - position
            while skip:
                count = min(skip, 0x7fff)
                command += b"\x80" + struct.pack("<H", count)
                skip -= count
            command += bytes([1, value])
            position = pixel + 1
        return command + end

    second = {0: 3, 303: 5, 304: 7, 18244: 8, width * height - 1: 11}
    third = {0: 1, 8: 8, 303: 3, 18244: 4, width * height - 1: 5}
    closing = {pixel: second.get(pixel, 0) ^ third.get(pixel, 0)
               for pixel in second.keys() | third.keys()}
    return encode_wsa(width, height, [first + end, delta(second), delta(third), delta(closing)])


def continuation_fixture(data=None):
    if data is None:
        data = fixture()
    offsets = list(struct.unpack_from("<5I", data, 10))
    first_length = offsets[1] - offsets[0]
    return (data[:10] + struct.pack("<5I", 0, *(offset - first_length for offset in offsets[1:])) +
            data[offsets[1]:])


class WSAPlanarTest(unittest.TestCase):
    def test_briefing_background_palette_order(self):
        source = (ROOT / "src/gui/mentat.c").read_text()
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef uint16_t uint16;
typedef struct Widget Widget;
enum { SCREEN_0, SCREEN_1, SCREEN_2, SCREEN_WIDTH = 320, SCREEN_HEIGHT = 200 };
enum { GUI_SPRITE_COLOUR_EMBEDDED };
static int g_playerHouseID, g_curWidgetXBase, g_curWidgetYBase, g_shoulderLeft, g_shoulderTop;
static void *g_sprites[400];
static bool mono, paletteLit, backgroundLit;
static int g_palette1[768], copies, fades;
#define Video_Atari_Mono() mono
#define Sprites_UnloadTiles() ((void)0)
#define GUI_Mentat_Display(...) ((void)0)
#define GFX_Screen_SetActive(...) ((void)0)
#define Widget_SetAndPaintCurrentWidget(...) ((void)0)
#define GFX_Screen_Get_ByIndex(...) NULL
#define GFX_Screen_GetSize_ByIndex(...) 0
#define WSA_LoadFile(...) NULL
#define WSA_DisplayFrame(...) ((void)wsa)
#define WSA_Unload(...) ((void)0)
#define GUI_DrawSprite(...) ((void)0)
#define GUI_Mouse_Hide_Safe() ((void)0)
#define GUI_Mouse_Show_Safe() ((void)0)
#define GUI_Mentat_PreparePlanarFrames() ((void)0)
#define GUI_Mentat_FreePlanarFrames() ((void)0)
#define GUI_Widget_PrepareSpriteDraws(...) ((void)0)
#define GUI_Widget_FreeSpriteDraws() ((void)0)
#define GUI_Widget_HandleEvents(...) 0x8001
#define GUI_PaletteAnimate() ((void)0)
#define GUI_Mentat_Animation(...) ((void)0)
#define sleepIdle() ((void)0)
#define Input_History_Clear() ((void)0)
#define Load_Palette_Mercenaries() ((void)0)
#define Sprites_LoadTiles() ((void)0)
static void GUI_SetPaletteAnimated(int *palette, int ticks) {
    assert(palette == g_palette1 && ticks == 15);
    assert(copies == !mono);
    paletteLit = true;
    fades++;
}
#define GUI_Screen_Copy(...) (copies++, backgroundLit = paletteLit)
#define GUI_Mentat_Loop(...) ((void)stringBuffer, 0)
""" + function(source, "GUI_Mentat_Show") + r"""
int main(void) {
    for (int mode = 0; mode < 2; mode++) {
        mono = mode;
        /* The win path explicitly blackens the palette after the map returns. */
        paletteLit = false;
        copies = fades = 0;
        GUI_Mentat_Show(NULL, NULL, NULL);
        assert(copies == 1 && fades == 1 && paletteLit);
        if (mono) assert(backgroundLit);
    }
    return 0;
}
"""
        compiler = shlex.split(os.environ.get("CC", "cc"))
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "briefing"
            subprocess.run(compiler + ["-std=c99", "-DTOS", "-x", "c", "-", "-o", str(binary)],
                           input=harness, text=True, check=True)
            subprocess.run([str(binary)], check=True)

    def test_native_intro_playback_budget_and_tail_pacing(self):
        source = (ROOT / "src/cutscene.c").read_text()
        playback = function(source, "GameLoop_PlayAnimation")
        harness = r"""
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "GFX_HEADER"
#include "HOUSE_HEADER"
#include "WSA_HEADER"
#include "MATH_HEADER"
#define Debug(...) ((void)0)
volatile uint32 g_timerGUI, g_timerTimeout;
static uint32 wallMs, processedTicks, loadMs, dissolveMs, drawMs, stallMs, paletteMs;
static uint32 shown[128];
static unsigned shownCount, sourceFrames, loads, fades, speechPumps, frameAttempt, skipAfter;
static uint16 s_subtitleIndex;
static uint8 palette[768], g_palette_998A[768];
uint8 *g_palette1 = palette;
static uint8 screens[4][64000];
static bool direct = true, skip;
bool g_canSkipIntro;
static char logs[4096];
static void Warning(const char *format, ...) {
    va_list ap; va_start(ap, format);
    vsnprintf(logs + strlen(logs), sizeof(logs) - strlen(logs), format, ap);
    va_end(ap);
}
static void Error(const char *format, ...) { (void)format; assert(false); }
static void PrepareEnd(void) { assert(false); }
static void sleepIdle(void) {
    wallMs += 5;
    uint32 current = wallMs / 20, elapsed = current - processedTicks;
    g_timerGUI += elapsed;
    g_timerTimeout -= g_timerTimeout < elapsed ? g_timerTimeout : elapsed;
    processedTicks = current;
}
static bool Video_Atari_CursorDirect(void) { return direct; }
static void Video_Atari_PresentPalette(uint8 *p) { assert(p == g_palette1); }
void *GFX_Screen_Get_ByIndex(Screen screen) { return screens[screen]; }
uint16 GFX_Screen_GetSize_ByIndex(Screen screen) { (void)screen; return 64000; }
static void GUI_ClearScreen(Screen screen) { (void)screen; }
static void GameLoop_PlaySubtitle(uint8 step) { assert(step == 0); }
static uint16 GameLoop_PalettePart_Update(bool finish) { (void)finish; speechPumps++; return 0; }
static void GameLoop_CopySubtitlePalette(uint8 *p) { (void)p; }
static void GUI_SetPaletteAnimated(uint8 *p, int16 ticks) {
    (void)p; (void)ticks; wallMs += paletteMs; sleepIdle();
}
static uint16 Input_Keyboard_NextKey(void) { return skip || shownCount >= skipAfter; }
void *WSA_LoadFile(const char *name, void *wsa, uint32 size, bool reserve, bool allow) {
    (void)size; (void)reserve; (void)allow;
    assert(!strcmp(name, "INTRO8A.WSA"));
    wallMs += loadMs; loads++;
    return wsa == NULL ? screens[SCREEN_3] : wsa;
}
void *WSA_LoadIntro(const char *name, bool reserve) {
    return WSA_LoadFile(name, NULL, 1, reserve, true);
}
bool WSA_IsContinuation(void *wsa) { (void)wsa; return false; }
bool WSA_PreparePlanarContinuation(void *wsa, const char *const *parents, uint16 count) {
    (void)wsa; (void)parents; (void)count; assert(false); return false;
}
WSAFrameFormat WSA_GetFrameFormat(void *wsa) { assert(wsa); return WSA_FRAME_PLANAR; }
uint16 WSA_GetFrameCount(void *wsa) { assert(wsa); return sourceFrames; }
void WSA_Unload(void *wsa) { assert(wsa); }
bool WSA_DisplayFrame(void *wsa, uint16 frame, uint16 x, uint16 y, Screen screen) {
    assert(wsa && x == 8 && y == 24);
    if (frame >= sourceFrames) return false;
    wallMs += drawMs;
    if (frame == 1) wallMs += stallMs;
    if (screen == SCREEN_0) {
        assert(frameAttempt++ == frame);
        assert(shownCount < 128); shown[shownCount++] = wallMs;
    }
    return true;
}
static bool GUI_Screen_FadeInPlanar(void *wsa, uint16 x, uint16 y, uint16 width, uint16 height) {
    assert(wsa && x == 1 && y == 24 && width == 38 && height == 120);
    fades++; frameAttempt = 1;
    wallMs += dissolveMs / 2;
    sleepIdle();
    wallMs += dissolveMs - dissolveMs / 2; /* Deliberately leave pending timer work. */
    return true;
}
static void GUI_Screen_FadeIn(int xs, int ys, int xd, int yd, int width, int height,
                              Screen src, Screen dst) {
    (void)xs; (void)ys; (void)xd; (void)yd; (void)width; (void)height; (void)src; (void)dst;
    GUI_Screen_FadeInPlanar(screens[SCREEN_3], 1, 24, 38, 120);
}
static void GUI_Screen_FadeIn2(int x, int y, int width, int height,
                               Screen src, Screen dst, int speed, bool clear) {
    (void)speed; (void)clear;
    GUI_Screen_FadeIn(1, y, x / 8, y, width / 8, height, src, dst);
}
/* PLAYBACK */
static void reset(void) {
    g_timerGUI = g_timerTimeout = wallMs = processedTicks = 0;
    shownCount = loads = fades = speechPumps = frameAttempt = 0;
    loadMs = dissolveMs = stallMs = paletteMs = 0;
    sourceFrames = 16; drawMs = 1; skip = false; skipAfter = 128; g_canSkipIntro = true;
    logs[0] = '\0';
}
static void check_pacing(unsigned first, unsigned minimum) {
    for (unsigned i = first + 1; i < shownCount; i++) {
        if (shown[i] - shown[i - 1] < minimum)
            fprintf(stderr, "frame %u gap=%u minimum=%u\n%s", i,
                shown[i] - shown[i - 1], minimum, logs);
        assert(shown[i] - shown[i - 1] >= minimum);
    }
}
int main(void) {
    HouseAnimation_Animation scene[2] = {{"INTRO8A", 30, 0, HOUSEANIM_FLAGS_MODE2 |
        HOUSEANIM_FLAGS_FADEIN}, {{0}, 0, 0, 0}};
    for (unsigned variant = 0; variant < 2; variant++) {
        reset(); loadMs = 8000; dissolveMs = variant == 0 ? 3000 : 8000;
        GameLoop_PlayAnimation(scene, true);
        assert(loads == 1 && fades == 1 && shownCount == 15 && speechPumps > 15);
        assert(logs[0] == '\0');
        assert(shown[shownCount - 1] - shown[0] >= 3000);
        check_pacing(0, 210);
    }
    /* No transition: a long unpumped load must not erase the playback budget. */
    reset(); scene[0].flags = HOUSEANIM_FLAGS_MODE2; loadMs = 10000;
    GameLoop_PlayAnimation(scene, true);
    assert(fades == 0 && shownCount == sourceFrames && logs[0] == '\0');
    check_pacing(0, 210);
    /* A stall can still overrun the deadline, but its tail must remain paced. */
    reset(); scene[0].flags |= HOUSEANIM_FLAGS_FADEIN;
    dissolveMs = 3000; stallMs = 4000;
    GameLoop_PlayAnimation(scene, true);
    assert(shownCount == 15 && logs[0] == '\0');
    check_pacing(0, 210);
    /* A paced tail keeps keyboard skipping responsive too. */
    reset(); dissolveMs = 3000; stallMs = 4000; skipAfter = 3;
    GameLoop_PlayAnimation(scene, true);
    assert(shownCount == 3 && logs[0] == '\0');
    /* Other setup can exhaust the deadline too: log it and keep nominal pacing. */
    reset(); scene[0].flags = HOUSEANIM_FLAGS_MODE2 | HOUSEANIM_FLAGS_FADEINTEXT;
    paletteMs = 8000;
    GameLoop_PlayAnimation(scene, true);
    assert(strstr(logs, "playback budget exhausted"));
    assert(shownCount == sourceFrames);
    check_pacing(1, 230);
    /* Opted-out cutscenes retain their existing timing and produce no intro logs. */
    reset(); scene[0].flags = HOUSEANIM_FLAGS_MODE2 | HOUSEANIM_FLAGS_FADEIN;
    dissolveMs = 8000;
    GameLoop_PlayAnimation(scene, false);
    assert(shownCount == 15 && logs[0] == '\0');
    assert(shown[2] - shown[1] < 20);
    return 0;
}
"""
        harness = (harness.replace("GFX_HEADER", str(ROOT / "src/gfx.h"))
                   .replace("HOUSE_HEADER", str(ROOT / "src/house.h"))
                   .replace("WSA_HEADER", str(ROOT / "src/wsa.h"))
                   .replace("MATH_HEADER", str(ROOT / "src/os/math.h"))
                   .replace("/* PLAYBACK */", playback))
        with tempfile.TemporaryDirectory(prefix="intro-timing-") as directory:
            c_file, binary = Path(directory) / "test.c", Path(directory) / "test"
            c_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run(compiler + ["-std=c99", "-DTOS", "-O2", "-Wall", "-Wextra", "-Werror",
                                      *flags, "-I", str(ROOT / "include"), str(c_file),
                                      "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_original_and_planar_replay(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        presenter = "\n".join(function(video, name) for name in (
            "Video_Atari_CopyColourRun", "Video_Atari_CopyMonoRun",
            "Video_Atari_MonoPenWords", "Video_Atari_PaintColour", "Video_Atari_PaintMono")) + r"""
static unsigned copyRuns;
static void counted_colour_copy(uint8 *dst, uint16 ds, const uint8 *src, uint16 ss,
                                uint16 groups, uint16 height) {
    copyRuns++;
    Video_Atari_CopyColourRun(dst, ds, src, ss, groups, height);
}
static void counted_mono_copy(uint8 *dst, uint16 ds, const uint8 *src, uint16 ss,
                              uint16 groups, uint16 height) {
    copyRuns++;
    Video_Atari_CopyMonoRun(dst, ds, src, ss, groups, height);
}
static const struct {
    void (*copyRun)(uint8 *, uint16, const uint8 *, uint16, uint16, uint16);
    void (*paint)(uint16 *, uint16, uint16, uint16, uint16, uint16, const uint16 *, uint16, uint8, int16, int16);
    uint8 xShift;
} rectangleBackend[] = {{counted_colour_copy, Video_Atari_PaintColour, 1},
    {counted_mono_copy, Video_Atari_PaintMono, 2}},
    *s_planarBackend = &rectangleBackend[0];
static inline uint16 Video_Atari_GroupWords(void) { return g_videoAtariMono ? 2 : 4; }
""" + "\n".join(function(video, name) for name in (
            "Video_Atari_PlanarOffset", "Video_Atari_CopyPlanar", "Video_Atari_PaintPlanar",
            "Video_Atari_MergePlanarRows", "Video_Atari_GetPlanarCacheInfo",
            "Video_Atari_PlanarMappingHash", "Video_Atari_PlanarDeltaChanged",
            "Video_Atari_EncodePlanarDelta", "Video_Atari_ApplyPlanarDelta",
            "Video_Atari_LiveBegin", "Video_Atari_LiveEnd",
            "Video_Atari_PublishPlanarRun", "Video_Atari_PublishPlanarRect",
            "Video_Atari_PresentRestoreStrided", "Video_Atari_PresentPlanarSubRect",
            "Video_Atari_PresentPlanarRect"))
        gui = (ROOT / "src/gui/gui.c").read_text()
        fade = "\n".join(function(gui, name) for name in (
            "GUI_Screen_FadeInInternal", "GUI_Screen_FadeIn", "GUI_Screen_FadeInPlanar"))
        palette_setter = "\n".join(function(video, name) for name in (
            "Video_Atari_MonoCoverage", "Video_Atari_SetMonoCoverage",
            "Video_SetPalette"))
        harness = r"""
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "atari_mono.h"
#include "atari_mono_palette.h"
static int failAllocation = -1, allocationCalls, liveAllocations;
static void *checked_malloc(size_t size) {
    if (allocationCalls++ == failAllocation) return NULL;
    void *p = malloc(size);
    if (p != NULL) liveAllocations++;
    return p;
}
static void *checked_calloc(size_t count, size_t size) {
    if (allocationCalls++ == failAllocation) return NULL;
    void *p = calloc(count, size);
    if (p != NULL) liveAllocations++;
    return p;
}
static void checked_free(void *p) {
    if (p != NULL) liveAllocations--;
    free(p);
}
#include "CODEC_HEADER"
static unsigned decompressions, imageCopies;
static void *counted_memcpy(void *dst, const void *src, size_t size) {
    if (size == 19200) imageCopies++;
    return memcpy(dst, src, size);
}
static uint16 counted_format80(uint8 *dst, const uint8 *src, uint16 size) {
    decompressions++;
    return Format80_Decode(dst, src, size);
}
#define malloc checked_malloc
#define calloc checked_calloc
#define free checked_free
#define Format80_Decode counted_format80
#define memcpy counted_memcpy
#include "WSA_SOURCE"
#undef malloc
#undef calloc
#undef free
#undef Format80_Decode
#undef memcpy
WidgetProperties g_widgetProperties[22] = {{0, 0, 40, 200, 0, 0, 0}};
Screen g_screenActiveID = SCREEN_0;
static uint8 screens[4][64000];
static uint8 pens[256];
static uint16 visible[16000];
uint32 g_dirty_blocks[200];
#define dirtyScreen g_dirty_blocks
static FILE *files[8];
static unsigned encodes, publications, publishedGroups, warnings, fileReads;
static unsigned cacheOpens, cacheWrites, cacheDeletes;
static bool failCacheOpen, failCacheRead;
static int failCacheWord = -1, cacheWords;
static bool direct = true, cursorActive;
bool g_videoAtariMono;
static bool s_monoWhiteIsOne = true;
static AtariDitherLookup s_palette4BitDither;
static void Video_Atari_PublishNativeRect(const uint16 *, const uint16 *,
    uint16, uint16, uint16, uint16, int16, int16);
#define Video_Atari_DisplayListFlush() ((void)0)
#define Video_Atari_RestoreTileCursor() ((void)0)
enum { MCH_ST, MCH_STE, MCH_MEGA_STE, MCH_TT, MCH_FALCON };
static int s_machine_type = MCH_STE;
static bool s_presentMode, s_screen_needrepaint;
static unsigned s_paletteGeneration;
#define s_palette4BitMap pens
static uint8 s_paletteMonoCoverage[256];
static uint8 Palette_FindClosestColor(uint8 r, uint8 g, uint8 b) { return (r + g + b) & 15; }
static void Rebuild_Palette4BitPairMap(int first, int count);
static void set_mapping(void) {
    for (unsigned c = 0; c < 256; c++)
        for (unsigned y = 0; y < 4; y++)
            for (unsigned x = 0; x < 4; x++)
                s_palette4BitDither.pens[y][x][c] = g_videoAtariMono ?
                    ((pens[c] >> ((y & 1) * 2 + (x & 1))) ^ (x >> 1) ^ (y >> 1)) & 1 : pens[c];
}
void Video_Atari_CursorPreloadIcons(void) {}
static void VsetRGB(int first, int count, uint8 *rgb) {
    (void)first; (void)count; (void)rgb; assert(false);
}
static void EsetPalette(int first, int count, uint16 *rgb) {
    (void)first; (void)count; (void)rgb; assert(false);
}
static uint16 cursorSaved[4];
enum { ST_PLANAR_LINE_BYTES = 160, CURSOR_ROW = 50, CURSOR_GROUP = 19 };
static uint16 *cursor_words(void) { return visible + CURSOR_ROW * 80 + CURSOR_GROUP * 4; }
static void cursor_draw(void) {
    for (unsigned p = 0; p < 4; p++) cursor_words()[p] = cursorSaved[p] | 0x2020;
}
void Warning(const char *format, ...) { (void)format; warnings++; }
void Error(const char *format, ...) { (void)format; assert(false); }
/* PALETTE */
static void Rebuild_Palette4BitPairMap(int first, int count) {
    assert(first >= 0 && count > 0 && first + count <= 256);
    if (g_videoAtariMono)
        for (int i = first; i < first + count; i++)
            Video_Atari_SetMonoCoverage(&s_palette4BitDither, i, s_paletteMonoCoverage[i]);
}
static void exercise_palette(void) {
    uint8 palette[768] = {0};
    for (unsigned i = 0; i < 256; i++) palette[i * 3] = 15;
    s_presentMode = true;
    Video_SetPalette(palette, 0, 256);
    assert(!s_screen_needrepaint && pens[215] == 15);
    for (unsigned i = 0; i < 256; i++) palette[i * 3] = 3;
    s_presentMode = false;
    Video_SetPalette(palette, 0, 256);
    assert(s_screen_needrepaint == !g_videoAtariMono && pens[215] == 3);
    s_screen_needrepaint = false;
    if (g_videoAtariMono) {
        unsigned generation = s_paletteGeneration;
        /* Same ST pen as (3,0,0) in the stub, but a much brighter source RGB. */
        uint8 brighter[] = {51, 48, 48};
        Video_SetPalette(brighter, 215, 1);
        assert(pens[215] == 3 && s_paletteGeneration == generation + 1);
        assert(s_paletteMonoCoverage[215] == 12 && s_paletteMonoCoverage[216] == 0);
        unsigned white = 0;
        for (unsigned y = 0; y < 4; y++)
            for (unsigned x = 0; x < 4; x++)
                white += s_palette4BitDither.pens[y][x][215];
        assert(white == 12 && !s_screen_needrepaint);
        Video_SetPalette(brighter, 215, 1);
        assert(s_paletteGeneration == generation + 1);
    }
}
FILE *fopendatadir(enum SearchDirectory directory, const char *name, const char *mode) {
    assert(directory == SEARCHDIR_PERSONAL_DATA_DIR);
    cacheOpens++;
    if (mode[0] == 'r' && failCacheRead) { errno = EACCES; return NULL; }
    if (mode[0] == 'w') {
        cacheWrites++; cacheWords = 0;
        if (failCacheOpen) { errno = EACCES; return NULL; }
    }
    return fopen(name, mode);
}
void File_Delete_Personal(const char *name) { cacheDeletes++; remove(name); }
bool fread_le_uint16(uint16 *value, FILE *file) {
    uint8 bytes[2];
    if (fread(bytes, 1, 2, file) != 2) return false;
    *value = READ_LE_UINT16(bytes); return true;
}
bool fread_le_uint32(uint32 *value, FILE *file) {
    uint8 bytes[4];
    if (fread(bytes, 1, 4, file) != 4) return false;
    *value = READ_LE_UINT32(bytes); return true;
}
bool fwrite_le_uint16(uint16 value, FILE *file) {
    uint8 bytes[2] = {value & 255, value >> 8};
    if (cacheWords++ == failCacheWord) return false;
    return fwrite(bytes, 1, 2, file) == 2;
}
bool fwrite_le_uint32(uint32 value, FILE *file) {
    uint8 bytes[4] = {value & 255, (value >> 8) & 255, (value >> 16) & 255, value >> 24};
    if (cacheWords++ == failCacheWord) return false;
    return fwrite(bytes, 1, 4, file) == 4;
}
uint8 File_Open_Ex(enum SearchDirectory directory, const char *name, uint8 mode) {
    (void)directory;
    assert(mode == FILE_MODE_READ);
    for (uint8 i = 0; i < 8; i++) if (files[i] == NULL) {
        files[i] = fopen(name, "rb"); assert(files[i] != NULL); return i;
    }
    assert(false); return 0;
}
bool File_Exists_Ex(enum SearchDirectory directory, const char *name, uint32 *size) {
    (void)directory; (void)size;
    FILE *file = fopen(name, "rb");
    if (file == NULL) return false;
    fclose(file); return true;
}
void File_Close(uint8 i) { assert(files[i]); fclose(files[i]); files[i] = NULL; }
uint32 File_Read(uint8 i, void *buffer, uint32 size) {
    fileReads++;
    return fread(buffer, 1, size, files[i]);
}
uint16 File_Read_LE16(uint8 i) {
    uint8 b[2]; assert(File_Read(i, b, 2) == 2); return READ_LE_UINT16(b);
}
uint32 File_Read_LE32(uint8 i) {
    uint8 b[4]; assert(File_Read(i, b, 4) == 4); return READ_LE_UINT32(b);
}
uint32 File_Seek(uint8 i, uint32 position, uint8 mode) {
    assert(fseek(files[i], (int32)position, mode == 0 ? SEEK_SET : mode == 1 ? SEEK_CUR : SEEK_END) == 0);
    return ftell(files[i]);
}
void *GFX_Screen_Get_ByIndex(Screen screen) {
    if (screen == SCREEN_ACTIVE) screen = g_screenActiveID;
    assert(screen >= SCREEN_0 && screen <= SCREEN_3); return screens[screen];
}
void GFX_Screen_SetDirty_(uint16 left, uint16 top, uint16 right, uint16 bottom) {
    (void)left; (void)top; assert(right <= 320 && bottom <= 200);
}
bool Video_Atari_CursorDirect(void) { return direct; }
bool Video_Atari_PresentChunky(const void *src, uint16 stride, int16 x, int16 y,
                               uint16 width, uint16 height) {
    (void)src; (void)stride; (void)x; (void)y; (void)width; (void)height;
    assert(false); return false;
}
static unsigned native_word(unsigned stride, unsigned x, unsigned y, unsigned p) {
    return g_videoAtariMono ? y * stride + (p / 2) * (stride / 2) + (x * 2 + (p & 1)) / 16 :
        y * stride + (x / 16) * 4 + p;
}
static uint16 native_mask(unsigned x, unsigned p) {
    return 0x8000u >> (g_videoAtariMono ? (x * 2 + (p & 1)) & 15 : x & 15);
}
static bool native_pixel(const uint16 *src, unsigned stride, unsigned x, unsigned y, unsigned p) {
    return (src[native_word(stride, x, y, p)] & native_mask(x, p)) != 0;
}
static void native_put(uint16 *dst, unsigned stride, unsigned x, unsigned y, unsigned p, bool value) {
    uint16 *word = &dst[native_word(stride, x, y, p)], bit = native_mask(x, p);
    *word = (*word & ~bit) | (value ? bit : 0);
}
static bool expected_pixel(uint8 index, unsigned x, unsigned y, unsigned p) {
    if (g_videoAtariMono)
        return s_palette4BitDither.pens[(y * 2 + p / 2) & 3][(x * 2 + (p & 1)) & 3][index] ^
            !s_monoWhiteIsOne;
    return (s_palette4BitDither.pens[y & 3][x & 3][index] & (1u << p)) != 0;
}
void Video_Atari_PreparePlanar(const AtariDitherSource *source,
                              const AtariDitherLookup *lookup, uint16 *dst) {
    assert(lookup == NULL);
    encodes++;
    unsigned stride = ((source->width + 15) / 16) * 4;
    if (g_videoAtariMono) {
        AtariMonoPackedLookup packed;
        Video_Atari_MonoPreparePackedLookup(&packed, &s_palette4BitDither, 0, 256, s_monoWhiteIsOne);
        Video_Atari_MonoPackNative(source, &packed, dst, stride);
        return;
    }
    memset(dst, 0, stride * source->height * 2);
    for (unsigned y = 0; y < source->height; y++)
        for (unsigned x = 0; x < source->width; x++)
            for (unsigned p = 0; p < 4; p++)
                native_put(dst, stride, x, y, p,
                    expected_pixel(source->pixels[y * source->stride + x],
                        source->originX + x, source->originY + y, p));
}
void Video_Atari_EncodePlanarStrided(const uint8 *src, uint16 stride, uint16 *dst,
                                    uint16 width, uint16 height) {
    const AtariDitherSource source = {src, width, height, stride, 0, 0, 1, 1};
    Video_Atari_PreparePlanar(&source, NULL, dst);
}
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)visible; }
static bool s_viewportBlitter;
static bool Video_Atari_CursorRectOverlap(uint8 *base, uint16 first, uint16 end,
                                         uint16 y, uint16 height) {
    assert(base == (uint8 *)visible && first == 0 && end == 20 && y + height <= 200);
    assert(!cursorActive);
    return false;
}
static void Video_Atari_CursorEraseFull(void) { assert(false); }
static void Video_Atari_CursorSync(uint8 *base) { (void)base; assert(false); }
static void Video_Atari_PlanarFinishRun(uint8 *base, uint16 x, uint16 y,
                                       uint16 width, uint16 height) {
    assert(base == (uint8 *)visible);
    publications++;
    publishedGroups += width / 16 * height;
    if (cursorActive && y <= CURSOR_ROW && y + height > CURSOR_ROW &&
        x <= CURSOR_GROUP * 16 && x + width > CURSOR_GROUP * 16) {
        memcpy(cursorSaved, cursor_words(), 8);
        cursor_draw();
    }
}
bool g_screenViewportPlanar;
void GFX_Screen_ClearDirtyRect_(uint16 left, uint16 top, uint16 right, uint16 bottom) {
    for (unsigned y = top; y < bottom; y++)
        for (unsigned g = left / 16; g < (right + 15u) / 16; g++) dirtyScreen[y] &= ~(1u << g);
}
static bool Video_Atari_PlanarOverlaysOverlap(uint8 *base, uint16 x, uint16 y,
                                            uint16 width, uint16 height) {
    assert(base == (uint8 *)visible);
    return cursorActive && x < (CURSOR_GROUP + 1) * 16 && x + width > CURSOR_GROUP * 16 &&
           y <= CURSOR_ROW && y + height > CURSOR_ROW;
}
static void Video_Atari_PlanarMergePlain(uint16 *dst, uint16 mask, const uint16 *src) {
    for (unsigned p = 0; p < 4; p++) dst[p] = (dst[p] & ~mask) | (src[p] & mask);
}
static void Video_Atari_PlanarMergeGroup(uint8 *base, uint16 y, uint16 group,
                                       uint16 mask, const uint16 *src) {
    if (g_videoAtariMono) {
        for (unsigned x = 0; x < 16; x++)
            if (mask & (0x8000u >> x))
                for (unsigned p = 0; p < 4; p++)
                    native_put((uint16 *)base, 80, group * 16 + x, y, p,
                        native_pixel(src, 4, x, 0, p));
        publications++; publishedGroups++;
        return;
    }
    uint16 *dst = (uint16 *)base + y * 80 + group * 4;
    if (cursorActive && y == CURSOR_ROW && group == CURSOR_GROUP) {
        Video_Atari_PlanarMergePlain(cursorSaved, mask, src);
        cursor_draw();
    } else Video_Atari_PlanarMergePlain(dst, mask, src);
    publications++; publishedGroups++;
}
static void Video_Atari_PublishNativeRect(const uint16 *pixels, const uint16 *masks,
    uint16 sourceWidth, uint16 sourceX, uint16 width, uint16 height, int16 x, int16 y) {
    assert(masks == NULL && x >= 0 && y >= 0);
    for (unsigned row = 0; row < height; row++)
        for (unsigned col = 0; col < width; col++)
            for (unsigned p = 0; p < 4; p++)
                native_put(visible, 80, x + col, y + row, p,
                    native_pixel(pixels, sourceWidth / 4, sourceX + col, row, p));
    GFX_Screen_ClearDirtyRect_(x & ~15, y, (x + width + 15) & ~15, y + height);
    publications++; publishedGroups += ((x + width + 15) / 16 - x / 16) * height;
}
/* PRESENTER */
static unsigned cells, sleeps, randomState;
static uint16 cellX[4000], cellY[4000], expectedX[4000], expectedY[4000];
static void record_cell(uint16 x, uint16 y) {
    assert(cells < 4000);
    cellX[cells] = x; cellY[cells++] = y;
}
static bool traced_region(void *wsa, uint16 x, uint16 y, uint16 left, uint16 top,
                          uint16 width, uint16 height) {
    assert(width == 8 && height == 2);
    record_cell(x + left, y + top);
    return WSA_PresentPlanarRegion(wsa, x, y, left, top, width, height);
}
static void GUI_Mouse_Hide_InRegion(uint16 x, uint16 y, uint16 right, uint16 bottom) {
    assert(x < right && y < bottom);
}
static void GUI_Mouse_Show_InRegion(void) {}
static uint16 Tools_RandomLCG_Range(uint16 low, uint16 high) {
    randomState = randomState * 1664525u + 1013904223u;
    return low + randomState % (high - low + 1);
}
static void Timer_Sleep(uint16 ticks) { assert(ticks == 1); sleeps++; }
static void GUI_Screen_Copy(int16 xs, int16 ys, int16 xd, int16 yd,
                            int16 width, int16 height, Screen src, Screen dst) {
    assert(xs == xd && ys == yd && width == 1 && height == 2);
    assert(src == SCREEN_1 && dst == SCREEN_0);
    record_cell(xd * 8, yd);
}
#define WSA_PresentPlanarRegion traced_region
/* FADE */
#undef WSA_PresentPlanarRegion
static void exercise_fade(WSAHeader *wsa) {
    cells = sleeps = randomState = 0;
    GUI_Screen_FadeIn(1, 24, 1, 24, 38, 120, SCREEN_1, SCREEN_0);
    assert(cells == 2280 && sleeps == 30);
    memcpy(expectedX, cellX, sizeof(cellX)); memcpy(expectedY, cellY, sizeof(cellY));
    cells = sleeps = randomState = 0;
    unsigned beforeEncodes = encodes, beforeDecodes = decompressions, beforeReads = fileReads;
    assert(GUI_Screen_FadeInPlanar(wsa, 1, 24, 38, 120));
    assert(cells == 2280 && sleeps == 30);
    assert(!memcmp(expectedX, cellX, sizeof(cellX)) && !memcmp(expectedY, cellY, sizeof(cellY)));
    bool visited[60][38] = {{false}};
    for (unsigned cell = 0; cell < cells; cell++) {
        unsigned x = (cellX[cell] - 8) / 8, y = (cellY[cell] - 24) / 2;
        assert(x < 38 && y < 60 && !visited[y][x]); visited[y][x] = true;
    }
    assert(encodes == beforeEncodes && decompressions == beforeDecodes && fileReads == beforeReads);
}
static void check_window(WSAHeader *wsa, unsigned left, unsigned top, bool padded) {
    for (unsigned y = 0; y < 200; y++)
        for (unsigned x = 0; x < 320; x++) {
            bool inside = x >= left && x < left + wsa->width && y >= top && y < top + wsa->height;
            for (unsigned plane = 0; plane < 4; plane++) {
                bool expected = inside ?
                    expected_pixel(screens[SCREEN_1][(y - top) * 320 + x - left], x - left, y - top, plane) :
                    padded && y >= top && y < top + wsa->height ?
                        g_videoAtariMono && !s_monoWhiteIsOne : !!(0xa55a & native_mask(x, plane));
                assert(native_pixel(visible, 80, x, y, plane) == expected);
            }
        }
}
static void exercise_intro(const char *name, const char *const *parents, unsigned count) {
    cursorActive = false;
    memset(screens, 0xcd, sizeof(screens));
    memset(screens[SCREEN_1], 0, sizeof(screens[SCREEN_1]));
    memset(dirtyScreen, 0, sizeof(dirtyScreen));
    for (unsigned i = 0; i < 16000; i++) visible[i] = 0xa55a;
    WSAHeader *original = WSA_LoadFile(name, NULL, 1, false, false);
    WSAHeader *prepared = WSA_LoadFile(name, NULL, 1, true, true);
    assert(original && prepared);
    assert(WSA_IsContinuation(prepared) == (count != 0));
    if (count != 0) assert(WSA_PreparePlanarContinuation(prepared, parents, count));
    assert(WSA_GetFrameFormat(prepared) == WSA_FRAME_PLANAR);
    for (unsigned parent = 0; parent < count; parent++) {
        WSAHeader *previous = WSA_LoadFile(parents[parent], NULL, 1, false, false);
        assert(previous);
        for (unsigned frame = 0; frame < previous->frames; frame++)
            assert(WSA_DisplayFrame(previous, frame, 0, 0, SCREEN_1));
        WSA_Unload(previous);
    }
    unsigned x = prepared->width == 320 || !strcmp(name, "INTRO1.WSA") ? 0 : 8;
    unsigned y = x == 0 ? 0 : 24;
    static uint8 untouched[sizeof(screens)];
    for (unsigned step = 0; step < prepared->frames * 3u; step++) {
        unsigned frame = step < prepared->frames ? step :
            step < prepared->frames * 2u ? prepared->frames * 2u - step - 1 :
            (step * 7) % prepared->frames;
        assert(WSA_DisplayFrame(original, frame, 0, 0, SCREEN_1));
        if (!strncmp(name, "INTRO", 5))
            for (unsigned row = 0; row < original->height; row++)
                for (unsigned column = 0; column < original->width; column++) {
                    unsigned index = screens[SCREEN_1][row * 320 + column];
                    assert(index < 215 || index > 220);
                }
        memcpy(untouched, screens, sizeof(screens));
        unsigned beforeEncodes = encodes, beforeDecodes = decompressions, beforeReads = fileReads;
        assert(WSA_DisplayFrame(prepared, frame, x, y, SCREEN_0));
        assert(!memcmp(untouched, screens, sizeof(screens)));
        assert(encodes == beforeEncodes && decompressions == beforeDecodes && fileReads == beforeReads);
        check_window(prepared, x, y, false);
        if (step == 1 && x == 8 && prepared->width == 304) {
            native_put(visible, 80, 304, y, 0, !native_pixel(visible, 80, 304, y, 0));
            dirtyScreen[y] = 1u << 19;
            assert(WSA_DisplayFrame(prepared, frame, x, y, SCREEN_0));
            check_window(prepared, x, y, false);
        }
        if (step == 0 && x == 8 && prepared->width == 304 && prepared->height == 120) {
            for (unsigned i = 0; i < 16000; i++) visible[i] = 0xa55a;
            exercise_fade(prepared);
            check_window(prepared, x, y, false);
            assert(!memcmp(untouched, screens, sizeof(screens)));
        }
    }
    WSA_Unload(original);
    assert(rename(name, "INTRO.TMP") == 0);
    unsigned beforeReads = fileReads, beforeDecodes = decompressions, beforeEncodes = encodes;
    WSAHeader *cached = WSA_LoadFile(name, NULL, 1, true, true);
    assert(cached && cached->buffer == NULL && cached->fileContent == NULL);
    assert(WSA_IsContinuation(cached) == (count != 0));
    assert(fileReads == beforeReads && decompressions == beforeDecodes && encodes == beforeEncodes);
    for (unsigned frame = 0; frame < cached->frames; frame++) {
        assert(WSA_DisplayFrame(prepared, frame, x, y, SCREEN_2));
        assert(WSA_DisplayFrame(cached, frame, x, y, SCREEN_0));
        assert(!memcmp(cached->planar->pixels, prepared->planar->pixels,
                       (uint32)cached->planar->groups * cached->height * 8));
    }
    assert(!memcmp(untouched, screens, sizeof(screens)));
    assert(fileReads == beforeReads && decompressions == beforeDecodes && encodes == beforeEncodes);
    assert(rename("INTRO.TMP", name) == 0);
    WSA_Unload(cached); WSA_Unload(prepared);
    assert(liveAllocations == 0);
}
static void check_padded_image(WSAHeader *wsa) {
    for (unsigned row = 0; row < wsa->height; row++)
        for (unsigned x = 0; x < 320; x++)
            for (unsigned p = 0; p < 4; p++) {
                bool expected = x >= 8 && x < 312 ?
                    expected_pixel(screens[SCREEN_1][row * 320 + x - 8], x - 8, row, p) :
                    g_videoAtariMono && !s_monoWhiteIsOne;
                assert(native_pixel(wsa->planar->pixels, 80, x, row, p) == expected);
            }
}
static void exercise_padded_intro(const char *name, const char *const *parents, unsigned count) {
    cursorActive = false;
    memset(screens, 0, sizeof(screens));
    memset(dirtyScreen, 0, sizeof(dirtyScreen));
    for (unsigned i = 0; i < 16000; i++) visible[i] = 0xa55a;
    /* A previous compact cache must be recoded, not mistaken for screen-stride data. */
    WSAHeader *compact = WSA_LoadFile(name, NULL, 1, true, true);
    assert(compact);
    if (count != 0) assert(WSA_PreparePlanarContinuation(compact, parents, count));
    assert(compact->planar && compact->planar->groups == 19 && !compact->intro);
    WSA_Unload(compact);
    unsigned beforeWarnings = warnings, beforeWrites = cacheWrites;
    WSAHeader *prepared = WSA_LoadIntro(name, true);
    assert(prepared && prepared->intro && warnings == beforeWarnings + 1);
    if (count != 0) assert(WSA_PreparePlanarContinuation(prepared, parents, count));
    assert(prepared->planar && prepared->planar->groups == 20 && prepared->planar->composed == NULL);
    assert(cacheWrites == beforeWrites + 1);
    char cache[13];
    assert(WSA_PlanarFilename(name, cache));
    FILE *file = fopen(cache, "rb");
    uint8 header[56];
    assert(file && fread(header, 1, sizeof(header), file) == sizeof(header));
    fclose(file);
    assert((READ_LE_UINT16(header + 10) & 4) != 0 && READ_LE_UINT32(header + 52) == 19200);
    assert(READ_LE_UINT16(header + 6) == 304 && READ_LE_UINT16(header + 8) == 120);
    for (unsigned parent = 0; parent < count; parent++) {
        WSAHeader *previous = WSA_LoadFile(parents[parent], NULL, 1, false, false);
        assert(previous);
        for (unsigned frame = 0; frame < previous->frames; frame++)
            assert(WSA_DisplayFrame(previous, frame, 0, 0, SCREEN_1));
        WSA_Unload(previous);
    }
    WSAHeader *original = WSA_LoadFile(name, NULL, 1, false, false);
    assert(original);
    uint16 unstarted = prepared->frameCurrent;
    unsigned unstartedCopies = imageCopies;
    assert(!WSA_DisplayFrame(prepared, 0, 0, 24, SCREEN_0));
    assert(prepared->frameCurrent == unstarted && imageCopies == unstartedCopies);
    unsigned initial = prepared->frames - 1;
    assert(WSA_DisplayFrame(original, initial, 0, 0, SCREEN_1));
    unsigned oldPublications = publications, oldCopies = copyRuns;
    assert(WSA_DisplayFrame(prepared, initial, 8, 24, SCREEN_1));
    assert(prepared->planar->screen == NULL && publications == oldPublications && copyRuns == oldCopies);
    check_padded_image(prepared);
    for (unsigned i = 0; i < 16000; i++) assert(visible[i] == 0xa55a);
    exercise_fade(prepared);
    check_window(prepared, 8, 24, false);
    uint16 retained[9600];
    memcpy(retained, prepared->planar->pixels, sizeof(retained));
    static uint8 untouched[sizeof(screens)];
    for (unsigned step = 0; step < prepared->frames * 3u + 4; step++) {
        unsigned frame = step < prepared->frames ? step :
            step < prepared->frames * 2u ? prepared->frames * 2u - step - 1 :
            (step * 7) % prepared->frames;
        assert(WSA_DisplayFrame(original, frame, 0, 0, SCREEN_1));
        memcpy(untouched, screens, sizeof(screens));
        unsigned beforeEncodes = encodes, beforeReads = fileReads, beforeDecodes = decompressions;
        unsigned beforeImages = imageCopies;
        oldPublications = publications; oldCopies = copyRuns;
        dirtyScreen[23] = dirtyScreen[24] = dirtyScreen[143] = dirtyScreen[144] = 0xfffff;
        assert(WSA_DisplayFrame(prepared, frame, 8, 24, SCREEN_ACTIVE));
        assert(prepared->planar->screen == visible + 24 * 80);
        assert(!memcmp(retained, prepared->planar->pixels, sizeof(retained)));
        assert(imageCopies == beforeImages + (step == 0));
        assert(copyRuns == oldCopies && publications == oldPublications);
        assert(encodes == beforeEncodes && fileReads == beforeReads && decompressions == beforeDecodes);
        assert(!memcmp(untouched, screens, sizeof(screens)));
        assert(dirtyScreen[23] == 0xfffff && dirtyScreen[144] == 0xfffff);
        assert(dirtyScreen[24] == 0 && dirtyScreen[143] == 0);
        check_window(prepared, 8, 24, true);
    }
    /* Repeated frames remain copy-free; private preparation detaches only once. */
    unsigned frame = prepared->frameCurrent, beforeImages = imageCopies;
    assert(WSA_DisplayFrame(prepared, frame, 8, 24, SCREEN_0));
    assert(imageCopies == beforeImages);
    assert(!WSA_DisplayFrame(prepared, prepared->frames, 8, 24, SCREEN_0));
    assert(!WSA_DisplayFrame(prepared, frame, 0, 24, SCREEN_0));
    assert(!WSA_DisplayFrame(prepared, frame, 8, 81, SCREEN_0));
    assert(prepared->frameCurrent == frame && imageCopies == beforeImages);
    static uint16 unchanged[16000];
    memcpy(unchanged, visible, sizeof(visible));
    assert(WSA_DisplayFrame(prepared, frame, 8, 24, SCREEN_2));
    assert(prepared->planar->screen == NULL && imageCopies == beforeImages + 1);
    assert(!memcmp(unchanged, visible, sizeof(visible)));
    check_padded_image(prepared);
    frame = (frame + 1) % prepared->frames;
    assert(WSA_DisplayFrame(original, frame, 0, 0, SCREEN_1));
    assert(WSA_DisplayFrame(prepared, frame, 8, 24, SCREEN_2));
    check_padded_image(prepared);
    exercise_fade(prepared);
    assert(WSA_DisplayFrame(prepared, frame, 8, 24, SCREEN_0));
    check_window(prepared, 8, 24, true);
    /* A regional request also recovers the current image from the live accumulator. */
    beforeImages = imageCopies;
    assert(WSA_PresentPlanarRegion(prepared, 8, 24, 0, 0, 8, 2));
    assert(prepared->planar->screen == NULL && imageCopies == beforeImages + 1);
    check_padded_image(prepared);
    WSA_Unload(original);
    assert(rename(name, "PADDED.TMP") == 0);
    unsigned beforeReads = fileReads, beforeDecodes = decompressions, beforeEncodes = encodes;
    WSAHeader *cached = WSA_LoadIntro(name, false);
    assert(cached && cached->intro && cached->planar && cached->buffer == NULL);
    assert(WSA_IsContinuation(cached) == (count != 0));
    assert(fileReads == beforeReads && decompressions == beforeDecodes && encodes == beforeEncodes);
    for (unsigned step = 0; step < cached->frames * 2u + 3; step++) {
        frame = (step * 7) % cached->frames;
        assert(WSA_DisplayFrame(prepared, frame, 8, 24, SCREEN_2));
        assert(WSA_DisplayFrame(cached, frame, 8, 24, SCREEN_0));
        assert(!memcmp(visible + 24 * 80, prepared->planar->pixels, 19200));
    }
    assert(fileReads == beforeReads && decompressions == beforeDecodes && encodes == beforeEncodes);
    assert(rename("PADDED.TMP", name) == 0);
    WSA_Unload(cached); WSA_Unload(prepared);
    /* General loading must never interpret an intro canvas as a compact image. */
    beforeWarnings = warnings;
    compact = WSA_LoadFile(name, NULL, 1, true, true);
    assert(compact && !compact->intro && warnings == beforeWarnings + 1);
    if (count != 0) assert(WSA_PreparePlanarContinuation(compact, parents, count));
    assert(compact->planar && compact->planar->groups == 19);
    WSA_Unload(compact);
    prepared = WSA_LoadIntro(name, false);
    assert(prepared && prepared->intro);
    if (count != 0) assert(WSA_PreparePlanarContinuation(prepared, parents, count));
    assert(prepared->planar && prepared->planar->groups == 20);
    WSA_Unload(prepared);
    assert(liveAllocations == 0);
}
static void exercise_subrect(void) {
    uint8 source[128];
    uint16 pixels[32];
    for (unsigned i = 0; i < sizeof(source); i++) source[i] = i * 11;
    Video_Atari_EncodePlanarStrided(source, 64, pixels, 64, 2);
    const unsigned widths[] = {1, 8, 16, 33};
    for (unsigned phase = 0; phase < 16; phase++)
        for (unsigned sx = 0; sx < 32; sx++)
            for (unsigned size = 0; size < 4; size++) {
                unsigned x = 16 + phase, width = widths[size];
                if (width > 64 - sx) width = 64 - sx;
                for (unsigned i = 0; i < 16000; i++) visible[i] = 0xa55a;
                assert(Video_Atari_PresentPlanarSubRect(pixels, 32, sx, x, 100, width, 2));
                for (unsigned y = 0; y < 2; y++)
                    for (unsigned dx = 0; dx < 112; dx++) {
                        for (unsigned p = 0; p < 4; p++) {
                            bool expected = dx >= x && dx < x + width ?
                                expected_pixel(source[y * 64 + sx + dx - x], sx + dx - x, y, p) :
                                !!(0xa55a & native_mask(dx, p));
                            assert(native_pixel(visible, 80, dx, 100 + y, p) == expected);
                        }
                    }
            }
    assert(!Video_Atari_PresentPlanarSubRect(pixels, 32, 63, 0, 0, 2, 1));
    assert(!Video_Atari_PresentPlanarSubRect(pixels, 32, 0, 319, 0, 2, 1));
}
static void compare_frame(WSAHeader *prepared, const uint16 *overlay, const uint16 *masks) {
    unsigned groups = prepared->planar->groups;
    for (unsigned y = 0; y < prepared->height; y++)
        for (unsigned x = 0; x < prepared->width; x++) {
            unsigned bit = 0x8000u >> (x & 15), group = x / 16;
            uint8 expected = screens[SCREEN_1][y * 320 + x];
            for (unsigned p = 0; p < 4; p++) {
                assert(native_pixel(prepared->planar->pixels, groups * 4, x, y, p) ==
                    expected_pixel(expected, x, y, p));
                bool output = (masks[y * groups + group] & bit) ?
                    native_pixel(overlay, groups * 4, x, y, p) : expected_pixel(expected, x, y, p);
                bool shown = native_pixel(visible, 80, x + 128, y + 48, p);
                if (cursorActive && y + 48 == CURSOR_ROW && group + 8 == CURSOR_GROUP)
                    shown = (cursorSaved[p] & bit) != 0;
                assert(shown == output);
            }
        }
    if (prepared->width & 15) {
        for (unsigned y = 0; y < prepared->height; y++)
            for (unsigned x = prepared->width; x < groups * 16; x++)
                for (unsigned p = 0; p < 4; p++) {
                    bool shown = native_pixel(visible, 80, x + 128, y + 48, p);
                    if (cursorActive && y + 48 == CURSOR_ROW && x / 16 + 8 == CURSOR_GROUP)
                        shown = (cursorSaved[p] & native_mask(x + 128, p)) != 0;
                    assert(shown == !!(0xa55a & native_mask(x + 128, p)));
                }
    }
}
static void exercise(const char *name, bool disk) {
    allocationCalls = 0;
    WSAHeader *original = WSA_LoadFile(name, NULL, disk ? 1 : 0, false, false);
    WSAHeader *prepared = WSA_LoadFile(name, NULL, disk ? 1 : 0, false, false);
    assert(original && prepared && WSA_GetFrameFormat(prepared) == WSA_FRAME_CHUNKY);
    unsigned width = prepared->width, height = prepared->height;
    uint8 *saved = malloc(prepared->bufferLength);
    memcpy(saved, prepared->buffer, prepared->bufferLength);
    unsigned before = encodes;
    assert(WSA_PreparePlanar(prepared, width, height));
    assert(encodes == before + prepared->frames);
    assert(!memcmp(saved, prepared->buffer, prepared->bufferLength));
    assert(WSA_GetFrameFormat(prepared) == WSA_FRAME_PLANAR);
    assert(WSA_PreparePlanar(prepared, width, height));
    assert(!WSA_PreparePlanar(prepared, width - 1, height));
    free(saved);
    memset(screens, 0, sizeof(screens));
    for (unsigned i = 0; i < 16000; i++) visible[i] = 0xa55a;
    cursorActive = !g_videoAtariMono && width == 184 && height == 112;
    memcpy(cursorSaved, cursor_words(), 8);
    if (cursorActive) cursor_draw();
    unsigned groups = prepared->planar->groups;
    uint16 *overlay = calloc(groups * height * 4, sizeof(uint16));
    uint16 *masks = calloc(groups * height, sizeof(uint16));
    masks[0] = 0x8000; /* An opaque black overlay pixel. */
    masks[groups * height - 1] = 0x5555;
    overlay[(groups * height - 1) * 4] = 0x5555;
    for (unsigned step = 0; step < prepared->frames * 3u + 9; step++) {
        uint16 frame = step < prepared->frames * 2 ? step % prepared->frames :
            (step * 7 + prepared->frames / 2) % prepared->frames;
        assert(WSA_DisplayFrame(original, frame, 0, 0, SCREEN_1));
        unsigned oldEncodes = encodes, oldDecodes = decompressions, oldReads = fileReads;
        assert(WSA_DisplayFrame(prepared, frame, 128, 48, SCREEN_2));
        bool force = step == prepared->frames;
        if (force) { masks[0] = 0xf000; overlay[1] = 0xf000; }
        memset(dirtyScreen, 0, sizeof(dirtyScreen));
        if (step == 2) dirtyScreen[48 + height / 2] = (1u << 8) | (1u << 7);
        uint32 expectedDirty[200];
        for (unsigned y = 0; y < height; y++)
            expectedDirty[y] = force ? (1u << groups) - 1 :
                prepared->planar->dirty[y] | ((dirtyScreen[y + 48] >> 8) & ((1u << groups) - 1));
        assert(WSA_PresentPlanar(prepared, 128, 48, overlay, masks, force));
        assert(encodes == oldEncodes && decompressions == oldDecodes && fileReads == oldReads);
        compare_frame(prepared, overlay, masks);
        unsigned oldPublications = publications;
        assert(WSA_DisplayFrame(prepared, frame, 128, 48, SCREEN_2));
        assert(WSA_PresentPlanar(prepared, 128, 48, overlay, masks, false));
        assert(publications == oldPublications);
        for (unsigned y = 0; y < height; y++)
            assert((dirtyScreen[y + 48] & (expectedDirty[y] << 8)) == 0);
        if (step == 2) assert(dirtyScreen[48 + height / 2] & (1u << 7));
    }
    assert(!WSA_DisplayFrame(prepared, prepared->frames, 128, 48, SCREEN_2));
    /* Foreground redraw after playback stopped: no new WSA frame or overlay build. */
    unsigned damagedRow = 48 + height - 1;
    for (unsigned x = 128; x < 144; x++)
        for (unsigned p = 0; p < 4; p++)
            native_put(visible, 80, x, damagedRow, p, !native_pixel(visible, 80, x, damagedRow, p));
    dirtyScreen[damagedRow] = (1u << 8) | (1u << 7);
    unsigned oldEncodes = encodes, oldDecodes = decompressions, oldReads = fileReads;
    unsigned oldGroups = publishedGroups;
    assert(WSA_PresentPlanar(prepared, 128, 48, overlay, masks, false));
    compare_frame(prepared, overlay, masks);
    assert(publishedGroups == oldGroups + 1);
    assert(dirtyScreen[damagedRow] == (1u << 7));
    assert(encodes == oldEncodes && decompressions == oldDecodes && fileReads == oldReads);
    assert(!WSA_PresentPlanar(prepared, 321, 48, overlay, masks, false));
    assert(!WSA_PresentPlanar(prepared, 128, 48, overlay, NULL, false));
    WSA_Unload(prepared);
    WSA_Unload(original);
    free(overlay); free(masks);
    cursorActive = false;
    assert(liveAllocations == 0);
}
static void exercise_cache(const char *name) {
    char cache[13];
    assert(WSA_PlanarFilename(name, cache));
    unsigned oldOpens = cacheOpens;
    WSAHeader *original = WSA_LoadFile(name, NULL, 0, false, false);
    assert(original && cacheOpens == oldOpens);
    unsigned oldWrites = cacheWrites;
    assert(WSA_PresentPlanarPreview(name, NULL, 0, 128, 48, original->width, original->height));
    assert(cacheWrites == oldWrites + 1);
    WSAHeader *prepared = WSA_LoadFile(name, NULL, 0, false, true);
    assert(prepared && prepared->planar && cacheWrites == oldWrites + 1);
    FILE *file = fopen(cache, "rb");
    assert(file);
    char magic[4];
    assert(fread(magic, 1, 4, file) == 4 && !memcmp(magic, "PWS5", 4));
    assert(fseek(file, 56, SEEK_SET) == 0);
    for (unsigned i = 0; i < prepared->planar->groups * prepared->height * 4u; i++) {
        uint8 bytes[2];
        uint16 word = prepared->planar->frames[0][i];
        assert(fread(bytes, 1, 2, file) == 2);
        assert(bytes[0] == word >> 8 && bytes[1] == (word & 255));
    }
    fclose(file);
    assert(rename(name, "SOURCE.TMP") == 0);
    unsigned oldReads = fileReads, oldDecodes = decompressions, oldEncodes = encodes;
    WSAHeader *preview = WSA_LoadPlanar(name, cache, NULL, 0, false, true);
    assert(preview && preview->frames == 0 && preview->planar->pixels == NULL &&
        preview->planar->composed == NULL);
    assert(!memcmp(preview->planar->frames[0], prepared->planar->frames[0],
        prepared->planar->groups * prepared->height * 8u));
    WSA_Unload(preview);
    assert(WSA_PresentPlanarPreview(name, NULL, 0, 128, 48, original->width, original->height));
    uint32 *caller = malloc(64000);
    assert(caller);
    memset(caller, 0xa5, 64000);
    WSAHeader *cached = WSA_LoadFile(name, caller, 64000, false, true);
    assert(cached == (void *)caller && cached->planar);
    assert(cached->buffer == NULL && cached->fileContent == NULL && !cached->flags.malloced);
    for (unsigned i = sizeof(*cached); i < 64000; i++)
        assert(((uint8 *)caller)[i] == 0xa5);
    assert(fileReads == oldReads && decompressions == oldDecodes && encodes == oldEncodes);
    assert(cacheWrites == oldWrites + 1);
    WSAHeader *owned = WSA_LoadFile(name, NULL, 1, false, true);
    assert(owned && owned->planar && owned->flags.malloced && owned->buffer == NULL);
    WSA_Unload(owned);
    assert(fileReads == oldReads && decompressions == oldDecodes && encodes == oldEncodes);
    assert(cached->frames == prepared->frames && cached->width == prepared->width &&
           cached->height == prepared->height && cached->flags.noAnimation == prepared->flags.noAnimation);
    unsigned groups = cached->planar->groups, height = cached->height;
    for (unsigned i = 0; i <= cached->frames; i++) {
        unsigned bytes = i == 0 ? groups * height * 8 : WSA_PlanarDeltaLength(prepared->planar->frames[i]);
        assert(!memcmp(cached->planar->frames[i], prepared->planar->frames[i], bytes));
    }
    assert(rename("SOURCE.TMP", name) == 0);
    for (unsigned i = 0; i < 16000; i++) visible[i] = 0xa55a;
    memset(screens, 0, sizeof(screens));
    memset(dirtyScreen, 0, sizeof(dirtyScreen));
    uint16 *overlay = calloc(groups * height * 4, 2), *masks = calloc(groups * height, 2);
    for (unsigned step = 0; step < cached->frames * 2u + 3; step++) {
        uint16 frame = (step * 7) % cached->frames;
        assert(WSA_DisplayFrame(original, frame, 0, 0, SCREEN_1));
        oldReads = fileReads; oldDecodes = decompressions; oldEncodes = encodes;
        assert(WSA_DisplayFrame(cached, frame, 128, 48, SCREEN_2));
        assert(WSA_PresentPlanar(cached, 128, 48, NULL, NULL, false));
        compare_frame(cached, overlay, masks);
        assert(fileReads == oldReads && decompressions == oldDecodes && encodes == oldEncodes);
    }
    free(overlay); free(masks);
    WSA_Unload(cached);
    WSA_Unload(cached);
    free(caller);
    WSA_Unload(prepared);
    WSA_Unload(original);
    assert(liveAllocations == 0);
    oldOpens = cacheOpens;
    original = WSA_LoadFile(name, NULL, 0, false, false);
    assert(original && !original->planar && cacheOpens == oldOpens);
    WSA_Unload(original);
    original = WSA_LoadFile(name, NULL, 0, true, true);
    assert(original && original->planar && cacheOpens > oldOpens);
    WSA_Unload(original);
    assert(liveAllocations == 0);
}
static void cache_failures(const char *name) {
    char cache[13];
    assert(WSA_PlanarFilename(name, cache));
    FILE *file = fopen(cache, "rb");
    assert(file && fseek(file, 0, SEEK_END) == 0);
    unsigned size = ftell(file);
    rewind(file);
    uint8 *good = malloc(size), *bad = malloc(size + 1);
    assert(fread(good, 1, size, file) == size);
    fclose(file);
    unsigned imageBytes = READ_LE_UINT32(good + 52);
    for (unsigned variant = 0; variant < 12; variant++) {
        memcpy(bad, good, size);
        unsigned length = size;
        switch (variant) {
            case 0: bad[0] = 'X'; break;
            case 1: bad[4] = bad[5] = 0xff; break; /* Invalid frame count. */
            case 2: bad[6] = bad[7] = 0; break; /* Invalid geometry. */
            case 3: bad[10] = 8; break; /* Unknown flags. */
            case 4: memset(bad + 52, 0xff, 4); break; /* Oversized/odd block. */
            case 5: length = 11; break;
            case 6: length--; break;
            case 7: bad[size] = 0; length++; break; /* Trailing data. */
            case 8: bad[56 + imageBytes + 6] = 0xff; break; /* Delta exceeds its row. */
            case 9: bad[12] ^= 1; break; /* Native layout / mono polarity mismatch. */
            case 10: bad[16] ^= 1; break; /* Palette/dither mapping mismatch. */
            case 11: /* Unidentified legacy mapping is rebuilt. */
                bad[3] = '4'; length -= 40; memmove(bad + 12, good + 52, length - 12); break;
        }
        file = fopen(cache, "wb"); assert(file);
        assert(fwrite(bad, 1, length, file) == length); fclose(file);
        unsigned before = warnings;
        WSAHeader *wsa = WSA_LoadFile(name, NULL, 0, false, true);
        assert(wsa && wsa->planar && warnings == before + 1);
        WSA_Unload(wsa);
        assert(liveAllocations == 0);
    }
    free(good); free(bad);
    failCacheRead = true;
    unsigned beforeRead = warnings;
    WSAHeader *readFallback = WSA_LoadFile(name, NULL, 0, false, true);
    failCacheRead = false;
    assert(readFallback && readFallback->planar && warnings == beforeRead + 1);
    WSA_Unload(readFallback);
    assert(liveAllocations == 0);
    for (int fault = 0; fault < 9; fault++) {
        failAllocation = fault; allocationCalls = 0;
        unsigned before = warnings;
        WSAHeader *wsa = WSA_LoadFile(name, NULL, 0, false, true);
        failAllocation = -1;
        assert(wsa && wsa->planar && warnings == before + 1);
        WSA_Unload(wsa);
        assert(liveAllocations == 0);
    }
    for (unsigned variant = 0; variant < 2; variant++) {
        remove(cache);
        failCacheOpen = variant == 0;
        failCacheWord = variant == 1 ? 4 : -1;
        unsigned before = warnings, oldDeletes = cacheDeletes;
        WSAHeader *wsa = WSA_LoadFile(name, NULL, 0, false, true);
        failCacheOpen = false; failCacheWord = -1;
        assert(wsa && wsa->planar && warnings == before + 1);
        assert(cacheDeletes == oldDeletes + (variant == 1));
        file = fopen(cache, "rb"); assert(file == NULL);
        WSA_Unload(wsa);
        assert(liveAllocations == 0);
    }
    direct = false;
    unsigned oldOpens = cacheOpens;
    WSAHeader *wsa = WSA_LoadFile(name, NULL, 0, false, true);
    assert(wsa && !wsa->planar && cacheOpens == oldOpens);
    WSA_Unload(wsa);
    direct = true;
    assert(liveAllocations == 0);
}
static void exercise_mapping_cache(void) {
    WSAHeader *prepared = WSA_LoadFile("TEST.WSA", NULL, 0, false, true);
    assert(prepared && prepared->planar);
    assert(prepared->planar->colours[31 / 8] & (1u << (31 & 7)));
    assert(!(prepared->planar->colours[200 / 8] & (1u << (200 & 7))));
    WSA_Unload(prepared);
    unsigned oldReads = fileReads, oldEncodes = encodes, oldWrites = cacheWrites, before = warnings;
    s_palette4BitDither.pens[0][0][200] ^= 1; /* An unused slot must not invalidate. */
    assert(rename("TEST.WSA", "MAPPING.TMP") == 0);
    prepared = WSA_LoadFile("TEST.WSA", NULL, 0, false, true);
    assert(prepared && prepared->planar && prepared->buffer == NULL);
    assert(fileReads == oldReads && encodes == oldEncodes &&
        cacheWrites == oldWrites && warnings == before);
    WSA_Unload(prepared);
    assert(rename("MAPPING.TMP", "TEST.WSA") == 0);
    s_palette4BitDither.pens[0][0][200] ^= 1;
    s_palette4BitDither.pens[0][0][31] ^= 1; /* Same flat pens, different dither policy. */
    prepared = WSA_LoadFile("TEST.WSA", NULL, 0, false, true);
    assert(prepared && prepared->planar && prepared->buffer != NULL);
    assert(fileReads > oldReads && encodes > oldEncodes &&
        cacheWrites == oldWrites + 1 && warnings == before + 1);
    assert(WSA_DisplayFrame(prepared, 0, 0, 0, SCREEN_2));
    for (unsigned p = 0; p < 4; p++)
        assert(native_pixel(prepared->planar->pixels, prepared->planar->groups * 4, 0, 0, p) ==
            expected_pixel(31, 0, 0, p));
    WSA_Unload(prepared);
    s_palette4BitDither.pens[0][0][31] ^= 1;
    assert(liveAllocations == 0);
}
int main(int argc, char **argv) {
    assert(argc > 2);
    bool hitOnly = strstr(argv[1], "-hit") != NULL;
    g_videoAtariMono = !strncmp(argv[1], "mono", 4);
    s_monoWhiteIsOne = strcmp(argv[1], "mono-inverted") != 0;
    s_planarBackend = &rectangleBackend[g_videoAtariMono];
    argc--; argv++;
    exercise_palette();
    for (unsigned i = 0; i < 256; i++) pens[i] = (i * i + i * 3 + 5) & 15;
    pens[0] = pens[12] = 0;
    set_mapping();
    if (hitOnly) {
        const char *names[] = {"COEXIST.WSA", "PADDED.WSA"};
        for (unsigned i = 0; i < 2; i++) {
            assert(rename(names[i], "COEXIST.TMP") == 0);
            unsigned oldReads = fileReads, oldEncodes = encodes, oldWrites = cacheWrites;
            WSAHeader *cached = i == 0 ? WSA_LoadFile(names[i], NULL, 0, false, true) :
                WSA_LoadIntro(names[i], false);
            assert(cached && cached->planar && cached->buffer == NULL);
            assert(cached->intro == (i == 1));
            assert(fileReads == oldReads && encodes == oldEncodes && cacheWrites == oldWrites);
            WSA_Unload(cached);
            assert(rename("COEXIST.TMP", names[i]) == 0 && liveAllocations == 0);
        }
        return 0;
    }
    unsigned initialWarnings = warnings;
    assert(WSA_LoadFile("BAD.WSA", NULL, 0, false, false) == NULL);
    assert(warnings == initialWarnings + 1 && liveAllocations == 0);
    for (int i = 1; i < argc; i++) {
        exercise(argv[i], false);
        exercise(argv[i], true);
        exercise_cache(argv[i]);
    }
    cache_failures(argv[1]);
    exercise_mapping_cache();
    exercise_subrect();
    const char *one[] = {"TEST.WSA"}, *two[] = {"TEST.WSA", "CONT1.WSA"};
    exercise_intro("CONT1.WSA", one, 1);
    exercise_intro("CONT2.WSA", two, 2);
    exercise_padded_intro("PADDED.WSA", NULL, 0);
    const char *paddedParents[] = {"PADDED.WSA"};
    exercise_padded_intro("PADCONT.WSA", paddedParents, 1);
    if (File_Exists("INTRO1.WSA")) {
        const char *independent[] = {"INTRO1.WSA", "INTRO2.WSA", "INTRO3.WSA", "INTRO4.WSA",
            "INTRO5.WSA", "INTRO6.WSA", "INTRO7A.WSA", "INTRO8A.WSA", "INTRO9.WSA",
            "INTRO10.WSA", "INTRO11.WSA", "WESTWOOD.WSA"};
        for (unsigned i = 0; i < sizeof(independent) / sizeof(*independent); i++)
            exercise_intro(independent[i], NULL, 0);
        const char *seven[] = {"INTRO7A.WSA"}, *eight[] = {"INTRO8A.WSA", "INTRO8B.WSA"};
        exercise_intro("INTRO7B.WSA", seven, 1);
        exercise_intro("INTRO8B.WSA", eight, 1);
        exercise_intro("INTRO8C.WSA", eight, 2);
        for (unsigned i = 1; i < sizeof(independent) / sizeof(*independent) - 1; i++)
            exercise_padded_intro(independent[i], NULL, 0);
        exercise_padded_intro("INTRO7B.WSA", seven, 1);
        exercise_padded_intro("INTRO8B.WSA", eight, 1);
        exercise_padded_intro("INTRO8C.WSA", eight, 2);
    }
    for (int fault = 0; fault < 16; fault++) {
        allocationCalls = 0;
        WSAHeader *wsa = WSA_LoadFile(argv[1], NULL, 0, false, false);
        uint8 *saved = malloc(wsa->bufferLength);
        memcpy(saved, wsa->buffer, wsa->bufferLength);
        failAllocation = fault; allocationCalls = 0;
        unsigned beforeWarnings = warnings;
        bool ready = WSA_PreparePlanar(wsa, wsa->width, wsa->height);
        failAllocation = -1;
        assert(!memcmp(saved, wsa->buffer, wsa->bufferLength));
        if (!ready) {
            assert(warnings == beforeWarnings + 1);
            assert(WSA_GetFrameFormat(wsa) == WSA_FRAME_CHUNKY);
            memset(screens, 0, sizeof(screens));
            assert(WSA_DisplayFrame(wsa, 0, 0, 0, SCREEN_1));
            assert(pens[screens[SCREEN_1][0]] == pens[31]);
        }
        WSA_Unload(wsa); free(saved);
        assert(liveAllocations == 0);
    }
    WSAHeader *wsa = WSA_LoadFile(argv[1], NULL, 0, false, false);
    assert(!WSA_PreparePlanar(wsa, wsa->width - 1, wsa->height));
    direct = false;
    assert(!WSA_PreparePlanar(wsa, wsa->width, wsa->height));
    direct = true;
    wsa->flags.hasNoFirstFrame = true;
    assert(!WSA_PreparePlanar(wsa, wsa->width, wsa->height));
    wsa->flags.hasNoFirstFrame = false;
    assert(WSA_PreparePlanar(wsa, wsa->width, wsa->height));
    assert(WSA_DisplayFrame(wsa, 0, 128, 48, SCREEN_0));
    unsigned beforePublication = publications;
    assert(WSA_DisplayFrame(wsa, 1, 128, 48, SCREEN_ACTIVE));
    assert(publications > beforePublication);
    WSA_Unload(wsa);
    static uint8 callerBuffer[65536];
    wsa = WSA_LoadFile(argv[1], callerBuffer, sizeof(callerBuffer), false, false);
    assert(wsa == (void *)callerBuffer && WSA_PreparePlanar(wsa, wsa->width, wsa->height));
    WSA_Unload(wsa);
    assert(liveAllocations == 0 && WSA_GetFrameFormat(wsa) == WSA_FRAME_CHUNKY);
    WSA_Unload(wsa);
    return 0;
}
"""
        harness = (harness.replace("WSA_SOURCE", str(ROOT / "src/wsa.c"))
                   .replace("CODEC_HEADER", str(ROOT / "src/codec/format80.h"))
                   .replace("/* PRESENTER */", presenter).replace("/* FADE */", fade)
                   .replace("/* PALETTE */", palette_setter))
        with tempfile.TemporaryDirectory(prefix="wsa-planar-") as directory:
            folder = Path(directory)
            c_file, binary = folder / "test.c", folder / "test"
            c_file.write_text(harness)
            files = {"TEST.WSA": fixture()}
            files["COEXIST.WSA"] = fixture()
            bad = bytearray(fixture())
            struct.pack_into("<H", bad, 6, 32)
            (folder / "BAD.WSA").write_bytes(bad)
            archive = ROOT / "MENTAT.PAK"
            if archive.exists():
                files.update(archive_wsas(archive))
            for name, data in files.items():
                (folder / name).write_bytes(data)
            for name in ("CONT1.WSA", "CONT2.WSA"):
                (folder / name).write_bytes(continuation_fixture())
            (folder / "PADDED.WSA").write_bytes(intro_fixture())
            (folder / "PADCONT.WSA").write_bytes(continuation_fixture(intro_fixture()))
            intro = ROOT / "INTRO.PAK"
            if intro.exists():
                for name, data in archive_wsas(intro).items():
                    (folder / name).write_bytes(data)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run(compiler + shlex.split(os.environ.get("TEST_CFLAGS", "")) +
                                     ["-std=c99", "-DTOS", "-O2", "-Wall", "-Wextra", "-Werror",
                                      "-I", str(ROOT / "include"), "-I", str(ROOT / "src/video"), str(c_file),
                                      str(ROOT / "src/codec/format40.c"),
                                      str(ROOT / "src/codec/format80.c"),
                                      str(ROOT / "src/video/atari_mono.c"),
                                      str(ROOT / "src/video/atari_dither.c"), "-o", str(binary)], check=True)
            subprocess.run([str(binary), "colour", *files], cwd=folder, check=True)
            colour_cache = (folder / "COEXIST.PWS").read_bytes()
            colour_intro_cache = (folder / "PADDED.PWS").read_bytes()
            subprocess.run([str(binary), "mono", *files], cwd=folder, check=True)
            self.assertEqual((folder / "COEXIST.PWS").read_bytes(), colour_cache)
            self.assertEqual((folder / "PADDED.PWS").read_bytes(), colour_intro_cache)
            mono_cache = (folder / "COEXIST.PWM").read_bytes()
            mono_intro_cache = (folder / "PADDED.PWM").read_bytes()
            subprocess.run([str(binary), "colour-hit", *files], cwd=folder, check=True)
            self.assertEqual((folder / "COEXIST.PWM").read_bytes(), mono_cache)
            self.assertEqual((folder / "PADDED.PWM").read_bytes(), mono_intro_cache)
            subprocess.run([str(binary), "mono-hit", *files], cwd=folder, check=True)
            subprocess.run([str(binary), "mono-inverted", *files], cwd=folder, check=True)
            self.assertEqual((folder / "COEXIST.PWS").read_bytes(), colour_cache)
            self.assertEqual((folder / "PADDED.PWS").read_bytes(), colour_intro_cache)

    def test_mentat_overlay_cache(self):
        source = (ROOT / "src/gui/mentat.c").read_text()
        start = source.index("typedef struct MentatPlanarOverlay")
        end = source.index("\n#endif", start)
        production = source[start:end]
        animation = function(source, "GUI_Mentat_Animation")
        opacity = function((ROOT / "src/gui/gui.c").read_text(), "GUI_DrawSpriteOpacity")
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
enum { SCREEN_WIDTH = 320, SCREEN_HEIGHT = 200, SCREEN_0 = 0, SCREEN_2 = 2 };
#define DRAWSPRITE_FLAG_REMAP 0x100
#define GUI_SPRITE_COLOUR_EMBEDDED 0xfe
#define GUI_SPRITE_ID_UNKNOWN 0xffff
enum { HOUSE_HARKONNEN, HOUSE_ATREIDES, HOUSE_ORDOS };
static uint16 g_curWidgetWidth = 23, g_curWidgetHeight = 112;
static uint16 g_curWidgetXBase = 16, g_curWidgetYBase = 48;
static uint16 g_shoulderLeft = 131, g_shoulderTop = 58, g_playerHouseID;
static uint8 s_otherLeft = 72, s_otherTop = 152;
static uint8 screen[64000], sprite, *g_sprites[480];
static uint8 *s_mentatSprites[3][5];
static uint32 g_timerGUI;
static bool g_disableOtherMovement, g_interrogation;
static uint8 s_eyesLeft = 40, s_eyesTop = 80, s_eyesRight = 60, s_eyesBottom = 88;
static uint8 s_mouthLeft = 40, s_mouthTop = 96, s_mouthRight = 60, s_mouthBottom = 104;
static unsigned descriptions, shoulders, encodes;
static unsigned otherDraws;
#define Warning(...) assert(false)
static uint8 Sprite_GetWidth(uint8 *src) { assert(src == &sprite); return 96; }
static uint8 Sprite_GetHeight(uint8 *src) { assert(src == &sprite); return 48; }
static void *GFX_Screen_Get_ByIndex(unsigned index) { assert(index == 2); return screen; }
static void GUI_Mouse_Hide_InRegion(unsigned left, unsigned top, unsigned right, unsigned bottom) {
    (void)left; (void)top; (void)right; (void)bottom;
}
static void GUI_Mouse_Show_InRegion(void) {}
static unsigned Input_Test(unsigned key) { (void)key; return 0; }
static unsigned Mouse_InsideRegion(int left, int top, int right, int bottom) {
    (void)left; (void)top; (void)right; (void)bottom; return 0;
}
static uint16 Tools_RandomLCG_Range(uint16 low, uint16 high) {
    return low == 1 && high == 3 ? 1 : high;
}
static void GUI_Mentat_DrawInfo(char *text, unsigned x, unsigned y, unsigned height,
                                unsigned skip, int lines, unsigned flags) {
    assert(text && x == 133 && y == 51 && height == 8 && skip == 0 && flags == 0x31);
    descriptions++;
    for (int i = 0; i < lines; i++) {
        screen[(y + i * 8) * 320 + x] = 12;
        screen[(y + i * 8) * 320 + x + 1] = 31;
    }
}
static void GUI_DrawSprite(unsigned screenID, const uint8 *src, unsigned id,
                            unsigned colour, unsigned x, unsigned y, unsigned window, int flags) {
    if (screenID == SCREEN_0) {
        assert(src == &sprite && id == GUI_SPRITE_ID_UNKNOWN && colour == 0xfe);
        if (x == s_otherLeft && y == s_otherTop) otherDraws++;
        return;
    }
    assert(screenID == 2 && src == &sprite && id == 397 && colour == 0xfe && window == 0 && flags == 0);
    shoulders++;
    screen[y * 320 + x] = 12;
    screen[y * 320 + x + 1] = 0; /* Opaque colour 0. */
    screen[(y + 1) * 320 + x] = 31;
    screen[(y + 1) * 320 + x + 2] = 81;
}
static void GUI_DrawSpriteMask(uint8 *dst, uint16 width, uint16 height, const uint8 *src,
                               int x, int y, int flags, ...) {
    assert(src == &sprite && width == 192 && height == 112 && x == 3 && y == 10);
    assert(flags == DRAWSPRITE_FLAG_REMAP);
    va_list ap;
    va_start(ap, flags);
    const uint8 *map = va_arg(ap, const uint8 *);
    assert(va_arg(ap, int) == 1);
    for (unsigned i = 0; i < 256; i++) assert(map[i] == 1);
    va_end(ap);
    dst[y * width + x] = dst[y * width + x + 1] = 1;
    dst[(y + 1) * width + x] = dst[(y + 1) * width + x + 2] = 1;
}
static void Video_Atari_EncodePlanarStrided(const uint8 *src, uint16 stride, uint16 *dst,
                                           uint16 width, uint16 height) {
    assert(stride == 320 && width == 192 && height == 112);
    encodes++;
    memset(dst, 0, width * height / 2);
    for (unsigned y = 0; y < height; y++)
        for (unsigned x = 0; x < width; x++)
            for (unsigned p = 0; p < 4; p++)
                if ((src[y * stride + x] == 12 ? 0 : src[y * stride + x] & 15) & (1u << p))
                    dst[y * (width / 4) + (x / 16) * 4 + p] |= 0x8000u >> (x & 15);
}
/* OPACITY */
/* ANIMATION */
/* OVERLAY */
int main(void) {
    memset(screen, 0x55, sizeof(screen));
    g_sprites[397] = &sprite;
    MentatPlanarOverlay *overlay = GUI_Mentat_CreatePlanarOverlay();
    assert(overlay && overlay->width == 192 && overlay->height == 112);
    assert(GUI_Mentat_BuildPlanarOverlay(overlay, "test", 1));
    for (unsigned y = 0; y < 112; y++)
        for (unsigned x = 0; x < 192; x++) {
            bool expected = (y == 3 && (x == 5 || x == 6)) ||
                (y == 10 && (x == 3 || x == 4)) || (y == 11 && (x == 3 || x == 5));
            bool mask = !!(overlay->masks[y * 12 + x / 16] & (0x8000u >> (x & 15)));
            assert(mask == expected);
        }
    assert(overlay->pixels[(10 * 12) * 4] == 0);
    assert(overlay->masks[10 * 12] & (0x8000u >> 4)); /* Black is not a hole. */
    assert(screen[48 * 320 + 127] == 0x55 && screen[47 * 320 + 128] == 0x55);
    assert(!GUI_Mentat_BuildPlanarOverlay(overlay, "test", 1));
    assert(encodes == 1 && descriptions == 1 && shoulders == 1);
    assert(GUI_Mentat_BuildPlanarOverlay(overlay, "test", 2));
    assert(overlay->masks[11 * 12] & (0x8000u >> 6));
    assert(encodes == 2 && descriptions == 2 && shoulders == 2);
    GUI_Mentat_FreePlanarOverlay(overlay);
    GUI_Mentat_FreePlanarOverlay(NULL);
    /* Foreground animation must not rebuild the WSA overlay. */
    g_playerHouseID = HOUSE_ATREIDES;
    s_otherLeft = 72; s_otherTop = 152;
    for (unsigned part = 0; part < 3; part++)
        for (unsigned i = 0; i < 5; i++) s_mentatSprites[part][i] = &sprite;
    g_timerGUI = 10;
    GUI_Mentat_Animation(0);
    assert(otherDraws == 0);
    g_timerGUI = 71;
    GUI_Mentat_Animation(0);
    assert(otherDraws == 1 && encodes == 2);
    GUI_Mentat_Animation(0);
    assert(otherDraws == 1);
    g_disableOtherMovement = true;
    g_timerGUI = 1000;
    GUI_Mentat_Animation(0);
    assert(otherDraws == 1);
    return 0;
}
"""
        harness = (harness.replace("/* OPACITY */", opacity)
                   .replace("/* ANIMATION */", animation).replace("/* OVERLAY */", production))
        with tempfile.TemporaryDirectory(prefix="mentat-overlay-") as directory:
            c_file, binary = Path(directory) / "test.c", Path(directory) / "test"
            c_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run(compiler + ["-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                                      str(c_file), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_mentat_native_animation_sprites(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        draw = function(gui, "GUI_DrawSpriteInternal")
        mentat = (ROOT / "src/gui/mentat.c").read_text()
        sprites = mentat[mentat.index("enum { MENTAT_EYES"):mentat.index("\nbool g_interrogation")]
        cache = mentat[mentat.index("static GUI_PlanarSprite s_planarFrames"):mentat.index(
            "\n#endif", mentat.index("void GUI_Mentat_PreparePlanarFrames"))]
        widget = (ROOT / "src/gui/widget.c").read_text()
        widget_cache = widget[widget.index("typedef struct WidgetSpriteDraw"):widget.index(
            "\n#endif", widget.index("static bool GUI_Widget_DrawPreparedSprite"))]
        harness = r"""
#include <assert.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "gui/gui.h"
#include "gui/widget.h"
#include "os/endian.h"
#include "os/math.h"
#include "video/atari_mono.h"
WidgetProperties g_widgetProperties[22] = {{0, 0, 40, 200, 0, 0, 0}};
static uint8 screen[64000];
static uint8 reference[96 * 48];
static unsigned presents, dirty;
static uint8 *s_spriteBatchBuf;
static uint16 s_spriteBatchStride;
static int16 s_spriteBatchOriginX, s_spriteBatchOriginY, s_spriteBatchW, s_spriteBatchH;
void *GFX_Screen_Get_ByIndex(Screen screenID) { assert(screenID == SCREEN_0); return screen; }
#undef GFX_Screen_SetDirty
void GFX_Screen_SetDirty(Screen screenID, uint16 left, uint16 top, uint16 right, uint16 bottom) {
    assert(screenID == SCREEN_0 && left < right && top < bottom);
    dirty++;
}
static bool Video_Atari_CursorDirect(void) { return true; }
static uint16 Format80_Decode(uint8 *dst, const uint8 *src, uint16 size) {
    (void)dst; (void)src; (void)size; assert(false); return 0;
}
void GUI_Widget_Viewport_RepairTiles(int16 left, int16 top, int16 right, int16 bottom) {
    (void)left; (void)top; (void)right; (void)bottom; assert(false);
}
static bool Video_Atari_PresentChunkyTransparent(const void *pixels, uint16 stride,
                                                 int16 x, int16 y, uint16 width, uint16 height) {
    const uint8 *src = pixels;
    assert(x == 72 && y == 152 && width == 96 && height == 48 && stride == 96);
    memcpy(reference, src, sizeof(reference));
    for (unsigned row = 0; row < height; row++)
        for (unsigned col = 0; col < width; col++)
            assert(src[row * stride + col] == (row < 8 && col >= 56 ? 0 : 81));
    presents++;
    return true;
}
/* DRAW */
/* BUFFER */
/* SPRITES */
static uint8 s_otherLeft = 72, s_otherTop = 152;
static uint8 s_eyesLeft = 40, s_eyesTop = 80, s_mouthLeft = 56, s_mouthTop = 96;
static bool g_disableOtherMovement, g_videoDisplayListActive, mono, whiteIsOne;
static uint16 generation;
static unsigned preparations, publications, fallbacks, hides, shows;
static AtariDitherLookup lookup;
static AtariMonoPackedLookup packed;
static unsigned left, top, spriteWidth, spriteHeight;
static const uint8 *expectedSprite;
#define Warning(...) assert(false)
static uint8 Sprite_GetWidth(const uint8 *sprite) { return sprite ? sprite[3] : 0; }
static uint8 Sprite_GetHeight(const uint8 *sprite) { return sprite ? sprite[2] : 0; }
static uint16 Video_Atari_GetPaletteGeneration(void) { return generation; }
void GUI_Mouse_Hide_InRegion(uint16 x, uint16 y, uint16 right, uint16 bottom) {
    assert(x == left && y == top && right == x + spriteWidth && bottom == y + spriteHeight);
    hides++;
}
void GUI_Mouse_Show_InRegion(void) { shows++; }
void GUI_DrawSprite(Screen screenID, const uint8 *sprite, uint16 id, uint8 colour,
                    int16 x, int16 y, uint16 window, int flags, ...) {
    assert(screenID == SCREEN_0 && sprite == expectedSprite && id == GUI_SPRITE_ID_UNKNOWN);
    assert(colour == GUI_SPRITE_COLOUR_EMBEDDED && x == (int)left && y == (int)top);
    assert(window == 0 && flags == 0);
    fallbacks++;
}
static void Video_Atari_PreparePlanar(const AtariDitherSource *src,
                                     const AtariDitherLookup *dither, uint16 *dst) {
    assert(dither == NULL);
    preparations++;
    if (mono) {
        Video_Atari_MonoPackNative(src, &packed, dst, src->width / 4);
    } else {
        for (unsigned y = 0; y < src->height; y++)
            for (unsigned x = 0; x < src->width; x++)
                for (unsigned p = 0; p < 4; p++)
                    if (src->pixels[y * src->stride + x] & (1u << p))
                        dst[y * src->width / 4 + x / 16 * 4 + p] |= 0x8000u >> (x & 15);
    }
}
static void Video_Atari_PresentPlanarText(const uint16 *pixels, const uint16 *masks,
                                         uint16 width, uint16 height, uint16 x, uint16 y) {
    unsigned phase = left & 15, groups = width / 16;
    assert(x == (left & ~15u) && y == top &&
           width == ((phase + spriteWidth + 15) & ~15u) && height == spriteHeight);
    publications++;
    for (unsigned row = 0; row < height; row++)
        for (unsigned col = 0; col < width; col++) {
            unsigned group = col / 16, bit = col & 15;
            unsigned src = 0;
            if (col >= phase && col < phase + spriteWidth) {
                if (top == s_otherTop) src = reference[row * 96 + col - phase];
                else if (col > phase) src = top == s_mouthTop ? 37 : 62;
            }
            assert(!!(masks[row * groups + group] & (0x8000u >> bit)) == (src != 0));
            if (!src) continue; /* No writes over the existing picture or edge padding. */
            if (mono) {
                uint16 words[4];
                Video_Atari_MonoReadGroup(pixels, width / 4, row, group, words);
                for (unsigned dy = 0; dy < 2; dy++)
                    for (unsigned dx = 0; dx < 2; dx++) {
                        unsigned d = 2 * bit + dx;
                        unsigned expected = lookup.pens[(2 * row + dy) & 3]
                            [(2 * (col - phase) + dx) & 3][src] == whiteIsOne;
                        assert(((words[2 * dy + d / 16] >> (15 - d % 16)) & 1) == expected);
                    }
            } else {
                for (unsigned p = 0; p < 4; p++)
                    assert(((pixels[row * width / 4 + group * 4 + p] >> (15 - bit)) & 1) == ((src >> p) & 1));
            }
        }
}
/* CACHE */
/* DISPATCH */
uint8 g_remap[256], g_monoWidgetRemap[256];
static bool s_widgetReset;
static bool Video_Atari_Mono(void) { return mono; }
bool GFX_Screen_IsActive(Screen screenID) { return screenID == SCREEN_0; }
Widget *GUI_Widget_GetNext(Widget *w) { return w->next; }
/* WIDGET CACHE */
static void check_frame(uint16 part, uint16 frame, uint16 x, uint16 y, const uint8 *sprite) {
    left = x; top = y; expectedSprite = sprite;
    spriteWidth = sprite == NULL ? 0 : sprite[3];
    spriteHeight = sprite == NULL ? 0 : sprite[2];
    GUI_Mentat_DrawFrame(part, frame, x, y);
}
int main(void) {
    uint8 sprite[10 + 128 * 48] = {2, 0, 48, 96, 0};
    uint8 mouth[] = {3, 0, 1, 9, 0, 0, 0, 0, 0, 0,
                      0, 37, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                      2, 1, 1, 1, 1, 1, 1, 1, 1};
    uint8 eyes[] = {2, 0, 2, 3, 0, 0, 0, 0, 0, 0, 0, 1, 62, 62, 0, 1, 62, 62};
    unsigned end = 10;
    for (unsigned row = 0; row < 48; row++) {
        unsigned opaque = row < 8 ? 56 : 96;
        memset(sprite + end, 81, opaque); end += opaque;
        if (row < 8) { sprite[end++] = 0; sprite[end++] = 40; }
    }
    memset(screen, 0x55, sizeof(screen));
    GUI_DrawSpriteInternal(SCREEN_0, sprite, 72, 152, 0, 0, NULL, NULL, 0, 0);
    assert(presents == 1 && dirty == 0);
    for (unsigned i = 0; i < sizeof(screen); i++) assert(screen[i] == 0x55);
    GUI_DrawSpriteInternal(SCREEN_0, sprite, 72, 152, 0,
                           DRAWSPRITE_FLAG_NO_PLANAR_DIRECT, NULL, NULL, 0, 0);
    assert(presents == 1 && dirty == 1);
    assert(screen[152 * 320 + 128] == 0x55); /* Transparent WSA overlap stays untouched. */
    s_mentatSprites[MENTAT_OTHER][0] = sprite;
    s_mentatSprites[MENTAT_MOUTH][4] = mouth; /* Palette index 2 decodes to zero. */
    s_mentatSprites[MENTAT_EYES][3] = eyes;
    for (unsigned mode = 0; mode < 3; mode++) {
        mono = mode != 0;
        whiteIsOne = mode == 1;
        for (unsigned y = 0; y < 4; y++)
            for (unsigned x = 0; x < 4; x++) {
                lookup.pens[y][x][81] = (y + (x >> 1)) % 3 == 0;
                lookup.pens[y][x][37] = (y ^ x) & 1;
                lookup.pens[y][x][62] = ((y >> 1) ^ (x >> 1)) & 1;
            }
        Video_Atari_MonoPreparePackedLookup(&packed, &lookup, 0, 256, whiteIsOne);
        GUI_Mentat_PreparePlanarFrames();
        check_frame(MENTAT_OTHER, 0, s_otherLeft, s_otherTop, sprite);
        check_frame(MENTAT_EYES, 3, s_eyesLeft, s_eyesTop, eyes);
        check_frame(MENTAT_MOUTH, 4, s_mouthLeft, s_mouthTop, mouth);
        mouth[11] = 99; /* Later draws use the predecoded embedded palette. */
        check_frame(MENTAT_MOUTH, 4, s_mouthLeft, s_mouthTop, mouth);
        mouth[11] = 37;
        assert(preparations == 3 * (mode + 1) && publications == 4 * (mode + 1));
        assert(fallbacks == 4 * mode);
        check_frame(MENTAT_EYES, 0, s_eyesLeft, s_eyesTop, NULL);
        g_videoDisplayListActive = true;
        check_frame(MENTAT_MOUTH, 4, s_mouthLeft, s_mouthTop, mouth);
        g_videoDisplayListActive = false;
        generation++;
        check_frame(MENTAT_EYES, 3, s_eyesLeft, s_eyesTop, eyes);
        GUI_Mentat_FreePlanarFrames();
        generation--;
        check_frame(MENTAT_OTHER, 0, s_otherLeft, s_otherTop, sprite);
        assert(fallbacks == 4 * (mode + 1) && hides == fallbacks && shows == fallbacks);
    }
    g_disableOtherMovement = true;
    GUI_Mentat_PreparePlanarFrames();
    check_frame(MENTAT_MOUTH, 4, s_mouthLeft, s_mouthTop, mouth);
    check_frame(MENTAT_OTHER, 0, s_otherLeft, s_otherTop, sprite);
    assert(preparations == 11 && publications == 13 && fallbacks == 13);
    GUI_Mentat_FreePlanarFrames();
    Widget buttons[2] = {0};
    for (unsigned i = 0; i < 256; i++) g_remap[i] = i;
    g_remap[37] = 62;
    buttons[0].offsetX = buttons[1].offsetX = 168;
    buttons[0].offsetY = buttons[1].offsetY = 168;
    buttons[0].next = &buttons[1];
    for (unsigned i = 0; i < 2; i++) {
        buttons[i].drawModeNormal = buttons[i].drawModeSelected = buttons[i].drawModeDown = DRAW_MODE_SPRITE;
        buttons[i].drawParameterNormal.sprite = buttons[i].drawParameterSelected.sprite = i ? eyes : mouth;
        buttons[i].drawParameterDown.sprite = i ? mouth : eyes;
    }
    GUI_Widget_PrepareSpriteDraws(buttons);
    assert(s_widgetReset && preparations == 13 && s_spriteDrawCount == 2);
    left = top = 168; spriteWidth = mouth[3]; spriteHeight = mouth[2];
    assert(GUI_Widget_DrawPreparedSprite(&buttons[0], mouth, g_remap, left, top));
    assert(publications == 14 && preparations == 13);
    generation++;
    assert(!GUI_Widget_DrawPreparedSprite(&buttons[0], mouth, g_remap, left, top));
    generation--;
    GUI_Widget_FreeSpriteDraws();
    assert(!GUI_Widget_DrawPreparedSprite(&buttons[0], mouth, g_remap, left, top));
    /* Keep the fallback for sprites larger than the new 4,608-byte capacity. */
    sprite[2] = 40; sprite[3] = 128;
    memset(sprite + 10, 81, 128 * 40);
    GUI_DrawSpriteInternal(SCREEN_0, sprite, 0, 0, 0, 0, NULL, NULL, 0, 0);
    assert(presents == 1 && dirty == 2);
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="mentat-native-sprites-") as directory:
            c_file, binary = Path(directory) / "test.c", Path(directory) / "test"
            c_file.write_text(harness.replace("/* DRAW */", draw)
                              .replace("/* BUFFER */", function(gui, "GUI_DrawSpriteToBuffer"))
                              .replace("/* SPRITES */", sprites)
                              .replace("/* CACHE */", function(gui, "GUI_PreparePlanarSprite") + "\n" + cache)
                              .replace("/* WIDGET CACHE */", widget_cache)
                              .replace("/* DISPATCH */", function(mentat, "GUI_Mentat_DrawFrame")))
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run(compiler + ["-std=c99", "-DTOS", "-O2", "-Wall", "-Wextra", "-Werror",
                                      "-I", str(ROOT / "include"), "-iquote", str(ROOT / "src"),
                                      str(c_file), str(ROOT / "src/video/atari_mono.c"),
                                      "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_palette_quantization(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        start = video.index("const uint8 s_palette4BitPC[")
        end = video.index("\n};", start) + len("\n};")
        harness = r"""
#include <assert.h>
#include "types.h"
#define MAKE_PC_COLOR(r, g, b) (r)>>2, (g)>>2, (b)>>2, 0
/* PALETTE */
static uint16 s_SquareTable[256];
/* QUANTIZER */
static uint8 reference(unsigned r, unsigned g, unsigned b) {
    r &= ~3u; g &= ~3u; b &= ~3u;
    unsigned best = 0, distance = ~0u;
    for (unsigned pen = 0; pen < 16; pen++) {
        int dr = (s_palette4BitPC[pen * 4] & ~3) - (int)r;
        int dg = (s_palette4BitPC[pen * 4 + 1] & ~3) - (int)g;
        int db = (s_palette4BitPC[pen * 4 + 2] & ~3) - (int)b;
        unsigned error = 3 * dr * dr + 6 * dg * dg + 2 * db * db;
        if (error < distance) { distance = error; best = pen; }
    }
    return best;
}
int main(void) {
    for (unsigned i = 0; i < 256; i++) s_SquareTable[i] = i * i;
    for (unsigned r = 0; r < 64; r++)
        for (unsigned g = 0; g < 64; g++)
            for (unsigned b = 0; b < 64; b++) {
                unsigned pen = Palette_FindClosestColor(r, g, b);
                assert(pen == reference(r, g, b));
            }
    assert(Palette_FindClosestColor(0, 0, 0) == 0);
    assert(Palette_FindClosestColor(1, 0, 0) == 0);
    assert(Palette_FindClosestColor(0, 1, 0) == 0);
    assert(Palette_FindClosestColor(0, 0, 1) == 0);
    return 0;
}
"""
        harness = harness.replace("/* PALETTE */", video[start:end]).replace(
            "/* QUANTIZER */", function(video, "Palette_FindClosestColor"))
        with tempfile.TemporaryDirectory(prefix="palette-quantization-") as directory:
            folder = Path(directory)
            c_file, binary = folder / "test.c", folder / "test"
            c_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run(compiler + ["-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                                      "-I", str(ROOT / "include"), str(c_file),
                                      "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_static_intro_subtitles(self):
        cutscene = (ROOT / "src/cutscene.c").read_text()
        functions = "\n".join(function(cutscene, name) for name in (
            "GameLoop_CopySubtitlePalette", "GameLoop_PrepareAnimation"))
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "GFX_HEADER"
typedef struct { uint16 colour; } HouseAnimation_Subtitle;
typedef struct { uint16 unused; } HouseAnimation_SoundEffect;
enum { PPD_STOPPED };
static const HouseAnimation_Subtitle *s_houseAnimation_subtitle;
static const HouseAnimation_SoundEffect *s_houseAnimation_soundEffect;
static unsigned s_houseAnimation_currentSubtitle, s_houseAnimation_currentSoundEffect;
static unsigned g_fontCharOffset, s_feedback_base_index, s_subtitleIndex, s_subtitleWait;
static bool s_subtitleActive, s_staticSubtitlePalette, direct = true;
static unsigned s_palettePartDirection, s_palettePartCount, s_paletteAnimationTimeout;
static uint8 s_palettePartCurrent[18], s_palettePartTarget[18], s_palettePartChange[18];
static uint8 palette1[768], g_palette_998A[768], sourcePalette[768];
uint8 *g_palette1 = palette1;
static void *g_fontIntro;
bool Video_Atari_CursorDirect(void) { return direct; }
void GFX_ClearScreen(Screen screen) { (void)screen; }
Screen GFX_Screen_SetActive(Screen screen) { return screen; }
static void Font_Select(void *font) { assert(font == g_fontIntro); }
static void File_ReadBlockFile(const char *name, void *buffer, unsigned bytes) {
    assert(!strcmp(name, "INTRO.PAL") && bytes == 768);
    memcpy(buffer, sourcePalette, bytes);
}
static void GUI_InitColors(const uint8 *colors, uint8 first, uint8 last) {
    assert(first == 0 && last == 15 && colors[0] == 0);
    for (unsigned i = 0; i < 6; i++) assert(colors[i + 1] == 215 + i);
}
/* FUNCTIONS */
int main(void) {
    const uint8 red[6] = {55, 49, 42, 36, 30, 23};
    for (unsigned i = 0; i < 6; i++) sourcePalette[(215 + i) * 3] = red[i];
    HouseAnimation_Subtitle subtitle = {0};
    GameLoop_PrepareAnimation(&subtitle, 0x4a, NULL, true);
#ifdef TOS
    assert(s_staticSubtitlePalette && !memcmp(g_palette1, sourcePalette, 768));
    memset(s_palettePartCurrent, 0, 18);
    GameLoop_CopySubtitlePalette(g_palette1);
    assert(!memcmp(g_palette1, sourcePalette, 768));
    memset(g_palette_998A + 3, 63, 765); /* White flash still keeps subtitle mapping. */
    GameLoop_CopySubtitlePalette(g_palette_998A);
    assert(!memcmp(g_palette_998A + 215 * 3, sourcePalette + 215 * 3, 18));
    memset(s_palettePartCurrent, 7, 18); /* A different house/fade ramp is ignored. */
    GameLoop_CopySubtitlePalette(g_palette1);
    GameLoop_CopySubtitlePalette(g_palette_998A);
    assert(!memcmp(g_palette1, sourcePalette, 768));
    assert(!memcmp(g_palette_998A + 215 * 3, sourcePalette + 215 * 3, 18));
#else
    assert(!s_staticSubtitlePalette);
    for (unsigned i = 0; i < 18; i++) assert(g_palette1[215 * 3 + i] == 0);
#endif
    GameLoop_PrepareAnimation(&subtitle, 0xffff, NULL, false);
    assert(!s_staticSubtitlePalette);
    for (unsigned i = 0; i < 18; i++) assert(g_palette1[215 * 3 + i] == 0);
    memset(s_palettePartCurrent, 9, 18);
    GameLoop_CopySubtitlePalette(g_palette1);
    for (unsigned i = 0; i < 18; i++) assert(g_palette1[215 * 3 + i] == 9);
    direct = false;
    GameLoop_PrepareAnimation(&subtitle, 0x4a, NULL, true);
    assert(!s_staticSubtitlePalette);
    for (unsigned i = 0; i < 18; i++) assert(g_palette1[215 * 3 + i] == 0);
    return 0;
}
"""
        harness = harness.replace("GFX_HEADER", str(ROOT / "src/gfx.h")).replace(
            "/* FUNCTIONS */", functions)
        with tempfile.TemporaryDirectory(prefix="intro-subtitles-") as directory:
            folder = Path(directory)
            c_file, binary = folder / "test.c", folder / "test"
            c_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for defines in ([], ["-DTOS"]):
                subprocess.run(compiler + defines + [
                    "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "include"), str(c_file), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_non_tos_compilation(self):
        with tempfile.TemporaryDirectory(prefix="wsa-original-") as directory:
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run(compiler + ["-std=c99", "-Wall", "-Wextra", "-Werror", "-I",
                                      str(ROOT / "include"), "-c", str(ROOT / "src/wsa.c"),
                                      "-o", str(Path(directory) / "wsa.o")], check=True)


if __name__ == "__main__":
    unittest.main()
