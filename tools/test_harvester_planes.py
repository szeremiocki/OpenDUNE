"""Compare offline harvester analysis with production decoding and planar code."""

import ctypes
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools import analyze_harvester_planes as analysis
from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]
WORD = ctypes.c_uint16
BYTE = ctypes.c_uint8


@unittest.skipUnless((ROOT / "DUNE.PAK").is_file(), "Local DUNE.PAK assets required")
class HarvesterPlanesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        files = analysis.read_pak(ROOT / "DUNE.PAK")
        cls.sprites = analysis.load_sprites(files)
        cls.palette = files["IBM.PAL"]
        cls.lookup = analysis.palette_lookup(cls.palette)
        cls.variants = [*analysis.build_variants(cls.sprites, cls.lookup),
                        *analysis.build_variants(cls.sprites, cls.lookup, True)]
        video = (ROOT / "src/video/video_atari.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        tile = (ROOT / "src/tile.c").read_text()
        start = video.index("#define MAKE_PC_COLOR")
        palette = video[start:video.index("\n};", start) + 3]
        production = "\n".join([
            function(video, "Palette_FindClosestColor"),
            function(video, "Video_Atari_PlanarMergePlain"),
            function(video, "Video_Atari_ComposePlanarSprite"),
            function(video, "Video_Atari_BuildSpriteBlitRecipe"),
            function(tile, "Orientation_Orientation256ToOrientation8"),
            function(viewport, "GUI_Widget_Viewport_AddSpriteLayer"),
            function(viewport, "GUI_Widget_Viewport_GroundSprites"),
        ])
        harness = r"""
#include <assert.h>
#include <stddef.h>
#include "types.h"
#include "src/unit.h"
#include "src/map.h"
#include "src/tile.h"
#include "src/gui/gui.h"
static uint16 s_SquareTable[256];
UnitInfo g_table_unitInfo[UNIT_MAX];
Unit *g_unitSelected;
uint8 Unit_GetHouseID(Unit *unit) { return unit->o.houseID; }
uint16 Map_GetLandscapeType(uint16 packed) { (void)packed; return LST_SPICE; }
static int GUI_Widget_Viewport_HousePaletteFlags(uint16 id, uint8 house, uint8 *palette) {
    (void)id; (void)house; (void)palette; assert(0); return 0;
}
/* PALETTE */
/* PRODUCTION */
uint8 NativePen(uint8 r, uint8 g, uint8 b) {
    for (unsigned i = 0; i < 256; i++) s_SquareTable[i] = i * i;
    return Palette_FindClosestColor(r,g,b);
}
uint16 NativeLayout(uint16 house, uint16 direction, uint16 phase,
                    uint16 harvest, uint16 smoke, uint16 selected, int16 *out) {
    Unit unit = {0};
    unit.o.type = UNIT_HARVESTER; unit.o.houseID = house;
    unit.orientation[0].current = direction * 32;
    unit.spriteOffset = phase; unit.actionID = harvest ? ACTION_HARVEST : ACTION_MOVE;
    unit.o.flags.s.isSmoking = smoke;
    g_unitSelected = selected ? &unit : NULL;
    UnitInfo *info = &g_table_unitInfo[UNIT_HARVESTER];
    info->groundSpriteID = 248; info->turretSpriteID = 0xffff;
    info->displayMode = DISPLAYMODE_UNIT; info->movementType = MOVEMENT_HARVESTER;
    GUI_SpriteLayers layers;
    int flags;
    out[0] = GUI_Widget_Viewport_GroundSprites(&unit,&flags,&layers,UNIT_SPRITE_ALL);
    out[1] = out[2] = 0; out[3] = flags & 3;
    for (unsigned i = 0; i < layers.count; i++) {
        out[(i+1)*4] = layers.layer[i].spriteID;
        out[(i+1)*4+1] = layers.layer[i].offsetX;
        out[(i+1)*4+2] = layers.layer[i].offsetY;
        out[(i+1)*4+3] = layers.layer[i].flags & 3;
    }
    return layers.count + 1;
}
"""
        cls.directory = tempfile.TemporaryDirectory(prefix="harvester-analysis-", dir=ROOT / "objs")
        cls.addClassCleanup(cls.directory.cleanup)
        source = Path(cls.directory.name) / "native.c"
        library = Path(cls.directory.name) / "native.so"
        source.write_text(harness.replace("/* PALETTE */", palette)
                          .replace("/* PRODUCTION */", production))
        compiler = shlex.split(os.environ.get("CC", "cc"))
        subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-fPIC", "-shared", "-I" + str(ROOT), "-I" + str(ROOT / "include"),
                        str(source), str(ROOT / "src/codec/format80.c"), "-o", str(library)], check=True)
        cls.native = ctypes.CDLL(str(library))
        cls.native.NativePen.argtypes = [BYTE, BYTE, BYTE]
        cls.native.NativePen.restype = BYTE
        cls.native.Format80_Decode.argtypes = [ctypes.POINTER(BYTE), ctypes.POINTER(BYTE), WORD]
        cls.native.Format80_Decode.restype = WORD
        cls.native.NativeLayout.argtypes = [WORD] * 6 + [ctypes.POINTER(ctypes.c_int16)]
        cls.native.NativeLayout.restype = WORD
        cls.native.Video_Atari_ComposePlanarSprite.argtypes = [
            ctypes.POINTER(WORD), ctypes.POINTER(WORD), WORD, WORD,
            ctypes.POINTER(WORD), ctypes.POINTER(WORD), WORD, WORD, WORD, WORD]
        cls.native.Video_Atari_BuildSpriteBlitRecipe.argtypes = [
            ctypes.POINTER(WORD), ctypes.POINTER(WORD), WORD]
        cls.native.Video_Atari_BuildSpriteBlitRecipe.restype = BYTE

    def test_production_codec_and_quantizer(self):
        for i in range(256):
            self.assertEqual(self.lookup[i], self.native.NativePen(*self.palette[i * 3:i * 3 + 3]))
        for sprite in self.sprites.values():
            if sprite.compressed is None:
                continue
            source = (BYTE * len(sprite.compressed)).from_buffer_copy(sprite.compressed)
            output = (BYTE * len(sprite.decoded))()
            self.assertEqual(len(output), self.native.Format80_Decode(output, source, len(output)))
            self.assertEqual(bytes(output), sprite.decoded)

    def test_restricted_ordos_search(self):
        variants = [v for v in self.variants[:960] if v.house == 2]
        permutation = analysis.search_blink_preserving(variants)
        self.assertEqual(sorted(permutation), list(range(16)))
        self.assertTrue(all(permutation[n | 4] == (permutation[n] | 4) for n in range(16)))
        self.assertTrue(all(permutation[n] == n for n in (0, 2, 4, 6)))
        self.assertTrue(all(analysis.constant_planes(v.pen_mask, permutation) == 1
                            for v in variants if v.family == "body"))
        house_swap = list(range(16))
        house_swap[1], house_swap[14] = house_swap[14], house_swap[1]
        self.assertTrue(all(analysis.constant_planes(v.pen_mask, house_swap)
                            == analysis.constant_planes(v.pen_mask) for v in variants))

    def test_production_layout_composition_and_recipes(self):
        permutation = analysis.search_permutation(self.variants[:960], (0, 2, 4))
        self.assertEqual(sorted(permutation), list(range(16)))
        self.assertEqual(tuple(permutation[i] for i in (0, 2, 4)), (0, 2, 4))
        for i, variant in enumerate(self.variants):
            layout = (ctypes.c_int16 * 16)()
            count = self.native.NativeLayout(
                variant.house, variant.direction, variant.phase,
                "attachment" in variant.family, "smoke" in variant.family, i >= 960, layout)
            layers = [tuple(layout[j * 4:j * 4 + 4]) for j in range(count)]
            left = min(dx - self.sprites[sid].width // 2 for sid, dx, dy, flags in layers)
            top = min(dy - self.sprites[sid].height // 2 for sid, dx, dy, flags in layers)
            groups = (variant.width + 15) // 16
            pixels = (WORD * (groups * variant.height * 4))()
            masks = (WORD * (groups * variant.height))()
            for j, (sid, dx, dy, flags) in enumerate(layers):
                sprite = self.sprites[sid]
                src_groups = (sprite.width + 15) // 16
                src_pixels = (WORD * (src_groups * sprite.height * 4))()
                src_masks = (WORD * (src_groups * sprite.height))()
                layer = analysis.render_layer(sprite, self.lookup, variant.house if j == 0 else None,
                                              bool(flags & 1))
                for (x, y), pen in layer.items():
                    x += sprite.width // 2
                    y += sprite.height // 2
                    word = y * src_groups + x // 16
                    bit = 0x8000 >> (x & 15)
                    src_masks[word] |= bit
                    for plane in range(4):
                        if pen & (1 << plane):
                            src_pixels[word * 4 + plane] |= bit
                self.native.Video_Atari_ComposePlanarSprite(
                    pixels, masks, groups * 16, variant.height,
                    src_pixels, src_masks, src_groups * 16, sprite.height,
                    dx - sprite.width // 2 - left, dy - sprite.height // 2 - top)
            remapped_pixels = (WORD * len(pixels))()
            for y in range(variant.height):
                for x in range(groups * 16):
                    word = y * groups + x // 16
                    bit = 0x8000 >> (x & 15)
                    value = None
                    if masks[word] & bit:
                        value = sum(1 << plane for plane in range(4)
                                    if pixels[word * 4 + plane] & bit)
                        for plane in range(4):
                            if permutation[value] & (1 << plane):
                                remapped_pixels[word * 4 + plane] |= bit
                    if x < variant.width:
                        self.assertEqual(value, variant.pixels[y * variant.width + x])
                    else:
                        self.assertIsNone(value)
            for canvas, mapping in ((pixels, tuple(range(16))), (remapped_pixels, permutation)):
                passes = self.native.Video_Atari_BuildSpriteBlitRecipe(canvas, masks, len(masks))
                self.assertEqual(passes.bit_count(), 8 - analysis.constant_planes(variant.pen_mask, mapping))
        old = sum(v.weight * (8 - analysis.constant_planes(v.pen_mask)) for v in self.variants[:960])
        new = sum(v.weight * (8 - analysis.constant_planes(v.pen_mask, permutation))
                  for v in self.variants[:960])
        self.assertLess(new, old)


if __name__ == "__main__":
    unittest.main()
