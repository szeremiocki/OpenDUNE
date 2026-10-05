"""Check the real 68000 object; execution/profiling remains a target-side check."""

from pathlib import Path
import re
import shutil
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
                    r"^([0-9a-f]+)\s+T\s+(_c2p1x1_4_st(?:_strided)?)$", symbols, re.M):
                entries[name] = int(address, 16)
            self.assertEqual(len(entries), 2)
            code = binary.read_bytes()
            blocks = [
                disassembly.split("<" + name + ">:", 1)[1].split(
                    "\n" + format(entries["_c2p1x1_4_st_strided"], "08x") + " <", 1)[0]
                for name in ("_c2p1x1_4_st", "_c2p1x1_4_st_strided")
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
