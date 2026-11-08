"""Exercise production feedback scheduling and retained message cleanup."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function
from tools.test_unit_smoke_damage import run_harness


ROOT = Path(__file__).resolve().parents[1]


class ViewportMessagesTest(unittest.TestCase):
    def test_queued_cache_lifetimes_cursor_order_and_glyph_fallback(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        draw = function((ROOT / "src/gui/viewport.c").read_text(), "GUI_Widget_Viewport_Draw")
        start = draw.index("\tif (planarViewport && s_tileCursorShown")
        finish = draw.index("\n#endif\n\tif (updateDisplay)", start)
        tail = draw[start:finish]
        cache = gui[gui.index("#define TEXT_PLANAR_ENTRIES"):
                    gui.index("\n#endif", gui.index("#define TEXT_PLANAR_ENTRIES"))]
        production = "\n".join(function(video, name) for name in (
            "Video_Atari_PlanarMergePlain", "Video_Atari_PlanarCopyGroup",
            "Video_Atari_PublishViewportCursorRect", "Video_Atari_PresentPlanarText"))
        production += "\n" + function(gui, "GUI_TextPlanar_PresentGlyph")
        production += "\n" + cache + "\n" + function(gui, "GUI_DrawText_Planar")
        harness = r"""
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "src/gfx.h"
#include "src/gui/font.h"
#include "src/gui/glyph.h"
#include "src/video/video.h"
#include "src/os/endian.h"
#define ST_PLANAR_LINE_BYTES 160
#define min(a,b) ((a)<(b)?(a):(b))
bool g_videoViewportBlitter = true;
bool g_screenViewportPlanar = true;
static uint16 screen[16000], saved[16000];
static bool overlays, s_textPlanarAllowed, cursorDamaged = true;
static uint16 *s_planarTarget;
static unsigned executions, commands, tails, rasterizations, restores, refreshed;
static uint8 fontData;
static FontChar chars[256];
static Font font = { .height = 6, .chars = chars };
Font *g_fontCurrent = &font;
int8 g_fontCharOffset;
static uint8 g_colours[16];
static const char *g_viewportMessageText;
static uint16 g_viewportMessageCounter, s_tileCursorCol = 4, s_tileCursorRow = 6;
static bool s_tileCursorShown = true, s_tileCursorTarget, s_viewportSpriteFilterActive;
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)screen; }
bool Video_Atari_CursorDirect(void) { return true; }
static bool GUI_Sidebar_Active(void) { return false; }
bool GFX_Screen_IsActive(Screen screenID) { return screenID == SCREEN_0; }
static bool Video_Atari_PlanarOverlaysOverlap(uint8 *base, uint16 x, uint16 y, uint16 w, uint16 h) {
    (void)base; (void)x; (void)y; (void)w; (void)h; return overlays;
}
static void Video_Atari_PlanarMergeGroup(uint8 *base, uint16 y, uint16 group,
                                        uint16 mask, const uint16 *pixels) {
    assert(base == (uint8 *)screen);
    for (unsigned p=0;p<4;p++) {
        unsigned offset=y*80+group*4+p;
        saved[offset]=(saved[offset] & (uint16)~mask) | (pixels[p] & mask);
        screen[offset]=saved[offset]; /* backup-aware compatibility publication */
    }
}
static void Video_Atari_RefreshViewportCursor(uint8 *base, uint16 first, uint16 end,
    uint16 top, uint16 bottom, const uint16 *masks, uint16 stride) {
    (void)base; (void)first; (void)end; (void)top; (void)bottom; (void)masks; (void)stride;
    refreshed++;
}
void GFX_Screen_ClearDirtyRect_(uint16 x, uint16 y, uint16 right, uint16 bottom) {
    assert(x < right && right <= 320 && y < bottom && bottom <= 200);
}
void (*g_videoTileCursorTail)(void);
void Video_Atari_RestoreTileCursor(void) { if (g_videoTileCursorTail != NULL) restores++; }
static void cursor(void) {
    tails++;
    for (unsigned p=0;p<4;p++) screen[139*80+16+p] = p == 2 ? 0xffff : 0;
}
void Video_Atari_TileCursorFrame(uint16 col, uint16 row, bool target) {
    (void)col; (void)row; (void)target; cursor();
}
void Video_Atari_EndViewportProtection(void) { g_videoTileCursorTail = NULL; }
static bool GUI_Widget_Viewport_SpriteDamageRect(int16 l, int16 t, int16 r, int16 b, bool redraw) {
    assert(l == 64 && t == 136 && r == 80 && b == 152);
    return redraw || cursorDamaged;
}
uint16 endian_bswap16(uint16 v) { return (v >> 8) | (v << 8); }
uint32 endian_bswap32(uint32 v) { return __builtin_bswap32(v); }
void Error(const char *fmt, ...) { (void)fmt; abort(); }
static struct { const uint16 *pixels, *masks; uint16 *dst; uint16 groups, rows; } queued[64];
static unsigned next;
void Video_Atari_QueueMaskedRect(const uint16 *pixels, const uint16 *masks, uint16 *dst,
                                uint16 groups, uint16 rows) {
    assert(next < 64);
    queued[next].pixels=pixels; queued[next].masks=masks; queued[next].dst=dst;
    queued[next].groups=groups; queued[next].rows=rows;
    *g_videoDisplayListNext++=HTOBE16(0x4e70);
    *g_videoDisplayListNext++=HTOBE16(next++);
    for (unsigned i=0;i<14;i++) *g_videoDisplayListNext++=0;
}
void Video_Atari_ExecuteDisplayList(const uint16 *stream) {
    assert(!g_videoDisplayListActive); executions++;
    while (true) {
        uint16 op=BETOH16(*stream++);
        if (op == 0x4e75) break;
        if (op == 0x4e71) continue;
        if (op == 0x4eb9) {
            uint32 address=(uint32)BETOH16(stream[0]) << 16 | BETOH16(stream[1]);
            assert(address == (uint32)(size_t)cursor);
            stream+=2; cursor(); continue;
        }
        assert(op == 0x4e70);
        unsigned index=BETOH16(*stream++); stream+=14; commands++;
        for (unsigned row=0;row<queued[index].rows;row++)
            for (unsigned group=0;group<queued[index].groups;group++)
                for (unsigned p=0;p<4;p++) {
                    uint16 *dst=queued[index].dst+row*80+group*4+p;
                    unsigned source=row*queued[index].groups+group;
                    uint16 mask=queued[index].masks[source];
                    *dst=(*dst & (uint16)~mask) | (queued[index].pixels[source*4+p] & mask);
                }
    }
}
#include "src/video/atari_display_list.c"
bool GUI_Glyph_Usable(const Font *f) { return f == &font; }
uint16 GUI_Glyph_Line(const Font *f, const uint8 colours[16], const char *text,
    uint16 phase, uint16 maxGroups, uint16 rows, uint16 *pixels, uint16 pixelStride,
    uint16 *masks, uint16 maskStride) {
    (void)colours; (void)phase; assert(f == &font && rows == f->height);
    uint16 groups=text[0] == 'W' ? 8 : 2; assert(groups <= maxGroups);
    rasterizations++;
    for (unsigned row=0;row<rows;row++) for (unsigned group=0;group<groups;group++) {
        masks[row*maskStride+group]=(row+group)%3 == 0 ? 0 : 0xa55a;
        for (unsigned p=0;p<4;p++)
            pixels[row*pixelStride+group*4+p]=text[0]*137+row*31+group*17+p;
    }
    return groups;
}
void Video_Atari_EncodePlanar(const uint8 *src, uint16 *pixels, uint16 width, uint16 height) {
    unsigned groups=width/16;
    memset(pixels,0,(size_t)groups*height*8);
    for (unsigned row=0;row<height;row++) for (unsigned col=0;col<width;col++) {
        unsigned pen=(src[row*width+col]*7)&15;
        for (unsigned p=0;p<4;p++) if (pen & (1u<<p))
            pixels[row*groups*4+(col/16)*4+p] |= 0x8000u>>(col&15);
    }
}
void GUI_DrawText_Wrapper(const char *text, int16 left, int16 top, uint8 fg, uint8 bg, int flags, ...);
/* PRODUCTION */
void GUI_DrawText_Wrapper(const char *text, int16 left, int16 top, uint8 fg, uint8 bg, int flags, ...) {
    assert(left == 112 && top == 139 && fg == 15 && bg == 0 && flags == 0x132);
    assert(GUI_DrawTextPlanarCached(text,64,top));
}
static void finish(bool planarViewport) {
    /* RENDERER */
}
int main(void) {
    static const char *strings[]={"A","B","C","D","E","Wide"};
    for (unsigned i=0;i<256;i++) { chars[i].width=1; chars[i].data=&fontData; }
    for (unsigned i=0;i<16000;i++) screen[i]=saved[i]=0x2468;
    Video_Atari_DisplayListBegin();
    for (unsigned i=0;i<4;i++) GUI_DrawText_Planar(strings[i],112,139,15,0,0x132);
    assert(rasterizations == 4 && !executions && !commands);
    Video_Atari_DisplayListFlush();
    unsigned before=executions;
    GUI_DrawText_Planar(strings[0],112,139,15,0,0x132);
    GUI_DrawText_Planar(strings[4],112,139,15,0,0x132);
    assert(executions == before+1); /* occupied victim drains before mutation */
    Video_Atari_DisplayListFlush();
    before=rasterizations;
    g_viewportMessageCounter=1; g_viewportMessageText=strings[4];
    g_videoTileCursorTail=cursor; s_viewportSpriteFilterActive=true;
    finish(true);
    assert(rasterizations == before && tails == 1 && !restores && !g_videoDisplayListActive);
    const TextPlanarEntry *entry=&s_textPlanar[0];
    for (unsigned p=0;p<4;p++) {
        uint16 mask=entry->store[entry->height*2*4];
        uint16 old=p == 2 ? 0xffff : 0;
        assert(screen[139*80+16+p] == ((old & (uint16)~mask) | (entry->store[p] & mask)));
    }
    /* A warm wide message is two commands; capacity drains do not inject cursors. */
    Video_Atari_DisplayListBegin();
    GUI_DrawText_Planar(strings[5],112,139,15,0,0x132);
    Video_Atari_DisplayListFlush();
    unsigned oldCommands=commands; before=rasterizations;
    while (g_videoDisplayListNext != g_videoDisplayListLimit) *g_videoDisplayListNext++=HTOBE16(0x4e71);
    g_videoTileCursorTail=cursor;
    GUI_DrawText_Planar(strings[5],112,139,15,0,0x132);
    assert(tails == 1 && rasterizations == before);
    Video_Atari_EndViewportProtection(); Video_Atari_DisplayListEnd();
    assert(commands == oldCommands+2 && tails == 1);
    /* Stack glyph data are consumed offscreen, never referenced by the list. */
    uint8 glyph[32*32], original[32*32];
    for (unsigned i=0;i<sizeof(glyph);i++) glyph[i]=i%5 == 0 ? 0 : i%31+1;
    memcpy(original,glyph,sizeof(glyph));
    Video_Atari_DisplayListBegin();
    GUI_TextPlanar_PresentGlyph(glyph,32,32,79,150);
    memset(glyph,0,sizeof(glyph));
    assert(Video_Atari_DisplayListPending());
    GUI_TextPlanar_PresentGlyph(glyph,1,1,200,150); /* reuse drains old glyph */
    for (unsigned row=0;row<32;row++) for (unsigned col=0;col<32;col++) {
        unsigned colour=original[row*32+col], x=79+col;
        if (colour == 0) continue;
        for (unsigned p=0;p<4;p++)
            assert(!!(screen[(150+row)*80+(x/16)*4+p] & (0x8000u>>(x&15))) ==
                   !!(((colour*7)&15) & (1u<<p)));
    }
    Video_Atari_DisplayListEnd();
    /* Non-list publication and real backup overlaps retain the immediate path. */
    uint16 pixel[4]={0xffff,0,0xffff,0}, mask=0xa55a;
    overlays=true; before=commands;
    Video_Atari_DisplayListBegin();
    Video_Atari_PresentPlanarText(pixel,&mask,16,1,64,139);
    assert(!Video_Atari_DisplayListPending() && commands == before);
    for (unsigned p=0;p<4;p++)
        assert(screen[139*80+16+p] == saved[139*80+16+p]);
    Video_Atari_DisplayListEnd();
    overlays=false; before=refreshed;
    Video_Atari_PresentPlanarText(pixel,&mask,16,1,64,139);
    assert(refreshed == before+1 && !restores);
    Video_Atari_DisplayListFree();
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production).replace("/* RENDERER */", tail))

    def test_message_lifecycle(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        viewport = function(
            (ROOT / "src/gui/viewport.c").read_text(), "GUI_Widget_Viewport_Draw")
        start = viewport.rindex("\tif ((g_viewportMessageCounter & 1)")
        message = viewport[start:viewport.index(
            "\n\tif (updateDisplay && !drawToMainScreen", start)]
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
typedef int Screen;
#define SCREEN_0 0
#define SCREEN_1 1
#define SELECTIONTYPE_MENTAT 0
#define SELECTIONTYPE_DEBUG 5
#define SELECTIONTYPE_UNKNOWN6 6
#define SELECTIONTYPE_INTRO 7
#define SELECTIONTYPE_PLACE 2
#define LANGUAGE_ENGLISH 0
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define lengthof(a) (sizeof(a) / sizeof((a)[0]))
static uint8 g_dirtyMinimap[512], g_dirtyViewport[512], g_displayedViewport[512];
static uint16 g_dirtyViewportCount, g_viewportPosition, g_minimapPosition;
static uint16 g_viewportMessageCounter, g_selectionType = 4;
static uint16 g_selectionRectanglePosition, g_selectionPosition;
static uint16 g_selectionWidth = 1, g_selectionHeight = 1, g_curWidgetIndex;
static int16 g_selectionState;
static uint32 g_timerGUI;
static const char *g_viewportMessageText;
static bool g_viewport_forceRedraw, g_selectionRectangleNeedRepaint;
static unsigned terrain, candidates, fullDraws, messages, soundPlays, speechStarts;
static uint8 pixels[160][240], shifted[160][240];
static Screen activeScreen;
#ifdef TOS
static bool s_viewportMessageDrawn, direct;
static bool Video_Atari_CursorDirect(void) { return direct; }
static bool GUI_Widget_Viewport_IsPlanar(void) { return direct; }
static bool GUI_Widget_Viewport_TileCursorActive(void) { return false; }
static void Map_SetViewportDamagePosition(uint16 p) { (void)p; }
static void Video_Atari_PlacementSet(int16 x, int16 y, uint16 w, uint16 h, bool valid) {
    (void)x; (void)y; (void)w; (void)h; (void)valid;
}
static void Video_Atari_PlacementHide(void) {}
static bool Video_Atari_ShiftPlanar(int16 x, int16 y, uint16 w, uint16 h,
                                  int16 dx, int16 dy) {
    if (!direct) return false;
    memcpy(shifted, pixels, sizeof(pixels));
    memset(pixels, 0, sizeof(pixels));
    for (unsigned row = 0; row < h; row++)
        for (unsigned col = 0; col < w; col++)
            pixels[y - 40 + dy + row][x + dx + col] = shifted[y - 40 + row][x + col];
    return true;
}
#endif
static uint16 Tile_GetPackedX(uint16 p) { return p & 63; }
static uint16 Tile_GetPackedY(uint16 p) { return p >> 6; }
static bool BitArray_Test(const uint8 *bits, uint16 p) {
    assert(p < 4096); return (bits[p >> 3] >> (p & 7)) & 1;
}
static void BitArray_Set(uint8 *bits, uint16 p) {
    assert(p < 4096); bits[p >> 3] |= 1u << (p & 7);
}
static bool Map_IsTileVisible(uint16 p) { return p < 4096; }
static unsigned count(const uint8 *bits) {
    unsigned n = 0;
    for (unsigned p = 0; p < 4096; p++) n += BitArray_Test(bits, p);
    return n;
}
#ifdef TOS
#define TEST_NATIVE_VIEWPORT
#undef TOS
#endif
/* UPDATE */
#ifdef TEST_NATIVE_VIEWPORT
#define TOS
#endif
/* INVALIDATE */
static Screen GFX_Screen_SetActive(Screen screen) {
    Screen previous = activeScreen; activeScreen = screen; return previous;
}
static bool GFX_Screen_IsActive(Screen screen) { return activeScreen == screen; }
static void Explosion_Tick(void) {}
static void Animation_Tick(void) {}
static void Unit_Sort(void) {}
static uint16 Map_SetSelectionObjectPosition(uint16 p) { return p; }
static void Map_UpdateMinimapPosition(uint16 p, bool force) { (void)p; (void)force; }
static void GUI_Mouse_Hide_InWidget(uint16 w) { (void)w; }
static void GUI_Mouse_Show_InWidget(void) {}
static void GUI_Screen_CopyOverlap(int x, int y, int dx, int dy, int w, int h, Screen s) {
    (void)x; (void)y; (void)dx; (void)dy; (void)w; (void)h; (void)s;
}
static void GUI_DrawText_Wrapper(const char *text, int x, int y, int fg, int bg, int flags) {
    assert(text == g_viewportMessageText && x == 112 && y == 139);
    assert(fg == 15 && bg == 0 && flags == 0x132);
    unsigned width = strlen(text) * 4;
    assert(width <= 200);
    for (unsigned row = 99; row < 110; row++)
        memset(pixels[row] + 112 - width / 2, 15, width);
    messages++;
}
#define GUI_DrawText_Planar GUI_DrawText_Wrapper
static void GUI_Widget_Viewport_Draw(bool force, bool hasScrolled, bool planarShifted,
                                     bool drawToMainScreen) {
    bool trackCopyDamage = false;
    int16 minX[10] = {0}, maxX[10] = {0};
    (void)minX; (void)maxX; (void)drawToMainScreen;
    terrain = count(g_dirtyMinimap);
    candidates = count(g_dirtyViewport);
    if (hasScrolled && !planarShifted) force = true;
    fullDraws += force;
    for (unsigned row = 0; row < 10; row++)
        for (unsigned col = 0; col < 15; col++) {
            uint16 p = g_viewportPosition + row * 64 + col;
            if (!force && !BitArray_Test(g_dirtyMinimap, p)) continue;
            for (unsigned y = row * 16; y < row * 16 + 16; y++)
                memset(pixels[y] + col * 16, 1, 16);
        }
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    memset(g_dirtyViewport, 0, sizeof(g_dirtyViewport));
    g_dirtyViewportCount = 0;
#ifdef TOS
    bool planarViewport = false; /* This fixture models the legacy message boundary. */
#endif
    /* MESSAGE */
}
/* SCREEN */
static uint16 s_spokenWords[5], s_currentVoicePriority;
static unsigned g_enableVoices;
static struct { unsigned sounds; } g_gameConfig;
static struct { unsigned language; } g_config;
static struct { uint16 soundId, messageId, voiceId[5]; } g_feedback[2];
static uint16 g_translatedVoice[2][5];
static void Driver_Voice_Stop(void) {}
static void Driver_Sound_Play(uint16 s, uint16 volume) {
    (void)s; assert(volume == 255); soundPlays++;
}
static const char *String_Get_ByIndex(uint16 i) {
    return i == 0 ? "Long feedback message" : "Short";
}
static void Sound_StartSpeech(void) { speechStarts++; }
/* SOUND */
static void draw(void) { GUI_DrawScreen(SCREEN_0); }
static void reset(void) {
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    memset(g_dirtyViewport, 0, sizeof(g_dirtyViewport));
    memset(g_displayedViewport, 0, sizeof(g_displayedViewport));
    memset(pixels, 1, sizeof(pixels));
    g_dirtyViewportCount = 0;
    g_viewportPosition = g_minimapPosition = 20 * 64 + 20;
    g_viewportMessageCounter = 0;
    g_viewportMessageText = NULL;
    g_viewport_forceRedraw = false;
    g_timerGUI = 0;
    activeScreen = SCREEN_0;
    terrain = candidates = fullDraws = messages = soundPlays = speechStarts = 0;
    g_enableVoices = g_gameConfig.sounds = 0;
    g_feedback[1].messageId = 1;
    for (unsigned i = 0; i < lengthof(s_spokenWords); i++) s_spokenWords[i] = 0xffff;
#ifdef TOS
    s_viewportMessageDrawn = false;
#endif
}
static void show(void) {
    g_viewportMessageText = String_Get_ByIndex(0);
    g_viewportMessageCounter = 3;
    draw();
    assert(messages == 1);
}
static void check_pixels(bool visible) {
    unsigned width = visible ? strlen(g_viewportMessageText) * 4 : 0;
    for (unsigned y = 0; y < 160; y++)
        for (unsigned x = 0; x < 240; x++) {
            bool text = visible && y >= 99 && y < 110 &&
                x >= 112 - width / 2 && x < 112 + (width + 1) / 2;
            assert(pixels[y][x] == (text ? 15 : 1));
        }
}
int main(void) {
#ifdef TOS
    direct = true;
    /* No message: only genuinely exposed terrain, for short click jumps too. */
    const int moves[][2] = {{1,0}, {-1,0}, {0,1}, {0,-1}, {1,1}, {4,3}};
    for (unsigned m = 0; m < lengthof(moves); m++) {
        reset();
        int dx = moves[m][0], dy = moves[m][1];
        g_viewportPosition += dx + dy * 64;
        draw();
        assert(terrain == 150u - (15 - abs(dx)) * (10 - abs(dy)));
        assert(!fullDraws && !messages);
        check_pixels(false);
    }
    /* An odd counter that was never rendered must not invent old coverage. */
    reset();
    g_viewportMessageCounter = 3;
    Sound_Output_Feedback(1);
    assert(!g_viewport_forceRedraw && !g_dirtyViewportCount);
    /* Visible replacements and cancellations repair 14 tiles, with the halo. */
    for (unsigned cancel = 0; cancel < 2; cancel++) {
        reset(); show();
        Sound_Output_Feedback(cancel ? 0xfffe : 1);
        assert(!g_viewport_forceRedraw && g_dirtyViewportCount == 14);
        draw();
        assert(terrain == 14 && candidates == 48 && !fullDraws);
        check_pixels(false);
        reset(); show();
        g_viewportPosition += 64; /* Target changed before feedback, old pixels not yet shifted. */
        Sound_Output_Feedback(cancel ? 0xfffe : 1);
        assert(!g_viewport_forceRedraw && g_dirtyViewportCount == 14);
        assert(count(g_dirtyMinimap) == 14 && count(g_dirtyViewport) == 48);
        assert(BitArray_Test(g_dirtyMinimap, g_minimapPosition + 6 * 64));
        assert(!BitArray_Test(g_dirtyMinimap, g_viewportPosition + 6 * 64));
        draw();
        assert(!fullDraws);
        check_pixels(false);
    }
    /* Scrolled old coverage and the fixed new text position are both correct. */
    for (unsigned m = 0; m < lengthof(moves); m++) {
        reset(); show();
        g_viewportPosition += moves[m][0] + moves[m][1] * 64;
        draw();
        assert(!fullDraws && messages == 2);
        check_pixels(true);
    }
    /* Replacement can become visible in the same frame it removes the old text. */
    reset(); show();
    draw();
    assert(messages == 2 && !terrain && !candidates);
    check_pixels(true);
    Sound_Output_Feedback(1);
    g_timerGUI = 1000;
    draw();
    assert(g_viewportMessageCounter == 3 && terrain == 14 && !fullDraws);
    check_pixels(true);
    /* Blink appearance and disappearance; publication still happens on every visible pass. */
    reset();
    g_viewportMessageText = String_Get_ByIndex(0);
    g_viewportMessageCounter = 4;
    for (unsigned next = 3;; next--) {
        g_timerGUI = 2000 + (3 - next) * 61;
        draw();
        assert(g_viewportMessageCounter == next && terrain == 14 && candidates == 48);
        assert(!fullDraws);
        check_pixels((next & 1) != 0);
        if (next == 0) break;
    }
    /* A NULL message counter can keep ticking, without any message-only damage. */
    reset();
    g_viewportMessageCounter = 4;
    for (unsigned next = 3;; next--) {
        g_timerGUI = 3000 + (3 - next) * 61;
        draw();
        assert(g_viewportMessageCounter == next && !terrain && !candidates);
        check_pixels(false);
        if (next == 0) break;
    }
    /* Expiry during scrolling clears the shifted old strip, not only the new row. */
    reset(); show();
    g_viewportPosition += 64;
    g_timerGUI = 3500;
    draw();
    assert(g_viewportMessageCounter == 2 && !fullDraws);
    check_pixels(false);
    /* A pre-existing full redraw request must survive message invalidation. */
    reset(); show();
    g_viewport_forceRedraw = true;
    Sound_Output_Feedback(0xfffe);
    assert(g_viewport_forceRedraw);
    draw(); assert(fullDraws == 1); check_pixels(false);
    /* Large jumps rebuild rather than scheduling displaced message strips. */
    reset(); show();
    g_viewportPosition += 15;
    draw();
    assert(fullDraws == 1 && terrain == 150);
    check_pixels(true);
    /* A hidden phase has no scroll strip; exposed-edge repairs remain. */
    reset(); show();
    g_timerGUI = 4000; draw();
    assert(g_viewportMessageCounter == 2);
    g_viewportPosition++;
    draw();
    assert(terrain == 10 && !fullDraws);
    check_pixels(false);
    Sound_Output_Feedback(0xfffe);
    assert(!g_viewport_forceRedraw && !g_dirtyViewportCount);
    draw();
    assert(!terrain && messages == 1);
    check_pixels(false);
    direct = false;
#endif
    /* Legacy rendering keeps its prior conservative scheduling/full redraws. */
    reset();
    g_viewportPosition++;
    draw();
    assert(terrain == 24);
    reset(); show();
    Sound_Output_Feedback(1);
    assert(g_viewport_forceRedraw && !g_dirtyViewportCount);
    reset(); show();
    Sound_Output_Feedback(0xfffe);
    assert(g_viewport_forceRedraw && g_viewportMessageText == NULL);
    reset();
    g_viewportMessageCounter = 3;
    Sound_Output_Feedback(0xffff);
    assert(g_viewportMessageCounter == 3 && !soundPlays && !g_viewport_forceRedraw);
    reset();
    g_enableVoices = g_gameConfig.sounds = 1;
    Sound_Output_Feedback(0);
    assert(speechStarts == 1 && !soundPlays && !g_viewport_forceRedraw);
    return 0;
}
"""
        harness = harness.replace("/* UPDATE */", function(
            (ROOT / "src/map.c").read_text(), "Map_Update"))
        harness = harness.replace(
            "/* INVALIDATE */", function(gui, "GUI_InvalidateViewportMessage"))
        harness = harness.replace("/* SCREEN */", function(gui, "GUI_DrawScreen"))
        harness = harness.replace("/* SOUND */", function(
            (ROOT / "src/audio/sound.c").read_text(), "Sound_Output_Feedback"))
        harness = harness.replace("/* MESSAGE */", message)
        with tempfile.TemporaryDirectory(prefix="viewport-messages-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for platform in ([], ["-DTOS"]):
                # Existing scrolling shifts negative signed offsets.
                subprocess.run(
                    [*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                     "-Wno-unused-function", "-Wno-unused-variable", *flags,
                     "-fno-sanitize=shift-base",
                     *platform, str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
