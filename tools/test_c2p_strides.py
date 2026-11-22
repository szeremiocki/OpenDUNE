"""Check the real 68000 c2p object and ST-Low output."""

from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class C2PStrideObjectTest(unittest.TestCase):
    def test_shared_kernel_and_stride_abi(self):
        tools = ("vasmm68k_mot", "m68k-atari-mint-nm",
                 "m68k-atari-mint-objdump", "m68k-atari-mint-objcopy")
        missing = [tool for tool in tools if shutil.which(tool) is None]
        if missing:
            self.skipTest("Atari object inspection requires: " + ", ".join(missing))
        with tempfile.TemporaryDirectory(prefix="c2p-strides-") as directory:
            obj = Path(directory) / "c2p.o"
            binary = Path(directory) / "c2p.bin"
            subprocess.run([tools[0], "-m68000", "-Faout", "-quiet", "-o", str(obj),
                            str(ROOT / "src/video/c2p1x1_8.s")], check=True)
            subprocess.run([tools[3], "-O", "binary", "-j", ".text", str(obj), str(binary)],
                           check=True)
            disassembly = subprocess.check_output([tools[2], "-d", str(obj)], text=True)
            symbols = subprocess.check_output([tools[1], str(obj)], text=True)
            entries = {}
            for address, name in re.findall(
                    r"^([0-9a-f]+)\s+T\s+(_c2p1x1_4_st_byte(?:_strided)?)$", symbols, re.M):
                entries[name] = int(address, 16)
            self.assertEqual(len(entries), 2)
            code = binary.read_bytes()
            blocks = [
                disassembly.split("<" + name + ">:", 1)[1].split(
                    "\n" + format(entries["_c2p1x1_4_st_byte_strided"], "08x") + " <", 1)[0]
                for name in ("_c2p1x1_4_st_byte", "_c2p1x1_4_st_byte_strided")
            ]
            kernels = []
            for block in blocks:
                instructions = re.findall(
                    r"^\s*([0-9a-f]+):\s+(?:[0-9a-f]{4}\s+)+(.+)$", block, re.M)
                start = next(i for i, (_, ins) in enumerate(instructions)
                             if ins.startswith("lea") and "%a0@(0,%fp:l),%a2" in ins)
                stop = next(i for i in range(start + 1, len(instructions))
                            if instructions[i][1].startswith(("lea", "addal")))
                kernels.append(code[int(instructions[start + 1][0], 16):
                                    int(instructions[stop][0], 16)])
                self.assertIn("moveml %d2-%d7/%a2-%fp,%sp@-", block)
                self.assertIn("moveml %sp@+,%d2-%d7/%a2-%fp", block)
                self.assertRegex(block, r"tstl %d1\n.*beqw")
            self.assertEqual(kernels[0], kernels[1])
            self.assertGreater(len(kernels[0]), 100)
            self.assertIn("muluw #320,%d1", blocks[0])
            self.assertIn("lea %a4@(320),%a4", blocks[0])
            self.assertIn("lea %a5@(160),%a5", blocks[0])
            self.assertIn("muluw %sp@(70),%d1", blocks[1])
            self.assertIn("addal %sp@(72),%a4", blocks[1])
            self.assertIn("addal %sp@(76),%a5", blocks[1])

    def test_byte_palette_and_direct_pens_match_reference(self):
        try:
            import unicorn
            from unicorn import m68k_const as regs
        except ImportError:
            self.skipTest("68000 execution requires Unicorn")
        tools = ("vasmm68k_mot", "m68k-atari-mint-nm", "m68k-atari-mint-objcopy")
        if any(shutil.which(tool) is None for tool in tools):
            self.skipTest("Atari assembly tools are unavailable")
        with tempfile.TemporaryDirectory(prefix="c2p-byte-") as directory:
            obj, binary = (Path(directory) / name for name in ("c2p.o", "c2p.bin"))
            subprocess.run([tools[0], "-m68000", "-Faout", "-quiet", "-o", str(obj),
                            str(ROOT / "src/video/c2p1x1_8.s")], check=True)
            subprocess.run([tools[2], "-O", "binary", "-j", ".text", str(obj), str(binary)],
                           check=True)
            symbols = subprocess.check_output([tools[1], str(obj)], text=True)
            entries = {name: int(address, 16) for address, name in
                       re.findall(r"^([0-9a-f]+)\s+T\s+(_c2p1x1_4_st\S*)$", symbols, re.M)}
            cpu = unicorn.Uc(unicorn.UC_ARCH_M68K, unicorn.UC_MODE_BIG_ENDIAN)
            cpu.ctl_set_cpu_model(regs.UC_CPU_M68K_M68000)
            cpu.mem_map(0, 0x80000)
            cpu.mem_write(0x10000, binary.read_bytes())

            for width, rows, ss, ds, suffix in (
                    (320, 3, 320, 160, ""), (32, 17, 38, 22, "_strided"),
                    (16, 1, 320, 160, ""), (32, 0, 38, 22, "_strided")):
                source = bytes((i * 157 + i // 256) & 255 for i in range(ss * max(rows, 1)))
                for phase in (0, 1):
                    palette = bytes(((i >> 4) ^ i ^ (phase * 7)) & 15 for i in range(256))
                    mapped = source.translate(palette)
                    cpu.mem_write(0x51001, palette)
                    initial = b"\xa5" * (ds * max(rows, 1) + 4)
                    expected = bytearray(initial)
                    for y in range(rows):
                        for x in range(0, width, 16):
                            pens = mapped[y * ss + x:y * ss + x + 16]
                            words = [sum(((pen >> plane) & 1) << (15 - i)
                                         for i, pen in enumerate(pens)) for plane in range(4)]
                            struct.pack_into(">4H", expected, 2 + y * ds + x // 2, *words)
                    for mode, data in (("_pens", mapped), ("_byte", source)):
                        cpu.mem_write(0x20002, data)
                        args = [0x1000, 0x60002, 0x20002, width, rows]
                        if mode == "_byte":
                            args.append(0x51001)
                        if suffix:
                            args += [ss, ds]
                        cpu.mem_write(0x7f000, struct.pack(f">{len(args)}I", *args))
                        cpu.mem_write(0x60000, initial)
                        cpu.reg_write(regs.UC_M68K_REG_A7, 0x7f000)
                        name = "_c2p1x1_4_st" + mode + suffix
                        cpu.emu_start(0x10000 + entries[name], 0x1000, count=100000)
                        self.assertEqual(cpu.reg_read(regs.UC_M68K_REG_PC), 0x1000, name)
                        self.assertEqual(cpu.mem_read(0x60000, len(initial)), expected, name)
