"""Execute compiled sprite recipes and their register ABI on a 68000 CPU."""

import ctypes
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import blit_plan_type, function


ROOT = Path(__file__).resolve().parents[1]


class SpriteBlitCodeTest(unittest.TestCase):
    def test_layerless_component_copy(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        cache = function(gui, "GUI_ViewportPlanarSprite")
        start = cache.index("if (count == 0 && blitter) {") + len("if (count == 0 && blitter) {")
        fast_path = cache[start:cache.index("\n\t\t\t} else {", start)]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int16_t int16;
#define VARIABLE_NOT_USED(v) ((void)(v))
static uint16 big_endian(uint16 value) {
    uint8 bytes[] = {value >> 8, value};
    uint16 result;
    memcpy(&result, bytes, 2);
    return result;
}
#define HTOBE16(v) big_endian(v)
static bool s_blitterDestinationWord;
/* PRODUCTION */
typedef struct {
    uint16 pixels[256], masks[64], width, height;
    uint8 blitPasses;
} Component;
typedef struct {
    uint16 pixels[1280], masks[320];
    Video_Atari_SpriteBlitCode blitCode;
} Entry;
static void copy_component(Entry *entry, Component *component,
                            uint16 stride, uint16 height, uint16 groups) {
    /* FAST PATH */
}
int main(void) {
    Component component;
    Entry entry;
    uint16 pixels[1280], masks[320];
    for (unsigned stride = 16; stride <= 32; stride += 16)
    for (unsigned height = 1; height <= 32; height++) {
        unsigned groups = stride / 16, count = groups * height;
        component.width = stride; component.height = height;
        for (unsigned i = 0; i < count; i++) {
            component.masks[i] = (i & 3) == 0 ? 0 : 0xa39f ^ (i * 131);
            for (unsigned p = 0; p < 4; p++)
                component.pixels[i * 4 + p] = (i * 137 + p * 91) & component.masks[i];
        }
        component.blitPasses = Video_Atari_BuildSpriteBlitRecipe(
            component.pixels, component.masks, count);
        memset(&entry, 0x5a, sizeof(entry));
        copy_component(&entry, &component, stride, height, groups);
        memset(pixels, 0, sizeof(pixels)); memset(masks, 0, sizeof(masks));
        Video_Atari_ComposePlanarSprite(pixels, masks, stride, height,
            component.pixels, component.masks, stride, height, 0, 0);
        assert(!memcmp(entry.pixels, pixels, count * 8));
        assert(!memcmp(entry.masks, masks, count * 2));
        Video_Atari_SpriteBlitCode reference;
        memset(&reference, 0x5a, sizeof(reference));
        Video_Atari_CompileSpriteBlitCode(&reference, component.blitPasses);
        assert(!memcmp(&reference, &entry.blitCode, sizeof(reference)));
        memset(&component, 0, sizeof(component));
        assert(!memcmp(entry.pixels, pixels, count * 8));
        assert(!memcmp(entry.masks, masks, count * 2));
    }
    return 0;
}
"""
        production = blit_plan_type() + "\n" + "\n".join(function(video, name) for name in (
            "Video_Atari_BuildSpriteBlitRecipe", "Video_Atari_CompileSpriteBlit",
            "Video_Atari_CompileSpriteBlitCode",
            "Video_Atari_PlanarMergePlain", "Video_Atari_ComposePlanarSprite"))
        with tempfile.TemporaryDirectory(prefix="sprite-layerless-copy-") as directory:
            source, binary = Path(directory) / "check.c", Path(directory) / "check"
            source.write_text(harness.replace("/* PRODUCTION */", production)
                              .replace("/* FAST PATH */", fast_path))
            subprocess.run(["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_native_recipes_and_register_abi(self):
        try:
            import unicorn
            from unicorn import m68k_const as registers
        except ImportError:
            self.skipTest("CPU-only execution requires the optional unicorn package")
        tools = ("cc", "vasmm68k_mot", "m68k-atari-mint-objcopy", "m68k-atari-mint-objdump")
        if any(shutil.which(tool) is None for tool in tools):
            self.skipTest("Host compiler and Atari assembler/object tools required")
        video = (ROOT / "src/video/video_atari.c").read_text()
        tables = video[video.index("static const uint16 s_blitterLeftMasks[16]"):
                       video.index("static PlanarBlit s_planarBlit;")]
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
static uint16 big_endian(uint16 value) {
    uint8 bytes[] = {value >> 8, value};
    uint16 result;
    memcpy(&result, bytes, 2);
    return result;
}
#define HTOBE16(v) big_endian(v)
static bool s_blitterDestinationWord;
/* PRODUCTION */
void make_plan(Video_Atari_SpriteBlitPlan *out, uint16 stride, uint16 sourceX,
               uint16 width, uint16 phase) {
    Video_Atari_BuildSpriteBlitPlan(out, stride, sourceX, width, phase);
}
void make_masked(Video_Atari_SpriteBlitCode *out, uint8 passes, uint16 line) {
    Video_Atari_CompileSpriteBlit(out, passes, 3, line);
}
"""
        production = (blit_plan_type() + tables +
                      function(video, "Video_Atari_BuildSpriteBlitPlan") + "\n" +
                      function(video, "Video_Atari_CompileSpriteBlit") + "\n" +
                      function(video, "Video_Atari_CompileSpriteBlitCode"))
        with tempfile.TemporaryDirectory(prefix="sprite-blit-code-") as directory:
            directory = Path(directory)
            source, library = directory / "code.c", directory / "code.so"
            source.write_text(harness.replace("/* PRODUCTION */", production))
            subprocess.run([tools[0], "-std=c99", "-shared", "-fPIC", "-O2",
                            "-Wall", "-Wextra", "-Werror", str(source), "-o", str(library)],
                           check=True)
            lib = ctypes.CDLL(str(library))

            class Plan(ctypes.Structure):
                _fields_ = [(name, ctypes.c_int16) for name in ("sx", "sy")] + [
                    (name, ctypes.c_uint16) for name in ("first", "middle", "last")] + [
                    (name, ctypes.c_int16) for name in ("dx", "dy")] + [
                    ("words", ctypes.c_uint16),
                    ("skew", ctypes.c_uint8)]

            lib.make_plan.argtypes = [ctypes.POINTER(Plan)] + [ctypes.c_uint16] * 4
            lib.Video_Atari_CompileSpriteBlitCode.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
            lib.make_masked.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint16]
            code_words = 8 * 17 + 2 * 3 + 1
            compiled = []
            for passes in range(256):
                storage = (ctypes.c_uint16 * (code_words + 2))()
                storage[code_words + 1] = 0xdead
                lib.Video_Atari_CompileSpriteBlitCode(storage, passes)
                self.assertEqual(ctypes.string_at(storage, code_words * 2 + 1)[-1], passes)
                self.assertEqual(storage[code_words + 1], 0xdead)
                compiled.append(ctypes.string_at(storage, code_words * 2))
            obj, binary = directory / "setup.o", directory / "setup.bin"
            subprocess.run([tools[1], "-m68000", "-Faout", "-quiet", "-o", str(obj),
                            str(ROOT / "src/video/atari_sprite_blit.s")], check=True)
            subprocess.run([tools[2], "-O", "binary", "-j", ".text", str(obj), str(binary)],
                           check=True)
            assembly = subprocess.check_output([tools[3], "-d", str(obj)], text=True)
            self.assertNotRegex(assembly, r"%sp|%fp|\b(?:link|movem)")
            self.assertIn("jmp %a4@", assembly)
            self.assertEqual(len(re.findall(r"\bmovel\b", assembly)), 3)
            self.assertEqual(len(re.findall(r"\bmovew\b", assembly)), 2)
            self.assertEqual(len(re.findall(r"\bmoveb\b", assembly)), 1)

            cpu = unicorn.Uc(unicorn.UC_ARCH_M68K, unicorn.UC_MODE_BIG_ENDIAN)
            cpu.ctl_set_cpu_model(registers.UC_CPU_M68K_M68000)
            cpu.mem_map(0, 0x100000)
            cpu.mem_map(0xffff8000, 0x1000)
            cpu.mem_write(0x10000, binary.read_bytes())
            latch = 0xa39fbc71
            pending = False
            launches = 0

            def read(address, size):
                return int.from_bytes(cpu.mem_read(address, size), "big")

            def write(address, value, size):
                cpu.mem_write(address, (value & ((1 << (size * 8)) - 1)).to_bytes(size, "big"))

            def mmio(cpu, access, address, size, value, data):
                nonlocal pending
                if address == 0xffff8a3c and value & 0xf0 == 0xc0:
                    pending = True

            def instruction(cpu, address, size, data):
                nonlocal pending, launches, latch
                if pending:
                    complete_blit()
                # Model the MMIO busy-bit probe and Z flag; Unicorn's 68000
                # implementation aborts on this memory-BTST instruction.
                if read(address, 2) == 0x0838:
                    self.assertEqual(read(address + 2, 2), 7)
                    self.assertEqual(read(address + 4, 2), 0x8a3c)
                    sr = cpu.reg_read(registers.UC_M68K_REG_SR)
                    sr = sr & ~4 if read(0xffff8a3c, 1) & 0x80 else sr | 4
                    sp = cpu.reg_read(registers.UC_M68K_REG_A7)
                    cpu.reg_write(registers.UC_M68K_REG_SR, sr)
                    cpu.reg_write(registers.UC_M68K_REG_A7, sp)
                    cpu.reg_write(registers.UC_M68K_REG_PC, address + 6)

            def complete_blit():
                nonlocal pending, launches, latch
                pending = False
                launches += 1
                base = 0xffff8a00
                sx, sy, dx, dy = (struct.unpack(">h", cpu.mem_read(base + off, 2))[0]
                                  for off in (0x20, 0x22, 0x2e, 0x30))
                src, dst = read(base + 0x24, 4), read(base + 0x32, 4)
                words, rows = read(base + 0x36, 2), read(base + 0x38, 2)
                skew, op = read(base + 0x3d, 1), read(base + 0x3b, 1)
                self.assertEqual(read(base + 0x3a, 1), 3 if protected else 2)
                self.assertEqual(read(base + 0x3c, 1) & 15, first_line if protected else 0)
                self.assertIn(op, (4, 7))
                for row in range(rows):
                    if skew & 0x80:
                        value = read(src, 2)
                        latch = ((latch >> 16) | (value << 16)) if sx < 0 else \
                            ((latch << 16) | value) & 0xffffffff
                        src += sx
                    for word in range(words):
                        suppress = bool(skew & 0x40) and word + 1 == words
                        old = read(dst, 2)
                        value = old if suppress else read(src, 2)
                        latch = ((latch >> 16) | (value << 16)) if sx < 0 else \
                            ((latch << 16) | value) & 0xffffffff
                        shifted = (latch >> (skew & 15)) & 0xffff
                        if protected:
                            shifted &= writable[(first_line + row) & 15]
                        result = old & ~shifted if op == 4 else old | shifted
                        mask = read(base + (0x28 if word == 0 else
                                           0x2c if word + 1 == words else 0x2a), 2)
                        write(dst, (old & ~mask) | (result & mask), 2)
                        if suppress:
                            value = read(dst, 2)
                            latch = ((latch >> 16) | (value << 16)) if sx < 0 else \
                                ((latch << 16) | value) & 0xffffffff
                        else:
                            src += sy if word + 1 == words or \
                                (skew & 0x40 and word + 2 == words) else sx
                        dst += dy if word + 1 == words else dx
                write(base + 0x24, src, 4)
                write(base + 0x32, dst, 4)
                write(base + 0x38, 0, 2)
                write(base + 0x3c, 0, 1)

            cpu.hook_add(unicorn.UC_HOOK_MEM_WRITE, mmio, begin=0xffff8a00, end=0xffff8a3f)
            cpu.hook_add(unicorn.UC_HOOK_CODE, instruction)
            background = bytes((i * 113 + 17) & 255 for i in range(160 * 4))
            for pattern in range(81):
                protected = (pattern & 1) != 0
                first_line = (pattern >> 1) & 15
                writable = [((line * 977) ^ 0xa39f) & 0xffff for line in range(16)]
                for line, word in enumerate(writable):
                    write(0xffff8a00 + line * 2, word, 2)
                states, value, passes = [], pattern, 0
                for plane in range(4):
                    state = value % 3
                    value //= 3
                    states.append(state)
                    if state != 1:
                        passes |= 1 << plane
                    if state != 0:
                        passes |= 0x10 << plane
                pixels, masks = bytearray(16 * 4), bytearray(16 * 4)
                for y in range(4):
                    for x in range(32):
                        if (x + y) % 5 == 0:
                            continue
                        bit = 0x8000 >> (x & 15)
                        offset = y * 16 + x // 16 * 8
                        for plane in range(4):
                            struct.pack_into(">H", masks, offset + plane * 2,
                                             struct.unpack_from(">H", masks, offset + plane * 2)[0] | bit)
                            if states[plane] == 1 or (states[plane] == 2 and (x + y) & 1):
                                struct.pack_into(">H", pixels, offset + plane * 2,
                                                 struct.unpack_from(">H", pixels, offset + plane * 2)[0] | bit)
                cpu.mem_write(0x50000, bytes(pixels))
                cpu.mem_write(0x60000, bytes(masks))
                if protected:
                    storage = (ctypes.c_uint16 * (code_words + 1))()
                    lib.make_masked(storage, passes, first_line)
                    cpu.mem_write(0x20000, ctypes.string_at(storage, code_words * 2))
                else:
                    cpu.mem_write(0x20000, compiled[passes])
                cpu.ctl_remove_cache(0x20000, 0x20000 + code_words * 2)
                for phase in range(16):
                    for source_x in (0, 1, 15, 16, 31):
                        for height in (1, 4):
                            width = 32 - source_x
                            plan = Plan()
                            lib.make_plan(ctypes.byref(plan), 32, source_x, width, phase)
                            self.assertEqual(plan.middle, 0xffff)
                            self.assertEqual(plan.dx, 8)
                            cpu.mem_write(0x30000, struct.pack(">hhHHHhhHBx", plan.sx, plan.sy,
                                                             plan.first, plan.middle, plan.last,
                                                             plan.dx, plan.dy, plan.words, plan.skew))
                            expected = bytearray(background)
                            for y in range(height):
                                for x in range(width):
                                    src = y * 16 + (source_x + x) // 16 * 8
                                    sb = 0x8000 >> ((source_x + x) & 15)
                                    db = 0x8000 >> ((phase + x) & 15)
                                    if not struct.unpack_from(">H", masks, src)[0] & sb:
                                        continue
                                    if protected and not writable[(first_line + y) & 15] & db:
                                        continue
                                    for plane in range(4):
                                        dst = y * 160 + (phase + x) // 16 * 8 + plane * 2
                                        old = struct.unpack_from(">H", expected, dst)[0]
                                        colour = struct.unpack_from(">H", pixels, src + plane * 2)[0]
                                        struct.pack_into(">H", expected, dst, (old & ~db) | (db if colour & sb else 0))
                            cpu.mem_write(0x40000, background)
                            cpu.mem_write(0xf0000, struct.pack(">I", 0x1000))
                            inputs = {"A0": 0x50000 + source_x // 16 * 8,
                                      "A1": 0x60000 + source_x // 16 * 8,
                                      "A2": 0x40000, "A3": 0x30000, "A4": 0x20000,
                                      "A7": 0xf0000, "D0": height}
                            for name, value in inputs.items():
                                cpu.reg_write(getattr(registers, "UC_M68K_REG_" + name), value)
                            before = launches
                            cpu.emu_start(0x10000, 0x1000, count=10000)
                            self.assertEqual(cpu.reg_read(registers.UC_M68K_REG_PC), 0x1000)
                            self.assertEqual(launches - before, passes.bit_count())
                            self.assertEqual(cpu.mem_read(0x40000, len(expected)), expected,
                                             (pattern, phase, source_x, height, passes))
                            for name in ("A0", "A1", "A2", "A4", "D0"):
                                self.assertEqual(cpu.reg_read(getattr(registers, "UC_M68K_REG_" + name)),
                                                 inputs[name])
                            self.assertEqual(cpu.reg_read(registers.UC_M68K_REG_A7), 0xf0004)

            tile = (ROOT / "src/video/atari_viewport_tile.s").read_text()
            start = tile.index("tile_blit:")
            tile_source = directory / "tile-setup.s"
            tile_source.write_text("_g_videoBlitterTileSetup equ $70000\n" +
                                   tile[start:tile.index("\n.ready:", start)] +
                                   "\n.ready:\trts\n")
            subprocess.run([tools[1], "-m68000", "-Faout", "-quiet", "-o", str(obj),
                            str(tile_source)], check=True)
            subprocess.run([tools[2], "-O", "binary", "-j", ".text", str(obj), str(binary)],
                           check=True)
            cpu.mem_write(0x80000, binary.read_bytes())
            expected_registers = {
                0x20: (4, 0x00020002), 0x28: (4, 0xffffffff),
                0x2c: (4, 0xffff0002), 0x30: (2, 154),
                0x36: (2, 4), 0x3a: (2, 0x0203), 0x3d: (1, 0),
            }
            for cached in (False, True):
                cpu.mem_write(0xffff8a00, bytes([0x5a]) * 64)
                write(0xffff8a3c, 0, 1)
                write(0x70000, int(cached), 1)
                cpu.mem_write(0xf0000, struct.pack(">I", 0x1000))
                cpu.reg_write(registers.UC_M68K_REG_A7, 0xf0000)
                cpu.emu_start(0x80000, 0x1000, count=100)
                self.assertEqual(cpu.reg_read(registers.UC_M68K_REG_PC), 0x1000)
                self.assertEqual(read(0x70000, 1), 1)
                for offset, (size, value) in expected_registers.items():
                    self.assertEqual(read(0xffff8a00 + offset, size),
                                     int.from_bytes(bytes([0x5a]) * size, "big") if cached else value)
                self.assertEqual(read(0xffff8a24, 4), 0x5a5a5a5a)
                self.assertEqual(read(0xffff8a32, 4), 0x5a5a5a5a)
                self.assertEqual(read(0xffff8a38, 2), 0x5a5a)
                self.assertEqual(read(0xffff8a3c, 1), 0)
