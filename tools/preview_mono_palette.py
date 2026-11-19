#!/usr/bin/env python3
"""Generate shared ST/STE dither palette tables and their asset preview from IBM.PAL."""

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

if __package__:
    from .analyze_harvester_planes import decode_format80, decode_sprite, read_pak
else:
    from analyze_harvester_planes import decode_format80, decode_sprite, read_pak


ROOT = Path(__file__).resolve().parents[1]

BAYER_RANKS = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
LUMA_RAMP = tuple(
    tuple("".join("1" if rank < coverage else "0" for rank in row) for row in BAYER_RANKS)
    for coverage in range(17)
)


def mono_coverage(rgb):
    luma = sum((value & 63) * weight for value, weight in zip(rgb, (299, 587, 114)))
    return (luma * 16 + 31500) // 63000


def direct_mono_pattern(rgb):
    return [[int(bit) for bit in row] for row in LUMA_RAMP[mono_coverage(rgb)]]


# Rows run top to bottom; 1 means white, with the leftmost character at x=0.
# These are proposed asset-fill patterns, not the policy for text or thin UI.
PROPOSALS = (
    ("Black", ("0000", "0000", "0000", "0000"), "Solid background / deepest shadow."),
    ("Dark green", ("1100", "0010", "0001", "1000"),
     "Five-cell oblique dashes, brighter than the four-cell neutral grey."),
    ("Dark red", ("1100", "0100", "0010", "0001"),
     "Five diagonal dots; lifted two white cells above the luma estimate for perceived brightness."),
    ("Dark blue", ("0001", "0001", "0001", "0011"),
     "Five predominantly vertical dots; the same brightness lift as red, with a different texture."),
    ("White", ("1111", "1111", "1111", "1111"), "Solid highlight / white."),
    ("Dark grey", ("1010", "0000", "1010", "0000"),
     "Four dispersed dots; lowered one white cell below the luma estimate."),
    ("Khaki", ("1111", "0101", "1011", "0101"),
     "Eleven white cells: brighter than peach, darker than pale blue."),
    ("Dark brown", ("0000", "0000", "0000", "1110"),
     "Three horizontal dots; deliberately darker than the lifted red and blue."),
    ("Ochre", ("1100", "0110", "0011", "1001"),
     "Half-white diagonal bands distinguish ochre from the nearby slate grey."),
    ("Light blue", ("1010", "0100", "1010", "0001"),
     "Six-cell dispersed stipple; brighter than the five-cell red/blue/green group."),
    ("Yellow", ("1111", "1111", "1111", "0111"),
     "One black dot per cell keeps yellow distinct from solid white."),
    ("Light sand", ("1111", "1101", "1111", "0111"),
     "Two black dots; between yellow and pale blue."),
    ("Pale blue", ("1111", "1101", "1111", "0101"),
     "Three black dots; below light sand in brightness."),
    ("Peach", ("1110", "0101", "1011", "0101"),
     "Ten-cell dispersed stipple."),
    ("Light green", ("1110", "0101", "1010", "0101"),
     "Nine-cell dispersed stipple; slightly brighter than half-white ochre."),
    ("Slate grey", ("1010", "0101", "1010", "0001"),
     "Seven-cell neutral stipple; distinguishes slate from ochre's diagonal bands."),
)

# Perceptual adjustments; code-value luma is only a baseline.
WHITE_CELL_BIAS = {2: 2, 3: 2, 5: -1}


def read_st_palette(path):
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", path.read_text(), flags=re.S)
    match = re.search(r"const uint8 s_palette4BitPC\[16\*4\]\s*=\s*\{(.*?)\};", source, re.S)
    if match is None:
        raise ValueError(f"{path}: current ST palette definition not found")
    colours = [
        tuple(map(int, rgb))
        for rgb in re.findall(
            r"MAKE_PC_COLOR\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", match[1]
        )
    ]
    if len(colours) != 16 or any(not 0 <= c <= 255 for rgb in colours for c in rgb):
        raise ValueError(f"{path}: expected exactly 16 RGB8 palette entries")
    return colours


def closest_pen(rgb6, colours):
    # Mirror Palette_FindClosestColor(): mask in SIX-bit units, weights 3:6:2,
    # and keep the first pen on ties. Do not quantize against displayed RGB8.
    rgb = tuple(c & ~3 for c in rgb6)
    return min(
        range(16),
        key=lambda pen: sum(
            weight * (component - ((catalogue >> 2) & ~3)) ** 2
            for component, catalogue, weight in zip(rgb, colours[pen], (3, 6, 2))
        ),
    )


def pack_pattern(rows):
    if len(rows) != 4 or any(len(row) != 4 or set(row) - {"0", "1"} for row in rows):
        raise ValueError("A pen must have four rows of four binary digits")
    return int("".join(rows), 2)


def quadrant(rows, x, y):
    x, y = (x & 1) * 2, (y & 1) * 2
    return int(rows[y][x:x + 2] + rows[y + 1][x:x + 2], 2)


def build_data(colours, palette, archive):
    if len(palette) != 768 or max(palette) > 63:
        raise ValueError("IBM.PAL must contain 256 RGB6 triplets")
    mapping = [closest_pen(palette[i:i + 3], colours) for i in range(0, 768, 3)]
    pens = []
    for index, (nominal, (name, rows, reason)) in enumerate(zip(colours, PROPOSALS)):
        hw3 = [c >> 5 for c in nominal]
        brightness = sum(c * w for c, w in zip(hw3, (299, 587, 114))) / 7000
        mask = pack_pattern(rows)
        cells = mask.bit_count()
        luma_cells = int(brightness * 16 + 0.5)
        bias = WHITE_CELL_BIAS.get(index, 0)
        if cells != luma_cells + bias:
            raise ValueError(f"Pen {index}: coverage does not match hardware luma plus perceptual bias")
        pens.append({
            "index": index, "name": name, "nominal": nominal, "hw3": hw3,
            "rgb": [round(c * 255 / 7) for c in hw3], "luma": brightness,
            "rows": rows, "mask": mask, "white": cells, "reason": reason,
            "lumaWhite": luma_cells, "whiteBias": bias,
            "quadrants": [[quadrant(rows, x, y) for x in range(2)] for y in range(2)],
            "mapped": mapping.count(index),
        })
    if len({pen["mask"] for pen in pens}) != 16:
        raise ValueError("All 16 pen patterns must be distinct")
    return {
        "archive": archive,
        "paletteSha256": hashlib.sha256(palette).hexdigest(),
        "colours": [list(palette[i:i + 3]) for i in range(0, 768, 3)],
        "mapping": mapping, "pens": pens,
        "patternPalettes": {
            "st": [[[pen] * 4 for _ in range(4)] for pen in mapping],
            "mono": [
                [[int(bit) for bit in row] for row in pens[pen]["rows"]]
                for pen in mapping
            ],
            "monoDirect": [direct_mono_pattern(palette[i:i + 3]) for i in range(0, 768, 3)],
        },
    }


