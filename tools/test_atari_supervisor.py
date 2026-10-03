"""Check opt-in supervisor residency, dispatch and actual 68000 entry points."""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class AtariSupervisorTest(unittest.TestCase):
    def test_lifecycle_and_dispatch(self):
        source = (ROOT / "src/opendune.c").read_text()
        functions = "\n".join(function(source, name) for name in
                              ("Atari_SupervisorRestore", "Atari_SupervisorInit"))
        harness = r"""
#include <assert.h>
#include <stddef.h>
#include "os/atari.h"
static unsigned traps, calls;
#if ATARI_SUPERVISOR_RESIDENT
static unsigned entries, restores, registrations, errors;
bool g_atariSupervisorResident;
static long cookie;
static bool found, supervisor, registrationFails;
static void (*onExit)(void);
#define C__MCH 0x5f4d4348L
#define C_FOUND 0
static int Getcookie(long key, long *value) {
    assert(key == C__MCH); *value = cookie; return found ? C_FOUND : -1;
}
static long super(long value) {
    if (value == 1) return supervisor ? -1 : 0;
    assert(value == 0 && !supervisor);
    supervisor = true; entries++; return 0x1234;
}
static void restore(long stack) {
    assert(supervisor && !g_atariSupervisorResident && stack == 0x1234);
    restores++; supervisor = false;
}
static int register_exit(void (*callback)(void)) {
    assert(!supervisor); registrations++; onExit = callback;
    return registrationFails ? -1 : 0;
}
#define Super(value) super(value)
#define SuperToUser(stack) restore(stack)
#define atexit(callback) register_exit(callback)
#define Error(...) (++errors)
#define Debug(...) ((void)0)
static long s_atariSupervisorStack;
/* FUNCTIONS */
#endif
static void write_registers(void) { calls++; }
static long read_registers(void) { calls++; return 0xab; }
int main(void) {
#if ATARI_SUPERVISOR_RESIDENT
    long machines[] = {0, 0x10000, 0x10010, 0x20000, 0x30000, 0x40000};
    for (unsigned i = 0; i < sizeof(machines) / sizeof(machines[0]); i++)
        for (unsigned hasCookie = 0; hasCookie < 2; hasCookie++) {
            cookie = machines[i]; found = hasCookie;
            entries = restores = registrations = traps = calls = errors = 0;
            supervisor = registrationFails = g_atariSupervisorResident = false;
            onExit = NULL;
            assert(Atari_SupervisorInit());
            bool active = !found || i < 3;
            assert(g_atariSupervisorResident == active && supervisor == active);
            assert(entries == active && registrations == active);
            Atari_SupervisorExec(write_registers);
            assert(Atari_SupervisorRead(read_registers) == 0xab);
            assert(calls == 2 && traps == (active ? 0 : 2));
            if (onExit) onExit();
            assert(restores == active && !supervisor && !g_atariSupervisorResident);
        }
    found = true; cookie = 0x10000; supervisor = true;
    entries = restores = registrations = 0; onExit = NULL;
    assert(Atari_SupervisorInit() && g_atariSupervisorResident);
    assert(!entries && !registrations && !onExit);
    supervisor = g_atariSupervisorResident = false;
    registrationFails = true; errors = 0;
    assert(!Atari_SupervisorInit());
    assert(errors == 1 && !entries && !supervisor && !g_atariSupervisorResident);
#else
    Atari_SupervisorExec(write_registers);
    assert(Atari_SupervisorRead(read_registers) == 0xab);
    assert(calls == 2 && traps == 2);
#endif
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="atari-supervisor-") as directory:
            temp = Path(directory)
            (temp / "mint").mkdir()
            (temp / "mint/osbind.h").write_text(
                "#define Supexec(callback) (traps++, (callback)())\n")
            cfile, exe = temp / "test.c", temp / "test"
            cfile.write_text(harness.replace("/* FUNCTIONS */", functions))
            for enabled in (0, 1):
                subprocess.run(["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                                f"-DATARI_SUPERVISOR_RESIDENT={enabled}", "-I", str(temp),
                                "-iquote", str(ROOT / "src"), "-I", str(ROOT / "include"),
                                str(cfile), "-o", str(exe)], check=True)
                subprocess.run([str(exe)], check=True)
        main = function(source, "main")
        self.assertLess(main.index("atexit(exit_handler)"), main.index("Atari_SupervisorInit()"))
        self.assertLess(main.index("Atari_SupervisorInit()"), main.index("Load_IniFile()"))
        init = function(source, "Atari_SupervisorInit")
        self.assertLess(init.index("atexit(Atari_SupervisorRestore)"), init.index("Super(0L)"))
        video = (ROOT / "src/video/video_atari.c").read_text()
        self.assertNotRegex(video, r"\bSupexec\(")
        audio = (ROOT / "src/audio/dsp_atari.c").read_text()
        self.assertNotRegex(audio, r"\bSupexec\(")
        play = function(audio, "DSP_Play")
        self.assertIn("if (g_atariSupervisorResident) set_dma_sound_supervisor(", play)
        self.assertIn("set_dma_sound(data + 2, len, DMASOUND_MODE)", play)

    def test_68000_supervisor_stack_binding(self):
        tools = ("m68k-atari-mint-gcc", "m68k-atari-mint-objdump")
        if any(shutil.which(tool) is None for tool in tools):
            self.skipTest("Atari compiler and objdump required")
        source = (ROOT / "src/opendune.c").read_text()
        harness = """
