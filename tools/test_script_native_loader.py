"""Exercise native script construction, loader fallback and buffer ownership."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_script_budget import ROOT, function


class ScriptNativeLoaderTest(unittest.TestCase):
    def test_decode_and_lifetime(self):
        source = (ROOT / "src/script/script.c").read_text()
        native = (ROOT / "src/script/script_native.c").read_text()
        production = function(native, "Script_CompileNative") + "\n"
        production += "\n".join(function(source, name) for name in
                                ("Script_ClearInfo", "Script_LoadFromFile"))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int8_t int8;
typedef int16_t int16;
#include "/* HEADER */"
#include "/* ENDIAN */"
#include "/* FOURCC */"
const uint32 Script_NativeHandlers[] = {/* HANDLERS */};
uint16 endian_bswap16(uint16 value) {
    return (uint16)((value << 8) | (value >> 8));
}
uint32 endian_bswap32(uint32 value) {
    return ((value & 0xff) << 24) | ((value & 0xff00) << 8) |
           ((value >> 8) & 0xff00) | (value >> 24);
}
static bool nativeST = true, exists = true, failDecode;
static unsigned warnings, opened, closed;
static const uint8 text[] = {1, 2, 3};
static uint16 offsets[2], data[4];
static uint32 orderLength = sizeof(offsets), dataLength = sizeof(data);
static bool Video_Atari_CursorDirect(void) { return nativeST; }
static bool File_Exists(const char *filename) {
    assert(!strcmp(filename, "TEST.EMC"));
    return exists;
}
static uint8 ChunkFile_Open(const char *filename) {
    assert(!strcmp(filename, "TEST.EMC"));
    opened++;
    return 7;
}
static uint32 ChunkFile_Seek(uint8 index, uint32 chunk) {
    assert(index == 7);
    if (chunk == HTOBE32(CC_TEXT)) return sizeof(text);
    if (chunk == HTOBE32(CC_ORDR)) return orderLength;
    assert(chunk == HTOBE32(CC_DATA));
    return dataLength;
}
static void ChunkFile_Read(uint8 index, uint32 chunk, void *buffer, uint32 length) {
    assert(index == 7 && buffer != NULL);
    const void *source = chunk == HTOBE32(CC_TEXT) ? (const void *)text :
                         chunk == HTOBE32(CC_ORDR) ? (const void *)offsets :
                         (const void *)data;
    memcpy(buffer, source, length);
}
static void ChunkFile_Close(uint8 index) {
    assert(index == 7);
    closed++;
}
static void Warning(const char *format, const char *filename) {
    assert(strstr(format, "using bytecode decoder") != NULL);
    assert(!strcmp(filename, "TEST.EMC"));
    warnings++;
}
static void *test_calloc(size_t count, size_t size) {
    if (failDecode && count == 4 && size == 16)
        return NULL;
    return calloc(count, size);
}
#define calloc test_calloc
/* PRODUCTION */
#undef calloc
static const ScriptFunction callbacks[SCRIPT_FUNCTIONS_COUNT] = {0};
static void check_loaded(const ScriptInfo *info, bool cached) {
    assert(info->functions == callbacks);
    assert(info->startCount == 4 && info->offsetsCount == 2);
    assert(info->offsets[0] == 0 && info->offsets[1] == 2);
    assert(!memcmp(info->start, data, sizeof(data)));
    assert((info->nativeCode != NULL) == cached);
    if (cached) {
        assert(BETOH16(info->nativeCode[0]) == 0x58aa);
        assert(BETOH16(info->nativeCode[2]) == 0x357c);
        assert(BETOH16(info->nativeCode[3]) == 0xf123);
        assert(BETOH16(info->nativeCode[2 * 8 + 3]) == 0xffff);
        assert(BETOH16(info->nativeCode[3 * 8 + 4]) == 0x7e10);
        assert(BETOH16(info->nativeCode[3 * 8 + 3]) == 2);
    }
}
int main(void) {
    ScriptInfo info = {0};
    assert(!Script_CompileNative(&info) && info.nativeCode == NULL);
    /* All flag combinations, opcode bits and signed inline parameters. */
    uint16 words[2];
    info.start = words;
    info.startCount = 2;
    for (unsigned encoding = 0; encoding <= 0xffff; encoding++) {
        words[0] = HTOBE16(encoding);
        words[1] = HTOBE16(0xf123);
        assert(Script_CompileNative(&info));
        unsigned opcode = (encoding >> 8) & 31;
        uint16 parameter = 0;
        unsigned length = 1;
        if (encoding & 0x8000) {
            opcode = SCRIPT_JUMP;
            parameter = encoding & 0x7fff;
        } else if (encoding & 0x4000) {
            parameter = (int16)(int8)(encoding & 255);
        } else if (encoding & 0x2000) {
            parameter = 0xf123;
            length = 2;
        }
        unsigned handler = opcode <= SCRIPT_RETURN ? opcode : 40;
        if ((opcode == SCRIPT_PUSH_RETURN_OR_LOCATION ||
             opcode == SCRIPT_POP_RETURN_OR_LOCATION) && parameter > 1) handler = 40;
        if (opcode == SCRIPT_UNARY) handler = parameter < 3 ? 19 + parameter : 40;
        if (opcode == SCRIPT_BINARY) handler = parameter < 18 ? 22 + parameter : 43;
        uint16 operation = 0x323c;
        uint16 argument = handler < 40 ? 0x7e00 | length * 16 : opcode | 0x7000;
        if (opcode == SCRIPT_SETRETURNVALUE || opcode == SCRIPT_STACK_REWIND ||
            opcode == SCRIPT_STACK_FORWARD) {
            handler = length == 1 ? 42 : 44;
            operation = opcode == SCRIPT_SETRETURNVALUE ? 0x357c :
                        opcode == SCRIPT_STACK_REWIND ? 0x062a : 0x042a;
            argument = opcode == SCRIPT_SETRETURNVALUE ? 10 : 13;
            if (opcode != SCRIPT_SETRETURNVALUE) parameter &= 255;
        }
        uint32 target = ((uint32)BETOH16(info.nativeCode[6]) << 16) |
                        BETOH16(info.nativeCode[7]);
        assert(BETOH16(info.nativeCode[0]) == (length == 1 ? 0x54aa : 0x58aa));
        assert(BETOH16(info.nativeCode[1]) == 2);
        assert(BETOH16(info.nativeCode[2]) == operation);
        assert(BETOH16(info.nativeCode[3]) == parameter);
        assert(BETOH16(info.nativeCode[4]) == argument);
        assert(BETOH16(info.nativeCode[5]) == 0x4ef9);
        assert(target == Script_NativeHandlers[handler]);
        Script_ClearInfo(&info);
        info.start = words;
    }
    /* The uint16 loop must terminate even at the largest DATA word count. */
    Script_ClearInfo(&info);
    info.isAllocated = 1;
    info.startCount = 0xffff;
    info.start = calloc(info.startCount, sizeof(*info.start));
    assert(info.start != NULL);
    info.start[0xfffe] = HTOBE16(0x2100);
    assert(Script_CompileNative(&info));
    assert(BETOH16(info.nativeCode[0xfffe * 8]) == 0x4e71);
    assert(BETOH16(info.nativeCode[0xfffe * 8 + 4]) == 0x7021);
    Script_ClearInfo(&info);

    offsets[0] = HTOBE16(0); offsets[1] = HTOBE16(2);
    data[0] = HTOBE16(0x2100); data[1] = HTOBE16(0xf123);
    data[2] = HTOBE16(0x41ff); data[3] = HTOBE16(0x8002);
    uint16 borrowed[32] = {0};
    for (unsigned owned = 0; owned < 2; owned++) {
        uint8 *buffer = owned ? NULL : (uint8 *)borrowed;
        for (unsigned cached = 0; cached < 2; cached++) {
            nativeST = cached != 0;
            for (unsigned reload = 0; reload < 3; reload++) {
                assert(Script_LoadFromFile("TEST.EMC", &info, callbacks, buffer) == 15);
                check_loaded(&info, cached != 0);
                assert(info.isAllocated == owned);
                if (!owned) {
                    assert(info.text == borrowed);
                    assert(info.offsets == borrowed + 2);
                    assert(info.start == borrowed + 4);
                }
            }
        }
        nativeST = true;
        failDecode = true;
        unsigned before = warnings;
        assert(Script_LoadFromFile("TEST.EMC", &info, callbacks, buffer) == 15);
        check_loaded(&info, false);
        assert(warnings == before + 1);
        failDecode = false;
        assert(Script_LoadFromFile("TEST.EMC", &info, callbacks, buffer) == 15);
        check_loaded(&info, true);
        /* Failure after a successful load must release the previous cache. */
        for (unsigned missing = 0; missing < 3; missing++) {
            exists = missing != 0;
            orderLength = missing == 1 ? 0 : sizeof(offsets);
            dataLength = missing == 2 ? 0 : sizeof(data);
            assert(Script_LoadFromFile("TEST.EMC", &info, callbacks, buffer) == 0);
            assert(info.nativeCode == NULL && info.start == NULL);
            assert(info.text == NULL && info.offsets == NULL);
            exists = true;
            orderLength = sizeof(offsets);
            dataLength = sizeof(data);
            assert(Script_LoadFromFile("TEST.EMC", &info, callbacks, buffer) == 15);
            check_loaded(&info, true);
        }
        Script_ClearInfo(&info);
        Script_ClearInfo(&info);
        assert(info.nativeCode == NULL && info.start == NULL);
    }
    Script_ClearInfo(NULL);
    assert(Script_LoadFromFile(NULL, &info, callbacks, NULL) == 0);
    assert(Script_LoadFromFile("TEST.EMC", NULL, callbacks, NULL) == 0);
    assert(opened == closed);
    return 0;
}
"""
        harness = harness.replace("/* HEADER */", str(ROOT / "src/script/script.h"))
        harness = harness.replace("/* ENDIAN */", str(ROOT / "src/os/endian.h"))
        harness = harness.replace("/* FOURCC */", str(ROOT / "include/multichar.h"))
        harness = harness.replace("/* HANDLERS */",
                                  ",".join(hex(0x100000 + i * 16) for i in range(45)))
        harness = harness.replace("/* PRODUCTION */", production)
        with tempfile.TemporaryDirectory(prefix="script-native-loader-") as directory:
            c_file = Path(directory) / "test.c"
            c_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            binary = Path(directory) / "test"
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", "-DTOS", str(c_file), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
