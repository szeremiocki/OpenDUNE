"""Compare the production planar sidebar with the legacy widget renderer."""

import os
from pathlib import Path
import shlex
import struct
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function
from tools.test_dither_preparation import glyph_backend, surface_backend


ROOT = Path(__file__).resolve().parents[1]


class SidebarPlanarTest(unittest.TestCase):
    def test_panels_callbacks_and_fragment_publication(self):
        self.check_panels()

    def test_standard_font_and_sidebar_artwork(self):
        if not (ROOT / "DUNE.PAK").exists():
            self.skipTest("Local DUNE.PAK required for standard sidebar artwork")
        self.check_panels(real_resources=True)

    def check_panels(self, real_resources=False):
        gui = (ROOT / "src/gui/gui.c").read_text()
        widget = (ROOT / "src/gui/widget.c").read_text()
        font = (ROOT / "src/gui/font.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        blitter = (ROOT / "src/video/atari_sidebar.c").read_text()
        blit_compiler = "\n".join(
            function(blitter, name) for name in (
                "Sidebar_Long", "Sidebar_Word", "Sidebar_Launch", "Sidebar_Interleaved",
                "Video_Atari_CompileSidebarBlit",
            )
        ).replace("Video_Atari_CompileSidebarBlit", "Sidebar_TestCompileBlit")
        sidebar = (ROOT / "src/gui/sidebar.c").read_text()
        # Both paths model the approved ST visuals; the reference still draws into chunky memory.
        flat_buttons = function(sidebar, "GUI_Sidebar_FlatButtons")
        sidebar = sidebar.replace(flat_buttons, flat_buttons.replace("Video_Atari_CursorDirect()", "true"))
        for name, counter in (
            ("GUI_Sidebar_Char", "sidebarChars"),
            ("GUI_Sidebar_Fill", "sidebarFills"),
            ("GUI_Sidebar_Sprite", "sidebarSprites"),
            ("GUI_Sidebar_CaptureBegin", "sidebarCaptures"),
            ("GUI_Sidebar_RestoreStats", "statsRestores"),
            ("GUI_Sidebar_RestoreRepair", "repairRestores"),
            ("GUI_Sidebar_RestoreTitle", "titleRestores"),
        ):
            body = function(sidebar, name)
            instrumentation = counter + "++;"
            if name != "GUI_Sidebar_CaptureBegin":
                instrumentation += " assert(!s_capturing);"
            sidebar = sidebar.replace(body, body.replace("{", "{\n" + instrumentation, 1))
        sidebar = "\n".join(line for line in sidebar.splitlines() if not line.startswith("#include "))
        functions = "\n".join(
            function(source, name)
            for source, names in (
                (font, ("Font_Select", "Font_GetCharWidth", "Font_GetStringWidth")),
                (gui, ("GUI_InitColors", "GUI_TextState_Get", "GUI_TextState_Set",
                       "GUI_RenderGlyph", "GUI_DrawChar", "GUI_DrawText",
                       "GUI_DrawText_Wrapper", "GUI_DrawFilledRectangle",
                       "GUI_DrawWiredRectangle", "GUI_DrawBorder", "GUI_DrawBorderRepeating", "GUI_DrawProgressbar",
                       "GUI_UpdateProductionStringID", "GUI_Palette_CreateRemap",
                       "GUI_DrawCreditsCaption", "GUI_Palette_RemapScreen")),
                (widget, ("GUI_Widget_GetNext", "GUI_Widget_Get_ByIndex",
                          "GUI_Widget_MakeInvisible", "GUI_Widget_MakeVisible",
                          "GUI_Widget_Draw", "GUI_Widget_MakeSelected",
                          "GUI_Widget_MakeNormal")),
                (video, ("Video_Atari_BlitPlanarSprite",)),
            )
            for name in names
        )
        # Count uncached sprite composition, not native glyph publication.
        sprite_merge = "\tVideo_Atari_BlitPlanarSprite(s_dst + localY * s_stride"
        assert sprite_merge in sidebar
        sidebar = sidebar.replace(sprite_merge, "\tsidebarCompositions++;\n" + sprite_merge)
        measure = function(font, "Font_GetStringWidth")
        functions = functions.replace(measure, measure.replace("{", "{\ntextMeasurements++;", 1))
        layout = "\tif (strchr(string, '%') == NULL"
        assert layout in functions
        functions = functions.replace(layout, "\ttextLayouts++;\n" + layout, 1)
        harness = r"""
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include "types.h"
#include "gui/gui.h"
#include "gui/widget.h"
#include "gui/sidebar.h"
#include "gui/glyph.h"
#include "video/atari_planar.h"
#include "video/video.h"
#include "video/atari_sidebar.h"
static AtariDitherLookup s_palette4BitDither;
#include "gui/font.h"
#include "unit.h"
#include "structure.h"
#include "house.h"
#include "config.h"
#include "map.h"
#include "opendune.h"
#include "table/strings.h"
#include "pool/unit.h"
#include "pool/house.h"
#include "os/math.h"
#include "os/common.h"
/* The m68k helper assumes 4-byte longs. */
#define Memory_Equal16(a, b, bytes) (memcmp((a), (b), (bytes)) == 0)
#include "os/endian.h"

static bool direct;
bool g_videoViewportBlitter, g_videoDisplayListActive, g_videoBlitterTileSetup;
uint16 endian_bswap16(uint16 value) { return __builtin_bswap16(value); }
uint32 endian_bswap32(uint32 value) { return __builtin_bswap32(value); }
static bool s_textPlanarAllowed;
static void GUI_TextPlanar_PresentGlyph(const uint8 *p,uint16 w,uint16 h,uint16 x,uint16 y) {
    (void)p;(void)w;(void)h;(void)x;(void)y; abort();
}
typedef struct TestBlit {
    const uint16 *pixels, *masks;
    uint16 stride, width, height, phase;
} TestBlit;
/* BLIT COMPILER */
static unsigned preparedBlits, queuedBlits, batchBegins, queuedHealth, nonemptyFlushes, productionFaces, statsRestores, repairRestores, titleRestores, backgroundBlits;
static struct {
    TestBlit blit;
    uint16 *dst, width;
    uint8 foreground, background;
    bool health;
    void (*cpu)(const void *);
    uint16 cpuData[256];
} pendingBlits[4096];
static unsigned pendingBlitCount;
size_t Video_Atari_CompileSidebarBlit(VideoAtariSidebarBlit *code,const uint16 *pixels,
    const uint16 *masks,uint16 stride,uint16 width,uint16 height,uint16 phase) {
    TestBlit blit={pixels,masks,stride,width,height,phase};
    VideoAtariSidebarBlit compiled;
    size_t bytes=Sidebar_TestCompileBlit(&compiled,pixels,masks,stride,width,height,phase);
    _Static_assert(sizeof(blit)<=sizeof(code->words),"mock command fits");
    assert(sizeof(blit)<=bytes);
    memset(code->words,0,sizeof(code->words));
    memcpy(code->words,&blit,sizeof(blit));
    preparedBlits++;
    return bytes;
}
void Video_Atari_DisplayListFlush(void) {
    if(pendingBlitCount) nonemptyFlushes++;
    for(unsigned n=0;n<pendingBlitCount;n++) {
        if(pendingBlits[n].cpu) {
            pendingBlits[n].cpu(pendingBlits[n].cpuData);
            continue;
        }
        TestBlit *b=&pendingBlits[n].blit;
        uint16 *dst=pendingBlits[n].dst;
        if(pendingBlits[n].health) {
            for(unsigned y=0;y<7;y++) for(unsigned x=0;x<24;x++) {
                unsigned dx=x+5, bit=0x8000u>>(dx&15);
                uint8 pen=x<pendingBlits[n].width?pendingBlits[n].foreground:pendingBlits[n].background;
                for(unsigned p=0;p<4;p++) {
                    uint16 *d=dst+y*80+(dx/16)*4+p;
                    *d=(*d&~bit)|((pen&(1u<<p))?bit:0);
                }
            }
            continue;
        }
        for(unsigned y=0;y<b->height;y++) for(unsigned x=0;x<b->width;x++) {
            unsigned i=y*(b->stride/4)+(x/16)*4, bit=0x8000u>>(x&15);
            unsigned dx=x+b->phase, dbit=0x8000u>>(dx&15);
            for(unsigned p=0;p<4;p++) {
                if(b->masks && !(b->masks[i+p]&bit)) continue;
                uint16 *d=dst+y*80+(dx/16)*4+p;
                *d=(*d&~dbit)|((b->pixels[i+p]&bit)?dbit:0);
            }
        }
    }
    pendingBlitCount=0;
}
void Video_Atari_DisplayListBegin(void) {
    assert(!g_videoDisplayListActive && !pendingBlitCount);
    g_videoDisplayListActive=true; batchBegins++;
}
void Video_Atari_DisplayListEnd(void) {
    assert(g_videoDisplayListActive);
    Video_Atari_DisplayListFlush(); g_videoDisplayListActive=false;
}
void Video_Atari_QueueSidebarBlit(const uint16 *code,uint16 *dst) {
    assert(g_videoDisplayListActive && pendingBlitCount<4096);
    memcpy(&pendingBlits[pendingBlitCount].blit,code,sizeof(TestBlit));
    if(pendingBlits[pendingBlitCount].blit.width==64 && pendingBlits[pendingBlitCount].blit.height==82)
        backgroundBlits++;
    if(pendingBlits[pendingBlitCount].blit.width==64 && pendingBlits[pendingBlitCount].blit.height==37)
        productionFaces++;
    pendingBlits[pendingBlitCount].cpu=NULL;
    pendingBlits[pendingBlitCount].health=false;
    pendingBlits[pendingBlitCount++].dst=dst; queuedBlits++;
}
void Video_Atari_QueueSidebarHealth(uint16 *dst,uint16 width,uint8 foreground,uint8 background) {
    assert(g_videoDisplayListActive && pendingBlitCount<4096 && width<=24);
    pendingBlits[pendingBlitCount].health=true;
    pendingBlits[pendingBlitCount].cpu=NULL;
    pendingBlits[pendingBlitCount].dst=dst;
    pendingBlits[pendingBlitCount].width=width;
    pendingBlits[pendingBlitCount].foreground=foreground;
    pendingBlits[pendingBlitCount++].background=background;
    queuedHealth++;
}
void *Video_Atari_QueueSidebarCPU(void (*code)(const void *),size_t bytes) {
    assert(g_videoDisplayListActive && pendingBlitCount<4096);
    assert(bytes<=sizeof(pendingBlits[pendingBlitCount].cpuData));
    pendingBlits[pendingBlitCount].cpu=code;
    return pendingBlits[pendingBlitCount++].cpuData;
}
static uint16 generation;
static unsigned encodes, liveEnds, copies, hides, shows, widgetDraws[12], opacityDecodes;
static unsigned sidebarChars, sidebarFills, sidebarSprites, sidebarCompositions, sidebarCaptures;
static unsigned textMeasurements, textLayouts;
static uint16 display[320 * 200 / 4], reference[320 * 200 / 4];
static uint8 screens[2][320 * 200], mapping[256], remapping[256];
static uint8 assetData[355][5 + 32 * 24], *assets[355];
uint8 **g_sprites = assets;
uint8 *g_paletteMapping1 = remapping;
uint8 g_remap[256], g_monoWidgetRemap[256];
bool g_videoAtariMono;
uint8 Sprite_GetWidth(uint8 *sprite) { return sprite[3]; }
static uint8 fontData[256][16 * 16];
static FontChar chars[256];
static Font font6 = {8, 6, 255, chars, NULL};
Font *g_fontCurrent = &font6, *g_fontNew6p = &font6, *g_fontNew8p = &font6;
int8 g_fontCharOffset;
static uint16 *s_planarTarget;
static uint16 s_planarGroups;
static bool s_planarLineDone;
static bool GUI_DrawTextPlanarCached(const char *s, int16 l, int16 t) { (void)s; (void)l; (void)t; return false; }
static bool GUI_PlanarTarget_Line(const char *s, uint16 l, uint16 t) { (void)s; (void)l; (void)t; return false; }
static uint16 GUI_PlanarTarget_Text(const char *s, uint16 l, uint16 t) { (void)s; (void)l; (void)t; return 0xFFFF; }
static void GUI_PlanarTarget_Chunky(const FontChar *f, uint16 l, uint16 t) { (void)f; (void)l; (void)t; }
static uint8 g_colours[16];
static uint16 s_textFontFlags = -1, s_textStyleFlags = -1;
static uint16 s_colourBorderSchema[5][4] = {
    {26,29,29,29}, {20,26,16,20}, {20,16,26,20}, {233,235,232,233}, {233,232,235,233}
};
UnitInfo g_table_unitInfo[UNIT_MAX];
StructureInfo g_table_structureInfo[STRUCTURE_MAX];
#include "table/actioninfo.c"
const uint16 g_table_actionsAI[4] = {ACTION_ATTACK,ACTION_MOVE,ACTION_GUARD,ACTION_HARVEST};
const XYSize g_table_structure_layoutSize[STRUCTURE_LAYOUT_MAX] = {{2,2}};
const HouseInfo g_table_houseInfo[HOUSE_MAX] = {{.specialWeapon = 1}};
DuneCfg g_config;
Tile g_map[4096];
HouseType g_playerHouseID;
uint16 g_houseMissileCountdown;
uint16 g_activeAction, g_selectionType, g_structureActiveType, g_selectionPosition;
uint16 g_productionStringID;
bool g_debugGame, g_debugScenario, g_structureHighHealth;
Unit *g_unitSelected, *g_unitHouseMissile;
Widget *g_widgetLinkedListHead;
WidgetProperties g_widgetProperties[22];
uint16 g_curWidgetIndex, g_curWidgetXBase, g_curWidgetYBase, g_curWidgetWidth, g_curWidgetHeight;
uint8 g_curWidgetFGColourBlink, g_curWidgetFGColourNormal;
Screen g_screenActiveID;
static Widget widgets[9];
static Unit unit, linked;
static Structure structure;
static House house;
static bool structureSelected, upgradable;
static bool wideCaption;
static unsigned upgradedChecks;
bool Video_Atari_CursorDirect(void) { return direct; }
uint16 Video_Atari_GetPaletteGeneration(void) { return generation; }
uint8 Video_Atari_GetPalettePen(uint8 colour) { return mapping[colour]; }
void *GFX_Screen_Get_ByIndex(Screen screen) {
    return screens[screen == SCREEN_ACTIVE ? g_screenActiveID : screen];
}
bool GFX_Screen_IsActive(Screen screen) { return screen == g_screenActiveID; }
Screen GFX_Screen_SetActive(Screen screen) {
    Screen old = g_screenActiveID; g_screenActiveID = screen; return old;
}
void GFX_Screen_SetDirty_(uint16 l, uint16 t, uint16 r, uint16 b) {
    (void)l; (void)t; (void)r; (void)b;
    assert(!GUI_Sidebar_Active());
}
void GFX_PutPixel(uint16 x, uint16 y, uint8 colour) {
    assert(!GUI_Sidebar_Active());
    screens[g_screenActiveID][y * 320 + x] = colour;
}
void Error(const char *format, ...) {
    va_list ap; va_start(ap,format); vfprintf(stderr,format,ap); va_end(ap);
}
void Warning(const char *format, ...) { (void)format; abort(); }
void GUI_Mouse_Hide_InRegion(uint16 l, uint16 t, uint16 r, uint16 b) {
    (void)l; (void)t; (void)r; (void)b; hides++;
}
void GUI_Mouse_Show_InRegion(void) { shows++; }
void GUI_Mouse_Hide_InWidget(uint16 index) { assert(index == 6); hides++; }
void GUI_Mouse_Show_InWidget(void) { shows++; }
uint16 Widget_SetCurrentWidget(uint16 index) {
    uint16 old = g_curWidgetIndex;
    g_curWidgetIndex = index;
    g_curWidgetXBase = g_widgetProperties[index].xBase;
    g_curWidgetYBase = g_widgetProperties[index].yBase;
    g_curWidgetWidth = g_widgetProperties[index].width;
    g_curWidgetHeight = g_widgetProperties[index].height;
    g_curWidgetFGColourBlink = g_widgetProperties[index].fgColourBlink;
    return old;
}
House *House_Get_ByIndex(uint8 index) { assert(index < HOUSE_MAX); return &house; }
#undef Unit_Get_ByIndex
Unit *Unit_Get_ByIndex(uint16 index) { assert(index == 1); return &linked; }
uint8 Unit_GetHouseID(Unit *u) { return u->deviated ? 1 : u->o.houseID; }
Structure *Structure_Get_ByPackedTile(uint16 packed) {
    assert(packed == g_selectionPosition); return structureSelected ? &structure : NULL;
}
uint16 Map_GetLandscapeType(uint16 packed) { (void)packed; return structureSelected ? LST_STRUCTURE : LST_NORMAL_SAND; }
bool Structure_IsUpgradable(Structure *s) { assert(s == &structure); upgradedChecks++; return upgradable; }
Unit *Structure_GetLinkedUnit(Structure *s) { return s->o.linkedID == 0xff ? NULL : &linked; }
uint8 GUI_Widget_GetShortcut(uint8 c) { return c; }
char *String_Get_ByIndex(uint16 id) {
    switch (id) {
        case STR_CANCEL: return "Cancel";
        case STR_TARGET: return "Target";
        case STR_MOVEMENT: return "Movement";
        case STR_HARVEST: return "Harvest";
        case STR_ATTACK: return "Attack";
        case STR_MOVE: return wideCaption ? "Extra long caption" : "Move";
        case STR_GUARD: return "Guard";
        case STR_RETREAT: return "Retreat";
        case STR_AREA_GUARD: return "Area Guard";
        case STR_RETURN: return "Return";
        case STR_STOP2: return "Stop";
        case STR_AMBUSH: return "Ambush";
        case STR_SABOTAGE: return "Sabotage";
        case STR_DIE: return "Die";
        case STR_HUNT: return "Hunt";
        case STR_DEPLOY: return "Deploy";
        case STR_DESTRUCT: return "Destruct";
        case STR_REPAIR: return "Repair";
        case STR_REPAIRING: return "Repairing";
        case STR_UPGRADE: return "Upgrade";
        case STR_UPGRADING: return "Upgrading";
        case STR_PLACE_IT: return "Place It";
        case STR_COMPLETED: return "Completed";
        case STR_ON_HOLD: return "On Hold";
        case STR_BUILD_IT: return "Build It";
        case STR_LAUNCH: return "Launch";
        case STR_FREMEN: return "Fremen";
        case STR_SABOTEUR: return "Saboteur";
        case STR_SELECTTARGET: return "Select\rTarget";
        case STR_SELECTDESTINATION: return "Select\rDestination";
        case STR_SELECTPLACE_TOHARVEST: return "Select\rHarvest";
        case STR_D_DONE: return "%d done";
        case STR_UPGRADINGD_DONE: return "Upgrade %d";
        case STR_POWER_INFONEEDEDOUTPUT: return "Power\rNeed\rOut";
        case STR_SPICEHOLDS_4DMAX_4D: return "Spice\r%4d\r%4d";
        case STR_RADAR_SCANFRIEND_2DENEMY_2D: return "Radar\rF %2d\rE %2d";
        case STR_FRIGATEARRIVAL_INTMINUS_D: return "Arrival\rT %d";
        case STR_PICK_TARGETTMINUS_D: return "Target\rT %d";
        default: return "DMG";
    }
}
static void put_pen(uint16 *pixels, unsigned x, unsigned y, uint8 pen) {
    uint16 bit = 0x8000u >> (x & 15);
    for (unsigned p = 0; p < 4; p++) {
        uint16 *word = pixels + y * 80 + (x >> 4) * 4 + p;
        *word = (*word & ~bit) | ((pen & (1u << p)) ? bit : 0);
    }
}
static void copy_rect(int xs, int ys, int xd, int yd, unsigned width, unsigned height, Screen src) {
    copies++;
    for (unsigned y = 0; y < height; y++) for (unsigned x = 0; x < width; x++)
        put_pen(display, xd + x, yd + y, mapping[screens[src][(ys+y)*320+xs+x]]);
}
void GUI_Screen_Copy(int16 xs, int16 ys, int16 xd, int16 yd, int16 w, int16 h, Screen src, Screen dst) {
    assert(dst == SCREEN_0);
    if (src == SCREEN_ACTIVE) src = g_screenActiveID;
    copy_rect(xs*8, ys, xd*8, yd, w*8, h, src);
}
void GFX_Screen_Copy2(int16 xs, int16 ys, int16 xd, int16 yd, int16 w, int16 h,
                       Screen src, Screen dst, bool skip) {
    assert(dst == SCREEN_0 && !skip); copy_rect(xs,ys,xd,yd,w,h,src);
}
void GUI_DrawLine(int16 x1, int16 y1, int16 x2, int16 y2, uint8 colour) {
    assert(x1 == x2 || y1 == y2);
    if (GUI_Sidebar_Active()) {
        GUI_Sidebar_Fill(min(x1,x2),min(y1,y2),max(x1,x2),max(y1,y2),colour);
        return;
    }
    if (y1 == y2) for (int x = min(x1,x2); x <= max(x1,x2); x++) GFX_PutPixel(x,y1,colour);
    else for (int y = min(y1,y2); y < max(y1,y2); y++) GFX_PutPixel(x1,y,colour);
}
void GUI_DrawSpriteToBuffer(uint8 *dst, uint16 width, uint16 height,
                            const uint8 *sprite, int16 x, int16 y) {
    for (unsigned row=0; row<sprite[2]; row++) for(unsigned col=0; col<sprite[3]; col++) {
        uint8 colour = sprite[5+row*sprite[3]+col];
        if ((sprite[0]&1) && colour==255) colour=0;
        if (sprite[5+row*sprite[3]+col] && row+y<height && col+x<width)
            dst[(row+y)*width+col+x] = colour;
    }
}
void GUI_DrawSpriteOpacity(uint8 *dst,uint16 width,uint16 height,const uint8 *sprite,int16 x,int16 y) {
    opacityDecodes++;
    for(unsigned row=0;row<sprite[2];row++) for(unsigned col=0;col<sprite[3];col++)
        if(sprite[5+row*sprite[3]+col] && row+y<height && col+x<width) dst[(row+y)*width+col+x]=1;
}
void GUI_DrawSprite(Screen screen, const uint8 *sprite, uint16 id, uint8 houseID,
                    int16 x, int16 y, uint16 window, int flags, ...) {
    (void)houseID; assert(window == 0);
    const uint8 *remap = NULL; unsigned count = 0;
    va_list ap; va_start(ap,flags);
    if (flags & DRAWSPRITE_FLAG_REMAP) { remap=va_arg(ap,uint8*); count=va_arg(ap,int); }
    va_end(ap);
    if (GUI_Sidebar_Active()) { GUI_Sidebar_Sprite(sprite,id,x,y,flags,remap,count); return; }
    uint8 *dst = GFX_Screen_Get_ByIndex(screen);
    for (unsigned row=0; row<sprite[2]; row++) for (unsigned col=0; col<sprite[3]; col++) {
        uint8 colour=sprite[5+row*sprite[3]+col];
        if (!colour) continue;
        if ((sprite[0]&1) && colour==255) colour=0;
        for (unsigned n=0;n<count;n++) colour=remap[colour];
        if(row+y<200 && col+x<320) dst[(row+y)*320+col+x]=colour;
    }
}
bool Video_Atari_PresentFill(int16 x,int16 y,uint16 w,uint16 h,uint8 colour) {
    (void)x;(void)y;(void)w;(void)h;(void)colour; abort();
}
bool Video_Atari_PresentChunkyTransparent(const void *src,uint16 stride,int16 x,int16 y,uint16 w,uint16 h) {
    (void)src;(void)stride;(void)x;(void)y;(void)w;(void)h; abort();
}
void Video_Atari_EncodePlanar(const uint8 *src,uint16 *dst,uint16 w,uint16 h) {
    encodes++;
    memset(dst,0,w*h/2);
    for(unsigned y=0;y<h;y++) for(unsigned x=0;x<w;x++)
        for(unsigned p=0;p<4;p++) if(mapping[src[y*w+x]]&(1<<p))
            dst[y*(w/4)+(x/16)*4+p]|=0x8000u>>(x&15);
}
void Video_Atari_EncodePlanarStrided(const uint8 *src,uint16 stride,uint16 *dst,uint16 w,uint16 h) {
    assert(stride==320 && g_screenActiveID==SCREEN_1);
    encodes++;
    memset(dst,0,w*h/2);
    for(unsigned y=0;y<h;y++) for(unsigned x=0;x<w;x++)
        for(unsigned p=0;p<4;p++) if(mapping[src[y*stride+x]]&(1<<p))
            dst[y*(w/4)+(x/16)*4+p]|=0x8000u>>(x&15);
}
uint16 *Video_Atari_LiveBegin(uint16 x,uint16 y,uint16 w,uint16 h) {
    assert(x >= 256 && x+w <= 320 && y >= 42 && y+h <= 124 && (x & 15) == 0);
    return display+y*80+(x/16)*4;
}
void Video_Atari_LiveEnd(uint16 x,uint16 y,uint16 w,uint16 h) {
    (void)x;(void)y;(void)w;(void)h; liveEnds++;
}
static void Video_Atari_PlanarMergePlain(uint16 *dst, uint16 mask, const uint16 src[4]) {
    for(unsigned p=0;p<4;p++) dst[p]=(dst[p]&~mask)|(src[p]&mask);
}
void GFX_DrawTile(uint16 id,uint16 x,uint16 y,uint8 houseID) { (void)id;(void)x;(void)y;(void)houseID; abort(); }
void GUI_DrawXorFilledRectangle(int16 l,int16 t,int16 r,int16 b,uint8 c) { (void)l;(void)t;(void)r;(void)b;(void)c; abort(); }
void GUI_DrawBlockedRectangle(int16 l,int16 t,int16 w,int16 h,uint8 c) { (void)l;(void)t;(void)w;(void)h;(void)c; abort(); }
static void GUI_Widget_DrawBlocked(Widget *w,uint8 c) { (void)w;(void)c; abort(); }
/* PRODUCTION */
/* GLYPH */
/* PLANAR */
/* SIDEBAR */
#include "gui/widget_draw.c"

static void setup_widgets(void) {
    static const unsigned positions[9][4] = {
        {256,42,64,6},{258,76,60,10},{258,87,60,35},{258,51,32,24},
        {258,110,58,11},{258,77,60,10},{258,88,60,10},{258,99,60,10},{258,110,60,10}
    };
    for(unsigned i=0;i<9;i++) {
        Widget *w=&widgets[i]; memset(w,0,sizeof(*w));
        w->index=i+3; w->next=i==8?NULL:w+1;
        w->flags.invisible=true;
        w->offsetX=positions[i][0]; w->offsetY=positions[i][1];
        w->width=positions[i][2]; w->height=positions[i][3];
        w->drawModeNormal=w->drawModeSelected=w->drawModeDown=DRAW_MODE_CUSTOM_PROC;
        w->drawParameterNormal.proc=i==3?GUI_Widget_SpriteButton_Draw:i==2?GUI_Widget_SpriteTextButton_Draw:GUI_Widget_TextButton2_Draw;
        w->drawParameterSelected=w->drawParameterDown=w->drawParameterNormal;
        if(i==0) w->drawModeNormal=w->drawModeSelected=w->drawModeDown=DRAW_MODE_NONE;
        if(i==4) w->stringID=STR_CANCEL;
    }
    g_widgetLinkedListHead=widgets;
}
static void check_panel(void) {
    direct=false; setup_widgets(); g_screenActiveID=SCREEN_0; Widget_SetCurrentWidget(0);
    memset(display,0x7b,sizeof(display)); memset(screens,0xa5,sizeof(screens));
    GUI_Widget_ActionPanel_Draw(true);
    memcpy(reference,display,sizeof(display));
    direct=true; setup_widgets(); g_screenActiveID=SCREEN_0; Widget_SetCurrentWidget(0);
    memset(display,0x7b,sizeof(display)); memset(screens,0xa5,sizeof(screens));
    memset(widgetDraws,0,sizeof(widgetDraws));
    unsigned beforeCopies=copies;
    GUI_Sidebar_Invalidate();
    GUI_Widget_ActionPanel_Draw(true);
    assert(g_screenActiveID==SCREEN_0 && g_curWidgetIndex==0 && hides==shows);
    assert(!memcmp(display,reference,sizeof(display)) && copies==beforeCopies);
    for(unsigned i=0;i<9;i++)
        if(!widgets[i].flags.invisible) assert(widgetDraws[widgets[i].index]==1);
    for(unsigned i=0;i<sizeof(screens);i++) assert(((uint8*)screens)[i]==0xa5);
    unsigned p=liveEnds, e=encodes;
    GUI_Widget_ActionPanel_Draw(false);
    assert(liveEnds==p && encodes==e);
    unsigned prepared=preparedBlits, compositions=sidebarCompositions;
    GUI_Widget_ActionPanel_Draw(true);
    assert(liveEnds>p && encodes==e && !memcmp(display,reference,sizeof(display)));
    if(g_videoViewportBlitter) {
        if(preparedBlits!=prepared)
            fprintf(stderr,"warm panel type=%u structure=%u prepared %u new blits\n",
                    g_selectionType,structure.o.type,preparedBlits-prepared);
        assert(preparedBlits==prepared && sidebarCompositions==compositions);
        assert(queuedBlits && batchBegins && !pendingBlitCount && !g_videoDisplayListActive);
    }
    if(g_selectionType==SELECTIONTYPE_TARGET && !g_unitHouseMissile)
        assert(!widgets[4].flags.invisible && widgets[4].shortcut);
}
static void check_hover(unsigned i,unsigned down) {
    direct=false; setup_widgets(); g_screenActiveID=SCREEN_0; GUI_Widget_ActionPanel_Draw(true);
    assert(!widgets[i].flags.invisible);
    widgets[i].state.hover2=down; GUI_Widget_Draw(&widgets[i]);
    uint16 shortcut=widgets[i].shortcut;
    uint8 coloursAfter[16]; memcpy(coloursAfter,g_colours,sizeof(coloursAfter));
    GUITextState textAfter, textActual;
    GUI_TextState_Get(&textAfter);
    memcpy(reference,display,sizeof(display));
    direct=true; setup_widgets(); g_screenActiveID=SCREEN_0;
    GUI_Sidebar_Invalidate(); GUI_Widget_ActionPanel_Draw(true);
    static uint16 normal[sizeof(display)/sizeof(*display)];
    if(down && widgets[i].state.selected) {
        widgets[i].state.selected=false;
        GUI_Widget_Draw(&widgets[i]);
        widgets[i].state.selected=true;
    }
    memcpy(normal,display,sizeof(display));
    uint16 *bank=s_assetBank;
    widgets[i].state.hover2=down; unsigned c=copies, blits=queuedBlits;
    unsigned measurements=textMeasurements, layouts=textLayouts;
    GUI_Widget_Draw(&widgets[i]);
    if(g_videoViewportBlitter && widgets[i].index!=5 && widgets[i].index!=6) {
        assert(queuedBlits==blits+1);
        assert(textMeasurements==measurements && textLayouts==layouts);
    }
    if(memcmp(reference,display,sizeof(display))) {
        for(unsigned word=0;word<sizeof(display)/sizeof(*display);word++)
            if(reference[word]!=display[word]) {
                fprintf(stderr,"hover widget=%u down=%u structure=%u unit=%u selection=%u wide=%u differs at group=%u y=%u (%04x/%04x)\n",
                        i+3,down,structure.o.type,unit.o.type,g_selectionType,wideCaption,
                        (word%80)/4,word/80,reference[word],display[word]);
                break;
            }
    }
    assert(copies==c && !memcmp(reference,display,sizeof(display)) && widgets[i].shortcut==shortcut);
    if(down) {
        Widget *w=&widgets[i];
        for(unsigned y=w->offsetY+1;y<w->offsetY+w->height-1;y++)
        for(unsigned x=w->offsetX+1;x<w->offsetX+w->width-1;x++)
        for(unsigned plane=0;plane<4;plane++) {
            unsigned offset=y*80+(x/16)*4+plane, bit=0x8000u>>(x&15);
            assert((normal[offset]&bit)==(display[offset]&bit));
        }
        assert(!memcmp(display+w->offsetY*80,normal+w->offsetY*80,64*sizeof(uint16)));
        assert(memcmp(normal,display,sizeof(display)));
    }
    assert(s_assetBank==bank);
    if(down && widgets[i].index>=8) {
        bool selected=widgets[i].state.selected;
        widgets[i].state.selected=!selected;
        GUI_Widget_Draw(&widgets[i]);
        assert(!memcmp(reference,display,sizeof(display)));
        widgets[i].state.selected=selected;
    }
    widgets[i].shortcut=0;
    GUI_Widget_Draw(&widgets[i]);
    assert(!memcmp(reference,display,sizeof(display)) && widgets[i].shortcut==shortcut);
    GUI_TextState_Get(&textActual);
    assert(textActual.font==textAfter.font && textActual.spacing==textAfter.spacing);
    assert(textActual.fontFlags==textAfter.fontFlags && textActual.styleFlags==textAfter.styleFlags);
    assert(!memcmp(g_colours,coloursAfter,sizeof(coloursAfter)));
}
static void check_unit_selection(unsigned mask) {
    static uint16 previous[sizeof(display)/sizeof(*display)];
    Widget prior[9], expected[9];
    memcpy(previous,display,sizeof(previous));
    memcpy(prior,widgets,sizeof(prior));
    direct=false;
    GUI_Widget_ActionPanel_Draw(true);
    memcpy(reference,display,sizeof(reference));
    memcpy(expected,widgets,sizeof(expected));
    memcpy(display,previous,sizeof(display));
    memcpy(widgets,prior,sizeof(widgets));
    direct=true;
    unsigned backgrounds=backgroundBlits, sprites=sidebarSprites, titles=titleRestores;
    unsigned health=queuedHealth, blits=queuedBlits, ends=liveEnds;
    memset(widgetDraws,0,sizeof(widgetDraws));
    GUI_Widget_ActionPanel_Draw(true);
    assert(s_planarRedraw==mask && liveEnds==ends+1);
    if(memcmp(reference,display,sizeof(display)))
        for(unsigned word=0;word<lengthof(display);word++)
            if(reference[word]!=display[word]) {
                fprintf(stderr,"selection mask=%u type=%u owner=%u differs at group=%u y=%u (%04x/%04x)\n",
                        mask,unit.o.type,unit.o.houseID,(word%80)/4,word/80,reference[word],display[word]);
                break;
            }
    assert(!memcmp(reference,display,sizeof(display)));
    for(unsigned i=0;i<9;i++) {
        assert(widgets[i].flags.invisible==expected[i].flags.invisible);
        if(!expected[i].flags.invisible) {
            assert(widgets[i].stringID==expected[i].stringID);
            assert(widgets[i].shortcut==expected[i].shortcut && widgets[i].shortcut2==expected[i].shortcut2);
            assert(widgets[i].state.selected==expected[i].state.selected);
            assert(widgets[i].state.hover2==expected[i].state.hover2);
        }
    }
    if(mask==SIDEBAR_REDRAW_ALL) {
        if(g_videoViewportBlitter) assert(backgroundBlits==backgrounds+1);
    } else {
        assert(backgroundBlits==backgrounds);
        assert(sidebarSprites==sprites+!!(mask&SIDEBAR_REDRAW_PORTRAIT));
        assert(titleRestores==titles+!!(mask&SIDEBAR_REDRAW_NAME));
        if(g_videoViewportBlitter) {
            assert(queuedHealth==health+!!(mask&SIDEBAR_REDRAW_HEALTH));
            if(mask==0) assert(queuedBlits==blits);
        }
        if(!(mask&SIDEBAR_REDRAW_COMMANDS))
            for(unsigned i=8;i<12;i++) assert(!widgetDraws[i]);
    }
}
static void check_production_update(bool imageChanged) {
    static uint16 previous[sizeof(display)/sizeof(*display)];
    memcpy(previous,display,sizeof(previous));
    direct=false;
    GUI_Widget_ActionPanel_Draw(true);
    memcpy(reference,display,sizeof(reference));
    memcpy(display,previous,sizeof(display));
    direct=true;
    unsigned faces=productionFaces, sprites=sidebarSprites, health=queuedHealth, p=liveEnds;
    memset(widgetDraws,0,sizeof(widgetDraws));
    GUI_Widget_ActionPanel_Draw(false);
    assert(!memcmp(reference,display,sizeof(display)) && liveEnds==p+1);
    assert(widgetDraws[5]==1);
    for(unsigned i=3;i<12;i++) if(i!=5) assert(!widgetDraws[i]);
    assert(queuedHealth==health);
    if(g_videoViewportBlitter) {
        assert(productionFaces==faces+imageChanged);
        if(!imageChanged) assert(sidebarSprites==sprites);
    }
}
static void check_health_update(bool healthOnly,bool force) {
    static uint16 previous[sizeof(display)/sizeof(*display)];
    Widget prior[9];
    GUITextState text;
    GUI_TextState_Get(&text);
    memcpy(previous,display,sizeof(previous));
    memcpy(prior,widgets,sizeof(prior));
    direct=false;
    GUI_Widget_ActionPanel_Draw(true);
    memcpy(reference,display,sizeof(reference));
    memcpy(display,previous,sizeof(display));
    memcpy(widgets,prior,sizeof(widgets));
    direct=true;
    GUI_TextState_Set(&text);
    unsigned sprites=sidebarSprites, health=queuedHealth, blits=queuedBlits, p=liveEnds;
    unsigned conversions=encodes, prepared=preparedBlits, c=copies;
    unsigned restores=statsRestores;
    memset(widgetDraws,0,sizeof(widgetDraws));
    GUI_Widget_ActionPanel_Draw(force);
    if(memcmp(reference,display,sizeof(display)))
        for(unsigned word=0;word<lengthof(display);word++)
            if(reference[word]!=display[word]) {
                fprintf(stderr,"health hp=%u force=%u mask=%u differs at group=%u y=%u (%04x/%04x)\n",
                        unit.o.hitpoints,force,s_planarRedraw,(word%80)/4,word/80,reference[word],display[word]);
                break;
            }
    assert(!memcmp(reference,display,sizeof(display)) && liveEnds==p+1 && copies==c);
    if(healthOnly) {
        assert(sidebarSprites==sprites && encodes==conversions && preparedBlits==prepared);
        for(unsigned i=3;i<12;i++) assert(!widgetDraws[i]);
        if(g_videoViewportBlitter) assert(queuedHealth==health+1 && queuedBlits==blits);
        for(unsigned y=0;y<200;y++) for(unsigned group=0;group<20;group++) {
            uint16 changed=0;
            if(y>=52 && y<59) changed=group==18?0x07ff:group==19?0xfff8:0;
            for(unsigned plane=0;plane<4;plane++) {
                unsigned offset=y*80+group*4+plane;
                assert(!((previous[offset]^display[offset])&(uint16)~changed));
            }
        }
    } else if(g_videoViewportBlitter) {
        assert(queuedBlits>blits && statsRestores==restores);
    }
}
static void check_component_update(bool healthChanged, bool statsChanged, bool repairChanged, bool productionChanged) {
    static uint16 previous[sizeof(display)/sizeof(*display)];
    Widget previousWidgets[9], expectedRepair;
    GUITextState text;
    GUI_TextState_Get(&text);
    memcpy(previous,display,sizeof(previous));
    memcpy(previousWidgets,widgets,sizeof(widgets));
    direct=false;
    GUI_Widget_ActionPanel_Draw(true);
    memcpy(reference,display,sizeof(reference));
    expectedRepair=widgets[1];
    memcpy(display,previous,sizeof(display));
    memcpy(widgets,previousWidgets,sizeof(widgets));
    direct=true;
    GUI_TextState_Set(&text);
    unsigned sprites=sidebarSprites, health=queuedHealth, blits=queuedBlits, p=liveEnds;
    unsigned conversions=encodes, prepared=preparedBlits, restores=statsRestores, batches=batchBegins;
    unsigned repairClears=repairRestores;
    memset(widgetDraws,0,sizeof(widgetDraws));
    GUI_Widget_ActionPanel_Draw(false);
    assert(!memcmp(reference,display,sizeof(display)) && liveEnds==p+1);
    assert(statsRestores==restores+statsChanged);
    assert(repairRestores==repairClears+(repairChanged && expectedRepair.flags.invisible));
    if(!productionChanged) assert(sidebarSprites==sprites);
    assert(encodes==conversions && preparedBlits==prepared);
    assert(g_screenActiveID==SCREEN_0 && g_curWidgetIndex==0);
    for(unsigned i=3;i<12;i++)
        assert(widgetDraws[i]==(i==4 && repairChanged ? 1 :
                               i==5 && productionChanged ? 1 : 0));
    assert(widgets[1].flags.invisible==expectedRepair.flags.invisible);
    assert(widgets[1].state.selected==expectedRepair.state.selected);
    assert(widgets[1].stringID==expectedRepair.stringID && widgets[1].shortcut==expectedRepair.shortcut);
    if(g_videoViewportBlitter) {
        assert(batchBegins==batches+1 && !pendingBlitCount && !g_videoDisplayListActive);
        assert(queuedHealth==health+healthChanged && queuedBlits>blits);
        if(!productionChanged) assert(queuedBlits<=blits+3*statsChanged+2*repairChanged);
    }
    for(unsigned y=0;y<200;y++) for(unsigned group=0;group<20;group++) {
        uint16 changed=statsChanged && y>=88 && y<124 && group>=16 ? 0xffff : 0;
        if(repairChanged && y>=75 && y<=86 && group>=16) changed=0xffff;
        if(productionChanged && y>=86 && y<123 && group>=16) changed=0xffff;
        if(healthChanged && y>=52 && y<59)
            changed=group==18?0x07ff:group==19?0xfff8:0;
        for(unsigned plane=0;plane<4;plane++) {
            unsigned offset=y*80+group*4+plane;
            assert(!((previous[offset]^display[offset])&(uint16)~changed));
        }
    }
    p=liveEnds;
    GUI_Widget_ActionPanel_Draw(false);
    assert(liveEnds==p);
}
static void check_stats_update(bool healthChanged) {
    check_component_update(healthChanged,true,false,false);
}
static void check_sidebar_sprite(uint16 id, uint16 x, bool opaque, bool shared) {
    direct=false; g_screenActiveID=SCREEN_1;
    GUI_DrawFilledRectangle(256,42,319,123,20);
    GUI_DrawSprite(SCREEN_ACTIVE,g_sprites[id],id,GUI_SPRITE_COLOUR_EMBEDDED,x,51,0,0);
    copy_rect(256,42,256,42,64,82,SCREEN_1);
    memcpy(reference,display,sizeof(reference));
    direct=true; GUI_Sidebar_Begin(false);
    GUI_Sidebar_Fill(256,42,319,123,20);
    unsigned opacity=opacityDecodes;
    bool cold=s_sprites[id-SIDEBAR_SPRITE_FIRST]==NULL;
    GUI_DrawSprite(SCREEN_ACTIVE,g_sprites[id],id,GUI_SPRITE_COLOUR_EMBEDDED,x,51,0,0);
    GUI_Sidebar_End();
    assert(opacityDecodes==opacity+(cold && !opaque));
    assert(!memcmp(reference,display,sizeof(display)));
    SidebarSprite *entry=s_sprites[id-SIDEBAR_SPRITE_FIRST];
    assert((entry->masks==s_opaqueSpriteMasks)==shared);
    if(g_videoViewportBlitter && shared) {
        TestBlit blit;
        memcpy(&blit,entry->blits[(x-256)&15]->words,sizeof(blit));
        assert(blit.masks==NULL);
    }
    unsigned conversions=encodes, prepared=preparedBlits;
    GUI_Sidebar_Begin(false);
    GUI_DrawSprite(SCREEN_ACTIVE,g_sprites[id],id,GUI_SPRITE_COLOUR_EMBEDDED,x,51,0,
                   DRAWSPRITE_FLAG_REMAP,g_paletteMapping1,0);
    GUI_Sidebar_End();
    assert(opacityDecodes==opacity+(cold && !opaque));
    assert(entry==s_sprites[id-SIDEBAR_SPRITE_FIRST] && encodes==conversions && preparedBlits==prepared);
    assert(!memcmp(reference,display,sizeof(display)));
}
int main(int argc, char **argv) {
#ifdef TEST_SIDEBAR_BLITTER
    g_videoViewportBlitter=true;
#endif
    for(unsigned c=0;c<256;c++) {
        mapping[c]=(c*7+3)&15; remapping[c]=c?c-1:0;
        chars[c]=(FontChar){6,1,6,fontData[c]};
        for(unsigned p=0;p<36;p++) fontData[c][p]=(c+p*3)%5;
    }
    for(unsigned id=0;id<355;id++) {
        assets[id]=assetData[id]; assets[id][2]=24;
        assets[id][0]=1;
        assets[id][3]=32;
        if(id>=24 && id<=26) assets[id][2]=assets[id][3]=id==24?5:8;
        if(id==27) { assets[id][2]=5; assets[id][3]=28; }
        if(id==63) { assets[id][2]=14; assets[id][3]=20; }
        bool opaque=(id>=24 && id<=26) || (id>=28 && id<=30) || (id>=65 && id<=105);
        for(unsigned p=0;p<assets[id][2]*assets[id][3];p++)
            assets[id][p+5]=opaque || (id+p)%5?(id+p)%255+1:0;
    }
    /* REAL RESOURCES */
    if(argc>1) {
        uint16 id=(uint16)atoi(argv[1]), count=argc>2?(uint16)atoi(argv[2]):0;
        GUI_Sidebar_Sprite(g_sprites[65],id,258,51,DRAWSPRITE_FLAG_REMAP,g_paletteMapping1,count);
        abort();
    }
    g_widgetProperties[0]=(WidgetProperties){0,0,40,200,15,12,0};
    {
        uint8 normal[] = {0,0,1,4,0,0,0x90,0x96,0x97};
        uint8 down[] = {0,0,1,4,0,0,0x91,0x95,0x98};
        Widget button = {.width=4, .height=1,
            .drawModeNormal=DRAW_MODE_SPRITE_HOUSE_INK, .drawModeDown=DRAW_MODE_SPRITE_HOUSE_INK,
            .drawParameterNormal.sprite=normal, .drawParameterDown.sprite=down};
        uint8 *savedCaption = g_sprites[11];
        g_sprites[11] = normal;
        GFX_Screen_SetActive(SCREEN_1);
        for (unsigned mono=0; mono<2; mono++) {
            g_videoAtariMono=mono;
            GUI_Palette_CreateRemap(HOUSE_ORDOS);
            screens[1][191]=0x90; /* Chrome outside the caption. */
            memset(screens[1]+192, 77, 4);
            GUI_DrawCreditsCaption();
            GUI_Palette_RemapScreen(191,0,5,1,SCREEN_1,g_remap);
            assert(screens[1][191]==g_remap[0x90] && screens[1][192]==77);
            assert(screens[1][193]==(mono?12:g_remap[0x90]));
            assert(screens[1][194]==(mono?12:g_remap[0x96]) && screens[1][195]==0x97);
            for (unsigned pressed=0; pressed<2; pressed++) {
                button.state.hover2=pressed;
                memset(screens[1], 77, 4);
                GUI_Widget_Draw(&button);
                assert(screens[1][0]==77);
                assert(screens[1][1]==(mono?12:g_remap[0x90+pressed]));
                assert(screens[1][2]==(mono?12:g_remap[0x96-pressed]));
                assert(screens[1][3]==0x97+pressed);
            }
        }
        button.state.hover2=false;
        button.drawModeNormal=DRAW_MODE_SPRITE;
        GUI_Widget_Draw(&button);
        assert(screens[1][1]==g_remap[0x90]);
        g_sprites[11] = savedCaption;
        g_videoAtariMono=false;
        memset(screens[1], 0, 4);
        memset(screens[1]+191, 0, 5);
        GFX_Screen_SetActive(SCREEN_0);
    }
    g_widgetProperties[6]=(WidgetProperties){32,42,8,82,15,12,0};
    house.creditsStorage=1000; house.credits=425; house.windtrapCount=2;
    house.powerUsage=150; house.starportLinkedID=1; house.starportTimeLeft=12;
    house.unitCountAllied=9; house.unitCountEnemy=12;
    linked.o.type=UNIT_TANK;
    for(unsigned i=0;i<UNIT_MAX;i++) {
        g_table_unitInfo[i].o.hitpoints=100;
        g_table_unitInfo[i].o.buildTime=100;
        g_table_unitInfo[i].o.spriteID=65+i;
        g_table_unitInfo[i].o.stringID_abbrev=STR_MOVE;
        for(unsigned a=0;a<4;a++) g_table_unitInfo[i].o.actionsPlayer[a]=g_table_actionsAI[a];
    }
    for(unsigned i=0;i<STRUCTURE_MAX;i++) {
        g_table_structureInfo[i].o.hitpoints=100;
        g_table_structureInfo[i].o.buildTime=100;
        g_table_structureInfo[i].o.spriteID=65+i;
        g_table_structureInfo[i].o.stringID_abbrev=STR_MOVE;
        g_table_structureInfo[i].creditsStorage=1000;
        g_table_structureInfo[i].powerUsage=-100;
    }
    g_map[0].isUnveiled=true;
    unit.o.type=UNIT_TANK; unit.o.hitpoints=75; unit.actionID=ACTION_MOVE;
    unit.nextActionID=ACTION_INVALID; g_unitSelected=&unit;
    GUI_Glyph_FontBuild(&font6);
    direct=true; setup_widgets(); g_screenActiveID=SCREEN_0;
    memset(display,0x7b,sizeof(display));
    memcpy(reference,display,sizeof(display));
    GUITextState textBefore, textAfter;
    static uint8 workspaceBefore[sizeof(screens[1])];
    for(unsigned i=0;i<sizeof(screens[1]);i++) screens[1][i]=(uint8)(i*37+13);
    memcpy(workspaceBefore,screens[1],sizeof(workspaceBefore));
    unsigned setupEncodes=encodes, setupCompiles=preparedBlits, setupCaptures=sidebarCaptures;
    unsigned setupBegins=batchBegins, setupEnds=liveEnds;
    Widget_SetCurrentWidget(6);
    uint16 setupWidget=g_curWidgetIndex, setupX=g_curWidgetXBase, setupY=g_curWidgetYBase;
    uint16 setupWidth=g_curWidgetWidth, setupHeight=g_curWidgetHeight;
    uint8 setupBlink=g_curWidgetFGColourBlink, setupNormal=g_curWidgetFGColourNormal;
    static Widget widgetBefore[9];
    memcpy(widgetBefore,widgets,sizeof(widgets));
    s_planarTarget=reference;
    s_textPlanarAllowed=true;
    GUI_TextState_Get(&textBefore);
    GUI_Sidebar_Preload();
    GUI_TextState_Get(&textAfter);
    assert(textBefore.font==textAfter.font && textBefore.spacing==textAfter.spacing);
    assert(textBefore.fontFlags==textAfter.fontFlags && textBefore.styleFlags==textAfter.styleFlags);
    assert(!memcmp(textBefore.colours,textAfter.colours,sizeof(textBefore.colours)));
    assert(textBefore.planarTarget==textAfter.planarTarget && textBefore.planarAllowed==textAfter.planarAllowed);
    s_planarTarget=NULL;
    s_textPlanarAllowed=false;
    assert(g_screenActiveID==SCREEN_0 && !memcmp(workspaceBefore,screens[1],sizeof(workspaceBefore)));
    assert(!memcmp(widgetBefore,widgets,sizeof(widgets)) && g_curWidgetIndex==setupWidget);
    assert(g_curWidgetXBase==setupX && g_curWidgetYBase==setupY);
    assert(g_curWidgetWidth==setupWidth && g_curWidgetHeight==setupHeight);
    assert(g_curWidgetFGColourBlink==setupBlink && g_curWidgetFGColourNormal==setupNormal);
    assert(batchBegins==setupBegins && liveEnds==setupEnds);
    if(g_videoViewportBlitter) {
        /* Each asset is sized before relocation, then compiled at its final address.
         * One additional query sizes the three borrowed background commands. */
        assert(encodes-setupEncodes==86 && preparedBlits-setupCompiles==86*2+3+1);
        assert(sidebarCaptures-setupCaptures==86);
        assert(!s_prepared && !s_chrome && !s_buttonTemplate);
    }
    assert(!memcmp(reference,display,sizeof(display)) && !GUI_Sidebar_Valid());
    /* RESOURCE FOOTPRINT */
    if(g_videoViewportBlitter) {
        assert(s_sidebar.background.ready && s_sidebar.damageGauge.ready);
        assert(s_sprites[27-SIDEBAR_SPRITE_FIRST]==NULL);
        assert(s_sidebar.productionFace[0].ready && s_sidebar.productionFace[1].ready);
        assert(g_sidebarCaptions.action[ACTION_MOVE][0].ready);
        assert(g_sidebarCaptions.action[ACTION_MOVE][1].ready);
        assert(g_sidebarCaptions.action[ACTION_MOVE][2].ready);
        assert(s_assetBank && s_assetUsed==s_assetBytes);
        TestBlit caption;
        memcpy(&caption,g_sidebarCaptions.action[ACTION_MOVE][0].code,sizeof(caption));
        assert(caption.width==64 && caption.height==12 && caption.stride==64 && caption.phase==0 && !caption.masks);
    }
    /* An unrelated text button retains its legacy pressed colours and bevel. */
    Widget outside=widgets[5];
    outside.index=20; outside.offsetX=20; outside.offsetY=30;
    outside.stringID=STR_MOVE; outside.state.selected=false; outside.state.hover2=true;
    for(unsigned native=0;native<2;native++) {
        direct=native; g_screenActiveID=SCREEN_0;
        memset(display,0x7b,sizeof(display)); memset(screens,0xa5,sizeof(screens));
        GUI_Widget_TextButton2_Draw(&outside);
        if(!native) memcpy(reference,display,sizeof(display));
        else assert(!memcmp(reference,display,sizeof(display)));
    }
    /* Ready buttons skip layout but preserve both changed and unchanged wrapper state. */
    for(unsigned sameStyle=0;sameStyle<2;sameStyle++) for(unsigned state=0;state<4;state++) {
        direct=false; setup_widgets(); g_screenActiveID=SCREEN_1;
        GUI_Widget_ActionPanel_Draw(true);
        Widget button=widgets[5];
        button.stringID=g_table_actionInfo[g_table_unitInfo[unit.o.type].o.actionsPlayer[0]].stringID;
        button.state.selected=state&1; button.state.hover2=(state&2)!=0;
        GUI_DrawText_Wrapper(NULL,0,0,3,11,sameStyle?0x121:0x12);
        uint8 prior[2]={11,3};
        GUI_InitColors(prior,0,1);
        GUITextState before, expected, actual;
        GUI_TextState_Get(&before);
        GUI_Widget_TextButton2_Draw(&button);
        uint16 shortcut=button.shortcut;
        GUI_TextState_Get(&expected);
        copy_rect(256,42,256,42,64,82,SCREEN_1);
        memcpy(reference,display,sizeof(reference));
        direct=true; setup_widgets(); GUI_Widget_ActionPanel_Draw(true);
        GUI_TextState_Set(&before);
        GUI_Sidebar_Begin(false);
        unsigned measurements=textMeasurements, layouts=textLayouts, queued=queuedBlits;
        GUI_Widget_TextButton2_Draw(&button);
        GUI_TextState_Get(&actual);
        GUI_Sidebar_End();
        if(memcmp(reference,display,sizeof(display)))
            for(unsigned word=0;word<lengthof(display);word++)
                if(reference[word]!=display[word]) {
                    fprintf(stderr,"ready button style=%u state=%u differs at group=%u y=%u (%04x/%04x)\n",
                            sameStyle,state,(word%80)/4,word/80,reference[word],display[word]);
                    break;
                }
        assert(!memcmp(reference,display,sizeof(display)) && button.shortcut==shortcut);
        assert(actual.font==expected.font && actual.spacing==expected.spacing);
        assert(actual.fontFlags==expected.fontFlags && actual.styleFlags==expected.styleFlags);
        assert(!memcmp(actual.colours,expected.colours,sizeof(actual.colours)));
        assert(textMeasurements==measurements+!g_videoViewportBlitter);
        assert(textLayouts==layouts+!g_videoViewportBlitter);
        if(g_videoViewportBlitter) assert(queuedBlits==queued+1);
    }
    check_panel();
    unsigned p=liveEnds;
    unit.o.hitpoints=76; GUI_Widget_ActionPanel_Draw(false);
    assert(liveEnds==p); /* Same 18-pixel health bar. */
    unit.o.hitpoints=51; check_health_update(true,false);
    unit.o.hitpoints=50; check_health_update(true,false);
    unit.o.hitpoints=26; check_health_update(true,false);
    unit.o.hitpoints=25; check_health_update(true,false);
    unit.o.hitpoints=0; check_health_update(true,false);
    unit.o.hitpoints=74; check_health_update(true,false);
    unit.o.hitpoints=50; check_health_update(false,true);
    unit.o.hitpoints=74; GUI_Sidebar_Invalidate(); check_health_update(false,false);
    unit.o.hitpoints=50; unit.nextActionID=ACTION_ATTACK; check_health_update(false,false);
    unit.nextActionID=ACTION_INVALID; unit.o.hitpoints=75; unit.o.houseID=1; check_panel();
    unit.actionID=ACTION_GUARD; p=liveEnds; GUI_Widget_ActionPanel_Draw(false);
    assert(liveEnds==p);
    unit.o.hitpoints=50; unit.actionID=ACTION_ATTACK; check_health_update(true,false);
    unit.o.hitpoints=25; check_health_update(true,false);
    unit.o.houseID=0; unit.o.hitpoints=75; unit.actionID=ACTION_MOVE; check_panel();
    p=liveEnds;
    unit.nextActionID=ACTION_ATTACK; GUI_Widget_ActionPanel_Draw(false);
    assert(liveEnds>p);
    /* Retain unit layout across selections, including ownership and shorter titles. */
    unit.nextActionID=ACTION_INVALID; unit.actionID=ACTION_MOVE; check_panel();
    unit.o.index++;
    check_unit_selection(SIDEBAR_REDRAW_COMMANDS);
    for(unsigned i=8;i<12;i++) assert(!widgetDraws[i]);
    widgets[5].state.hover2=true; GUI_Widget_Draw(&widgets[5]);
    unit.o.index++; check_unit_selection(SIDEBAR_REDRAW_COMMANDS);
    assert(widgetDraws[8]==1 && !widgets[5].state.hover2);
    unit.o.index++; unit.o.hitpoints=50; unit.actionID=ACTION_ATTACK;
    check_unit_selection(SIDEBAR_REDRAW_HEALTH|SIDEBAR_REDRAW_COMMANDS);
    assert(widgetDraws[8]==1 && widgetDraws[9]==1);
    g_table_unitInfo[UNIT_LAUNCHER].o.stringID_abbrev=STR_AREA_GUARD;
    g_table_unitInfo[UNIT_LAUNCHER].o.actionsPlayer[1]=ACTION_RETREAT;
    g_table_unitInfo[UNIT_LAUNCHER].o.actionsPlayer[3]=ACTION_STOP;
    unit.o.index++; unit.o.type=UNIT_LAUNCHER;
    check_unit_selection(SIDEBAR_REDRAW_PORTRAIT|SIDEBAR_REDRAW_NAME|SIDEBAR_REDRAW_COMMANDS);
    unit.o.index++; unit.o.type=UNIT_TANK;
    check_unit_selection(SIDEBAR_REDRAW_PORTRAIT|SIDEBAR_REDRAW_NAME|SIDEBAR_REDRAW_COMMANDS);
    unit.o.houseID=1; check_unit_selection(SIDEBAR_REDRAW_ALL);
    unit.o.index++; check_unit_selection(0);
    unit.o.index++; unit.o.hitpoints=49; check_unit_selection(SIDEBAR_REDRAW_HEALTH);
    unit.o.index++; unit.o.type=UNIT_LAUNCHER; unit.o.hitpoints=25;
    check_unit_selection(SIDEBAR_REDRAW_PORTRAIT|SIDEBAR_REDRAW_NAME|SIDEBAR_REDRAW_HEALTH);
    unit.o.index++; unit.o.houseID=2; unit.o.type=UNIT_TANK;
    check_unit_selection(SIDEBAR_REDRAW_PORTRAIT|SIDEBAR_REDRAW_NAME);
    unit.o.houseID=0; check_unit_selection(SIDEBAR_REDRAW_COMMANDS);
    unit.o.houseID=1; check_unit_selection(SIDEBAR_REDRAW_ALL);
    unit.o.index++; unit.o.houseID=0; unit.o.type=UNIT_LAUNCHER;
    check_unit_selection(SIDEBAR_REDRAW_ALL);
    unit.o.index++; GUI_Sidebar_Invalidate(); check_unit_selection(SIDEBAR_REDRAW_ALL);
    check_unit_selection(SIDEBAR_REDRAW_ALL); /* Explicit restoration, not a new selection. */
    unit.o.index++; g_config.language=LANGUAGE_FRENCH; check_unit_selection(SIDEBAR_REDRAW_ALL);
    g_selectionType=SELECTIONTYPE_TARGET; g_activeAction=ACTION_ATTACK;
    GUI_Widget_ActionPanel_Draw(true);
    g_selectionType=SELECTIONTYPE_UNIT; unit.o.index++; check_unit_selection(SIDEBAR_REDRAW_ALL);
    g_debugGame=true; unit.o.index++; check_unit_selection(SIDEBAR_REDRAW_ALL);
    g_debugGame=false;
    g_table_unitInfo[UNIT_LAUNCHER].o.stringID_abbrev=STR_MOVE;
    for(unsigned a=0;a<4;a++) g_table_unitInfo[UNIT_LAUNCHER].o.actionsPlayer[a]=g_table_actionsAI[a];
    unit.o.type=UNIT_TANK; unit.o.houseID=0; unit.o.hitpoints=75; unit.actionID=ACTION_MOVE;
    unit.nextActionID=ACTION_ATTACK;
    g_config.language=LANGUAGE_ENGLISH; check_panel();
    for(unsigned a=0;a<3;a++) {
        g_selectionType=SELECTIONTYPE_TARGET;
        g_activeAction=a==0?ACTION_ATTACK:a==1?ACTION_MOVE:ACTION_HARVEST;
        check_panel();
        /* Cancel press/release also goes through the native widget path. */
        Widget *cancel=&widgets[4];
        cancel->state.hover2=true; unsigned c=copies; GUI_Widget_Draw(cancel);
        assert(copies==c);
        static uint16 pressed[sizeof(display)/sizeof(*display)];
        memcpy(pressed,display,sizeof(pressed));
        GUI_Widget_ActionPanel_Draw(true);
        assert(!memcmp(pressed,display,sizeof(pressed)) && !cancel->flags.invisible);
        cancel->state.hover2=false; GUI_Widget_Draw(cancel);
        assert(!memcmp(reference,display,sizeof(display)));
    }
    g_selectionType=SELECTIONTYPE_PLACE; g_structureActiveType=STRUCTURE_WINDTRAP; check_panel();
    g_selectionType=SELECTIONTYPE_UNIT;
    g_unitHouseMissile=&unit; g_houseMissileCountdown=12; check_panel();
    g_houseMissileCountdown--; check_panel();
    g_unitHouseMissile=g_unitSelected=NULL; structureSelected=true;
    structure.o.hitpoints=75; structure.o.linkedID=1;
    structure.objectType=UNIT_TANK; structure.countDown=50*256;
    for(unsigned type=0;type<STRUCTURE_MAX;type++) {
        structure.o.type=type; check_panel();
    }
    static const unsigned factories[]={STRUCTURE_LIGHT_VEHICLE,STRUCTURE_CONSTRUCTION_YARD};
    for(unsigned f=0;f<2;f++) {
        structure.o.type=factories[f]; structure.objectType=f?STRUCTURE_WINDTRAP:UNIT_TANK;
        g_table_structureInfo[factories[f]].o.flags.factory=true;
        structure.countDown=50*256; check_panel();
        p=liveEnds; unsigned e=encodes;
        structure.countDown--; GUI_Widget_ActionPanel_Draw(false);
        assert(liveEnds==p && encodes==e);
        structure.countDown-=3*256;
        check_production_update(false);
        structure.o.flags.s.repairing=structure.o.flags.s.onHold=true;
        check_component_update(false,false,true,true);
        structure.o.flags.s.repairing=structure.o.flags.s.onHold=false;
        check_component_update(false,false,true,true);
        structure.o.hitpoints=80; structure.o.flags.s.repairing=structure.o.flags.s.onHold=true;
        check_component_update(true,false,true,true);
        widgets[3].state.hover2=true; GUI_Widget_Draw(&widgets[3]);
        structure.o.hitpoints=100; structure.o.flags.s.repairing=structure.o.flags.s.onHold=false;
        check_component_update(true,false,true,true);
        widgets[3].state.hover2=false; GUI_Widget_Draw(&widgets[3]);
        structure.upgradeTimeLeft=100; check_component_update(false,false,true,false);
        structure.upgradeTimeLeft=0; check_component_update(false,false,true,false);
        structure.o.hitpoints=75; check_component_update(true,false,true,false);
        structure.o.flags.s.onHold=true; check_production_update(false);
        structure.o.flags.s.onHold=false; check_production_update(false);
        structure.objectType=f?STRUCTURE_TURRET:UNIT_INFANTRY;
        check_production_update(true);
        structure.countDown=1*256; check_production_update(false);
        structure.countDown=0; check_production_update(false);
        check_panel();
        structure.o.flags.s.onHold=true; check_panel();
        structure.o.flags.s.onHold=false; structure.countDown=0; check_panel();
        structure.o.flags.s.upgrading=true; structure.upgradeTimeLeft=57;
        check_component_update(false,false,true,true);
        structure.upgradeTimeLeft=90; check_production_update(false);
        structure.upgradeTimeLeft=91; check_production_update(false);
        widgets[2].state.hover2=true; GUI_Widget_Draw(&widgets[2]);
        structure.upgradeTimeLeft=1; check_production_update(false);
        widgets[2].state.hover2=false; GUI_Widget_Draw(&widgets[2]);
        structure.o.flags.s.upgrading=false; structure.upgradeTimeLeft=0;
        check_component_update(false,false,true,true);
        structure.countDown=50*256; structure.o.hitpoints=75;
        for(unsigned i=1;i<4;i++) for(unsigned down=0;down<2;down++) check_hover(i,down);
    }
    structure.o.type=STRUCTURE_TURRET; structure.o.hitpoints=75; check_panel();
    structure.o.hitpoints=50; check_health_update(true,false);
    assert(!g_structureHighHealth);
    structure.o.hitpoints=25; check_health_update(true,false);
    structure.o.flags.s.repairing=true; check_component_update(false,false,true,false);
    structure.o.flags.s.repairing=false; check_component_update(false,false,true,false);
    structure.o.flags.s.repairing=true; check_health_update(false,true);
    structure.o.flags.s.repairing=false; GUI_Sidebar_Invalidate(); check_health_update(false,false);
    structure.o.hitpoints=100; check_component_update(true,false,true,false);
    structure.o.hitpoints=99; check_component_update(true,false,true,false);
    structure.o.type=STRUCTURE_WINDTRAP; structure.o.hitpoints=75; check_panel();
    structure.o.hitpoints=50; check_stats_update(true);
    structure.o.houseID=1; check_panel();
    structure.o.hitpoints=25; check_health_update(true,false);
    structure.o.flags.s.repairing=true;
    p=liveEnds; GUI_Widget_ActionPanel_Draw(false); assert(liveEnds==p);
    structure.o.flags.s.repairing=false;
    structure.o.houseID=0; structure.o.hitpoints=75;
    structure.o.type=STRUCTURE_OUTPOST; check_panel();
    house.unitCountAllied++; check_stats_update(false);
    house.unitCountAllied=1; house.unitCountEnemy=1;
    structure.o.hitpoints=50; check_stats_update(true);
    structure.o.type=STRUCTURE_WINDTRAP; check_panel();
    house.powerUsage+=10; check_stats_update(false);
    structure.o.hitpoints=80; check_stats_update(true);
    structure.o.type=STRUCTURE_SILO; check_panel();
    house.credits=1000; check_stats_update(false);
    house.credits=9; check_stats_update(false);
    structure.o.type=STRUCTURE_REFINERY; structure.o.hitpoints=75;
    structure.o.flags.s.repairing=structure.o.flags.s.onHold=true;
    house.credits=425; check_panel();
    structure.o.hitpoints=80; house.credits=375; check_stats_update(true);
    structure.o.hitpoints=85; check_health_update(true,false);
    structure.o.hitpoints=86; house.credits=9; check_stats_update(false);
    house.credits=8; check_health_update(false,true);
    house.credits=7; GUI_Sidebar_Invalidate(); check_health_update(false,false);
    structure.o.hitpoints=100; house.credits=6; check_component_update(true,true,true,false);
    structure.o.flags.s.repairing=structure.o.flags.s.onHold=false;
    structure.o.hitpoints=75;
    structure.o.type=STRUCTURE_STARPORT; check_panel();
    house.starportTimeLeft=1; check_stats_update(false);
    house.starportLinkedID=0xffff; check_stats_update(false);
    house.starportLinkedID=1; house.starportTimeLeft=9;
    structure.o.hitpoints=50; check_stats_update(true);
    structure.o.houseID=1; check_panel();
    p=liveEnds; house.starportTimeLeft--; GUI_Widget_ActionPanel_Draw(false); assert(liveEnds==p);
    structure.o.houseID=0;
    structure.o.type=STRUCTURE_WINDTRAP; structure.o.hitpoints=100; upgradable=true;
    structure.upgradeTimeLeft=0; check_panel(); assert(structure.upgradeTimeLeft==100 && upgradedChecks);
    structure.o.flags.s.repairing=true; structure.o.hitpoints=10; check_panel();
    structure.o.flags.s.repairing=false;
    structure.o.houseID=1; g_playerHouseID=1; check_panel();
    g_playerHouseID=0; check_panel();
    g_debugGame=true; check_panel(); g_debugGame=false; structure.o.houseID=0;
    structureSelected=false; g_unitSelected=&unit; check_panel();
    unit.deviated=1; check_panel(); unit.deviated=0;
    if(g_videoViewportBlitter) {
        /* All loaded action/state members survive changing selections and statistics. */
        unsigned prepared=preparedBlits, flushes=nonemptyFlushes;
        unsigned action=unit.actionID;
        for(unsigned a=0;a<ACTION_MAX;a++) {
            unit.actionID=a;
            GUI_Widget_ActionPanel_Draw(true);
            assert(preparedBlits==prepared);
        }
        assert(g_sidebarCaptions.action[ACTION_MOVE][0].ready);
        assert(nonemptyFlushes==flushes+ACTION_MAX);
        unit.actionID=action;
    }
    for(unsigned language=0;language<3;language++) {
        g_config.language=language; GUI_Sidebar_Free(); check_panel();
    }
    /* Every command button state compares against the same legacy callbacks. */
    for(unsigned i=5;i<9;i++) for(unsigned down=0;down<2;down++) {
        check_hover(i,down);
    }
    wideCaption=true;
    GUI_Sidebar_Free();
    check_panel();
    if(g_videoViewportBlitter) {
        TestBlit caption;
        memcpy(&caption,g_sidebarCaptions.action[ACTION_MOVE][0].code,sizeof(caption));
        assert(caption.width==64 && !caption.masks);
    }
    for(unsigned i=5;i<9;i++) check_hover(i,true);
    wideCaption=false;
    GUI_Sidebar_Free();
    /* Resource transitions rebuild loaded members; prompt colour remains live state. */
    g_selectionType=SELECTIONTYPE_TARGET; g_activeAction=ACTION_MOVE;
    for(unsigned language=0;language<3;language++) {
        g_config.language=language; GUI_Sidebar_Free(); check_panel();
    }
    g_widgetProperties[6].fgColourBlink=6; check_panel();
    g_widgetProperties[6].fgColourBlink=15; check_panel();
    Font alternate=font6; alternate.height=9;
    g_fontNew6p=&alternate;
    GUI_Sidebar_Free();
    GUI_DrawText_Wrapper(NULL,0,0,15,0,0x11);
    check_panel();
    g_fontNew6p=&font6;
    GUI_Sidebar_Free();
    GUI_DrawText_Wrapper(NULL,0,0,15,0,0x11);
    generation++; mapping[29]^=1; check_panel();
    g_selectionType=SELECTIONTYPE_UNIT; check_panel();
    /* Even an unchanged key must republish after interface or mapping replacement. */
    GUI_Sidebar_Invalidate(); p=liveEnds;
    GUI_Widget_ActionPanel_Draw(false); assert(liveEnds>p);
    generation++; mapping[29]^=1; p=liveEnds;
    unsigned beforeCopies=copies;
    widgets[5].state.hover2=true;
    GUI_Widget_Draw(&widgets[5]);
    assert(!GUI_Sidebar_Valid() && copies==beforeCopies);
    GUI_Widget_ActionPanel_Draw(false); assert(liveEnds>p);
    assert(GUI_Sidebar_Valid());
    /* Clipping, both edge groups, transparency and an opaque pen-zero glyph. */
    uint8 colours[16]={0}; colours[1]=11; colours[2]=6; colours[3]=29; colours[4]=15;
    for(unsigned phase=0;phase<16;phase++) {
        GUI_Sidebar_Begin(true);
        GUI_Sidebar_Fill(256,42,319,123,20);
        memset(reference,0,sizeof(reference));
        for(unsigned y=42;y<124;y++) for(unsigned x=256;x<320;x++) put_pen(reference,x,y,mapping[20]);
        for(unsigned edge=0;edge<3;edge++) {
            unsigned x=edge==0?253:edge==1?256+phase:314+phase;
            unsigned y=50+edge*10;
            GUI_Sidebar_Char('A',x,y,colours);
            const FontChar *fc=&chars['A'];
            for(unsigned row=0;row<font6.height;row++) for(unsigned col=0;col<fc->width;col++) {
                uint8 colour=row>=fc->unusedLines && row<fc->unusedLines+fc->usedLines?
                    colours[fc->data[(row-fc->unusedLines)*fc->width+col]]:colours[0];
                if(colour && x+col>=256 && x+col<320) put_pen(reference,x+col,y+row,mapping[colour]);
            }
        }
        GUI_Sidebar_End();
        for(unsigned y=42;y<124;y++) assert(!memcmp(display+y*80+64,reference+y*80+64,32));
    }
    /* Write-only borders against the legacy renderer, over an underlay that only repeats per row. */
    GUI_Sidebar_Free();
    srand(7);
    for(unsigned n=0;n<400;n++) {
        unsigned w=2+rand()%63, h=3+rand()%80, x=256+rand()%(64-w+1), y=42+rand()%(82-h+1);
        unsigned schema=rand()%5; bool fill=true;
        direct=false; g_screenActiveID=SCREEN_1;
        for(unsigned col=256;col<320;col++) GUI_DrawFilledRectangle(col,42,col,123,(col*5+n)%17+1);
        GUI_DrawBorder(x,y,w,h,schema,fill);
        copy_rect(256,42,256,42,64,82,SCREEN_1);
        memcpy(reference,display,sizeof(display));
        direct=true; GUI_Sidebar_Begin(false);
        for(unsigned col=256;col<320;col++) GUI_Sidebar_Fill(col,42,col,123,(col*5+n)%17+1);
        GUI_DrawBorderRepeating(x,y,w,h,schema);
        GUI_Sidebar_End();
        for(unsigned row=42;row<124;row++) assert(!memcmp(display+row*80+64,reference+row*80+64,32));
        GUI_Sidebar_Free();
    }
    /* Prepare the combined frame once; subsequent health updates only submit the CPU fill. */
    GUI_Sidebar_Free();
    direct=false; g_screenActiveID=SCREEN_1;
    GUI_DrawFilledRectangle(256,42,319,123,20);
    GUI_DrawSprite(SCREEN_ACTIVE,g_sprites[27],27,GUI_SPRITE_COLOUR_EMBEDDED,292,60,0,0);
    GUI_DrawText_Wrapper(String_Get_ByIndex(STR_DMG),296,65,29,0,0x11);
    direct=true; GUI_Sidebar_Begin(false);
    GUI_Sidebar_Fill(256,42,319,123,20);
    if(g_videoViewportBlitter) {
        unsigned queued=queuedBlits;
        assert(GUI_Sidebar_DamageGauge());
        assert(queuedBlits==queued+1 && s_sprites[27-SIDEBAR_SPRITE_FIRST]==NULL);
        /* Health is a hole in the static asset, not a stored fill. */
        TestBlit gauge;
        memcpy(&gauge,s_sidebar.damageGauge.code,sizeof(gauge));
        assert(gauge.masks);
        for(unsigned y=52;y<59;y++) for(unsigned x=293;x<317;x++)
            assert(!(gauge.masks[(y-51)*(gauge.stride/4)+((x-288)/16)*4]&
                     (0x8000u>>((x-288)&15))));
    } else {
        GUI_DrawSprite(SCREEN_ACTIVE,g_sprites[27],27,GUI_SPRITE_COLOUR_EMBEDDED,292,60,0,0);
        GUI_DrawText_Wrapper(String_Get_ByIndex(STR_DMG),296,65,29,0,0x11);
    }
    GUI_Sidebar_End();
    for(unsigned step=0;step<=200;step++) {
        unsigned current=step<=100?step:200-step;
        direct=false; g_screenActiveID=SCREEN_1;
        GUI_DrawProgressbar(current,100);
        copy_rect(256,42,256,42,64,82,SCREEN_1);
        memcpy(reference,display,sizeof(display));
        direct=true; GUI_Sidebar_Begin(false);
        unsigned prepared=preparedBlits, flushes=nonemptyFlushes, health=queuedHealth, blits=queuedBlits;
        GUI_DrawProgressbar(current,100);
        if(g_videoViewportBlitter) {
            assert(nonemptyFlushes==flushes && queuedHealth==health+1);
            assert(preparedBlits==prepared && queuedBlits==blits);
            assert(pendingBlitCount==1);
        }
        GUI_Sidebar_End();
        assert(!memcmp(display,reference,sizeof(display)));
    }
    GUI_Sidebar_Free();
    for(unsigned id=24;id<=30;id++)
        check_sidebar_sprite(id,258,id!=27,id>=28);
    check_sidebar_sprite(31,258,false,false);
    check_sidebar_sprite(62,258,false,false);
    check_sidebar_sprite(63,258,false,false);
    check_sidebar_sprite(64,258,false,false);
    for(unsigned id=65;id<=105;id++) check_sidebar_sprite(id,258,true,true);
    for(unsigned phase=0;phase<16;phase++) {
        check_sidebar_sprite(65,256+phase,true,true);
        check_sidebar_sprite(65,288+phase,true,true);
        check_sidebar_sprite(24,256+phase,true,false);
        check_sidebar_sprite(24,304+phase,true,false);
        check_sidebar_sprite(63,256+phase,false,false);
        check_sidebar_sprite(63,288+phase,false,false);
        check_sidebar_sprite(64,256+phase,false,false);
        check_sidebar_sprite(64,288+phase,false,false);
    }
    /* Different geometry must retain real opacity, even within a known-opaque ID range. */
    const uint16 geometryIDs[]={24,28,65};
    for(unsigned i=0;i<lengthof(geometryIDs);i++) {
        uint16 id=geometryIDs[i];
        GUI_Sidebar_Free();
        uint8 height=assets[id][2], width=assets[id][3], first=assets[id][5];
        if(id==28) assets[id][3]--;
        else assets[id][2]--;
        assets[id][5]=0;
        check_sidebar_sprite(id,258,false,false);
        GUI_Sidebar_Free();
        assets[id][2]=height; assets[id][3]=width; assets[id][5]=first;
    }
    /* Whole-string labels against the legacy renderer over equal and different backgrounds. */
    GUI_Sidebar_Free();
    for(unsigned pass=0;pass<3;pass++) {
        uint8 background=pass==0?11:20;
        uint8 labelColours[16]={0,11,6,29,15};
        if(pass==2) labelColours[2]=29;
        direct=false; g_screenActiveID=SCREEN_1;
        GUI_DrawFilledRectangle(256,42,319,123,background);
        GUI_InitColors(labelColours,0,15);
        GUI_DrawText(pass==1?"AB\rCD\r\nE":"AB",260,50,11,0);
        copy_rect(256,42,256,42,64,82,SCREEN_1);
        memcpy(reference,display,sizeof(display));
        direct=true; GUI_Sidebar_Begin(false);
        GUI_Sidebar_Fill(256,42,319,123,background);
        GUI_InitColors(labelColours,0,15);
        GUI_DrawText(pass==1?"AB\rCD\r\nE":"AB",260,50,11,0);
        GUI_Sidebar_End();
        assert(!memcmp(display,reference,sizeof(display)));
    }
    GUI_Sidebar_Free();
    /* Queued live text owns its string and colour state, and follows earlier graphics. */
    if(g_videoViewportBlitter) {
        uint8 colours[16]={0,11,6,29,15};
        char text[]="AB";
        direct=false; g_screenActiveID=SCREEN_1;
        GUI_DrawFilledRectangle(256,42,319,123,20);
        GUI_InitColors(colours,0,15);
        GUI_DrawText(text,260,50,11,0);
        copy_rect(256,42,256,42,64,82,SCREEN_1);
        memcpy(reference,display,sizeof(display));
        direct=true; GUI_Sidebar_Begin(false);
        GUI_Sidebar_Fill(256,42,319,123,20);
        GUI_InitColors(colours,0,15);
        GUI_DrawText(text,260,50,11,0);
        strcpy(text,"CD");
        memset(g_colours,0,sizeof(g_colours));
        assert(pendingBlitCount==2);
        GUI_Sidebar_End();
        assert(!memcmp(display,reference,sizeof(display)));
    }
    GUI_Sidebar_Free();
    assert(!GUI_Sidebar_Valid() && hides==shows);
    return 0;
}
"""
        # Count actual widget draws, not MakeVisible/MakeSelected calls.
        functions = functions.replace(
            "\n\tif (w == NULL) return;\n\n#ifdef TOS\n\tsidebar",
            "\n\tif (w == NULL) return;\n\twidgetDraws[w->index]++;\n\n#ifdef TOS\n\tsidebar",
        )
        # The sidebar skips glyphs past the screen edge instead of wrapping the string.
        wrap = "\t\tif (x + width > SCREEN_WIDTH) {\n\t\t\tx = left;\n\t\t\ty += g_fontCurrent->height;\n\t\t}\n"
        assert wrap in functions
        functions = functions.replace(wrap, "\t\tif (x + width > SCREEN_WIDTH) { x += width; s++; continue; }\n")
        harness = harness.replace("/* PRODUCTION */", surface_backend(video) +
                                  function(video, "Video_Atari_DrawPlanarBorder") + functions)
        glyph = "\n".join(line for line in (ROOT / "src/gui/glyph.c").read_text().splitlines()
                          if not line.startswith("#include "))
        harness = harness.replace("/* GLYPH */", glyph_backend(video) + glyph)
        planar = "\n".join(line for line in (ROOT / "src/video/atari_planar.c").read_text().splitlines()
                           if not line.startswith("#include "))
        harness = harness.replace("/* PLANAR */", planar)
        harness = harness.replace("/* SIDEBAR */", sidebar)
        harness = harness.replace("/* BLIT COMPILER */", blit_compiler)
        if real_resources:
            from tools.analyze_harvester_planes import decode_sprite, read_pak

            files = read_pak(ROOT / "DUNE.PAK")
            data = files["NEW6P.FNT"]
            start, offsets, widths = struct.unpack_from("<HHH", data, 4)
            count = struct.unpack_from("<H", data, 10)[0] - widths
            lines = struct.unpack_from("<H", data, 12)[0]
            setup = [f"font6.height={data[start + 4]}; font6.maxWidth={data[start + 5]}; font6.count={count};"]
            for char in range(count):
                width = data[widths + char]
                unused, used = data[lines + char * 2:lines + char * 2 + 2]
                offset = struct.unpack_from("<H", data, offsets + char * 2)[0]
                setup.append(f"chars[{char}]=(FontChar){{{width},{unused},{used},"
                             f"{f'fontData[{char}]' if offset else 'NULL'}}};")
                if offset:
                    pixels = [((data[offset + y * ((width + 1) // 2) + x // 2]
                                >> (4 * (x & 1))) & 15)
                              for y in range(used) for x in range(width)]
                    setup.append(f"memcpy(fontData[{char}],(uint8[]){{{','.join(map(str, pixels))}}},{len(pixels)});")
            shapes = files["SHAPES.SHP"]
            count = struct.unpack_from("<H", shapes)[0]
            modern = struct.unpack_from("<I", shapes, 2)[0] == 4 + count * 4
            for sprite_id in (*range(24, 32), *range(62, 106)):
                offset = struct.unpack_from("<I" if modern else "<H", shapes,
                                            2 + (sprite_id - 12) * (4 if modern else 2))[0]
                sprite = decode_sprite(shapes[offset + (2 if modern else 0):])
                if sprite_id in (*range(24, 27), *range(28, 31), *range(65, 106)):
                    size = 5 if sprite_id == 24 else 8 if sprite_id <= 26 else 32
                    self.assertEqual((sprite.width, sprite.height), (size, size if size < 32 else 24))
                    self.assertNotIn(None, sprite.pixels, f"Opaque sidebar sprite {sprite_id}")
                pixels = [0 if pixel is None else
                          (sprite.palette[pixel] if sprite.palette else pixel) or 255
                          for pixel in sprite.pixels]
                self.assertLessEqual(len(pixels), 32 * 24)
                setup.append(f"assets[{sprite_id}][2]={sprite.height}; assets[{sprite_id}][3]={sprite.width};"
                             f"memcpy(assets[{sprite_id}]+5,(uint8[]){{{','.join(map(str, pixels))}}},{len(pixels)});")
            harness = harness.replace("/* REAL RESOURCES */", "\n".join(setup))
            harness = harness.replace(
                "/* RESOURCE FOOTPRINT */",
                'if(g_videoViewportBlitter) fprintf(stderr,"Real-font/artwork fixture: asset bank %zu bytes\\n",s_assetBytes);',
            )
        with tempfile.TemporaryDirectory(prefix="sidebar-planar-", dir=ROOT / "objs") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            from tools.test_sidebar_blitter import SUPPORT
            source.write_text(SUPPORT + harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for blitter in (False, True):
                with self.subTest(blitter=blitter):
                    subprocess.run(
                        [*compiler, "-std=gnu17", "-DTOS", "-O2", "-Wall", "-Wextra",
                         "-Werror", "-Wno-sign-compare", "-ffunction-sections",
                         "-fdata-sections", "-I", str(ROOT / "include"), "-I", str(ROOT),
                         "-iquote", str(ROOT / "src"), *flags,
                         *(["-DTEST_SIDEBAR_BLITTER"] if blitter else []), str(source),
                         "-Wl,--gc-sections", "-o", str(binary)], check=True,
                    )
                    subprocess.run([str(binary)], check=True)
                    for sprite_id, remap_count in ((23, 0), (106, 0), (65535, 0), (65, 1), (65, 2)):
                        rejected = subprocess.run(
                            [str(binary), str(sprite_id), str(remap_count)],
                            capture_output=True, text=True,
                        )
                        self.assertEqual(rejected.returncode, 1)
                        self.assertIn(f"Unsupported sidebar sprite request {sprite_id}", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
