"""Execute the real compiler and 68000 runner against the original C VM.

Requires the Atari cross toolchain and the optional Python unicorn package.
This is an instruction simulator, not a cycle-accurate performance benchmark.
"""

from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

from tools import test_script_budget as budget_tests

ROOT = budget_tests.ROOT


class ScriptNativeTest(unittest.TestCase):
    def test_native_against_raw_vm(self):
        try:
            from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_CODE
            from unicorn.m68k_const import (UC_CPU_M68K_M68000, UC_M68K_REG_PC,
                                            UC_M68K_REG_A7, UC_M68K_REG_D0,
                                            UC_M68K_REG_A2)
        except ImportError:
            self.skipTest("Native execution requires the optional unicorn package")
        tools = ("m68k-atari-mint-gcc", "vasmm68k_mot", "m68k-atari-mint-nm")
        missing = [tool for tool in tools if shutil.which(tool) is None]
        if missing:
            self.skipTest("Native execution requires: " + ", ".join(missing))
        harness = budget_tests.ScriptBudgetTest().make_harness()
        harness = harness.replace("#include <assert.h>", """
extern void test_fail(unsigned line);
#define assert(expression) ((expression) ? (void)0 : test_fail(__LINE__))
""")
        names = ("_calloc", "_free", "_memcmp", "_memset", "_memcpy", "_test_fail")
        stubs = "    text\n    xdef " + ",".join((*names, "___main")) + "\n"
        stubs += "\n".join(name + ":\n    rts" for name in (*names, "___main")) + "\n"
        with tempfile.TemporaryDirectory(prefix="script-native-") as directory:
            directory = Path(directory)
            source = directory / "test.c"
            source.write_text(harness)
            stub_source = directory / "stubs.s"
            stub_source.write_text(stubs)
            runner = directory / "runner.o"
            stub_object = directory / "stubs.o"
            for asm, obj in ((ROOT / "src/script/script_native_runner.s", runner),
                             (stub_source, stub_object)):
                subprocess.run([tools[1], "-m68000", "-Faout", "-quiet", "-o",
                                str(obj), str(asm)], check=True)
            for debug in (False, True):
                with self.subTest(debug=debug):
                    binary = directory / f"test-{debug}.tos"
                    subprocess.run([
                        tools[0], "-m68000", "-msoft-float", "-std=c99", "-O2",
                        "-Wall", "-Wextra", "-Werror", "-DTOS", "-DNATIVE_EMULATED",
                        *(["-D_DEBUG"] if debug else []), "-nostdlib",
                        str(source), str(runner), str(stub_object), "-lgcc",
                        "-o", str(binary),
                    ], check=True)
                    symbols = subprocess.check_output([tools[2], "-n", str(binary)], text=True)
                    base = 0x10000
                    addresses = {name: base + int(address, 16) for address, name in
                                 re.findall(r"^([0-9a-f]+)\s+[TtBbDd]\s+(\S+)$", symbols, re.M)}
                    raw = binary.read_bytes()
                    self.assertEqual(raw[:2], b"\x60\x1a")
                    text, data, bss, symbol_size = struct.unpack_from(">4I", raw, 2)
                    image = bytearray(raw[28:28 + text + data])
                    relocation = 28 + text + data + symbol_size
                    offset = struct.unpack_from(">I", raw, relocation)[0]
                    relocation += 4
                    if offset:
                        while True:
                            value = struct.unpack_from(">I", image, offset)[0]
                            struct.pack_into(">I", image, offset, value + base)
                            while raw[relocation] == 1:
                                offset += 254
                                relocation += 1
                            increment = raw[relocation]
                            relocation += 1
                            if not increment:
                                break
                            offset += increment
                    cpu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
                    cpu.ctl_set_cpu_model(UC_CPU_M68K_M68000)
                    cpu.mem_map(0, 0x800000)
                    cpu.mem_write(base, bytes(image))
                    self.assertLess(base + text + data + bss, 0x200000)
                    allocations = {}
                    released = {}
                    heap = 0x200000
                    last_comparison = None
                    path_counts = {case: [0, 0] for case in range(1, 22)}
                    fusion_counts = {case: 0 for case in range(13, 22)}
                    fallthrough_pcs = []

                    def integer(address):
                        return struct.unpack(">I", cpu.mem_read(address, 4))[0]

                    def hook(cpu, address, size, user_data):
                        nonlocal heap, last_comparison
                        sp = cpu.reg_read(UC_M68K_REG_A7)
                        args = [integer(sp + 4 + i * 4) for i in range(3)]
                        if address == addresses["_test_fail"]:
                            line = harness.splitlines()[args[0] - 1].strip()
                            words = bytes(cpu.mem_read(addresses["_words"], 8)).hex()
                            raise AssertionError(
                                f"68000 harness line {args[0]}: {line}; "
                                f"bytecode={words}; last comparison={last_comparison}")
                        if address == addresses["_calloc"]:
                            length = args[0] * args[1]
                            pool = released.setdefault(length, [])
                            result = pool.pop() if pool else heap
                            if result == heap:
                                heap += (length + 3) & ~3
                            self.assertLess(heap, 0x700000)
                            allocations[result] = length
                            cpu.mem_write(result, bytes(length))
                        elif address == addresses["_free"]:
                            if args[0]:
                                length = allocations.pop(args[0])
                                released.setdefault(length, []).append(args[0])
                            result = 0
                        elif address == addresses["_memcmp"]:
                            left = bytes(cpu.mem_read(args[0], args[2]))
                            right = bytes(cpu.mem_read(args[1], args[2]))
                            result = (left > right) - (left < right)
                            last_comparison = (left.hex(), right.hex())
                        elif address == addresses["_memcpy"]:
                            cpu.mem_write(args[0], bytes(cpu.mem_read(args[1], args[2])))
                            result = args[0]
                        else:
                            cpu.mem_write(args[0], bytes([args[1] & 255]) * args[2])
                            result = args[0]
                        cpu.reg_write(UC_M68K_REG_D0, result & 0xffffffff)
                        cpu.reg_write(UC_M68K_REG_A7, sp + 4)
                        cpu.reg_write(UC_M68K_REG_PC, integer(sp))

                    for name in names:
                        cpu.hook_add(UC_HOOK_CODE, hook, begin=addresses[name], end=addresses[name])

                    def cursor_hook(cpu, address, size, user_data):
                        case = integer(addresses["_nativeCursorCase"])
                        if case:
                            path_counts[case][address == addresses["NativeFetch"]] += 1
                        if case == 1 and address == addresses["NativeCursorFetch"]:
                            engine = cpu.reg_read(UC_M68K_REG_A2)
                            fallthrough_pcs.append(integer(engine + 2))

                    for name in ("NativeCursorFetch", "NativeFetch"):
                        cpu.hook_add(UC_HOOK_CODE, cursor_hook,
                                     begin=addresses[name], end=addresses[name])

                    def fusion_hook(cpu, address, size, user_data):
                        case = integer(addresses["_nativeCursorCase"])
                        if case in fusion_counts:
                            fusion_counts[case] += 1

                    for name in ("NativeFusedNext", "NativeFusedJump"):
                        cpu.hook_add(UC_HOOK_CODE, fusion_hook,
                                     begin=addresses[name], end=addresses[name])
                    stop = 0x7f0000
                    cpu.reg_write(UC_M68K_REG_A7, 0x7ff000)
                    cpu.mem_write(0x7ff000, struct.pack(">I", stop))
                    cpu.emu_start(addresses["_main"], stop, count=500_000_000)
                    pc = cpu.reg_read(UC_M68K_REG_PC)
                    owner = max((item for item in addresses.items()
                                 if item[1] <= pc and not item[0].startswith(".")),
                                key=lambda item: item[1])
                    words = bytes(cpu.mem_read(addresses["_words"], 8)).hex()
                    self.assertEqual(pc, stop,
                                     f"Native simulation stopped at {pc:#x} ({owner}); "
                                     f"bytecode={words}; last comparison={last_comparison}")
                    self.assertEqual(cpu.reg_read(UC_M68K_REG_D0), 0)
                    self.assertFalse(allocations, "Native code allocation leaked")
                    self.assertEqual(fusion_counts, {case: 1 for case in range(13, 22)})
                    self.assertEqual(fallthrough_pcs, [addresses["_words"]] * 16,
                                     "Ordinary native opcodes must not publish bytecode PCs")
                    self.assertEqual(path_counts, {
                        1: [16, 1],  # Mixed one/two-word fall-through.
                        2: [4, 1],   # Prelinked jump to the same original PC.
                        3: [0, 4],   # Callback rebind after every opcode.
                        4: [3, 1],   # Operand word is also a jump destination.
                        5: [2, 1],   # Taken prelinked conditional branch.
                        6: [2, 1],   # Untaken conditional branch.
                        7: [2, 1],   # Return through the VM stack.
                        8: [2, 1],   # Restore frame and return location.
                        9: [3, 1],   # Audited callbacks bypass rebinding.
                        10: [2, 1],  # One/two-word audited callbacks.
                        11: [0, 1],  # Audited delay yields before advancing.
                        12: [1, 2],  # Stack-error unload, final/nonfinal budget.
                        **{case: [1, 1] for case in range(13, 22)},  # All fused pairs.
                    })


if __name__ == "__main__":
    unittest.main()
