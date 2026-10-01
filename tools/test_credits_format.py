"""Compare the Atari credits formatter with printf for every uint16 value."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CreditsFormatTest(unittest.TestCase):
    def test_all_values(self):
        source = (ROOT / "src/gui/gui.c").read_text()
        start = source.index("static void GUI_FormatCredits(")
        formatter = source[start:source.index("\n}", start) + 2]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
typedef uint16_t uint16;
#define lengthof(a) (sizeof(a) / sizeof((a)[0]))
/* FORMATTER */
int main(void) {
    unsigned value;
    char expected[7], guarded[9];
    for (value = 0; value <= UINT16_MAX; value++) {
        memset(guarded, '@', sizeof(guarded));
        snprintf(expected, sizeof(expected), "%6hu", (uint16)value);
        GUI_FormatCredits((uint16)value, guarded + 1);
        if (memcmp(expected, guarded + 1, sizeof(expected))) {
            fprintf(stderr, "Credits mismatch at %u: expected '%s', actual '%s'\n",
                    value, expected, guarded + 1);
            return 1;
        }
        assert(guarded[0] == '@' && guarded[8] == '@');
    }
#ifdef TOS
    {
        volatile unsigned checksum = 0;
        clock_t start, oldTicks, newTicks;
        unsigned i, j;
        FILE *out = fopen("BENCH.TXT", "w");
        assert(out != NULL);
        start = clock();
        for (i = 0; i < 5000; i++) {
            snprintf(expected, sizeof(expected), "%6hu", (uint16)(i * 13));
            for (j = 0; j < sizeof(expected); j++) checksum += expected[j];
        }
        oldTicks = clock() - start;
        start = clock();
        for (i = 0; i < 5000; i++) {
            GUI_FormatCredits((uint16)(i * 13), expected);
            for (j = 0; j < sizeof(expected); j++) checksum += expected[j];
        }
        newTicks = clock() - start;
        fprintf(out, "5000 formats: printf=%ld specialized=%ld ticks, Hz=%ld checksum=%u\n",
                (long)oldTicks, (long)newTicks, (long)CLOCKS_PER_SEC, checksum);
        fclose(out);
        assert(newTicks < oldTicks);
    }
#endif
    return 0;
}
"""
        harness = harness.replace("/* FORMATTER */", formatter)
        with tempfile.TemporaryDirectory(prefix="credits-format-") as directory:
            test = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            test.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(test), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