def render_header(data):
    names = [
        "ATARI_MONO_PATTERN_" + pen["name"].upper().replace(" ", "_")
        for pen in data["pens"]
    ]
    lines = [
        "/** @file src/video/atari_mono_palette.h Prepared source-anchored mono patterns. */",
        "",
        "#ifndef VIDEO_ATARI_MONO_PALETTE_H",
        "#define VIDEO_ATARI_MONO_PALETTE_H",
        "",
        '#include "types.h"',
        "",
        "/* Generated by tools/preview_mono_palette.py; edit its proposals, then regenerate.",
        " * Includes the direct-luma imagery ramp and legacy ST pen patterns.",
        f" * IBM.PAL SHA-256: {data['paletteSha256']}",
        " *",
        " * Each uint16 is a 4x4 cell: bit 15 is top-left, bit 0 bottom-right.",
        " * Bits mean white (1) / black (0), independently of hardware polarity.",
        " * A logical source pixel emits the 2x2 quadrant at columns 2*(sx&1)",
        " * and rows 2*(sy&1), using the stable original asset coordinates.",
        " * These are imagery fills, not opacity masks or the text/fine-UI policy.",
        " *",
        " * s_paletteMonoIBM is the legacy 512-byte lookup for BASE IBM.PAL indices.",
        " * Resolve sprite-local palettes and house remaps before indexing it.",
        " * Different palettes/fades require new mappings; do not treat this as",
        " * a universal mapping for every runtime palette.",
        " */",
        "",
    ]
    for pen, name in zip(data["pens"], names):
        lines.append(
            f"#define {name:<31} 0x{pen['mask']:04X}"
            f" /* ST {pen['index']:2}: {' '.join(pen['rows'])}; {pen['white']:2}/16 white */"
        )
    lines += ["", "/* Lookup for graphics that already contain ST pen indices (0..15). */",
              "static const uint16 s_paletteMonoST[16] = {"]
    for name in names:
        lines.append(f"\t{name},")
    lines += ["};", "", "/* Direct source RGB luma -> 0..16 white cells in a 4x4 Bayer pattern. */",
              "static const uint16 s_paletteMonoLuma[17] = {"]
    for coverage, rows in enumerate(LUMA_RAMP):
        lines.append(f"\t0x{pack_pattern(rows):04X}, /* {coverage:2}/16 white */")
    lines += ["};", "", "/* Legacy preview: base IBM.PAL index -> pattern via the ST pen. */",
              "static const uint16 s_paletteMonoIBM[256] = {"]
    for index, (rgb, pen) in enumerate(zip(data["colours"], data["mapping"])):
        lines.append(
            f"\t{names[pen]},"
            f" /* {index:3}: RGB6({rgb[0]:2},{rgb[1]:2},{rgb[2]:2}) -> ST {pen:2} */"
        )
    lines += ["};", "", "#endif", ""]
    return "\n".join(lines)


def render_dither_header(data):
    lines = [
        "/** @file src/video/atari_dither_palette.h Shared source-anchored pen patterns. */",
        "",
        "#ifndef VIDEO_ATARI_DITHER_PALETTE_H",
        "#define VIDEO_ATARI_DITHER_PALETTE_H",
        "",
        '#include "atari_dither.h"',
        "",
        "/* Generated by tools/preview_mono_palette.py; do not maintain a second palette.",
        f" * Base IBM.PAL SHA-256: {data['paletteSha256']}",
        " *",
        " * Each source colour selects 4x4 output pen indices, stored [row][column].",
        " * ST values are hardware pen indices 0..15; mono values mean black (0)",
        " * or white (1), independently of hardware bit polarity. Neither encodes opacity.",
        " * Resolve sprite-local palettes and house remaps before the IBM lookup.",
        " * Different palettes/fades require corresponding mappings.",
        " *",
        " * Sampling uses stable source coordinates, not destination coordinates:",
        " *   pattern[(sourceY * scaleY + dy) & 3][(sourceX * scaleX + dx) & 3]",
        " * Colour uses scale 1, emitting one pen; mono uses scale 2, emitting 2x2.",
        " * Keep sampling separate from one-/four-plane packing and asset policy.",
        " *",
        " * Each table is 4096 bytes; include in the preparation implementation",
        " * rather than duplicating static tables across multiple translation units.",
        " */",
        "",
    ]
    for kind, symbol, description in (
        ("st", "s_paletteDitherSTIBM", "Current nearest ST pen repeated in all cells: non-dithered baseline."),
        ("mono", "s_paletteDitherMonoIBM", "Agreed source-anchored mono patterns in the same pen-index format."),
    ):
        lines += [f"/* {description} */", f"static const AtariDitherPattern {symbol}[256] = {{"]
        for index, (pattern, pen) in enumerate(zip(data["patternPalettes"][kind], data["mapping"])):
            rows = ", ".join(
                "{ " + ", ".join(f"{value:2}" for value in row) + " }" for row in pattern
            )
            lines.append(f"\t{{ {rows} }}, /* IBM {index:3} -> ST {pen:2} */")
        lines += ["};", ""]
    lines += ["#endif", ""]
    return "\n".join(lines)