#include <stdlib.h>
#include <mint/cookie.h>
#include "os/atari.h"
#define Error(...) ((void)0)
#define Debug(...) ((void)0)
bool g_atariSupervisorResident;
static long s_atariSupervisorStack;
"""
        harness += "\n".join(function(source, name) for name in
                             ("Atari_SupervisorRestore", "Atari_SupervisorInit"))
        harness += "\nbool exercise(void) { return Atari_SupervisorInit(); }\n"
        with tempfile.TemporaryDirectory(prefix="supervisor-stack-object-") as directory:
            temp = Path(directory)
            cfile, obj = temp / "test.c", temp / "test.o"
            cfile.write_text(harness)
            subprocess.run([tools[0], "-m68000", "-std=gnu17", "-O2", "-fomit-frame-pointer",
                            "-Wall", "-Wextra", "-Werror", "-DATARI_SUPERVISOR_RESIDENT=1",
                            "-iquote", str(ROOT / "src"), "-I", str(ROOT / "include"),
                            "-c", str(cfile), "-o", str(obj)], check=True)
            disassembly = subprocess.check_output([tools[1], "-dr", str(obj)], text=True)
            restore = disassembly.split("<_Atari_SupervisorRestore>:")[1].split("rts")[0]
            self.assertIn("trap #1", restore)
            saved = re.search(r"movel %sp,(%d\d)", restore)
            self.assertIsNotNone(saved)
            self.assertIn(f"moveal {saved.group(1)},%sp", restore)
            self.assertGreaterEqual(disassembly.count("movew #32,%sp@-"), 3)
            self.assertIn("_atexit", disassembly)
            self.assertIn("_Getcookie", disassembly)

    def test_dma_start_stop_and_status_dispatch(self):
        audio = (ROOT / "src/audio/dsp_atari.c").read_text()
        harness = r"""
