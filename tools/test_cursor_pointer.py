"""Check pointer recoloring and the real 68000 cursor loops without Hatari."""

from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class CursorPointerTest(unittest.TestCase):
    def test_cached_and_fallback_colours(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        end = video.index("} CursorIcon;") + len("} CursorIcon;")
        icon = video[video.rfind("typedef struct {", 0, end):end]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
#define CURSOR_PHASES 16
#define CURSOR_MAX_GROUPS 6
#define CURSOR_MAX_H 32
#define Video_Atari_Mono() false
#define Video_Atari_MonoPenWords(p,x,y,out) ((void)(p), (void)(x), (void)(y), (void)(out), assert(false))
static uint8 s_palette4BitMap[256];
static bool s_curPointer;
static uint16 s_curH, s_curW, s_curShift, s_curGroups;
static uint16 s_curData[32][24], s_curMask[32][6];
/* PRODUCTION */
int main(void) {
    const uint8 chunky[] = {0, 12, 232, 233, 234, 236, 0};
    for (unsigned c = 0; c < 256; c++) s_palette4BitMap[c] = c & 15;
    for (unsigned pointer = 0; pointer < 2; pointer++)
    for (unsigned phase = 0; phase < 16; phase++) {
        CursorIcon icon = {0};
        icon.w = sizeof(chunky); icon.h = 1;
        assert(Video_Atari_CursorBuildPhase(&icon, phase, chunky, sizeof(chunky), pointer));
        s_curPointer = pointer;
        s_curW = icon.w; s_curH = 1; s_curShift = phase; s_curGroups = icon.groups[phase];
        Video_Atari_CursorBuild(chunky, sizeof(chunky));
        for (unsigned g = 0; g < icon.groups[phase]; g++) {
            assert(icon.mask[phase][g] == s_curMask[0][g]);
            for (unsigned p = 0; p < 4; p++)
                assert(icon.data[phase][g * 4 + p] == s_curData[0][g * 4 + p]);
        }
        for (unsigned x = 0; x < sizeof(chunky); x++) {
            unsigned pos = x + phase, pen = 0;
            uint16 bit = 0x8000u >> (pos & 15);
            assert(!!(icon.mask[phase][pos / 16] & bit) == (chunky[x] != 0));
            for (unsigned p = 0; p < 4; p++)
                if (icon.data[phase][pos / 16 * 4 + p] & bit) pen |= 1u << p;
            unsigned want = !chunky[x] ? 0 : pointer ?
                (chunky[x] == 232 || chunky[x] == 233 ? 4 : 0) : s_palette4BitMap[chunky[x]];
            assert(pen == want);
        }
        free(icon.data[phase]); free(icon.mask[phase]);
    }
    return 0;
}
"""
        production = icon + "\n" + "\n".join(function(video, name) for name in (
            "Video_Atari_CursorPen", "Video_Atari_CursorBuild",
            "Video_Atari_CursorBuildPhase"))
        with tempfile.TemporaryDirectory(prefix="cursor-pointer-colours-") as directory:
            source, binary = Path(directory) / "check.c", Path(directory) / "check"
            source.write_text(harness.replace("/* PRODUCTION */", production))
            subprocess.run(["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
        preload = function(video, "Video_Atari_CursorPreloadIcons")
        self.assertIn("w, i == 0)", preload)
        self.assertIn("s_curPointer = iconIndex == 0", function(video, "Video_Atari_CursorUseIcon"))
        self.assertIn("s_curDrawnPointer = s_curPointer", function(video, "Video_Atari_CursorDraw"))
        self.assertIn("if (s_curDrawnPointer)", function(video, "Video_Atari_RefreshViewportCursor"))

    def test_68000_composition_refresh_and_restore(self):
        try:
            import unicorn
            from unicorn import m68k_const as registers
        except ImportError:
            self.skipTest("CPU-only execution requires the optional unicorn package")
        tools = ("vasmm68k_mot", "m68k-atari-mint-nm", "m68k-atari-mint-objcopy")
        if any(shutil.which(tool) is None for tool in tools):
            self.skipTest("Atari assembler and object tools required")
        with tempfile.TemporaryDirectory(prefix="cursor-pointer-68000-") as directory:
            obj, binary = Path(directory) / "cursor.o", Path(directory) / "cursor.bin"
            subprocess.run([tools[0], "-m68000", "-Faout", "-quiet", "-o", str(obj),
                            str(ROOT / "src/video/atari_cursor.s")], check=True)
            subprocess.run([tools[2], "-O", "binary", "-j", ".text", str(obj), str(binary)],
                           check=True)
            listing = subprocess.check_output([tools[1], str(obj)], text=True)
            symbols = {name: 0x10000 + int(address, 16) for address, name in
                       re.findall(r"^([0-9a-f]+)\s+[Tt]\s+(\S+)$", listing, re.M)}
            cpu = unicorn.Uc(unicorn.UC_ARCH_M68K, unicorn.UC_MODE_BIG_ENDIAN)
            cpu.ctl_set_cpu_model(registers.UC_CPU_M68K_M68000)
            cpu.mem_map(0, 0x100000)
            cpu.mem_write(0x10000, binary.read_bytes())
            preserved = [getattr(registers, "UC_M68K_REG_" + name)
                         for name in ("D2", "D3", "D4", "D5", "D6", "D7",
                                      "A2", "A3", "A4", "A5", "A6")]

            def call(name, arguments):
                cpu.mem_write(0x20000, struct.pack(">" + "I" * len(arguments), *arguments))
                cpu.mem_write(0xf0000, struct.pack(">II", 0x1000, 0x20000))
                cpu.reg_write(registers.UC_M68K_REG_A7, 0xf0000)
                for i, reg in enumerate(preserved):
                    cpu.reg_write(reg, 0xabc000 + i)
                steps = [0]

                def count_instruction(cpu, address, size, data):
                    steps[0] += 1

                hook = cpu.hook_add(unicorn.UC_HOOK_CODE, count_instruction)
                cpu.emu_start(symbols[name], 0x1000, count=100000)
                cpu.hook_del(hook)
                self.assertEqual(cpu.reg_read(registers.UC_M68K_REG_PC), 0x1000)
                for i, reg in enumerate(preserved):
                    self.assertEqual(cpu.reg_read(reg), 0xabc000 + i)
                return steps[0]

            def word(data, offset):
                return struct.unpack_from(">H", data, offset)[0]

            def put(data, offset, value):
                struct.pack_into(">H", data, offset, value & 0xffff)

            for phase in range(16):
                for lines in (1, 14):
                    for clipped in (False, True):
                        groups = (phase + 13 + 15) // 16
                        source_groups = groups + 1
                        data = bytearray(lines * source_groups * 8)
                        masks = bytearray(lines * source_groups * 2)
                        for y in range(lines):
                            for x in range(13):
                                if (x + y) % 5 == 0:
                                    continue
                                pos = x + phase
                                offset = y * source_groups * 2 + pos // 16 * 2
                                bit = 0x8000 >> (pos & 15)
                                put(masks, offset, word(masks, offset) | bit)
                                if (x + y) & 1:
                                    offset = y * source_groups * 8 + pos // 16 * 8 + 4
                                    put(data, offset, word(data, offset) | bit)
                        skip = int(clipped and groups > 1)
                        visible_groups = groups - skip
                        background = bytes((i * 113 + 17) & 255 for i in range(lines * 160))
                        expected = bytearray(background)
                        want_save = bytearray([0xa5] * (lines * 48))
                        want_data = bytearray([0x5a] * (lines * 48))
                        want_masks = bytearray([0xcc] * (lines * 12))
                        for y in range(lines):
                            for g in range(visible_groups):
                                mask = word(masks, y * source_groups * 2 + (g + skip) * 2)
                                put(want_masks, y * 12 + g * 2, mask)
                                for p in range(4):
                                    src = y * source_groups * 8 + (g + skip) * 8 + p * 2
                                    dst = y * 160 + g * 8 + p * 2
                                    backup = y * 48 + g * 8 + p * 2
                                    put(want_save, backup, word(background, dst))
                                    put(want_data, backup, word(data, src))
                                    put(expected, dst, (word(background, dst) & ~mask) | word(data, src))
                        compose_args = [0x30000, 0x40000, 0x50000, 0x60000,
                                        0x80000 + skip * 8, 0x70000 + skip * 2,
                                        lines, visible_groups, 160 - visible_groups * 8,
                                        48 - visible_groups * 8, 12 - visible_groups * 2,
                                        (source_groups - visible_groups) * 8,
                                        (source_groups - visible_groups) * 2]
                        for suffix in ("", "Pointer"):
                            cpu.mem_write(0x30000, background)
                            cpu.mem_write(0x40000, bytes([0xa5] * (lines * 48)))
                            cpu.mem_write(0x50000, bytes([0x5a] * (lines * 48)))
                            cpu.mem_write(0x60000, bytes([0xcc] * (lines * 12)))
                            cpu.mem_write(0x70000, bytes(masks))
                            cpu.mem_write(0x80000, bytes(data))
                            steps = call("_Video_Atari_CursorCompose" + suffix, compose_args)
                            if suffix:
                                self.assertEqual(compose_steps - steps, lines * visible_groups)
                            else:
                                compose_steps = steps
                            for address, want in ((0x30000, expected), (0x40000, want_save),
                                                  (0x50000, want_data), (0x60000, want_masks)):
                                self.assertEqual(cpu.mem_read(address, len(want)), want)
                            written = bytearray(expected)
                            refreshed = bytearray(expected)
                            saved = bytearray(want_save)
                            writes = bytearray(lines * source_groups * 2)
                            for y in range(lines):
                                for g in range(visible_groups):
                                    write = 0 if (y + g) % 3 == 0 else 0x39e7
                                    put(writes, y * source_groups * 2 + g * 2, write)
                                    mask = word(want_masks, y * 12 + g * 2) & write
                                    for p in range(4):
                                        dst = y * 160 + g * 8 + p * 2
                                        backup = y * 48 + g * 8 + p * 2
                                        colour = (dst * 91 + 5) & 0xffff
                                        new = (word(written, dst) & ~write) | (colour & write)
                                        put(written, dst, new)
                                        put(saved, backup, (word(saved, backup) & ~write) | (new & write))
                                        put(refreshed, dst, (new & ~mask) | (word(want_data, backup) & mask))
                            cpu.mem_write(0x30000, bytes(written))
                            cpu.mem_write(0x90000, bytes(writes))
                            refresh_args = [0x30000, 0x40000, 0x50000, 0x60000, 0x90000,
                                            lines, visible_groups, 160 - visible_groups * 8,
                                            48 - visible_groups * 8, 12 - visible_groups * 2,
                                            (source_groups - visible_groups) * 2]
                            steps = call("_Video_Atari_CursorRefresh" +
                                         ("Pointer" if suffix else "Groups"), refresh_args)
                            if suffix:
                                touched = sum((y + g) % 3 != 0 for y in range(lines)
                                              for g in range(visible_groups))
                                self.assertEqual(refresh_steps - steps, touched * 2)
                            else:
                                refresh_steps = steps
                            self.assertEqual(cpu.mem_read(0x30000, len(refreshed)), refreshed)
                            self.assertEqual(cpu.mem_read(0x40000, len(saved)), saved)
                            # Restore takes separate arguments rather than a structure pointer.
                            cpu.mem_write(0xf0000, struct.pack(">6I", 0x1000, 0x30000,
                                                             0x40000, 48, lines, visible_groups))
                            cpu.reg_write(registers.UC_M68K_REG_A7, 0xf0000)
                            cpu.emu_start(symbols["_Video_Atari_CursorRestore"], 0x1000, count=100000)
                            restored = bytearray(refreshed)
                            for y in range(lines):
                                restored[y * 160:y * 160 + visible_groups * 8] = \
                                    saved[y * 48:y * 48 + visible_groups * 8]
                            self.assertEqual(cpu.mem_read(0x30000, len(restored)), restored)
