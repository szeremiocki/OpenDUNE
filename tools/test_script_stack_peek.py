"""Check inline argument reads against the out-of-line stack helper."""

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from tools.test_script_budget import ROOT


class ScriptStackPeekTest(unittest.TestCase):
    def test_checked_read_and_diagnostics(self):
        source = (ROOT / "src/script/script.c").read_text()
        start = source.index("#ifdef _DEBUG\nuint16 Script_Stack_Peek")
        reference = source[start:source.index("\n}\n", start) + 3]
        reference = reference.replace("Script_Stack_Peek(", "reference_peek(")
        harness = r"""
#include <assert.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
#include "/* HEADER */"
static unsigned errors, fallbackCalls;
static char diagnostic[256];
static void Script_Error(const char *format, ...) {
    va_list args;
    va_start(args, format);
    vsnprintf(diagnostic, sizeof(diagnostic), format, args);
    va_end(args);
    errors++;
}
/* REFERENCE */
#ifdef _DEBUG
uint16 Script_Stack_Peek(ScriptEngine *script, int position, const char *filename, int lineno) {
    fallbackCalls++;
    return reference_peek(script, position, filename, lineno);
}
#else
uint16 Script_Stack_Peek(ScriptEngine *script, int position) {
    fallbackCalls++;
    return reference_peek(script, position);
}
#endif
static uint16 argument(ScriptEngine *script, int position) {
#line 101 "peek-caller.c"
    return STACK_PEEK(position);
#line 1 "peek-test.c"
}
static void check(unsigned stackPointer, int position) {
    uint16 words[8] = {0};
    ScriptEngine seed = {0};
    seed.script = words;
    seed.stackPointer = stackPointer;
    seed.framePointer = 9;
    seed.returnValue = 0x1234;
    for (unsigned i = 0; i < 15; i++) seed.stack[i] = 0x9000 + i;
    ScriptEngine expected = seed, actual = seed;
    errors = fallbackCalls = 0;
    diagnostic[0] = '\0';
#ifdef _DEBUG
    uint16 value = reference_peek(&expected, position, "peek-caller.c", 101);
#else
    uint16 value = reference_peek(&expected, position);
#endif
    unsigned expectedErrors = errors;
    char expectedDiagnostic[sizeof(diagnostic)];
    memcpy(expectedDiagnostic, diagnostic, sizeof(diagnostic));
    errors = 0;
    diagnostic[0] = '\0';
    assert(argument(&actual, position) == value);
    assert(!memcmp(&expected, &actual, sizeof(actual)));
    assert(errors == expectedErrors);
    assert(!strcmp(diagnostic, expectedDiagnostic));
    bool valid = position <= 15 && stackPointer < (unsigned)(16 - position);
    assert(fallbackCalls == (valid ? 0 : 1));
}
int main(void) {
    for (unsigned stack = 0; stack <= 255; stack++) {
        for (int position = 1; position <= 32; position++) check(stack, position);
        check(stack, INT_MAX);
    }
    ScriptEngine state = {0};
    state.stackPointer = 7;
    state.stack[7] = 0xffff;
    ScriptEngine *script = &state;
    int position = 1;
    errors = fallbackCalls = 0;
    assert(STACK_PEEK(position++) == 0xffff);
    assert(position == 2 && errors == 0 && fallbackCalls == 0);
    return 0;
}
"""
        harness = harness.replace("/* HEADER */", str(ROOT / "src/script/script.h"))
        harness = harness.replace("/* REFERENCE */", reference)
        compiler = shlex.split(os.environ.get("CC", "cc"))
        with tempfile.TemporaryDirectory(prefix="script-peek-") as directory:
            source = Path(directory) / "test.c"
            source.write_text(harness)
            for debug in (False, True):
                with self.subTest(debug=debug):
                    binary = Path(directory) / f"test-{debug}"
                    subprocess.run([
                        *compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                        *(["-D_DEBUG"] if debug else []), str(source), "-o", str(binary),
                    ], check=True)
                    subprocess.run([str(binary)], check=True)

    def test_68000_inline_valid_path(self):
        compiler = shutil.which("m68k-atari-mint-gcc")
        if compiler is None:
            self.skipTest("68000 code generation requires the Atari cross compiler")
        harness = f"""
#include <stdbool.h>
#include <stdint.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
#include "{ROOT / 'src/script/script.h'}"
uint16 peek_argument(ScriptEngine *script) {{ return STACK_PEEK(1); }}
"""
        with tempfile.TemporaryDirectory(prefix="script-peek-68000-") as directory:
            source = Path(directory) / "test.c"
            assembly = Path(directory) / "test.s"
            source.write_text(harness)
            subprocess.run([
                compiler, "-m68000", "-msoft-float", "-Ofast", "-fno-split-paths",
                "-fomit-frame-pointer", "-std=gnu17", "-DNDEBUG", "-DTOS",
                "-S", str(source), "-o", str(assembly),
            ], check=True)
            text = assembly.read_text()
            self.assertRegex(text, r"\brts\b")
            fallback = re.search(
                r"\b(?:jbsr|jsr|jra|jmp)\b[^\n]*_Script_Stack_Peek\b", text
            )
            self.assertIsNotNone(fallback, text)
            branch = re.search(r"^\s*jge\s+(\.L\d+)\s*$", text, re.M)
            self.assertIsNotNone(branch, text)
            valid_path = text.split(branch[1] + ":", 1)[1].split("rts", 1)[0]
            self.assertRegex(valid_path, r"\bmove\.w\b")
            self.assertNotRegex(valid_path, r"\b(?:jbsr|jsr|jra|jmp)\b")
            self.assertNotIn("_Script_Stack_PeekInline", text)


if __name__ == "__main__":
    unittest.main()
