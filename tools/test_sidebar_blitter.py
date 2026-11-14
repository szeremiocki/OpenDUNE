"""Execute the independent sidebar commands on a 68000 with modelled BLITTER registers."""

import ctypes
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SidebarBlitterTest(unittest.TestCase):
    def test_cpu_commands_keep_inline_parameters_and_order(self):
        try:
            import unicorn
            from unicorn import m68k_const as reg
        except ImportError:
            self.skipTest("68000 execution requires the optional unicorn package")
        harness = r"""
#include <assert.h>
#include "types.h"
#include "src/video/video.h"
#include "src/video/atari_sidebar.h"
bool g_videoBlitterTileSetup, g_videoDisplayListActive;
void Video_Atari_SidebarHealthCode(void) {}
uint16 endian_bswap16(uint16 v) { return __builtin_bswap16(v); }
uint32 endian_bswap32(uint32 v) { return __builtin_bswap32(v); }
uint16 *g_videoDisplayListNext, *g_videoDisplayListLimit;
static uint16 stream[128];
void Video_Atari_DisplayListCheck(uint16 bytes) { assert(bytes <= sizeof(stream)); }
#include "src/video/atari_sidebar.c"
const uint16 *make_cpu_stream(uint16 bytes) {
    g_videoDisplayListActive = true;
    g_videoDisplayListNext = stream;
    for (unsigned n = 0; n < 2; n++) {
        unsigned offset = g_videoDisplayListNext - stream;
        uint8 *data = Video_Atari_QueueSidebarCPU((void (*)(const void *))(uintptr_t)0x20000, bytes);
        /* Relocate the host list address for the emulated 68000. */
        uint32 address = HTOBE32(0x10000 + offset * 2 + 18);
        memcpy(stream + offset + 1, &address, sizeof(address));
        for (unsigned i = 0; i < bytes; i++) data[i] = n * 79 + i;
    }
    *g_videoDisplayListNext = HTOBE16(0x4e75);
    return stream;
}
"""
        with tempfile.TemporaryDirectory(prefix="sidebar-cpu-") as directory:
            source, library = Path(directory) / "check.c", Path(directory) / "check.so"
            source.write_text(harness)
            subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-shared", "-fPIC",
                            "-std=gnu17", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-I", str(ROOT / "include"), "-I", str(ROOT),
                            str(source), "-o", str(library)], check=True)
            lib = ctypes.CDLL(str(library))
            lib.make_cpu_stream.argtypes = [ctypes.c_uint16]
            lib.make_cpu_stream.restype = ctypes.c_void_p
            cpu = unicorn.Uc(unicorn.UC_ARCH_M68K, unicorn.UC_MODE_BIG_ENDIAN)
            cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_M68000)
            cpu.mem_map(0, 0x100000)
            # C ABI callback: RTS; the hook inspects its stack argument.
            cpu.mem_write(0x20000, b"\x4e\x75")
            seen = []

            def callback(cpu, address, size, data):
                sp = cpu.reg_read(reg.UC_M68K_REG_A7)
                parameter = int.from_bytes(cpu.mem_read(sp + 4, 4), "big")
                seen.append(bytes(cpu.mem_read(parameter, payload)))

            cpu.hook_add(unicorn.UC_HOOK_CODE, callback, begin=0x20000, end=0x20000)
            for payload in (1, 2, 9, 32, 63):
                padded = (payload + 1) & ~1
                stream = ctypes.string_at(lib.make_cpu_stream(payload), 2 * (18 + padded) + 2)
                cpu.mem_write(0x10000, stream)
                cpu.ctl_remove_cache(0x10000, 0x11000)
                cpu.mem_write(0xf0000, struct.pack(">I", 0x1000))
                cpu.reg_write(reg.UC_M68K_REG_A7, 0xf0000)
                seen.clear()
                cpu.emu_start(0x10000, 0x1000, count=1000)
                self.assertEqual(cpu.reg_read(reg.UC_M68K_REG_PC), 0x1000)
                self.assertEqual(cpu.reg_read(reg.UC_M68K_REG_A7), 0xf0004)
                self.assertEqual(seen, [bytes(n * 79 + i for i in range(payload)) for n in range(2)])

    def test_direct_health_command(self):
        assembler = shutil.which("vasmm68k_mot")
        if assembler is None:
            self.skipTest("68000 execution requires vasm")
        try:
            import unicorn
            from unicorn import m68k_const as reg
        except ImportError:
            self.skipTest("68000 execution requires the optional unicorn package")
        harness = r"""
#include <assert.h>
#include "types.h"
#include "src/video/video.h"
#include "src/video/atari_sidebar.h"
bool g_videoBlitterTileSetup, g_videoDisplayListActive;
void Video_Atari_SidebarHealthCode(void) {}
uint16 endian_bswap16(uint16 v) { return __builtin_bswap16(v); }
uint32 endian_bswap32(uint32 v) { return __builtin_bswap32(v); }
uint16 *g_videoDisplayListNext, *g_videoDisplayListLimit;
static uint16 stream[20];
void Video_Atari_DisplayListCheck(uint16 bytes) { assert(bytes == 36); }
#include "src/video/atari_sidebar.c"
const uint16 *make_health(uint16 width, uint8 foreground, uint8 background) {
    g_videoDisplayListActive = true;
    g_videoDisplayListNext = stream;
    Video_Atari_QueueSidebarHealth((uint16 *)(uintptr_t)0x400a0, width, foreground, background);
    assert(g_videoDisplayListNext == stream + 18);
    stream[18] = HTOBE16(0x4e75);
    return stream;
}
"""
        with tempfile.TemporaryDirectory(prefix="sidebar-health-") as directory:
            source, library = Path(directory) / "check.c", Path(directory) / "check.so"
            source.write_text(harness)
            subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-shared", "-fPIC",
                            "-std=gnu17", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-I", str(ROOT / "include"), "-I", str(ROOT),
                            str(source), "-o", str(library)], check=True)
            kernel = Path(directory) / "health.bin"
            subprocess.run([assembler, "-m68000", "-Fbin", "-quiet", "-o", str(kernel),
                            str(ROOT / "src/video/atari_sidebar_health.s")], check=True)
            lib = ctypes.CDLL(str(library))
            lib.make_health.argtypes = [ctypes.c_uint16, ctypes.c_uint8, ctypes.c_uint8]
            lib.make_health.restype = ctypes.c_void_p
            cpu = unicorn.Uc(unicorn.UC_ARCH_M68K, unicorn.UC_MODE_BIG_ENDIAN)
            cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_M68000)
            cpu.mem_map(0, 0x100000)
            cpu.mem_write(0x20000, kernel.read_bytes())
            background = bytes((i * 113 + 17) & 255 for i in range(9 * 160))
            expected, writes = bytearray(background), {}

            def screen_write(cpu, access, address, size, value, data):
                offset = address - 0x40000
                self.assertEqual(value, int.from_bytes(expected[offset:offset + size], "big"))
                writes[address] = writes.get(address, 0) + 1

            cpu.hook_add(unicorn.UC_HOOK_MEM_WRITE, screen_write,
                         begin=0x40000, end=0x40000 + len(background) - 1)

            def reference(width, foreground, background_pen):
                result = bytearray(background)
                for y in range(1, 8):
                    for x in range(24):
                        pen = foreground if x < width else background_pen
                        dx, bit = x + 5, 0x8000 >> ((x + 5) & 15)
                        for plane in range(4):
                            off = y * 160 + dx // 16 * 8 + plane * 2
                            old = struct.unpack_from(">H", result, off)[0]
                            struct.pack_into(">H", result, off,
                                             (old & ~bit) | (bit if pen & (1 << plane) else 0))
                return result

            def stream(width, foreground, background_pen):
                data = bytearray(ctypes.string_at(lib.make_health(width, foreground, background_pen), 38))
                self.assertEqual(data[30:32], b"\x4e\xb9")
                data[32:36] = struct.pack(">I", 0x20000)
                return bytes(data)

            def execute(data, image):
                nonlocal expected
                expected = image
                writes.clear()
                cpu.mem_write(0x10000, data)
                cpu.ctl_remove_cache(0x10000, 0x11000)
                cpu.mem_write(0x40000, background)
                cpu.mem_write(0xf0000, struct.pack(">I", 0x1000))
                cpu.reg_write(reg.UC_M68K_REG_A7, 0xf0000)
                cpu.emu_start(0x10000, 0x1000, count=10000)
                self.assertEqual(cpu.reg_read(reg.UC_M68K_REG_PC), 0x1000)
                self.assertEqual(cpu.mem_read(0x40000, len(expected)), expected)
                self.assertEqual(len(writes), 28)
                self.assertTrue(all(count == 1 for count in writes.values()))

            for width in range(25):
                for foreground in range(16):
                    for background_pen in range(16):
                        execute(stream(width, foreground, background_pen),
                                reference(width, foreground, background_pen))
            # Later submissions cannot change already queued destination/colour values.
            first = stream(24, 9, 3)
            second = stream(1, 0, 15)
            execute(first, reference(24, 9, 3))
            execute(second, reference(1, 0, 15))

    def test_prepared_commands_and_display_list(self):
        try:
            import unicorn
            from unicorn import m68k_const as reg
        except ImportError:
            self.skipTest("68000 execution requires the optional unicorn package")
        harness = r"""
#include <assert.h>
#include "types.h"
#include "src/video/video.h"
#include "src/video/atari_sidebar.h"
bool g_videoBlitterTileSetup, g_videoDisplayListActive;
void Video_Atari_SidebarHealthCode(void) {}
uint16 endian_bswap16(uint16 v) { return __builtin_bswap16(v); }
uint32 endian_bswap32(uint32 v) { return __builtin_bswap32(v); }
uint16 *g_videoDisplayListNext, *g_videoDisplayListLimit;
static uint16 stream[8];
void Video_Atari_DisplayListCheck(uint16 bytes) { assert(bytes == 12); }
#include "src/video/atari_sidebar.c"
const uint16 *make_stream(const VideoAtariSidebarBlit *code) {
    g_videoDisplayListActive = true;
    g_videoDisplayListNext = stream;
    Video_Atari_QueueSidebarBlit(code->words, (uint16 *)(uintptr_t)0x40000);
    assert(g_videoDisplayListNext == stream + 6);
    stream[6] = HTOBE16(0x4e75);
    return stream;
}
"""
        with tempfile.TemporaryDirectory(prefix="sidebar-blitter-") as directory:
            source, library = Path(directory) / "check.c", Path(directory) / "check.so"
            source.write_text(harness)
            subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-shared", "-fPIC",
                            "-std=gnu17", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-I", str(ROOT / "include"), "-I", str(ROOT),
                            str(source), "-o", str(library)], check=True)
            lib = ctypes.CDLL(str(library))
            lib.Video_Atari_CompileSidebarBlit.argtypes = [ctypes.c_void_p] * 3 + [ctypes.c_uint16] * 4
            lib.make_stream.argtypes = [ctypes.c_void_p]
            lib.make_stream.restype = ctypes.c_void_p
            flag = ctypes.c_bool.in_dll(lib, "g_videoBlitterTileSetup")
            cpu = unicorn.Uc(unicorn.UC_ARCH_M68K, unicorn.UC_MODE_BIG_ENDIAN)
            cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_M68000)
            cpu.mem_map(0, 0x100000)
            cpu.mem_map(0xffff8000, 0x1000)
            pending, latch, launches = False, 0xa39fbc71, 0

            def read(address, size):
                return int.from_bytes(cpu.mem_read(address, size), "big")

            def write(address, value, size):
                cpu.mem_write(address, (value & ((1 << (size * 8)) - 1)).to_bytes(size, "big"))

            def complete():
                nonlocal pending, latch
                pending = False
                base = 0xffff8a00
                sx, sy, dx, dy = (struct.unpack(">h", cpu.mem_read(base + off, 2))[0]
                                  for off in (0x20, 0x22, 0x2e, 0x30))
                src, dst = read(base + 0x24, 4), read(base + 0x32, 4)
                words, rows = read(base + 0x36, 2), read(base + 0x38, 2)
                skew, op = read(base + 0x3d, 1), read(base + 0x3b, 1)
                self.assertEqual(read(base + 0x3a, 1), 2)
                self.assertIn(op, (3, 4, 7))
                if opaque:
                    self.assertEqual(op, 3)
                for _ in range(rows):
                    for word in range(words):
                        suppress = bool(skew & 0x40) and word + 1 == words
                        old = read(dst, 2)
                        latch = ((latch << 16) | (old if suppress else read(src, 2))) & 0xffffffff
                        value = (latch >> (skew & 15)) & 0xffff
                        result = value if op == 3 else old & ~value if op == 4 else old | value
                        mask = read(base + (0x28 if word == 0 else
                                           0x2c if word + 1 == words else 0x2a), 2)
                        write(dst, (old & ~mask) | (result & mask), 2)
                        if suppress:
                            latch = ((latch << 16) | read(dst, 2)) & 0xffffffff
                        else:
                            src += sy if word + 1 == words or (
                                skew & 0x40 and word + 2 == words) else sx
                        dst += dy if word + 1 == words else dx
                write(base + 0x24, src, 4)
                write(base + 0x32, dst, 4)
                write(base + 0x38, 0, 2)
                write(base + 0x3c, 0, 1)

            def mmio(cpu, access, address, size, value, data):
                nonlocal pending, launches
                if address == 0xffff8a3c and value == 0xc0:
                    pending = True
                    launches += 1

            def instruction(cpu, address, size, data):
                if pending:
                    complete()

            cpu.hook_add(unicorn.UC_HOOK_MEM_WRITE, mmio, begin=0xffff8a00, end=0xffff8a3f)
            cpu.hook_add(unicorn.UC_HOOK_CODE, instruction)
            for mode in ("masked", "opaque", "solid_masks"):
                opaque = mode == "opaque"
                for stride in ((32,) if mode == "solid_masks" else (16, 32, 64)):
                    for height in ((24,) if mode == "solid_masks" else (1, 24, 82)):
                        for phase in range(16):
                            for width in (1, stride - 3, stride):
                                size = stride // 2 * height
                                pixels, masks = bytearray(size), bytearray(size)
                                for y in range(height):
                                    for x in range(stride):
                                        if mode == "masked" and (x + y) % 5 == 0:
                                            continue
                                        index, bit = y * stride // 2 + x // 16 * 8, 0x8000 >> (x & 15)
                                        for plane in range(4):
                                            off = index + plane * 2
                                            struct.pack_into(">H", masks, off,
                                                struct.unpack_from(">H", masks, off)[0] | bit)
                                            if plane == 1 or (plane >= 2 and (x + y + plane) % 3):
                                                struct.pack_into(">H", pixels, off,
                                                    struct.unpack_from(">H", pixels, off)[0] | bit)
                                p = ctypes.create_string_buffer(bytes(pixels))
                                m = ctypes.create_string_buffer(bytes(masks))
                                storage = (ctypes.c_uint16 * 193)()
                                storage[192] = 0xdead
                                lib.Video_Atari_CompileSidebarBlit(storage, p, None if opaque else m,
                                                                stride, width, height, phase)
                                self.assertEqual(storage[192], 0xdead)
                                code = bytearray(ctypes.string_at(storage, 384))
                                for original, replacement in ((ctypes.addressof(flag), 0x70000),
                                                              (ctypes.addressof(p), 0x50000),
                                                              (ctypes.addressof(m), 0x60000)):
                                    for plane in range(4):
                                        old = struct.pack(">I", (original + plane * 2) & 0xffffffff)
                                        code = code.replace(old, struct.pack(">I", replacement + plane * 2))
                                stream = bytearray(ctypes.string_at(lib.make_stream(storage), 14))
                                self.assertEqual(stream[:6], struct.pack(">HI", 0x207c, 0x40000))
                                self.assertEqual(stream[6:8], b"\x4e\xb9")
                                stream[8:12] = struct.pack(">I", 0x20000)
                                cpu.mem_write(0x10000, bytes(stream))
                                cpu.mem_write(0x20000, bytes(code))
                                cpu.ctl_remove_cache(0x10000, 0x21000)
                                cpu.mem_write(0x50000, bytes(pixels))
                                cpu.mem_write(0x60000, bytes(masks))
                                background = bytes((i * 113 + 17) & 255 for i in range(height * 160))
                                expected = bytearray(background)
                                for y in range(height):
                                    for x in range(width):
                                        source_off = y * stride // 2 + x // 16 * 8
                                        sb, db = 0x8000 >> (x & 15), 0x8000 >> ((phase + x) & 15)
                                        if not opaque and not struct.unpack_from(">H", masks, source_off)[0] & sb:
                                            continue
                                        for plane in range(4):
                                            off = y * 160 + (phase + x) // 16 * 8 + plane * 2
                                            old = struct.unpack_from(">H", expected, off)[0]
                                            colour = struct.unpack_from(">H", pixels, source_off + plane * 2)[0]
                                            struct.pack_into(">H", expected, off, (old & ~db) | (db if colour & sb else 0))
                                cpu.mem_write(0x40000, background)
                                cpu.mem_write(0xf0000, struct.pack(">I", 0x1000))
                                write(0x70000, 1, 1)
                                cpu.reg_write(reg.UC_M68K_REG_A7, 0xf0000)
                                launches = 0
                                cpu.emu_start(0x10000, 0x1000, count=10000)
                                self.assertEqual(cpu.reg_read(reg.UC_M68K_REG_PC), 0x1000)
                                self.assertEqual(read(0x70000, 1), 0)
                                if phase == 0 and width == stride:
                                    self.assertEqual(launches, 1 if opaque else 2)
                                elif opaque:
                                    self.assertEqual(launches, 4)
                                self.assertEqual(cpu.mem_read(0x40000, len(expected)), expected,
                                                 (opaque, stride, width, height, phase))


if __name__ == "__main__":
    unittest.main()
