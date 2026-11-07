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

ROOT = Path(__file__).resolve().parents[1]


class DisplayListTest(unittest.TestCase):
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
static unsigned executions, commands;
static uint16 screen[8], source = 0x5678;
uint16 endian_bswap16(uint16 v) { return (v >> 8) | (v << 8); }
void Error(const char *fmt, ...) { (void)fmt; abort(); }
void Video_Atari_ExecuteDisplayList(const uint16 *stream) {
    assert(!g_videoDisplayListActive);
    executions++;
    while (*stream != HTOBE16(0x4e75)) {
        assert(*stream++ == HTOBE16(0x4e71));
        commands++; screen[0] = source;
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
    Video_Atari_DisplayListCheck(65534);
    for (unsigned i = 0; i < 32767; i++) append();
    assert(!executions && g_videoDisplayListNext == g_videoDisplayListLimit);
    Video_Atari_DisplayListCheck(2);
    assert(executions == 1 && commands == 32767 && g_videoDisplayListNext == first);
    append();
    assert(executions == 1);
    uint16 pixels[4] = {0xabcd,1,2,3}, masks[1] = {0x00ff};
    Video_Atari_PublishPlanarSpritePlain(screen, pixels, masks, 1, 1, 1);
    assert(executions == 2 && screen[0] == 0x56cd);
    source = 0x1357; append();
    Video_Atari_DisplayListFlush(); /* eviction barrier precedes mutation */
    source = 0xffff;
    assert(screen[0] == 0x1357 && executions == 3);
    Video_Atari_DisplayListEnd();
    Video_Atari_DisplayListBegin();
    Video_Atari_DisplayListEnd();
    assert(executions == 3);
    Video_Atari_DisplayListFree();
    assert(!g_videoDisplayListNext && !g_videoDisplayListLimit);
    return 0;
}
"""
        cpu = "\n".join(function(video, name) for name in (
            "Video_Atari_PlanarMergePlain", "Video_Atari_PlanarCopyGroup",
            "Video_Atari_PublishPlanarSpritePlain"))
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
static unsigned executions;
static const uint16 *queued;
static uint16 displayed;
uint16 endian_bswap16(uint16 v) { return (v >> 8) | (v << 8); }
void Error(const char *fmt, ...) { (void)fmt; abort(); }
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
        terrain = "\n".join(function(gfx, name) for name in (
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
        self.assertLess(draw.index("Video_Atari_DisplayListEnd"),
                        draw.index("Video_Atari_TileCursorFrame"))
        self.assertIn("s_tileCursorShown && !Video_Atari_ViewportBlitter()", draw)
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
            "Video_Atari_DisplayMoveLong", "Video_Atari_DisplayGeometry",
            "Video_Atari_DisplayPattern", "Video_Atari_DisplayPlane",
            "Video_Atari_QueueMaskedBlit", "Video_Atari_BuildSpriteBlitPlan",
            "Video_Atari_BuildSpriteBlitGeometry",
            "Video_Atari_CompileSpriteBlit", "Video_Atari_CompileSpriteBlitCode",
            "Video_Atari_SetHalftonePattern", "Video_Atari_BlitterStart",
            "Video_Atari_QueueTintBlit", "Video_Atari_PlacementTintBlit"))
        macros = video[video.index("#define BLITTER_SRC_XINC"):video.index("#define BLITTER_SKEW")]
        macros += video[video.index("#define BLITTER_SKEW"):video.index("\n", video.index("#define BLITTER_SKEW"))]
        source = r"""
#include <assert.h>
#include <stddef.h>
#include "types.h"
#include "src/video/video.h"
#include "src/os/endian.h"
#define ST_PLANAR_LINE_BYTES 160
bool g_videoDisplayListActive, g_videoBlitterTileSetup;
uint16 *g_videoDisplayListNext, *g_videoDisplayListLimit;
#define s_blitterTileSetup g_videoBlitterTileSetup
static const uint16 *s_blitterHalftonePattern;
extern void Video_Atari_BlitPlaneCode(void);
typedef struct PlacementTint {
    uint8 *dst; const uint16 *pattern; uint16 words,height,pen;
} PlacementTint;
static PlacementTint s_placeTint;
/* MACROS */
/* BLOCK */
/* FUNCTIONS */
void TestPlan(Video_Atari_SpriteBlitPlan *out, uint16 sx, uint16 width, uint16 phase) {
    Video_Atari_BuildSpriteBlitPlan(out,32,sx,width,phase);
}
void TestMasked(const uint16 *pixels, const uint16 *masks, uint16 *dst,
    const Video_Atari_SpriteBlitPlan *plan, const Video_Atari_SpriteBlitCode *code,
    uint16 effect, bool protected, uint16 line, const uint16 *pattern) {
    s_planarBlit.pixels=pixels; s_planarBlit.masks=masks; s_planarBlit.dst=dst;
    s_planarBlit.plan=plan; s_planarBlit.code=code; s_planarBlit.height=4;
    s_planarBlit.writable=pattern; s_planarBlit.firstLine=line;
    s_spriteHighlight=effect ? s_highlightRecipes[effect-1] : NULL;
    Video_Atari_QueueMaskedBlit(protected);
}
void TestTint(uint16 *dst, const uint16 *pattern) {
    s_placeTint.dst=(uint8 *)dst; s_placeTint.pattern=pattern;
    s_placeTint.words=2; s_placeTint.height=4;
    Video_Atari_PlacementTintBlit();
}
"""
        source = source.replace("/* MACROS */", macros).replace("/* BLOCK */", block)
        source = source.replace("/* FUNCTIONS */", production)
        with tempfile.TemporaryDirectory(prefix="flat-display-list-") as directory:
            directory = Path(directory)
            cfile, cobj = directory / "test.c", directory / "test.o"
            cfile.write_text(source)
            subprocess.run([tools[0], "-std=gnu17", "-m68000", "-msoft-float", "-O2", "-DNDEBUG", "-DTOS",
                            "-fomit-frame-pointer", "-I" + str(ROOT), "-I" + str(ROOT / "include"),
                            "-c", str(cfile), "-o", str(cobj)], check=True)
            objects = [cobj]
            for name in ("atari_display_list_runner", "atari_sprite_blit"):
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
                       re.finditer(r"^([0-9a-f]+) [A-Za-z] (_\S+)$", table, re.M)}
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

            def mmio(cpu, access, address, size, value, data):
                nonlocal pending
                if address == 0xffff8a3c and value & 0xf0 == 0xc0:
                    pending = True

            def complete():
                nonlocal pending, latch
                pending = False
                b = 0xffff8a00
                sx, sy, dx, dy = (struct.unpack(">h", cpu.mem_read(b + off, 2))[0]
                                  for off in (0x20, 0x22, 0x2e, 0x30))
                src, dst = read(b + 0x24, 4), read(b + 0x32, 4)
                words, rows = read(b + 0x36, 2), read(b + 0x38, 2)
                skew, hop, op, line = (read(b + off, 1) for off in (0x3d, 0x3a, 0x3b, 0x3c))
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
                        result = shifted if op == 3 else old & ~shifted if op == 4 else old | shifted
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
            background = bytes((i * 113 + 17) & 255 for i in range(160 * 16))
            pixels = b"".join(struct.pack(">H",
                (i * 137 + 0x369c) & ((i // 4 * 971 + 0xa39f) & 0xffff)) for i in range(32))
            masks = b"".join(struct.pack(">H", (i // 4 * 971 + 0xa39f) & 0xffff) for i in range(32))
            tile = bytes((i * 71 + 3) & 255 for i in range(128))
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
                        call("_Video_Atari_BlitSpriteCode", inputs=inputs)
                        self.assertEqual(read(symbols["_g_videoDisplayListNext"], 4), 0x70012 + 76)
                        for name in ("A0","A1","A2","A4","D0","D1"):
                            self.assertEqual(cpu.reg_read(reg(name)), inputs[name])
                        call("_Video_Atari_BuildSpriteBlitGeometry", (0x31000,32,sx,width))
                        geometry = 0x31000 + phase * 50
                        cached = bytes(cpu.mem_read(geometry,50))
                        before = read(symbols["_g_videoDisplayListNext"],4)
                        cached_inputs = dict(inputs, A3=geometry)
                        call("_Video_Atari_BlitSpriteGeometry", inputs=cached_inputs)
                        self.assertEqual(read(symbols["_g_videoDisplayListNext"],4)-before,40)
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
                                         48+(96 if protected else 0)+launches*30)
                        reference(effect,protected)
                        before = read(symbols["_g_videoDisplayListNext"],4)
                        call("_TestTint", (0x40282,0x30020))
                        self.assertEqual(read(symbols["_g_videoDisplayListNext"],4)-before,174)
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
                        call("_Video_Atari_RunDisplayList",(0x70000,),saved)
                        self.assertEqual(bytes(cpu.mem_read(0x40000,len(expected))),bytes(expected),
                                         (phase,sx,effect,protected))
                        self.assertEqual(bytes(cpu.mem_read(geometry,50)),cached)
                        for name,value in saved.items():
                            self.assertEqual(cpu.reg_read(reg(name)),value,name)
            write(symbols["_g_videoDisplayListNext"],0x70000,4)
            write(symbols["_g_videoDisplayListActive"],1,1)
            call("_TestPlan",(0x30000,0,16,0))
            for cell in range(16):
                call("_Video_Atari_QueueTile",(0x52000,0x40000))
                call("_TestMasked",(0x50000,0x60000,0x40000,0x30000,0x20000,0,1,0,0x30020))
            self.assertEqual(read(symbols["_g_videoDisplayListNext"],4)-0x70000,16*(384+18))


if __name__ == "__main__":
    unittest.main()