def decode_tiles(data):
    if data[:4] != b"FORM" or struct.unpack_from(">I", data, 4)[0] + 8 != len(data):
        raise ValueError("Invalid ICON.ICN FORM header")
    chunks = {}
    offset = 12
    while offset < len(data):
        name, size = struct.unpack_from(">4sI", data, offset)
        end = offset + 8 + size
        if end > len(data):
            raise ValueError("Truncated ICON.ICN chunk")
        chunks[name] = data[offset + 8:end]
        offset = end + (size & 1)
    width, height = (value * 8 for value in chunks[b"SINF"][:2])
    encoded = chunks[b"SSET"]
    encoding, size, skip = struct.unpack_from("<HIH", encoded)
    source = encoded[8 + skip:]
    if encoding == 0:
        pixels = source[:size]
    elif encoding == 4:
        pixels = decode_format80(source, size)
    else:
        raise ValueError(f"Unsupported tile compression {encoding}")
    tile_bytes = width * height // 2
    if len(pixels) != size or size != len(chunks[b"RTBL"]) * tile_bytes:
        raise ValueError("Invalid tile data/table length")
    tiles = []
    for tile, palette_index in enumerate(chunks[b"RTBL"]):
        palette = chunks[b"RPAL"][palette_index * 16:(palette_index + 1) * 16]
        if len(palette) != 16:
            raise ValueError("Invalid tile palette")
        expanded = []
        for value in pixels[tile * tile_bytes:(tile + 1) * tile_bytes]:
            expanded.extend((palette[value >> 4], palette[value & 15]))
        tiles.append(expanded)
    return width, height, tiles


