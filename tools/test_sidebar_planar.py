"""Compare the production planar sidebar with the legacy widget renderer."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class SidebarPlanarTest(unittest.TestCase):
    def test_panels_callbacks_and_fragment_publication(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        widget = (ROOT / "src/gui/widget.c").read_text()
        font = (ROOT / "src/gui/font.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        sidebar = (ROOT / "src/gui/sidebar.c").read_text()
        for name, counter in (
            ("GUI_Sidebar_Char", "sidebarChars"),
            ("GUI_Sidebar_Fill", "sidebarFills"),
            ("GUI_Sidebar_Sprite", "sidebarSprites"),
            ("GUI_Sidebar_FragmentEnd", "fragmentBuilds"),
        ):
            body = function(sidebar, name)
            sidebar = sidebar.replace(body, body.replace("{", "{\n" + counter + "++;", 1))
        sidebar = "\n".join(line for line in sidebar.splitlines() if not line.startswith("#include "))
        functions = "\n".join(
            function(source, name)
            for source, names in (
                (font, ("Font_Select", "Font_GetCharWidth", "Font_GetStringWidth")),
                (gui, ("GUI_InitColors", "GUI_DrawChar", "GUI_DrawText",
                       "GUI_DrawText_Wrapper", "GUI_Sidebar_ButtonBegin", "GUI_DrawFilledRectangle",
                       "GUI_DrawWiredRectangle", "GUI_DrawBorder", "GUI_DrawProgressbar",
                       "GUI_UpdateProductionStringID")),
                (widget, ("GUI_Widget_GetNext", "GUI_Widget_Get_ByIndex",
                          "GUI_Widget_MakeInvisible", "GUI_Widget_MakeVisible",
                          "GUI_Widget_Draw", "GUI_Widget_MakeSelected",
                          "GUI_Widget_MakeNormal")),
                (video, ("Video_Atari_ComposePlanarSprite",)),
            )
            for name in names
        )
        compose = function(video, "Video_Atari_ComposePlanarSprite")
        functions = functions.replace(compose, compose.replace("{", "{\nsidebarCompositions++;", 1))
        harness = r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include "types.h"
#include "gui/gui.h"
#include "gui/widget.h"
#include "gui/sidebar.h"
#include "video/video.h"
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
#include "os/endian.h"

static bool direct;
static uint16 generation;
static unsigned encodes, publications, publishedBytes, copies, hides, shows, widgetDraws[12];
static unsigned sidebarChars, sidebarFills, sidebarSprites, fragmentBuilds, sidebarCompositions;
static uint16 display[320 * 200 / 4], reference[320 * 200 / 4];
static uint8 screens[2][320 * 200], mapping[256], remapping[256];
static uint8 assetData[355][5 + 32 * 24], *assets[355];
uint8 **g_sprites = assets;
uint8 *g_paletteMapping1 = remapping;
uint8 g_remap[256];
uint8 Sprite_GetWidth(uint8 *sprite) { return sprite[3]; }
static uint8 fontData[256][36];
static FontChar chars[256];
static Font font6 = {8, 6, 255, chars};
Font *g_fontCurrent = &font6, *g_fontNew6p = &font6, *g_fontNew8p = &font6;
int8 g_fontCharOffset;
static uint8 g_colours[16];
static uint16 s_colourBorderSchema[5][4] = {
    {26,29,29,29}, {20,26,16,20}, {20,16,26,20}, {233,235,232,233}, {233,232,235,233}
};
UnitInfo g_table_unitInfo[UNIT_MAX];
StructureInfo g_table_structureInfo[STRUCTURE_MAX];
const ActionInfo g_table_actionInfo[ACTION_MAX] = {
    [ACTION_ATTACK] = {.stringID = STR_ATTACK},
    [ACTION_MOVE] = {.stringID = STR_MOVE},
    [ACTION_GUARD] = {.stringID = STR_GUARD},
    [ACTION_HARVEST] = {.stringID = STR_HARVEST}
};
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
void Error(const char *format, ...) { (void)format; abort(); }
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
House *House_Get_ByIndex(uint8 index) { assert(index <= 1); return &house; }
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
        case STR_REPAIR: return "Repair";
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
        default: return "Caption";
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
        dst[(row+y)*320+col+x]=colour;
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
bool Video_Atari_PresentRestoreStrided(int16 x,int16 y,uint16 w,uint16 h,const uint8 *src,uint16 stride) {
    assert(x >= 256 && x+w <= 320 && y >= 42 && y+h <= 124 && stride == 32);
    publications++; publishedBytes += w*h/2;
    for(unsigned row=0;row<h;row++)
        memcpy(display+(y+row)*80+(x/16)*4,src+row*stride,w/2);
    return true;
}
static void Video_Atari_PlanarMergePlain(uint16 *dst, uint16 mask, const uint16 src[4]) {
    for(unsigned p=0;p<4;p++) dst[p]=(dst[p]&~mask)|(src[p]&mask);
}
void GFX_DrawTile(uint16 id,uint16 x,uint16 y,uint8 houseID) { (void)id;(void)x;(void)y;(void)houseID; abort(); }
void GUI_DrawXorFilledRectangle(int16 l,int16 t,int16 r,int16 b,uint8 c) { (void)l;(void)t;(void)r;(void)b;(void)c; abort(); }
void GUI_DrawBlockedRectangle(int16 l,int16 t,int16 w,int16 h,uint8 c) { (void)l;(void)t;(void)w;(void)h;(void)c; abort(); }
static void GUI_Widget_DrawBlocked(Widget *w,uint8 c) { (void)w;(void)c; abort(); }
/* PRODUCTION */
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
    GUI_Widget_ActionPanel_Draw(true);
    assert(g_screenActiveID==SCREEN_0 && g_curWidgetIndex==0 && hides==shows);
    assert(!memcmp(display,reference,sizeof(display)) && copies==beforeCopies);
    for(unsigned i=0;i<9;i++)
        if(!widgets[i].flags.invisible) assert(widgetDraws[widgets[i].index]==1);
    for(unsigned i=0;i<sizeof(screens);i++) assert(((uint8*)screens)[i]==0xa5);
    unsigned p=publications, e=encodes;
    GUI_Widget_ActionPanel_Draw(false);
    assert(publications==p && encodes==e);
    unsigned charsBefore=sidebarChars, fillsBefore=sidebarFills;
    unsigned spritesBefore=sidebarSprites, buildsBefore=fragmentBuilds;
    unsigned compositionsBefore=sidebarCompositions;
    GUI_Widget_ActionPanel_Draw(true);
    assert(publications>p && encodes==e && !memcmp(display,reference,sizeof(display)));
    assert(sidebarChars==charsBefore && fragmentBuilds==buildsBefore);
    assert(sidebarCompositions==compositionsBefore);
    if(g_selectionType==SELECTIONTYPE_TARGET && !g_unitHouseMissile) {
        assert(sidebarFills==fillsBefore && sidebarSprites==spritesBefore);
        assert(!widgets[4].flags.invisible && widgets[4].shortcut);
    }
}
static void check_hover(unsigned i,unsigned down) {
    direct=false; setup_widgets(); g_screenActiveID=SCREEN_0; GUI_Widget_ActionPanel_Draw(true);
    assert(!widgets[i].flags.invisible);
    widgets[i].state.hover2=down; GUI_Widget_Draw(&widgets[i]);
    uint16 shortcut=widgets[i].shortcut;
    uint8 coloursAfter[16]; memcpy(coloursAfter,g_colours,sizeof(coloursAfter));
    Font *fontAfter=g_fontCurrent;
    int8 spacingAfter=g_fontCharOffset;
    memcpy(reference,display,sizeof(display));
    direct=true; setup_widgets(); g_screenActiveID=SCREEN_0; GUI_Widget_ActionPanel_Draw(true);
    widgets[i].state.hover2=down; unsigned c=copies; GUI_Widget_Draw(&widgets[i]);
    if(memcmp(reference,display,sizeof(display))) {
        for(unsigned word=0;word<sizeof(display)/sizeof(*display);word++)
            if(reference[word]!=display[word]) {
                fprintf(stderr,"hover widget=%u down=%u structure=%u differs at group=%u y=%u (%04x/%04x)\n",
                        i+3,down,structure.o.type,(word%80)/4,word/80,reference[word],display[word]);
                break;
            }
    }
    assert(copies==c && !memcmp(reference,display,sizeof(display)) && widgets[i].shortcut==shortcut);
    unsigned charsBefore=sidebarChars, fillsBefore=sidebarFills, buildsBefore=fragmentBuilds;
    widgets[i].shortcut=0;
    GUI_Widget_Draw(&widgets[i]);
    assert(!memcmp(reference,display,sizeof(display)) && widgets[i].shortcut==shortcut);
    assert(sidebarChars==charsBefore && fragmentBuilds==buildsBefore);
    if(i!=2) assert(sidebarFills==fillsBefore);
    assert(g_fontCurrent==fontAfter && g_fontCharOffset==spacingAfter);
    assert(!memcmp(g_colours,coloursAfter,sizeof(coloursAfter)));
}
int main(void) {
    for(unsigned c=0;c<256;c++) {
        mapping[c]=(c*7+3)&15; remapping[c]=c?c-1:0;
        chars[c]=(FontChar){6,1,6,fontData[c]};
        for(unsigned p=0;p<36;p++) fontData[c][p]=(c+p*3)%5;
    }
    for(unsigned id=0;id<355;id++) {
        assets[id]=assetData[id]; assets[id][2]=id==24?3:24;
        assets[id][0]=1;
        assets[id][3]=id==24?3:32;
        for(unsigned p=0;p<assets[id][2]*assets[id][3];p++)
            assets[id][p+5]=(id+p)%5?(id+p)%255+1:0;
    }
    g_widgetProperties[0]=(WidgetProperties){0,0,40,200,15,12,0};
    g_widgetProperties[6]=(WidgetProperties){32,42,8,82,15,12,0};
    house.creditsStorage=1000; house.credits=425; house.windtrapCount=2;
    house.powerUsage=150; house.starportLinkedID=1; house.starportTimeLeft=12;
    house.unitCountAllied=9; house.unitCountEnemy=12;
    linked.o.type=UNIT_TANK;
    for(unsigned i=0;i<UNIT_MAX;i++) {
        g_table_unitInfo[i].o.hitpoints=100;
        g_table_unitInfo[i].o.buildTime=100;
        g_table_unitInfo[i].o.spriteID=50+i;
        g_table_unitInfo[i].o.stringID_abbrev=STR_MOVE;
        for(unsigned a=0;a<4;a++) g_table_unitInfo[i].o.actionsPlayer[a]=g_table_actionsAI[a];
    }
    for(unsigned i=0;i<STRUCTURE_MAX;i++) {
        g_table_structureInfo[i].o.hitpoints=100;
        g_table_structureInfo[i].o.buildTime=100;
        g_table_structureInfo[i].o.spriteID=100+i;
        g_table_structureInfo[i].o.stringID_abbrev=STR_MOVE;
        g_table_structureInfo[i].creditsStorage=1000;
        g_table_structureInfo[i].powerUsage=-100;
    }
    g_map[0].isUnveiled=true;
    unit.o.type=UNIT_TANK; unit.o.hitpoints=75; unit.actionID=ACTION_MOVE;
    unit.nextActionID=ACTION_INVALID; g_unitSelected=&unit;
    check_panel();
    unsigned p=publications;
    unit.o.hitpoints=76; GUI_Widget_ActionPanel_Draw(false);
    assert(publications==p); /* Same 18-pixel health bar. */
    unit.nextActionID=ACTION_ATTACK; GUI_Widget_ActionPanel_Draw(false);
    assert(publications>p);
    for(unsigned a=0;a<3;a++) {
        g_selectionType=SELECTIONTYPE_TARGET;
        g_activeAction=a==0?ACTION_ATTACK:a==1?ACTION_MOVE:ACTION_HARVEST;
        check_panel();
        /* Cancel press/release also goes through the native widget path. */
        Widget *cancel=&widgets[4];
        cancel->state.hover2=true; unsigned c=copies; GUI_Widget_Draw(cancel);
        assert(copies==c);
        uint16 pressed[SIDEBAR_HEIGHT*SIDEBAR_WORDS];
        memcpy(pressed,s_pixels,sizeof(pressed));
        GUI_Widget_ActionPanel_Draw(true);
        assert(!memcmp(pressed,s_pixels,sizeof(pressed)) && !cancel->flags.invisible);
        unsigned charsBefore=sidebarChars, fillsBefore=sidebarFills, spritesBefore=sidebarSprites;
        GUI_Widget_ActionPanel_Draw(true);
        assert(sidebarChars==charsBefore && sidebarFills==fillsBefore && sidebarSprites==spritesBefore);
        assert(!memcmp(pressed,s_pixels,sizeof(pressed)));
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
        p=publications; unsigned e=encodes;
        structure.countDown--; GUI_Widget_ActionPanel_Draw(false);
        assert(publications==p && encodes==e);
        structure.countDown-=3*256;
        unsigned bytes=publishedBytes;
        GUI_Widget_ActionPanel_Draw(false);
        assert(publications>p && publishedBytes-bytes<64*82/2);
        check_panel();
        structure.o.flags.s.onHold=true; check_panel();
        structure.o.flags.s.onHold=false; structure.countDown=0; check_panel();
        structure.o.flags.s.upgrading=true; structure.upgradeTimeLeft=57; check_panel();
        structure.o.flags.s.upgrading=false; structure.upgradeTimeLeft=0;
        structure.countDown=50*256; structure.o.hitpoints=75;
        for(unsigned i=1;i<4;i++) for(unsigned down=0;down<2;down++) check_hover(i,down);
    }
    structure.o.type=STRUCTURE_OUTPOST; check_panel();
    p=publications; house.unitCountAllied++; GUI_Widget_ActionPanel_Draw(false); assert(publications>p);
    structure.o.type=STRUCTURE_WINDTRAP; check_panel();
    p=publications; house.powerUsage+=10; GUI_Widget_ActionPanel_Draw(false); assert(publications>p);
    structure.o.type=STRUCTURE_SILO; check_panel();
    p=publications; house.credits++; GUI_Widget_ActionPanel_Draw(false); assert(publications>p);
    structure.o.type=STRUCTURE_STARPORT; check_panel();
    p=publications; house.starportLinkedID=0xffff; GUI_Widget_ActionPanel_Draw(false); assert(publications>p);
    structure.o.type=STRUCTURE_WINDTRAP; structure.o.hitpoints=100; upgradable=true;
    structure.upgradeTimeLeft=0; check_panel(); assert(structure.upgradeTimeLeft==100 && upgradedChecks);
    structure.o.flags.s.repairing=true; structure.o.hitpoints=10; check_panel();
    structure.o.flags.s.repairing=false;
    structure.o.houseID=1; g_playerHouseID=1; check_panel();
    g_playerHouseID=0; check_panel();
    g_debugGame=true; check_panel(); g_debugGame=false; structure.o.houseID=0;
    structureSelected=false; g_unitSelected=&unit; check_panel();
    unit.deviated=1; check_panel(); unit.deviated=0;
    for(unsigned language=0;language<3;language++) {
        g_config.language=language; check_panel();
    }
    /* Every command button state compares against the same legacy callbacks. */
    for(unsigned i=5;i<9;i++) for(unsigned down=0;down<2;down++) {
        check_hover(i,down);
    }
    wideCaption=true;
    check_panel();
    check_hover(6,0); check_hover(6,1);
    wideCaption=false;
    /* Templates distinguish language, prompt colour, fonts and mapping generations. */
    g_selectionType=SELECTIONTYPE_TARGET; g_activeAction=ACTION_MOVE;
    for(unsigned language=0;language<3;language++) {
        g_config.language=language; check_panel();
    }
    g_widgetProperties[6].fgColourBlink=6; check_panel();
    g_widgetProperties[6].fgColourBlink=15; check_panel();
    Font alternate=font6; alternate.height=9;
    g_fontNew6p=&alternate;
    GUI_DrawText_Wrapper(NULL,0,0,15,0,0x11);
    check_panel();
    g_fontNew6p=&font6;
    GUI_DrawText_Wrapper(NULL,0,0,15,0,0x11);
    generation++; mapping[29]^=1; check_panel();
    g_selectionType=SELECTIONTYPE_UNIT; check_panel();
    /* Even an unchanged key must republish after interface or mapping replacement. */
    GUI_Sidebar_Invalidate(); p=publications;
    GUI_Widget_ActionPanel_Draw(false); assert(publications>p);
    generation++; mapping[29]^=1; p=publications;
    unsigned beforeCopies=copies;
    widgets[5].state.hover2=true;
    GUI_Widget_Draw(&widgets[5]);
    assert(!GUI_Sidebar_Valid() && copies==beforeCopies);
    GUI_Widget_ActionPanel_Draw(false); assert(publications>p);
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
            for(unsigned row=0;row<8;row++) for(unsigned col=0;col<6;col++) {
                uint8 colour=row>=1 && row<7?colours[fontData['A'][(row-1)*6+col]]:colours[0];
                if(colour && x+col>=256 && x+col<320) put_pen(reference,x+col,y+row,mapping[colour]);
            }
        }
        GUI_Sidebar_End();
        for(unsigned y=42;y<124;y++) assert(!memcmp(display+y*80+64,reference+y*80+64,32));
    }
    /* Cached labels replay writes even when their first pixels matched the background. */
    GUI_Sidebar_Free();
    for(unsigned pass=0;pass<3;pass++) {
        uint8 background=pass==0?11:20;
        uint8 labelColours[16]={0,11,6,29,15};
        if(pass==2) labelColours[2]=29;
        direct=false; g_screenActiveID=SCREEN_1;
        GUI_DrawFilledRectangle(256,42,319,123,background);
        GUI_InitColors(labelColours,0,15);
        GUI_DrawText("AB",260,50,11,0);
        copy_rect(256,42,256,42,64,82,SCREEN_1);
        memcpy(reference,display,sizeof(display));
        direct=true; GUI_Sidebar_Begin(false);
        GUI_Sidebar_Fill(256,42,319,123,background);
        GUI_InitColors(labelColours,0,15);
        unsigned charsBefore=sidebarChars;
        GUI_DrawText("AB",260,50,11,0);
        if(pass==1) assert(sidebarChars==charsBefore);
        else assert(sidebarChars>charsBefore);
        GUI_Sidebar_End();
        assert(!memcmp(display,reference,sizeof(display)));
    }
    /* Eviction stays bounded and never substitutes a different text/style/position. */
    for(unsigned i=0;i<180;i++) {
        char text[32]; snprintf(text,sizeof(text),"Label %u",i);
        GUI_Sidebar_Begin(false);
        GUI_DrawText(text,258,51,29,0);
        GUI_Sidebar_End();
    }
    unsigned resident=0;
    for(unsigned set=0;set<SIDEBAR_FRAGMENT_SETS;set++)
        for(unsigned way=0;way<SIDEBAR_FRAGMENT_WAYS;way++) resident+=s_fragments[set][way]!=NULL;
    assert(resident<=128 && resident>0);
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
        harness = harness.replace("/* PRODUCTION */", functions)
        harness = harness.replace("/* SIDEBAR */", sidebar)
        with tempfile.TemporaryDirectory(prefix="sidebar-planar-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run(
                [*compiler, "-std=gnu17", "-DTOS", "-O2", "-Wall", "-Wextra",
                 "-Werror", "-Wno-sign-compare", "-ffunction-sections",
                 "-fdata-sections", "-I", str(ROOT / "include"),
                 "-iquote", str(ROOT / "src"), *flags, str(source),
                 "-Wl,--gc-sections", "-o", str(binary)], check=True,
            )
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