#include <assert.h>
#include <stddef.h>
#include "os/atari.h"
#define DMASOUND_BUFFER_SIZE 32768
#define DMASOUND_VOC_DIVISOR 96
#define DMASOUND_MODE 0
#define READ_LE_UINT16(p) ((uint16)((p)[0] | ((uint16)(p)[1] << 8)))
#define Warning(...) assert(false)
#define Debug(...) ((void)0)
static unsigned traps, starts, directStarts, stops;
static uint32 dmaStatus;
static const uint8 *s_playingSample;
static uint16 sampleWords[16];
#if ATARI_SUPERVISOR_RESIDENT
bool g_atariSupervisorResident;
#endif
static void check_sample(const void *buffer, uint32 len, uint32 mode) {
    assert(buffer == (uint8 *)sampleWords + 28 && len == 4 && mode == DMASOUND_MODE);
    starts++; dmaStatus = 1;
}
static void set_dma_sound(const void *buffer, uint32 len, uint32 mode) {
    traps++; check_sample(buffer, len, mode);
}
#if ATARI_SUPERVISOR_RESIDENT
static void set_dma_sound_supervisor(const void *buffer, uint32 len, uint32 mode) {
    directStarts++; check_sample(buffer, len, mode);
}
#endif
static void stop_dma_sound(void) { stops++; dmaStatus = 0; }
static uint32 get_dma_status(void) { return dmaStatus; }
/* FUNCTIONS */
int main(void) {
    uint8 *sample = (uint8 *)sampleWords;
    sample[20] = 22;
    sample[22] = 1; sample[23] = 6; sample[26] = DMASOUND_VOC_DIVISOR;
    for (unsigned active = 0; active <= ATARI_SUPERVISOR_RESIDENT; active++) {
        traps = starts = directStarts = stops = 0;
#if ATARI_SUPERVISOR_RESIDENT
        g_atariSupervisorResident = active;
#endif
        DSP_Play(sample);
        assert(starts == 1 && directStarts == active && s_playingSample == sample);
        assert(DSP_GetStatus() == 2);
        DSP_Stop();
        assert(stops == 1 && !s_playingSample);
        assert(DSP_GetStatus() == 0);
        assert(traps == (active ? 0 : 4));
    }
    return 0;
}
"""
        functions = "\n".join(function(audio, name) for name in
                              ("DSP_Play", "DSP_Stop", "DSP_GetStatus"))
        with tempfile.TemporaryDirectory(prefix="supervisor-dma-dispatch-") as directory:
            temp = Path(directory)
            (temp / "mint").mkdir()
            (temp / "mint/osbind.h").write_text(
                "#define Supexec(callback) (traps++, (callback)())\n")
            cfile, exe = temp / "test.c", temp / "test"
            cfile.write_text(harness.replace("/* FUNCTIONS */", functions))
            for enabled in (0, 1):
                subprocess.run(["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                                f"-DATARI_SUPERVISOR_RESIDENT={enabled}", "-I", str(temp),
                                "-iquote", str(ROOT / "src"), "-I", str(ROOT / "include"),
                                str(cfile), "-o", str(exe)], check=True)
                subprocess.run([str(exe)], check=True)

    def test_68000_dma_and_interrupt_entries(self):
        tools = ("vasmm68k_mot", "m68k-atari-mint-objdump")
        if any(shutil.which(tool) is None for tool in tools):
            self.skipTest("Atari assembler and objdump required")
        with tempfile.TemporaryDirectory(prefix="supervisor-object-") as directory:
            temp = Path(directory)
            for filename in ("audio/atari_dma_sound.s", "input/atari_ikbd.s"):
                obj = temp / (Path(filename).stem + ".o")
                subprocess.run([tools[0], "-m68000", "-Faout", "-quiet", "-o", str(obj),
                                str(ROOT / "src" / filename)], check=True)
                disassembly = subprocess.check_output([tools[1], "-d", str(obj)], text=True)
                if filename.startswith("audio"):
                    legacy = disassembly.split("<_set_dma_sound>:")[1].split(
                        "<_set_dma_sound_supervisor>:")[0]
                    direct = disassembly.split("<_set_dma_sound_supervisor>:")[1].split(
                        "<_stop_dma_sound>:")[0]
                    self.assertIn("trap #14", legacy)
                    self.assertIn("#38", legacy)
                    self.assertNotIn("trap", direct)
                    for entry in (legacy, direct):
                        for offset, register in ((24, 7), (20, 6), (16, 5)):
                            self.assertIn(f"movel %sp@({offset}),%d{register}", entry)
                        self.assertIn("addl %d5,%d6", entry)
                        self.assertRegex(entry, r"\bmoveml\b.*%d5-%d7,%sp@-")
                        self.assertRegex(entry, r"\bmoveml\b.*%sp@\+,%d5-%d7")
                    self.assertRegex(direct, r"\bbsr\w*\b.*<setdma>")
                else:
                    for name, end in (("_install_ikbd_handler", "_uninstall_ikbd_handler"),
                                      ("_uninstall_ikbd_handler", "old_ikbd")):
                        entry = disassembly.split(f"<{name}>:")[1].split(f"<{end}>:")[0]
                        self.assertIn("movew %sr,%sp@-", entry)
                        self.assertIn("oriw #1792,%sr", entry)
                        self.assertIn("movew %sp@+,%sr", entry)
                        self.assertNotIn("#8960,%sr", entry)


if __name__ == "__main__":
    unittest.main()
