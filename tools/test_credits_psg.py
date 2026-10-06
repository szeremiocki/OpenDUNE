"""Exercise the credits PSG list with both 20 ms and 40 ms delay semantics."""

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class CreditsPSGTest(unittest.TestCase):
    def test_68000_interrupt_guard(self):
        compiler, objdump = "m68k-atari-mint-gcc", "m68k-atari-mint-objdump"
        if shutil.which(compiler) is None or shutil.which(objdump) is None:
            self.skipTest("Atari compiler and objdump required")
        with tempfile.TemporaryDirectory(prefix="credits-psg-68000-") as directory:
            obj = Path(directory) / "driver.o"
            for resident in (0, 1):
                subprocess.run(
                    [compiler, "-m68000", "-msoft-float", "-Ofast", "-fno-split-paths",
                     "-fomit-frame-pointer", "-std=gnu17", "-DTOS", "-DNDEBUG",
                     f"-DATARI_SUPERVISOR_RESIDENT={resident}",
                     "-I", str(ROOT / "include"), "-I", str(ROOT / "objs/release"),
                     "-c", str(ROOT / "src/audio/driver.c"), "-o", str(obj)], check=True)
                assembly = subprocess.check_output([objdump, "-d", str(obj)], text=True)
                names = ["Driver_CreditsPSG_Exec"]
                if resident:
                    names.append("Driver_Sound_PlayCredits")
                for name in names:
                    body = re.search(
                        rf"<_{name}>:\n(.*?)(?=\n[0-9a-f]+ <_|\Z)",
                        assembly, re.S).group(1)
                    register = re.search(r"movew %sr,(%d\d)", body).group(1)
                    self.assertIn("oriw #1792,%sr", body)
                    self.assertIn(f"movew {register},%sr", body)

    def test_sequence_ownership_settings_and_shutdown(self):
        driver = (ROOT / "src/audio/driver.c").read_text()
        start = driver.index("static uint8 s_creditsPSG[]")
        declarations = driver[start:driver.index("\nstatic void Driver_CreditsPSG_Update", start)]
        core = "\n".join(function(driver, name) for name in
                         ("Driver_CreditsPSG_Update", "Driver_CreditsPSG_Stop"))
        self.assertIn("Driver_CreditsPSG_Stop();", function(driver, "Driver_Sound_Stop"))
        self.assertIn("Driver_CreditsPSG_Stop();", function(driver, "Drivers_All_Uninit"))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