def asset_examples(files):
    assets = []
    width, height, tiles = decode_tiles(files["ICON.ICN"])
    icon_map = struct.unpack("<" + "H" * (len(files["ICON.MAP"]) // 2), files["ICON.MAP"])
    for offset, label in (
        (0, "Sand"), (16, "Rock"), (32, "Dunes"), (48, "Mountain"),
        (64, "Spice"), (80, "Thick spice"), (1, "Rock edge"),
        (17, "Dune edge"), (49, "Spice edge"),
    ):
        tile = icon_map[icon_map[9] + offset] & 0x1FF
        assets.append({
            "name": label, "category": "Terrain", "width": width, "height": height,
            "source": f"ICON.ICN tile {tile} · landscape +{offset}",
            "pixels": tiles[tile],
        })
    tile = icon_map[icon_map[8] + 2] & 0x1FF
    assets.append({
        "name": "Concrete slab", "category": "Terrain", "width": width, "height": height,
        "source": f"ICON.ICN tile {tile} · concrete +2", "pixels": tiles[tile],
    })
    examples = (
        ("SHAPES.SHP", 12, 84, "Siege tank portrait", "Portraits / UI"),
        ("SHAPES.SHP", 12, 85, "Launcher portrait", "Portraits / UI"),
        ("SHAPES.SHP", 12, 87, "Devastator portrait", "Portraits / UI"),
        ("SHAPES.SHP", 12, 89, "Carryall portrait", "Portraits / UI"),
        ("SHAPES.SHP", 12, 99, "Raider portrait", "Portraits / UI"),
        ("SHAPES.SHP", 12, 14, "Credits digit zero", "Portraits / UI"),
        ("UNITS2.SHP", 111, 111, "Tracked hull (no turret)", "Battlefield sprites"),
        ("UNITS2.SHP", 111, 121, "Siege hull (no turret)", "Battlefield sprites"),
        ("UNITS.SHP", 238, 238, "Trike", "Battlefield sprites"),
        ("UNITS.SHP", 238, 243, "Raider / quad body", "Battlefield sprites"),
        ("UNITS.SHP", 238, 248, "Harvester body", "Battlefield sprites"),
        ("UNITS.SHP", 238, 253, "MCV", "Battlefield sprites"),
        ("UNITS.SHP", 238, 329, "Infantry", "Battlefield sprites"),
        ("UNITS.SHP", 238, 289, "Ornithopter frame", "Battlefield sprites"),
        ("UNITS.SHP", 238, 258, "Missile", "Battlefield sprites"),
        ("UNITS1.SHP", 151, 180, "Smoke frame", "Battlefield sprites"),
        ("UNITS1.SHP", 151, 183, "Explosion frame", "Battlefield sprites"),
    )
    for bank, base, sprite_id, label, category in examples:
        data = files[bank]
        count = struct.unpack_from("<H", data)[0]
        index = sprite_id - base
        modern = struct.unpack_from("<I", data, 2)[0] == 4 + count * 4
        if not 0 <= index < count:
            raise ValueError(f"{bank}: missing example {index}")
        offset = struct.unpack_from("<I" if modern else "<H", data, 2 + index * (4 if modern else 2))[0]
        if not offset:
            raise ValueError(f"{bank}: empty example {index}")
        sprite = decode_sprite(data[offset + (2 if modern else 0):])
        houses = (0, 1, 2) if sprite_id == 248 else (0,)
        for house in houses:
            pixels = []
            for value in sprite.pixels:
                if value is not None and sprite.palette is not None:
                    value = sprite.palette[value]
                    if 0x90 <= value <= 0x98:
                        value += house << 4
                pixels.append(value)
            suffix = (" · " + ("Harkonnen", "Atreides", "Ordos")[house]) if sprite_id == 248 else ""
            assets.append({
                "name": label + suffix, "category": category,
                "width": sprite.width, "height": sprite.height,
                "source": f"{bank} local {index} · global sprite {sprite_id}",
                "pixels": pixels,
                "unitSample": house == 0 and sprite_id in (111, 121, 238, 243, 248, 253, 329),
                "housePalette": sprite.palette is not None,
            })
    return assets


def intro_frame(wsa, frame):
    frames, width, height, workspace, embedded_palette = struct.unpack_from("<5H", wsa)
    header = 10
    expected = header + 4 * (frames + 2)
    if expected not in struct.unpack_from("<2I", wsa, header):
        header, embedded_palette = 8, 0
    offsets = struct.unpack_from(f"<{frames + 2}I", wsa, header)
    if not 0 <= frame < frames or not offsets[0]:
        raise ValueError("Expected an independent WSA with the requested frame")
    palette_bytes = 768 if embedded_palette else 0
    pixels = bytearray(width * height)
    for first, last in zip(offsets[:frame + 1], offsets[1:frame + 2]):
        if not 0 < first < last <= len(wsa) - palette_bytes:
            raise ValueError("Invalid WSA frame offsets")
        delta = decode_format80(wsa[first + palette_bytes:last + palette_bytes], workspace, exact=False)
        pos = cursor = 0
        while True:
            cmd = delta[cursor]
            cursor += 1
            if cmd == 128:
                cmd, = struct.unpack_from("<H", delta, cursor)
                cursor += 2
                if cmd == 0:
                    break
                count, skip, fill = cmd & 0x7fff, cmd < 0x8000, cmd >= 0xc000
                if not skip:
                    count &= 0x3fff
            elif cmd == 0:
                count, skip, fill = delta[cursor], False, True
                cursor += 1
            else:
                count, skip, fill = cmd & 127, cmd > 128, False
            if pos + count > len(pixels):
                raise ValueError("WSA delta exceeds its image")
            if not skip:
                size = 1 if fill else count
                if cursor + size > len(delta):
                    raise ValueError("Truncated WSA delta")
                for i in range(count):
                    pixels[pos + i] ^= delta[cursor + (0 if fill else i)]
                cursor += size
            pos += count
    return width, height, list(pixels)


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenDUNE — ST mono 4×4 pen proposal</title>
<style>
:root { color-scheme:light; font:16px/1.5 system-ui,sans-serif; color:#20242a; background:#eceff2 }
* { box-sizing:border-box }
body { max-width:1440px; margin:auto; padding:24px }
h1 { line-height:1.15; margin-bottom:12px } h2 { margin-top:36px } h3 { margin:0 }
p { max-width:100ch } code { font-size:.9em } a { color:#164e90 }
.tag { display:inline-block; padding:3px 9px; background:#dbe7f6; border-radius:4px; font-size:.85rem }
.notice { border-left:5px solid #ba6a00; background:#fff5da; padding:12px 16px }
.muted { color:#505963; font-size:.88rem }
.pens { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px }
.card,.panel { background:white; border:1px solid #c5ccd3; border-radius:8px; padding:16px }
.pen-heading { display:flex; align-items:center; gap:10px; margin-bottom:12px }
.chip { width:32px; height:32px; border:1px solid #777; flex-shrink:0 }
.samples { display:flex; align-items:flex-start; gap:16px; margin:12px 0 }
.sample { display:block; border:1px solid #777; box-sizing:content-box }
.native { width:64px; height:64px; background-size:4px 4px }
.zoom { width:128px; height:128px; background-size:32px 32px }
.sample-label { display:block; font-size:.8rem; color:#505963; margin-top:4px }
.cell { display:grid; grid-template-columns:repeat(4,20px); width:max-content; border:1px solid #777 }
.cell i { display:block; width:20px; height:20px; border:1px solid #999 }
.cell i:nth-child(4n+2) { border-right:2px solid #e25822 }
.cell i:nth-child(n+5):nth-child(-n+8) { border-bottom:2px solid #e25822 }
.metric { font-variant-numeric:tabular-nums }
.reason { min-height:4.5em; font-size:.9rem }
.rowbits { white-space:pre; margin:0; font-size:.85rem }
.ramp { display:flex; overflow:auto; background:white; padding:12px; border:1px solid #c5ccd3 }
.ramp-item { min-width:64px; text-align:center; font-size:.8rem }
.ramp-item .sample { width:64px; height:64px }
.ramp-item .colour { height:16px; border:1px solid #888 }
.comparisons { display:flex; flex-wrap:wrap; gap:14px }
.comparisons .samples { margin-bottom:0 }
.pair-sample { width:96px; height:64px; background-size:4px 4px }
.legend { display:flex; gap:16px; flex-wrap:wrap; align-items:center }
select { font:inherit; padding:5px }
.palette { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:8px; margin-top:16px }
.entry { background:white; border:1px solid #c5ccd3; border-radius:5px; padding:8px }
.entry-label { display:flex; justify-content:space-between; font-size:.8rem; margin-bottom:6px }
.chain { display:grid; grid-template-columns:repeat(3,1fr); height:42px; border:1px solid #888 }
.chain > span { min-width:0 }
.chain .sample { width:100%; height:100%; border:0 }
.entry .muted { font-size:.72rem; margin-top:4px }
.assets { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr)); gap:14px; margin-top:16px }
.asset-versions { display:flex; flex-wrap:wrap; gap:12px; align-items:flex-start; margin-top:12px }
.asset-wide { grid-column:1 / -1; min-width:0 }
.asset-wide .asset-versions { display:grid; grid-template-columns:max-content max-content; overflow-x:auto }
.asset-versions figure { margin:0 }
.asset-versions figcaption { font-size:.8rem; margin-bottom:4px }
.asset-image, .unit-image { image-rendering:pixelated; display:block; border:1px solid #999; box-sizing:content-box; background:#808080 }
.asset-image[data-background="white"] { background:white }
.asset-image[data-background="black"] { background:black }
table { border-collapse:collapse; table-layout:fixed; width:100%; font-size:.9rem }
th,td { text-align:left; border-bottom:1px solid #ccd2d8; padding:8px; vertical-align:top; overflow-wrap:anywhere }
th { width:24% }
#packed { overflow-x:auto }
summary { cursor:pointer; font-weight:600 }
footer { margin-top:32px; border-top:1px solid #bcc4cc; padding-top:12px; overflow-wrap:anywhere }
@media(max-width:600px) { body { padding:12px } .pens { grid-template-columns:1fr } }
@media print { body { max-width:none } .card,.entry { break-inside:avoid } }
</style>
</head>
<body>
<header>
<span class="tag">atari-st-mono · palette comparison</span>
<h1>Source RGB → source-anchored 4×4 mono patterns</h1>
<p>The original 16-pen baseline below is the first-pass asset-fill proposal.
Coverage starts from relative brightness, with a deliberate two-cell lift for
dark red and dark blue and a one-cell reduction for dark grey.
Similarly bright colours receive different textures.
No destination-position phase variants are needed.</p>
<nav><a href="#unit-study">Unit comparison</a> · <a href="#assets">Asset catalogue</a> · <a href="#pens">16 proposed pens</a> · <a href="#similar">Similar-brightness comparisons</a> ·
<a href="#ibm">All 256 IBM.PAL mappings</a> · <a href="#method">Method and implementation data</a></nav>
<p class="notice"><strong>Not a text/UI policy.</strong> Text, thin borders, targeting and tiny
icons should use deliberate solid black/white styles or dedicated patterns.
These fills are for imagery; distinguishability must be judged on the real mono monitor.
“Native” means one HTML/CSS pixel per output pixel at 100% browser zoom, not calibrated CRT size.</p>
</header>
<section id="unit-study">
<h2>Ground-unit tones, house colours and internal edges</h2>
<p>The first two columns are fixed Atreides references with black outlines.
The controls change the house and interior-edge comparisons. Inversion flips
each sprite fill pixel without changing the terrain or the chosen outline.
The final column adds dark accents where distinct source tones map to the
same bright tone before inversion. These are isolated sprite frames, not
in-game composites.</p>
<label for="unit-ground">Terrain</label>
<select id="unit-ground">
<option value="Mountain">Mountain (original)</option>
<option value="mountain-building">Mountain (building ramp)</option>
<option value="Rock">Rock (original)</option>
<option value="rock-building">Rock (building ramp)</option>
<option value="rock-flat">Rock (flat, 25% white)</option>
<option value="rock-light">Rock (flat, 50% white)</option>
<option>Sand</option>
</select>
<label for="unit-ramp">Ramp for house and edge comparisons</label>
<select id="unit-ramp"><option value="old">High contrast (BLDEDGE)</option><option value="building">Building ramp</option></select>
<label for="unit-outline">Outline</label>
<select id="unit-outline"><option value="0">Black</option><option value="1">White</option></select>
<label><input id="unit-inverse" type="checkbox"> Invert sprite fill</label>
<div id="unit-grid"></div>
</section>
<section id="assets">
<h2>Real asset catalogue: legacy vs. direct mono</h2>
<p>Examples decoded from the local game archives, including terrain, portraits, unit
bodies and effects. Direct mono bypasses ST16 and selects one of 17 Bayer patterns
from the original RGB luma, with no added contrast. Both mono modes use identical
asset-anchored 2×2 quadrants. Colour references use 2× nearest-neighbour scaling.</p>
<p class="muted">These are isolated source assets, not a reconstruction of in-game
composites. Hulls have no separately drawn turret; smoke/effects have no runtime
special remap. Local sprite palettes are applied, with the three labelled harvester
variants using house-colour remaps. The generic imagery policy is deliberately also
shown on one credits digit to expose why small UI needs its own policy.
Grey behind transparent pixels is page background, not a third mono colour.</p>
<div class="legend">
<label for="asset-category">Category</label><select id="asset-category">
<option value="all">All examples</option>
<option>Terrain</option><option>Portraits / UI</option><option>Battlefield sprites</option><option>Intro frames</option>
</select>
<label for="asset-scale">Pixel zoom</label><select id="asset-scale">
<option value="1" selected>1× native output pixels</option><option value="2">2× output pixels</option>
<option value="3">3× output pixels</option><option value="4">4× output pixels</option>
</select>
<label for="asset-background">Transparency background</label><select id="asset-background">
<option value="grey">Grey (inspection only)</option><option value="black">Black</option><option value="white">White</option>
</select>
</div>
<div id="asset-grid" class="assets"></div>
</section>
<section>
<h2>Brightness order</h2>
<p class="muted">Hardware colour above, native-pixel mono below. Black/white endpoints are solid.
The ramp deliberately repeats coverage where different colours have similar brightness.</p>
<div id="ramp" class="ramp"></div>
</section>
<section id="pens">
<h2>The 16 proposed pens</h2>
<p>Each orange division marks a 2×2 quadrant: one logical source pixel. The complete
4×4 cell spans a 2×2 patch of logical source pixels. White bits are shown as <code>1</code>.</p>
<div id="pen-grid" class="pens"></div>
</section>
<section id="similar">
<h2>Similar brightness, different texture</h2>
<p>Red and blue get five white cells, with diagonal versus predominantly vertical structures.
Both are lifted from the three-cell luma estimate to improve perceived brightness
and separation from dark brown, which retains three horizontal dots.
Dark green retains five oblique dots; dark grey is lowered from five to four dispersed dots.
Pattern differences help identification but do not guarantee readable ownership colours in a battle.</p>
<div id="comparison-grid" class="comparisons"></div>
</section>
<section id="ibm">
<h2>IBM.PAL → current ST pen → mono</h2>
<p>Every entry follows the existing runtime colour matcher, including six-bit masking,
weighted squared error and first-pen tie breaking. These are the base IBM.PAL mappings,
not a claim that runtime palette cycling or house remaps never change them.</p>
<div class="legend">
<label for="filter">Show mappings to </label><select id="filter"><option value="all">all ST pens</option></select>
<span class="muted">Each triptych: IBM colour | actual ST hardware colour | repeated mono pattern</span>
</div>
<p class="muted" id="entry-count"></p>
<div id="palette-grid" class="palette"></div>
</section>
<section id="method" class="panel" style="margin-top:32px">
<h2 style="margin-top:0">Method, assumptions and preparation contract</h2>
<table>
<tr><th>Input</th><td id="provenance"></td></tr>
<tr><th>ST palette</th><td>Parsed from the active <code>s_palette4BitPC</code> definition in
<code>src/video/video_atari.c</code>; the commented-out older palette is excluded.
Cards show both nominal RGB8 and actual three-bit hardware RGB.</td></tr>
<tr><th>IBM → ST</th><td>For each RGB6 component: mask with <code>&amp; ~3</code>.
Compare against <code>(nominalRGB8 &gt;&gt; 2) &amp; ~3</code>.
Minimize <code>3·ΔR² + 6·ΔG² + 2·ΔB²</code>; ties keep the lowest pen index.</td></tr>
<tr><th>Brightness</th><td><code>Y′ = (299·R3 + 587·G3 + 114·B3) / 7000</code>.
Baseline white cells = nearest integer to <code>16·Y′</code>. This is a practical
code-value luma proxy, not linear-light photometry or a calibrated monitor model.
RGB8 swatches cannot simulate CRT phosphor/gamma.</td></tr>
<tr><th>Perceptual adjustment</th><td>Dark red (pen 2) and dark blue (pen 3) each
add two white cells: baseline 3/16 → proposed 5/16. Dark grey (pen 5) loses
one: baseline 5/16 → proposed 4/16. Brown remains 3/16 and dark green remains 5/16.
This is a deliberate visual adjustment,
not a change to the original palette or the IBM → ST matcher.</td></tr>
<tr><th>Pattern differentiation</th><td>Hand-selected shapes preserve the chosen
coverage, including those explicit adjustments. They trade neutral stipple for stronger texture in the near-equal groups.
No two complete 4×4 patterns are identical.</td></tr>
<tr><th>Source anchoring</th><td>Use the original asset/animation origin, including crop
offsets, never the screen position or changing crop bounds.
For source parity <code>(sx &amp; 1, sy &amp; 1)</code>, emit the corresponding 2×2 quadrant.
Preserve independent opacity: white and black bits can both belong to an opaque pixel.</td></tr>
<tr><th>Scope</th><td>This proposal intentionally preserves the current IBM → ST16 stage.
A later direct IBM → mono mapping could retain more tonal information, but is not shown here.
Per-asset overrides, palette animation and mono cache invalidation remain renderer work.</td></tr>
<tr><th>Shared colour format</th><td><code>src/video/atari_dither_palette.h</code>
provides both IBM-indexed palettes as <code>uint8[256][4][4]</code> output pen values,
4 KB each. The ST16 table repeats the current nearest pen in every cell: a
non-dithered reference in the same format as mono. This preview samples those tables.</td></tr>
<tr><th>Later colour reuse</th><td>The planned dithered planarization is shared groundwork
for 4×4 dithering at 320×200 too. Mono emits 2×2 physical pixels per source pixel
(source phase modulo two); colour emits one (source phase modulo four).
Share asset anchoring and policies, not hardcoded scaling or binary pen values.
The current ST16 intermediate is a proposal constraint, not a required future colour pipeline.</td></tr>
</table>
<details style="margin-top:18px"><summary>Proposed packed masks and parity lookup</summary>
<p class="muted">16-bit mask: bit 15 is top-left; bit 0 is bottom-right.
Quadrants are listed [top-left, top-right; bottom-left, bottom-right].
Each quadrant nibble is [top-left, top-right, bottom-left, bottom-right], MSB first.
These are semantic white bits; hardware polarity must be established separately.</p>
<pre id="packed"></pre>
</details>
</section>
<footer class="muted">
Generated locally with <code>python3 tools/preview_mono_palette.py</code>.
The same command generates <code>src/video/atari_dither_palette.h</code> and the compact
<code>src/video/atari_mono_palette.h</code> for code use.
Self-contained: no external fonts, scripts, image files or network requests.
<noscript>JavaScript must be enabled to render the embedded palette and pattern data.</noscript>
</footer>
<script id="proposal-data" type="application/json">__DATA__</script>
<script>
"use strict";
const data = JSON.parse(document.getElementById("proposal-data").textContent);
const rgb = values => `rgb(${values.join(",")})`;
const hex = values => "#" + values.map(v => v.toString(16).padStart(2,"0")).join("");
const pct = value => (value * 100).toFixed(1) + "%";
const maskHex = pen => "0x" + pen.mask.toString(16).padStart(4,"0").toUpperCase();
function pattern(pen) {
    let svg = '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4" viewBox="0 0 4 4" shape-rendering="crispEdges"><rect width="4" height="4" fill="black"/>';
    pen.rows.forEach((row,y) => [...row].forEach((v,x) => {
        if (v === "1") svg += `<rect x="${x}" y="${y}" width="1" height="1" fill="white"/>`;
    }));
    return `url("data:image/svg+xml,${encodeURIComponent(svg + "</svg>")}")`;
}
function swatch(pen, cls, label) {
    const node = document.createElement("span");
    node.className = "sample " + cls;
    node.style.backgroundImage = pattern(pen);
    node.setAttribute("role","img");
    node.setAttribute("aria-label",label || `Pen ${pen.index}: ${pen.name}, ${pen.white}/16 white`);
    return node;
}
function assetCanvas(asset, version) {
    const canvas=document.createElement("canvas");
    canvas.width=asset.width*2; canvas.height=asset.height*2;
    canvas.className="asset-image";
    canvas.setAttribute("role","img");
    canvas.setAttribute("aria-label",`${asset.name}, ${version}`);
    const context=canvas.getContext("2d"), image=context.createImageData(canvas.width,canvas.height);
    const palette=asset.palette ? data[asset.palette] : data;
    asset.pixels.forEach((value,i) => {
        if (value===null) return;
        const x=i%asset.width, y=Math.floor(i/asset.width);
        for (let dy=0;dy<2;dy++) for (let dx=0;dx<2;dx++) {
            let colour;
            if (version==="Original") colour=palette.colours[value].map(c=>Math.round(c*255/63));
            else if (version==="ST16") colour=data.pens[palette.mapping[value]].rgb;
            else {
                const patterns=version==="Direct mono" ? palette.patternPalettes.monoDirect : palette.patternPalettes.mono;
                const bit=patterns[value][(y*2+dy)&3][(x*2+dx)&3]*255;
                colour=[bit,bit,bit];
            }
            const out=((y*2+dy)*canvas.width+x*2+dx)*4;
            image.data.set([...colour,255],out);
        }
    });
    context.putImageData(image,0,0);
    return canvas;
}
function buildingTone(coverage) {
    return coverage<3 ? 0 : coverage<6 ? 4 : coverage<9 ? 8 : 12;
}
function spriteTone(coverage, ramp) {
    if (ramp==="building") return buildingTone(coverage);
    return coverage<2 ? 0 : coverage<4 ? 4 : coverage<6 ? 12 : 16;
}
function terrainCoverage(mode, colour) {
    const coverage=data.sourceCoverage[colour];
    if (mode==="rock-building" || mode==="mountain-building") return buildingTone(coverage);
    if (mode==="rock-flat") return 4;
    if (mode==="rock-light") return 8;
    return coverage;
}
function unitCanvas(asset, ground, groundMode, house, ramp, interior, outlineWhite, inverse) {
    const canvas=document.createElement("canvas");
    const w=asset.width*2, h=asset.height*2, margin=4;
    canvas.width=w+2*margin; canvas.height=h+2*margin;
    canvas.className="unit-image";
    const context=canvas.getContext("2d"), image=context.createImageData(canvas.width,canvas.height);
    const pixels=asset.pixels.map(c => asset.housePalette && c!==null && c>=0x90 && c<=0x98 ? c+16*house : c);
    function at(x,y) {
        if (x<0 || y<0 || x>=w || y>=h) return null;
        return pixels[(y>>1)*asset.width+(x>>1)];
    }
    for (let y=-margin;y<h+margin;y++) for (let x=-margin;x<w+margin;x++) {
        const c=at(x,y);
        let white;
        if (c===null) {
            const gx=(x+margin)>>1, gy=(y+margin)>>1;
            const bg=ground.pixels[(gy%ground.height)*ground.width+gx%ground.width];
            white=data.lumaPatterns[terrainCoverage(groundMode,bg)][(y+margin)&3][(x+margin)&3];
        } else {
            const neighbours=[at(x-1,y),at(x+1,y),at(x,y-1),at(x,y+1)];
            const luma=data.sourceCoverage[c], tone=spriteTone(luma,ramp);
            const outline=neighbours.includes(null);
            const feature=interior && !outline && tone>=12 && neighbours.some(n =>
                n!==null && data.sourceCoverage[n]>=luma+2 && spriteTone(data.sourceCoverage[n],ramp)===tone);
            const fill=data.lumaPatterns[tone][y&3][x&3];
            white=outline ? outlineWhite : feature ? 0 : inverse ? 1-fill : fill;
        }
        const shade=white*255, out=((y+margin)*canvas.width+x+margin)*4;
        image.data.set([shade,shade,shade,255],out);
    }
    context.putImageData(image,0,0);
    canvas.style.width=canvas.width*2+"px"; canvas.style.height=canvas.height*2+"px";
    return canvas;
}
function renderUnitStudy() {
    const grid=document.getElementById("unit-grid");
    const groundMode=document.getElementById("unit-ground").value;
    const groundName=groundMode==="Mountain" || groundMode==="mountain-building" ? "Mountain" :
        groundMode==="Sand" ? "Sand" : "Rock";
    const ground=data.assets.find(a=>a.name===groundName);
    const ramp=document.getElementById("unit-ramp").value;
    const outlineWhite=Number(document.getElementById("unit-outline").value);
    const inverse=document.getElementById("unit-inverse").checked;
    grid.replaceChildren();
    for (const asset of data.assets.filter(a=>a.unitSample)) {
        const row=document.createElement("article");
        row.className="card";
        const heading=document.createElement("h3"), variants=document.createElement("div");
        heading.textContent=asset.name.replace(" · Harkonnen","");
        variants.className="asset-versions";
        for (const [label,house,tones,edges,border,flip] of [
            ["Atreides · BLDEDGE",1,"old",false,0,false],
            ["Atreides · Building ramp",1,"building",false,0,false],
            ["Harkonnen",0,ramp,false,outlineWhite,inverse],
            ["Atreides",1,ramp,false,outlineWhite,inverse],
            ["Ordos",2,ramp,false,outlineWhite,inverse],
            ["Atreides + internal edges",1,ramp,true,outlineWhite,inverse]
        ]) {
            const figure=document.createElement("figure"), caption=document.createElement("figcaption");
            caption.textContent=label;
            figure.append(caption,unitCanvas(asset,ground,groundMode,house,tones,edges,border,flip));
            variants.append(figure);
        }
        row.append(heading,variants); grid.append(row);
    }
}
for (const id of ["unit-ground","unit-ramp","unit-outline","unit-inverse"]) {
    document.getElementById(id).addEventListener("change",renderUnitStudy);
}
renderUnitStudy();
function resizeAssets() {
    const scale=Number(document.getElementById("asset-scale").value);
    const background=document.getElementById("asset-background").value;
    document.querySelectorAll(".asset-image").forEach(canvas => {
        canvas.style.width=canvas.width*scale+"px"; canvas.style.height=canvas.height*scale+"px";
        canvas.dataset.background=background;
    });
}
function renderAssets() {
    const category=document.getElementById("asset-category").value, grid=document.getElementById("asset-grid");
    grid.replaceChildren();
    data.assets.forEach(asset => {
        if (category!=="all" && category!==asset.category) return;
        const card=document.createElement("article");
        card.className=asset.category==="Intro frames" ? "card asset-wide" : "card";
        card.innerHTML=`<h3>${asset.name}</h3><div class="muted">${asset.source}</div>
            <div class="muted">${asset.width}×${asset.height} source → ${asset.width*2}×${asset.height*2} output · ${asset.category}</div>
            <div class="asset-versions"></div>`;
        for (const version of ["Legacy mono","Direct mono","Original","ST16"]) {
            const figure=document.createElement("figure"), caption=document.createElement("figcaption");
            caption.textContent=version; figure.append(caption,assetCanvas(asset,version));
            card.querySelector(".asset-versions").append(figure);
        }
        grid.append(card);
    });
    resizeAssets();
}
document.getElementById("asset-category").addEventListener("change",renderAssets);
document.getElementById("asset-scale").addEventListener("change",resizeAssets);
document.getElementById("asset-background").addEventListener("change",resizeAssets);
renderAssets();
function penCard(pen) {
    const node = document.createElement("article");
    node.className = "card";
    node.innerHTML = `<div class="pen-heading"><span class="chip" style="background:${rgb(pen.rgb)}"></span>
        <h3>${pen.index.toString().padStart(2,"0")} · ${pen.name}</h3></div>
        <div class="muted">Nominal ${hex(pen.nominal)} → ST ${hex(pen.rgb)} · RGB3 ${pen.hw3.join(",")}</div>
        <div class="metric">Y′ ${pct(pen.luma)} → <strong>${pen.white}/16 white (${pct(pen.white/16)})</strong></div>
        <div class="muted">${pen.whiteBias ? `Perceptual bias ${pen.whiteBias > 0 ? "+" : ""}${pen.whiteBias}: baseline ${pen.lumaWhite}/16 → ${pen.white}/16 · ` : ""}Coverage − Y′: ${((pen.white/16-pen.luma)*100).toFixed(1)} percentage points · ${pen.mapped} IBM indices</div>
        <div class="samples"></div>
        <div class="legend"><div class="cell" aria-label="Enlarged 4 by 4 pattern cell"></div>
        <pre class="rowbits">${pen.rows.join("\n")}</pre></div>
        <p class="reason">${pen.reason}</p>
        <div class="muted"><code>${maskHex(pen)}</code> · quadrants <code>${pen.quadrants.map(row => row.map(q=>q.toString(16).toUpperCase()).join(" ")).join(" / ")}</code></div>`;
    for (const [cls,label] of [["native","Native pixels"],["zoom","8× pixels"]]) {
        const box = document.createElement("div");
        box.append(swatch(pen,cls));
        const caption = document.createElement("span");
        caption.className = "sample-label"; caption.textContent = label;
        box.append(caption); node.querySelector(".samples").append(box);
    }
    for (const bit of pen.rows.join("")) {
        const cell = document.createElement("i");
        cell.style.background = bit === "1" ? "white" : "black";
        node.querySelector(".cell").append(cell);
    }
    return node;
}
data.pens.forEach(pen => {
    document.getElementById("pen-grid").append(penCard(pen));
    const option = document.createElement("option");
    option.value = pen.index; option.textContent = `${pen.index} · ${pen.name} (${pen.mapped})`;
    document.getElementById("filter").append(option);
});
[...data.pens].sort((a,b)=>a.luma-b.luma).forEach(pen => {
    const node = document.createElement("div"); node.className = "ramp-item";
    node.innerHTML = `<div>${pen.index} · ${pen.white}/16</div><div class="colour" style="background:${rgb(pen.rgb)}"></div>`;
    node.append(swatch(pen,"native")); document.getElementById("ramp").append(node);
});
for (const ids of [[2,3,7],[1,5],[15,8]]) {
    const panel = document.createElement("div"); panel.className = "panel";
    panel.innerHTML = `<strong>Pens ${ids.join(" / ")}</strong><div class="samples"></div>`;
    for (const id of ids) {
        const pen=data.pens[id], box=document.createElement("div");
        box.innerHTML=`<div class="muted">${id} · ${pen.white}/16</div>`;
        box.append(swatch(pen,"pair-sample"));
        panel.querySelector(".samples").append(box);
    }
    document.getElementById("comparison-grid").append(panel);
}
function renderPalette() {
    const filter=document.getElementById("filter").value, grid=document.getElementById("palette-grid");
    grid.replaceChildren();
    data.colours.forEach((source,index) => {
        const pen=data.pens[data.mapping[index]];
        if (filter!=="all" && pen.index!==Number(filter)) return;
        const node=document.createElement("article"), sourceRgb=source.map(c=>Math.round(c*255/63));
        node.className="entry";
        node.innerHTML=`<div class="entry-label"><strong>IBM ${index.toString().padStart(3,"0")}</strong><span>ST ${pen.index}</span></div>
            <div class="chain"><span style="background:${rgb(sourceRgb)}" title="IBM RGB6: ${source.join(",")}"></span>
            <span style="background:${rgb(pen.rgb)}" title="ST pen ${pen.index}: ${pen.name}"></span></div>
            <div class="muted">RGB6 ${source.join(",")} → ${pen.white}/16 white</div>`;
        node.querySelector(".chain").append(swatch(pen,"native"));
        grid.append(node);
    });
    document.getElementById("entry-count").textContent=`${grid.children.length} of 256 palette entries shown.`;
}
document.getElementById("filter").addEventListener("change",renderPalette);
renderPalette();
document.getElementById("provenance").textContent=`IBM.PAL (768 bytes, RGB6), extracted from ${data.archive}. SHA-256 ${data.paletteSha256}`;
document.getElementById("packed").textContent=data.pens.map(pen =>
    `${pen.index.toString().padStart(2," ")}: ${maskHex(pen)}  /* ${pen.white.toString().padStart(2," ")} white; ${pen.name}; quadrants ${pen.quadrants.flat().map(q=>q.toString(16).toUpperCase()).join(",")} */`
).join("\n");
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "DUNE.PAK")
    parser.add_argument("--intro-archive", type=Path, help="Local INTRO.PAK for optional frame comparisons")
    parser.add_argument("--video-source", type=Path, default=ROOT / "src/video/video_atari.c")
    parser.add_argument("--output", type=Path, default=ROOT / "ATARI_MONO_PALETTE.html")
    parser.add_argument("--header-output", type=Path, default=ROOT / "src/video/atari_mono_palette.h")
    parser.add_argument("--dither-header-output", type=Path, default=ROOT / "src/video/atari_dither_palette.h")
    parser.add_argument("--check", action="store_true", help="Check all generated files without writing")
    args = parser.parse_args()
    files = read_pak(args.archive)
    colours = read_st_palette(args.video_source)
    data = build_data(colours, files["IBM.PAL"], args.archive.name)
    data["assets"] = asset_examples(files)
    data["sourceCoverage"] = [mono_coverage(rgb) for rgb in data["colours"]]
    data["lumaPatterns"] = [[[int(bit) for bit in row] for row in pattern] for pattern in LUMA_RAMP]
    if args.intro_archive:
        intro = read_pak(args.intro_archive)
        data["introPalette"] = build_data(colours, intro["INTRO.PAL"], args.intro_archive.name)
        for filename, frame in (("INTRO7A.WSA", 12), ("INTRO8A.WSA", 9)):
            width, height, pixels = intro_frame(intro[filename], frame)
            data["assets"].append({
                "name": f"{filename} frame {frame + 1}", "category": "Intro frames",
                "width": width, "height": height, "pixels": pixels,
                "palette": "introPalette", "source": "WSA using INTRO.PAL",
            })
    outputs = {
        args.output: HTML.replace("__DATA__", json.dumps(data, separators=(",", ":"))),
        args.header_output: render_header(data),
        args.dither_header_output: render_dither_header(data),
    }
    if args.check:
        stale = [str(path) for path, text in outputs.items()
                 if not path.is_file() or path.read_text(encoding="utf-8") != text]
        if stale:
            parser.exit(1, "Missing or stale generated files: " + ", ".join(stale) + "\n")
        print("C headers and HTML match the current proposals, ST palette and IBM.PAL")
    else:
        for path, text in outputs.items():
            path.write_text(text, encoding="utf-8")
            print(f"Wrote {path}")
    print(f"16 pens, 256 IBM.PAL mappings, {len(data['assets'])} example assets")
    print("White cells by pen:", ", ".join(str(pen["white"]) for pen in data["pens"]))


if __name__ == "__main__":
    main()
