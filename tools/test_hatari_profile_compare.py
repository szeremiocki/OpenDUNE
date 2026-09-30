"""Small format/attribution tests for the standalone Hatari profile reader."""

import tempfile
import unittest
from pathlib import Path

from hatari_profile_compare import parse_profile


HEADER = """Hatari CPU profile
Cycles/second: 1000
Field names: Executed instructions, Used cycles, Instruction cache misses, Data cache hits
Field regexp: deliberately incorrect
ST_RAM: 0x000000-0x400000
ROM_TOS: 0xe00000-0xe40000
CARTRIDGE: 0xfa0000-0xfc0000
PROGRAM_TEXT: 0x010000-0x020000
"""


class ProfileTests(unittest.TestCase):
    def parse(self, body, newline="\n"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.txt"
            path.write_bytes((HEADER + body).replace("\n", newline).encode("utf-8"))
            return parse_profile(path)

    def test_plain_crlf_local_labels_duplicates_and_rom(self):
        profile = self.parse("""_draw:
00010000 4e71 NOP 10.00% (2, 8, 0, 0)
loop:
00010002 4e75 RTS 10.00% (3, 48, 0, 0)
_draw:
00010010 4e75 RTS 10.00% (4, 64, 0, 0)
00E007E2 52b8 04ba ADDQ.L #$01,$04ba 10.00% (200, 4800, 0, 0)
00FA002A 0008 ILLEGAL 10.00% (1, 4, 0, 0)
""", "\r\n")
        self.assertEqual(profile["total_cycles"], 4924)
        self.assertEqual(profile["functions"]["_draw"]["cycles"], 120)
        self.assertEqual(profile["functions"]["_draw"]["entry_executions"], 6)
        self.assertEqual(profile["functions"]["_draw"]["entries"], [0x10000, 0x10010])
        self.assertEqual(profile["functions"]["<ROM_TOS>"]["cycles"], 4800)
        self.assertEqual(profile["functions"]["<CARTRIDGE>"]["cycles"], 4)
        self.assertEqual(profile["tos_clock_seconds"], 1)

    def test_dollar_format_and_caller_totals(self):
        profile = self.parse("""_caller:
$010000 : NOP 10.00% (2, 8, 0, 0)
_callee:
$010010 : RTS 10.00% (2, 32, 0, 0)
0x10010: 0x10000 = 2 s 5/12/80/0/0 2/4/32/0/0, 0xe00814 = 1 x, _callee
""")
        self.assertEqual(profile["total_cycles"], 40)
        self.assertEqual(profile["callers"][0]["caller"], "_caller")
        self.assertEqual(profile["callers"][0]["callee"], "_callee")
        self.assertEqual(profile["callers"][0]["inclusive"], [5, 12, 80, 0, 0])
        self.assertEqual(profile["callers"][0]["exclusive"], [2, 4, 32, 0, 0])
        self.assertEqual(profile["callers"][1]["types"], "x")
        self.assertIsNone(profile["tos_clock_seconds"])

    def test_invalid_counters_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid instruction counters"):
            self.parse("_draw:\n00010000 NOP 10.00% (bad, 8, 0, 0)\n")

    def test_field_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "field count mismatch"):
            self.parse("_draw:\n00010000 NOP 10.00% (1, 8)\n")

    def test_duplicate_instruction_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate instruction"):
            self.parse("""_draw:
00010000 NOP 10.00% (1, 8, 0, 0)
00010000 NOP 10.00% (1, 8, 0, 0)
""")

    def test_malformed_caller_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid caller record"):
            self.parse("""_draw:
00010000 NOP 10.00% (1, 8, 0, 0)
0x10000: 0x10000 = not-a-count s, _draw
""")


if __name__ == "__main__":
    unittest.main()