static unsigned midiCalls, midiIndex;
static void Driver_Sound_Play(int index, int volume) {
    assert(volume == 255);
    midiCalls++;
    midiIndex = index;
}
#ifdef TOS
static struct { uint16 sounds; } g_gameConfig = {1};
static bool g_enableSoundMusic = true;
static bool direct = true, locked;
static uint8 registers[16], original[16];
static const uint8 *playing;
static unsigned starts, accesses, delay, waits, ticks;
static bool emutos;
static bool Video_Atari_CursorDirect(void) { return direct; }
void Driver_Sound_PlayCredits(bool increasing);
void Driver_Sound_Stop(void);
void Drivers_All_Uninit(void);
typedef struct { uint16 index; } Driver;
typedef struct { uint16 index; } MSBuffer;
static Driver sound = {0xffff}, *g_driverSound = &sound;
static MSBuffer *g_bufferSound[4];
static unsigned soundUninit, voiceUninit;
static void MPU_Stop(uint16 index) { (void)index; assert(false); }
static void MPU_ClearData(uint16 index) { (void)index; assert(false); }
static void Drivers_SoundMusic_Uninit(void) {
    assert(!playing && registers[10] == 0);
    soundUninit++;
}
static void Drivers_Voice_Uninit(void) { voiceUninit++; }
static long Dosound(const void *list) {
    assert(locked);
    const uint8 *old = playing;
    if (list != (const void *)-1L) {
        playing = list;
        delay = 0;
        if (list != NULL) starts++;
    }
    return (long)old;
}
static int Giaccess(int value, int reg) {
    assert(locked && (reg & 127) < 16);
    accesses++;
    if (reg & 128) registers[reg & 127] = value;
    return registers[reg & 127];
}
static long Driver_CreditsPSG_Exec(void);
#define Atari_SupervisorExec(callback) do { \
    assert(!locked); locked = true; (callback)(); locked = false; \
} while (0)
/* DECLARATIONS */
/* CORE */
/* The real wrapper masks interrupts; exercise its body under the same lock. */
static long Driver_CreditsPSG_Exec(void) {
    assert(locked);
    Driver_CreditsPSG_Update();
    return 0;
}
/* LIFECYCLE */
static void irq(void) {
    unsigned instructions = 0;
    assert(!locked);
    ticks++;
    if (!playing) return;
    if (delay) {
        delay--;
        if (emutos || delay) return;
    }
    while (playing) {
        uint8 command = *playing++, value = *playing++;
        assert(++instructions <= 16);
        if (command >= 0x82) {
            delay = value;
            waits += value != 0;
            if (!value) playing = NULL;
            return;
        }
        assert(command < 16);
        /* The list must not touch A/B, noise, envelopes or PSG I/O ports. */
        assert(command == 4 || command == 5 || command == 7 || command == 10);
        if (command == 7) {
            assert((value & 0x1b) == (original[7] & 0x1b));
            /* Both stock TOS and EmuTOS retain current I/O-direction bits. */
            value = (value & 0x3f) | (registers[7] & 0xc0);
        }
        registers[command] = value;
    }
}
static void finish(void) {
    unsigned before = ticks;
    while (playing) {
        assert(ticks - before < 4);
        irq();
    }
    assert(!memcmp(registers, original, sizeof(registers)));
}
static void reset(unsigned mixer) {
    assert(!playing);
    for (unsigned i = 0; i < 16; i++) registers[i] = i * 7;
    registers[7] = mixer;
    registers[10] = 0;
    memcpy(original, registers, sizeof(original));
}
static void scenarios(void) {
    for (unsigned semantics = 0; semantics < 2; semantics++)
    for (unsigned mixer = 0; mixer < 256; mixer++) {
        emutos = semantics != 0;
        reset(mixer);
        unsigned before = starts, beforeWaits = waits;
        Driver_Sound_PlayCredits(true);
        assert(starts == before + 1 && playing == s_creditsPSG);
        assert(!memcmp(registers, original, sizeof(registers))); /* deferred */
        uint8 saved[sizeof(s_creditsPSG)];
        memcpy(saved, s_creditsPSG, sizeof(saved));
        Driver_Sound_PlayCredits(false);
        assert(starts == before + 1 && !memcmp(saved, s_creditsPSG, sizeof(saved)));
        irq();
        assert(registers[4] == 64 && registers[5] == 0 && registers[10] == 8);
        assert(!(registers[7] & 4) && (registers[7] & 32));
        Driver_Sound_PlayCredits(false);
        assert(starts == before + 1 && !memcmp(saved, s_creditsPSG, sizeof(saved)));
        finish();
        assert(waits == beforeWaits + 1);
        Driver_Sound_PlayCredits(false);
        irq();
        assert(registers[4] == 80);
        finish();
        Driver_Sound_PlayCredits(true);
        Driver_Sound_Stop(); /* cancel before the first interpreter tick */
        assert(!playing && !s_creditsPSGStarted);
        assert(!memcmp(registers, original, sizeof(registers)));
        Driver_Sound_PlayCredits(true);
        irq();
        Drivers_All_Uninit(); /* cancel while audible, before other teardown */
        assert(!playing && !registers[10]);
        assert(!memcmp(registers, original, sizeof(registers)));
    }
    assert(soundUninit == 512 && voiceUninit == 512);
    reset(0xc0);
    Driver_Sound_PlayCredits(true);
    irq();
    registers[7] ^= 0xc0; /* An OS port-direction change must survive the tail. */
    original[7] ^= 0xc0;
    finish();
    static const uint8 foreign[] = {8, 15, 0x82, 1, 8, 0, 0x82, 0};
    reset(0xc0);
    unsigned before = starts, beforeAccesses = accesses;
    playing = foreign;
    Driver_Sound_PlayCredits(true);
    Driver_CreditsPSG_Stop();
    assert(playing == foreign && starts == before && accesses == beforeAccesses);
    playing = NULL;
    registers[10] = 5;
    Driver_Sound_PlayCredits(true);
    assert(!playing && starts == before && registers[10] == 5);
    registers[10] = 0;
    Driver_Sound_PlayCredits(true);
    irq();
    /* A replacement OS sound owns the chip: cleanup must not alter its list/registers. */
    playing = foreign;
    memcpy(original, registers, sizeof(original));
    beforeAccesses = accesses;
    Driver_CreditsPSG_Stop();
    assert(playing == foreign && accesses == beforeAccesses);
    assert(!memcmp(registers, original, sizeof(registers)));
    playing = NULL;
    registers[10] = 0;
    before = starts;
    g_gameConfig.sounds = 0;
    Driver_Sound_PlayCredits(true);
    assert(starts == before);
    g_gameConfig.sounds = 1;
    g_enableSoundMusic = false;
    Driver_Sound_PlayCredits(true);
    assert(starts == before);
    g_enableSoundMusic = true;
    direct = false; /* TT/Falcon retain MIDI. */
}
#endif
/* PLAY */
int main(void) {
#ifdef TOS
    scenarios();
    assert(midiCalls == 0);
#endif
    Driver_Sound_PlayCredits(true);
    assert(midiCalls == 1 && midiIndex == 52);
    Driver_Sound_PlayCredits(false);
    assert(midiCalls == 2 && midiIndex == 53);
    return 0;
}
"""
        harness = harness.replace("/* DECLARATIONS */", declarations).replace("/* CORE */", core)
        harness = harness.replace("/* LIFECYCLE */", "\n".join(
            function(driver, name) for name in ("Driver_Sound_Stop", "Drivers_All_Uninit")))
        harness = harness.replace("/* PLAY */", function(driver, "Driver_Sound_PlayCredits"))
        with tempfile.TemporaryDirectory(prefix="credits-psg-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for platform in ([], ["-DTOS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                                *flags, *platform, str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
