"""Check conditional composite cropping and the 48x48 cache reservation."""

from pathlib import Path
import struct
import unittest

from tools.test_unit_smoke_damage import run_harness
from tools.test_viewport_sprite_cache import function

ROOT = Path(__file__).resolve().parents[1]


class ViewportCompositeCapacityTest(unittest.TestCase):
    def test_standard_asset_unit_layouts_fit(self):
        from tools.analyze_harvester_planes import decode_sprite, load_sprites, read_pak

        pak = ROOT / "DUNE.PAK"
        if not pak.exists():
            self.skipTest("Standard DUNE.PAK required for actual-asset coverage")
        files = read_pak(pak)
        sprites = load_sprites(files)
        data = files["UNITS2.SHP"]
        count = struct.unpack_from("<H", data)[0]
        modern = struct.unpack_from("<I", data, 2)[0] == 4 + count * 4
        for i in range(count):
            offset = struct.unpack_from("<I" if modern else "<H", data,
                                        2 + i * (4 if modern else 2))[0]
            if offset:
                sprites[111 + i] = decode_sprite(data[offset + (2 if modern else 0):])
        setup = []
        for sprite_id, sprite in sprites.items():
            self.assertLessEqual(sprite.width, 32)
            self.assertLessEqual(sprite.height, 32)
            opaque = [(i % sprite.width, i // sprite.width)
                      for i, pixel in enumerate(sprite.pixels) if pixel is not None]
            bounds = (min(x for x, y in opaque), min(y for x, y in opaque),
                      max(x for x, y in opaque) + 1, max(y for x, y in opaque) + 1) if opaque else (0, 0, 0, 0)
            setup.append(f"init({sprite_id},{sprite.width},{sprite.height},"
                         f"(GUI_SpriteBounds){{{','.join(map(str, bounds))}}});")
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        tile = (ROOT / "src/tile.c").read_text()
        production = "\n".join(function(source, name) for source, name in (
            (tile, "Orientation_Orientation256ToOrientation8"),
            (viewport, "GUI_Widget_Viewport_AddSpriteLayer"),
            (viewport, "GUI_Widget_Viewport_GroundSprites")))
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
#include "src/map.h"
#include "src/house.h"
#include "src/gui/gui.h"
#include "src/table/unitinfo.c"
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
static uint8 headers[355][10],*sprites[355];
uint8 **g_sprites=sprites;
GUI_SpriteBounds g_viewportSpriteBounds[355][4];
Unit *g_unitSelected;
uint8 Unit_GetHouseID(Unit *u) {(void)u;return 0;}
uint16 Map_GetLandscapeType(uint16 packed) {(void)packed;return LST_SPICE;}
static int GUI_Widget_Viewport_HousePaletteFlags(uint16 id,uint8 house,uint8 *palette) {
    (void)id;(void)house;(void)palette;return 0;
}
/* PRODUCTION */
static void init(unsigned id,unsigned w,unsigned h,GUI_SpriteBounds b) {
    sprites[id]=headers[id];headers[id][2]=h;headers[id][3]=w;
    for(unsigned flags=0;flags<4;flags++) {
        GUI_SpriteBounds c=b;
        if(flags&1) {c.left=w-b.right;c.right=w-b.left;}
        if(flags&2) {c.top=h-b.bottom;c.bottom=h-b.top;}
        g_viewportSpriteBounds[id][flags]=c;
    }
}
int main(void) {
    /* SETUP */
    for(unsigned type=0;type<UNIT_MAX;type++)
    for(int frame=-3;frame<8;frame++)
    for(unsigned bodyHeading=0;bodyHeading<8;bodyHeading++)
    for(unsigned turretHeading=0;turretHeading<8;turretHeading++) {
        Unit u;memset(&u,0,sizeof(u));
        u.o.type=type;u.spriteOffset=frame;u.actionID=ACTION_HARVEST;
        u.orientation[0].current=bodyHeading*32;
        u.orientation[1].current=turretHeading*32;
        u.o.flags.s.isSmoking=true;g_unitSelected=&u;
        GUI_SpriteLayers layers;int flags;
        uint16 id=GUI_Widget_Viewport_GroundSprites(&u,&flags,&layers,UNIT_SPRITE_ALL);
        assert(id<355 && sprites[id]);
        int w=headers[id][3],h=headers[id][2],minX=0,minY=0,maxX=w,maxY=h;
        int l=1000,t=1000,r=-1000,b=-1000;
        for(unsigned n=0;n<=layers.count;n++) {
            unsigned sid=n?layers.layer[n-1].spriteID:id;
            assert(sid<355 && sprites[sid]);
            int sw=headers[sid][3],sh=headers[sid][2];
            int x=n?w/2+layers.layer[n-1].offsetX-sw/2:0;
            int y=n?h/2+layers.layer[n-1].offsetY-sh/2:0;
            minX=min(minX,x);minY=min(minY,y);maxX=max(maxX,x+sw);maxY=max(maxY,y+sh);
            GUI_SpriteBounds c=*GUI_ViewportSpriteBounds(sid,n?layers.layer[n-1].flags:flags);
            if(c.left==c.right || c.top==c.bottom) continue;
            l=min(l,x+c.left);t=min(t,y+c.top);r=max(r,x+c.right);b=max(b,y+c.bottom);
        }
        if(l>=r || t>=b) continue;
        for(unsigned blitter=0;blitter<2;blitter++)
        for(unsigned phase=0;phase<16;phase++) {
            int x=minX,y=minY,right=maxX,bottom=maxY;
            if(!blitter)x-=((unsigned)(phase+x)&15);
            if(((right-x+15)&~15)>48 || bottom-y>48) {
                x=l;y=t;right=r;bottom=b;
                if(!blitter)x-=((unsigned)(phase+x)&15);
            }
            assert(((right-x+15)&~15)<=48 && bottom-y<=48);
        }
    }
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production).replace("/* SETUP */", "\n".join(setup)))

    def test_clipped_composition(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
/* PRODUCTION */
int main(void) {
    uint16 src[256], masks[64], pixels[578], opacity[146];
    uint16 expected[578], expectedMasks[146];
    for (unsigned i=0;i<64;i++) {
        masks[i]=(i*971+0xa39f)&0xffff;
        for(unsigned p=0;p<4;p++) src[i*4+p]=(i*137+p*977)&masks[i];
    }
    for(int y=-33;y<=49;y+=7)
    for(int x=-40;x<=49;x++)
    for(unsigned width=16;width<=48;width+=16) {
        for(unsigned i=0;i<578;i++) pixels[i]=expected[i]=i*113+17;
        for(unsigned i=0;i<146;i++) opacity[i]=expectedMasks[i]=i*71+3;
        for(unsigned sy=0;sy<32;sy++) for(unsigned sx=0;sx<32;sx++) {
            int dx=x+sx, dy=y+sy;
            unsigned si=sy*2+sx/16;
            uint16 sb=0x8000u>>(sx&15);
            if(dx<0 || dx>=(int)width || dy<0 || dy>=48 || !(masks[si]&sb)) continue;
            unsigned di=dy*(width/16)+dx/16;
            uint16 db=0x8000u>>(dx&15);
            expectedMasks[1+di]|=db;
            for(unsigned p=0;p<4;p++)
                expected[1+di*4+p]=(expected[1+di*4+p]&~db)|(src[si*4+p]&sb?db:0);
        }
        Video_Atari_ComposePlanarSpriteClipped(pixels+1,opacity+1,width,48,src,masks,32,32,x,y);
        assert(!memcmp(pixels,expected,sizeof(pixels)));
        assert(!memcmp(opacity,expectedMasks,sizeof(opacity)));
    }
    return 0;
}
"""
        production = "\n".join(function(video, name) for name in (
            "Video_Atari_PlanarMergePlain", "Video_Atari_ComposePlanarSpriteClipped"))
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_cache_crops_only_oversized_canvases(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        cache = gui[gui.index("enum { VIEWPORT_PLANAR_SPRITES"):
                    gui.index("\nvoid GUI_FreeViewportSpriteCache")]
        harness = r"""
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include "types.h"
#include "src/gui/gui.h"
#include "src/gui/widget.h"
#include "src/gui/viewport_key.h"
#include "src/video/video.h"
#include "src/os/endian.h"
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define lengthof(a) (sizeof(a)/sizeof((a)[0]))
#define DIRTY_SRC_SPRITE 1
#define HOUSE_MAX 6
typedef struct ViewportSpriteMask {
    const uint8 *sprite; uint16 *rows; uint16 width,height;
} ViewportSpriteMask;
/* CACHE */
static bool s_viewportPlanar=true;
bool g_videoViewportBlitter, g_videoDisplayListActive;
static uint8 headers[355][10], *sprites[355];
uint8 *g_paletteMapping2;
uint8 **g_sprites=sprites;
WidgetProperties g_widgetProperties[22];
GUI_SpriteBounds g_viewportSpriteBounds[355][4];
static ViewportSpriteMask spriteMasks[355];
static ViewportPlanarComponent components[355];
static unsigned compositions, clippedCompositions;
static int capturedX, capturedY;
static const ViewportPlanarImage *captured;
static uint16 g_blinkEffect;
#define Error(...) abort()
static ViewportSpriteMask *GUI_ViewportSpriteMaskSlot(uint16 id) { return &spriteMasks[id]; }
static ViewportPlanarComponent *GUI_ViewportPlanarComponent(ViewportSpriteMask *mask,
    uint16 id,uint8 house,int flags,const uint8 *palette) {
    (void)mask;(void)house;(void)flags;(void)palette;return &components[id];
}
static const ViewportPlanarImage *GUI_ViewportResidentSprite(uint16 id,int flags) {
    (void)id;(void)flags;return NULL;
}
static ViewportPlanarSprite *GUI_ViewportFindPlanarSprite(uint32 main,
    const uint32 *tail,uint16 *position) {
    (void)tail;*position=0;
    for(unsigned i=0;i<64;i++) if(s_viewportPlanarSprites[i].key.main==main)
        return &s_viewportPlanarSprites[i];
    return NULL;
}
static void GUI_ViewportIndexPlanarSprite(ViewportPlanarSprite *entry,uint16 position) {
    (void)entry;(void)position;
}
bool GUI_Widget_Viewport_ShouldDrawSprite(int16 l,int16 t,int16 r,int16 b) {
    (void)l;(void)t;(void)r;(void)b;return true;
}
void Video_Atari_DisplayListFlush(void) {}
void Video_Atari_BuildSpriteBlitGeometry(Video_Atari_SpriteBlitGeometry geometry[16],
    uint16 stride,uint16 sourceX,uint16 width) {
    (void)geometry;assert(stride<=48 && sourceX+width<=stride);
}
void Video_Atari_CompileSpriteBlitCode(Video_Atari_SpriteBlitCode *code,uint8 passes) {
    code->passes=passes;
}
static void GUI_ViewportPresentPlanarSprite(const ViewportPlanarImage *image,
    int16 x,int16 y,bool blitter,uint16 highlight) {
    (void)blitter;(void)highlight;captured=image;capturedX=x;capturedY=y;
}
/* PRODUCTION */
static void init(unsigned id,unsigned w,unsigned h,GUI_SpriteBounds bounds) {
    sprites[id]=headers[id];headers[id][2]=h;headers[id][3]=w;
    spriteMasks[id]=(ViewportSpriteMask){headers[id],NULL,w,h};
    components[id].width=(w+15)&~15;components[id].height=h;
    for(unsigned f=0;f<4;f++) g_viewportSpriteBounds[id][f]=bounds;
    for(unsigned y=bounds.top;y<(unsigned)bounds.bottom;y++)
    for(unsigned x=bounds.left;x<(unsigned)bounds.right;x++) {
        if((x+y)%5==0) continue;
        unsigned i=y*(components[id].width/16)+x/16;
        uint16 bit=0x8000u>>(x&15);
        components[id].masks[i]|=bit;
        for(unsigned p=0;p<4;p++) if((x+y)&(1u<<p)) components[id].pixels[i*4+p]|=bit;
    }
}
static void draw(unsigned id,GUI_SpriteLayers *layers,int x,int y) {
    GUI_ViewportPlanarSprite(sprites[id],id,GUI_SPRITE_COLOUR_EMBEDDED,x,y,
        DRAWSPRITE_FLAG_CENTER,NULL,layers,NULL);
}
static void check(unsigned id,GUI_SpriteLayers *layers,int x,int y) {
    uint16 expected[64*64*4]={0},actual[64*64*4]={0};
    uint16 masks[64*64]={0},actualMasks[64*64]={0};
    draw(id,layers,x,y);
    assert(captured->width<=48 && captured->height<=48);
    for(unsigned n=0;n<=layers->count;n++) {
        unsigned sid=n?layers->layer[n-1].spriteID:id;
        int left=x+(n?layers->layer[n-1].offsetX:0)-spriteMasks[sid].width/2;
        int top=y+(n?layers->layer[n-1].offsetY:0)-spriteMasks[sid].height/2;
        for(unsigned sy=0;sy<spriteMasks[sid].height;sy++)
        for(unsigned sx=0;sx<spriteMasks[sid].width;sx++) {
            unsigned si=sy*(components[sid].width/16)+sx/16;
            uint16 sb=0x8000u>>(sx&15);
            if(!(components[sid].masks[si]&sb)) continue;
            unsigned di=(top+sy)*64+left+sx;
            masks[di]=1;
            for(unsigned p=0;p<4;p++) expected[di*4+p]=(components[sid].pixels[si*4+p]&sb)!=0;
        }
    }
    for(unsigned sy=0;sy<captured->height;sy++)
    for(unsigned sx=0;sx<captured->width;sx++) {
        unsigned si=sy*(captured->width/16)+sx/16;
        uint16 sb=0x8000u>>(sx&15);
        if(!(captured->masks[si*(g_videoViewportBlitter?4:1)]&sb)) continue;
        unsigned di=(capturedY+sy)*64+capturedX+sx;
        actualMasks[di]=1;
        for(unsigned p=0;p<4;p++) actual[di*4+p]=(captured->pixels[si*4+p]&sb)!=0;
    }
    assert(!memcmp(expected,actual,sizeof(expected)));
    assert(!memcmp(masks,actualMasks,sizeof(masks)));
    unsigned before=compositions+clippedCompositions;
    draw(id,layers,x,y);
    assert(compositions+clippedCompositions==before);
}
int main(void) {
    (void)s_viewportPlanarKeys;(void)s_viewportPlanarLastHitPosition;
    (void)s_viewportPlanarMasks;(void)s_viewportComponentClock;
    (void)s_viewportResidentSprites;(void)s_viewportResidentStorage;(void)s_viewportResidentsReady;
    assert(sizeof(((ViewportPlanarSprite *)0)->pixels)==1152);
    assert(VIEWPORT_PLANAR_MASK_WORDS==144);
    assert(VIDEO_ATARI_DISPLAY_SPRITE_BYTES==6432);
    s_viewportPlanarSprites=calloc(64,sizeof(*s_viewportPlanarSprites));
    s_viewportPlanarComponents=calloc(64,sizeof(*s_viewportPlanarComponents));
    init(250,24,24,(GUI_SpriteBounds){2,4,23,22});
    init(229,16,16,(GUI_SpriteBounds){3,1,13,14});
    init(111,32,32,(GUI_SpriteBounds){12,12,20,20});
    init(112,32,32,(GUI_SpriteBounds){12,12,20,20});
    for(unsigned mode=0;mode<2;mode++) {
        g_videoViewportBlitter=mode;
        for(unsigned i=0;i<64;i++)
            s_viewportPlanarSprites[i].masks=calloc(144*(mode?4:1),sizeof(uint16));
        for(unsigned phase=0;phase<16;phase++) {
            GUI_SpriteLayers layers={1,{{229,GUI_SPRITE_COLOUR_EMBEDDED,14,1,0,{0}}}};
            memset(s_viewportPlanarSprites[0].pixels,0,sizeof(s_viewportPlanarSprites[0].pixels));
            for(unsigned i=0;i<64;i++) s_viewportPlanarSprites[i].key.main=0;
            unsigned old=clippedCompositions;
            check(250,&layers,24+phase,45);
            assert(clippedCompositions-old==(!mode && ((12+phase)&15)==15?2:0));
            for(unsigned i=0;i<64;i++) s_viewportPlanarSprites[i].key.main=0;
            layers.layer[0]=(GUI_SpriteLayer){112,GUI_SPRITE_COLOUR_EMBEDDED,0,-31,0,{0}};
            old=clippedCompositions;
            check(111,&layers,32,38);
            assert(clippedCompositions==old+2);
        }
        for(unsigned i=0;i<64;i++) {free(s_viewportPlanarSprites[i].masks);s_viewportPlanarSprites[i].key.main=0;}
    }
    free(s_viewportPlanarSprites);free(s_viewportPlanarComponents);
    return 0;
}
"""
        composer = function(video, "Video_Atari_ComposePlanarSprite").replace(
            "\n{\n", "\n{\n    compositions++;\n", 1)
        clipped = function(video, "Video_Atari_ComposePlanarSpriteClipped").replace(
            "\n{\n", "\n{\n    clippedCompositions++;\n", 1)
        production = "\n".join((
            function(video, "Video_Atari_PlanarMergePlain"), composer, clipped,
            function(video, "Video_Atari_BuildSpriteBlitRecipe"),
            function(gui, "GUI_ViewportSetPlanarImage"),
            function(gui, "GUI_ViewportBuildCompositeKey"),
            function(gui, "GUI_ViewportBuildCompositeKeyBlitter"),
            function(gui, "GUI_ViewportBuildCompositeKeyCPU"),
            function(gui, "GUI_ViewportPlanarSprite"),
        ))
        run_harness(harness.replace("/* CACHE */", cache).replace("/* PRODUCTION */", production))
