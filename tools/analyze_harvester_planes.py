#!/usr/bin/env python3
"""Inspect harvester composites without modifying game assets or runtime palettes."""

import argparse
from collections import Counter
from dataclasses import dataclass
from itertools import combinations, permutations
from pathlib import Path
import random
import re
import struct


ROOT = Path(__file__).resolve().parents[1]
HOUSES = ("Harkonnen", "Atreides", "Ordos", "Fremen", "Sardaukar", "Mercenary")
PHASES = {"body": 1, "attachment": 3, "smoke": 4, "attachment+smoke": 12}
DIRECTIONS = (0, 1, 2, 3, 4, 3, 2, 1)
OFFSETS = ((0, 7), (-7, 6), (-14, 1), (-9, -6),
           (0, -9), (9, -6), (14, 1), (7, 6))


def read_pak(path):
    data = path.read_bytes()
    entries = []
    cursor = 0
    while True:
        offset, = struct.unpack_from("<I", data, cursor)
        cursor += 4
        if offset == 0:
            break
        end = data.index(0, cursor)
        entries.append((data[cursor:end].decode("ascii"), offset))
        cursor = end + 1
    result = {}
    for i, (name, offset) in enumerate(entries):
        end = entries[i + 1][1] if i + 1 < len(entries) else len(data)
        if not cursor <= offset <= end <= len(data):
            raise ValueError(f"{path}: invalid PAK range for {name}")
        result[name] = data[offset:end]
    return result


def decode_format80(source, length, *, exact=True):
    output = bytearray()
    cursor = 0
    while len(output) < length:
        command = source[cursor]
        cursor += 1
        if command == 0x80:
            break
        if command < 0x80:
            size = (command >> 4) + 3
            offset = len(output) - (((command & 15) << 8) | source[cursor])
            cursor += 1
        elif command == 0xFE:
            size, = struct.unpack_from("<H", source, cursor)
            output.extend([source[cursor + 2]] * size)
            cursor += 3
            continue
        elif command == 0xFF:
            size, offset = struct.unpack_from("<HH", source, cursor)
            cursor += 4
        elif command & 0x40:
            size = (command & 63) + 3
            offset, = struct.unpack_from("<H", source, cursor)
            cursor += 2
        else:
            size = command & 63
            if cursor + size > len(source):
                raise ValueError("Truncated Format80 literal")
            output.extend(source[cursor:cursor + size])
            cursor += size
            continue
        if not 0 <= offset < len(output):
            raise ValueError("Invalid Format80 back reference")
        for _ in range(size):
            output.append(output[offset])
            offset += 1
    if len(output) > length or (exact and len(output) != length):
        raise ValueError(f"Invalid Format80 output length {len(output)} (limit {length})")
    return bytes(output)


@dataclass(frozen=True)
class Sprite:
    width: int
    height: int
    palette: bytes | None
    pixels: tuple
    compressed: bytes | None
    decoded: bytes


def decode_sprite(data):
    flags, height, width, _, packed, length = struct.unpack_from("<HBHBHH", data)
    if not width or not height or not 10 <= packed <= len(data):
        raise ValueError("Invalid sprite header")
    palette = data[10:26] if flags & 1 else None
    start = 26 if palette is not None else 10
    source = data[start:packed]
    raw = source if flags & 2 else decode_format80(source, length)
    if len(raw) != length:
        raise ValueError("Invalid sprite RLE length")
    pixels = []
    cursor = 0
    while cursor < len(raw):
        value = raw[cursor]
        cursor += 1
        if value:
            pixels.append(value)
        else:
            skip = raw[cursor]
            cursor += 1
            if not skip:
                raise ValueError("Empty sprite transparency run")
            pixels.extend([None] * skip)
    if len(pixels) != width * height:
        raise ValueError("Invalid sprite pixel count")
    return Sprite(width, height, palette, tuple(pixels),
                  None if flags & 2 else source, raw)


def load_sprites(files):
    result = {}
    for name, base in (("MOUSE.SHP", 0), ("UNITS1.SHP", 151), ("UNITS.SHP", 238)):
        data = files[name]
        count, = struct.unpack_from("<H", data)
        modern = struct.unpack_from("<I", data, 2)[0] == 4 + count * 4
        for i in range(count):
            offset, = struct.unpack_from("<I" if modern else "<H", data,
                                        2 + i * (4 if modern else 2))
            if not offset:
                continue
            result[base + i] = decode_sprite(data[offset + (2 if modern else 0):])
    return result


def palette_lookup(palette):
    if len(palette) != 768:
        raise ValueError("IBM.PAL must contain 256 RGB triplets")
    source = (ROOT / "src/video/video_atari.c").read_text()
    source = source.split("const uint8 s_palette4BitPC[16*4] =", 1)[1]
    source = source.split("/*", 1)[0]
    colours = [tuple((int(v) >> 2) & ~3 for v in rgb) for rgb in re.findall(
        r"MAKE_PC_COLOR\(\s*(\d+),\s*(\d+),\s*(\d+)\)", source)]
    if len(colours) != 16:
        raise ValueError("Cannot read the production master palette")
    lookup = []
    for offset in range(0, 768, 3):
        rgb = tuple(v & ~3 for v in palette[offset:offset + 3])
        lookup.append(min(range(16), key=lambda pen: sum(
            weight * (a - b) ** 2 for weight, a, b in
            zip((3, 6, 2), rgb, colours[pen]))))
    return tuple(lookup)


def render_layer(sprite, lookup, house=None, mirror=False, dx=0, dy=0):
    output = {}
    for i, value in enumerate(sprite.pixels):
        if value is None:
            continue
        if sprite.palette is not None:
            value = sprite.palette[value]
            if house is not None and 0x90 <= value <= 0x98:
                value += house << 4
        x = i % sprite.width
        if mirror:
            x = sprite.width - 1 - x
        output[x - sprite.width // 2 + dx,
               i // sprite.width - sprite.height // 2 + dy] = lookup[value]
    return output


@dataclass(frozen=True)
class Variant:
    house: int
    family: str
    direction: int
    phase: int
    width: int
    height: int
    pixels: tuple
    pen_mask: int

    @property
    def weight(self):
        return (12 // PHASES[self.family]) * ((self.width + 15) // 16) * self.height


def build_variants(sprites, lookup, selected=False):
    variants = []
    for house in range(6):
        for family, phases in PHASES.items():
            for direction in range(8):
                for phase in range(phases):
                    layers = [(248 + DIRECTIONS[direction], house, direction > 4, 0, 0)]
                    if "attachment" in family:
                        layers.append((223 + DIRECTIONS[direction] * 3 + phase % 3,
                                       None, direction > 4, *OFFSETS[direction]))
                    if "smoke" in family:
                        layers.append((180 + (0, 1, 2, 1)[phase & 3], None, False, 0, -14))
                    if selected:
                        layers.append((6, None, False, 0, 0))
                    pixels = {}
                    left = top = right = bottom = 0
                    for sprite_id, colour_house, mirror, dx, dy in layers:
                        sprite = sprites[sprite_id]
                        x, y = dx - sprite.width // 2, dy - sprite.height // 2
                        left, top = min(left, x), min(top, y)
                        right, bottom = max(right, x + sprite.width), max(bottom, y + sprite.height)
                        pixels.update(render_layer(sprite, lookup, colour_house, mirror, dx, dy))
                    canvas = tuple(pixels.get((x, y)) for y in range(top, bottom)
                                   for x in range(left, right))
                    pen_mask = sum(1 << pen for pen in set(pixels.values()))
                    variants.append(Variant(house, family, direction, phase, right - left,
                                            bottom - top, canvas, pen_mask))
    return variants


def constant_planes(pen_mask, permutation=tuple(range(16))):
    both_and, both_or = 15, 0
    for pen in range(16):
        if pen_mask & (1 << pen):
            both_and &= permutation[pen]
            both_or |= permutation[pen]
    return 4 - (both_and ^ both_or).bit_count()


def individual_ceiling(pen_mask):
    return 4 - (pen_mask.bit_count() - 1).bit_length()


def search_permutation(variants, pinned=(), restarts=64):
    weights = Counter()
    for variant in variants:
        weights[variant.pen_mask] += variant.weight
    scores = {}
    for side in combinations(range(16), 8):
        mask = sum(1 << pen for pen in side)
        opposite = mask ^ 0xFFFF
        if mask > opposite:
            continue
        score = sum(weight for pens, weight in weights.items()
                    if not (pens & mask) or not (pens & opposite))
        scores[mask] = scores[opposite] = score
    free = [pen for pen in range(16) if pen not in pinned]
    swaps = tuple(combinations(free, 2))
    rng = random.Random(0)
    best = tuple(range(16))
    best_score = -1
    for restart in range(restarts):
        permutation = list(range(16))
        if restart:
            for old, new in zip(free, rng.sample(free, len(free))):
                permutation[old] = new
        masks = [sum(1 << old for old, new in enumerate(permutation) if new & (1 << bit))
                 for bit in range(4)]
        score = sum(scores[mask] for mask in masks)
        while True:
            improvement, chosen = 0, None
            for a, b in swaps:
                changed = permutation[a] ^ permutation[b]
                toggle = (1 << a) | (1 << b)
                gain = sum(scores[mask ^ toggle] - scores[mask]
                           for bit, mask in enumerate(masks) if changed & (1 << bit))
                if gain > improvement:
                    improvement, chosen = gain, (a, b)
            if chosen is None:
                break
            a, b = chosen
            changed = permutation[a] ^ permutation[b]
            toggle = (1 << a) | (1 << b)
            masks = [mask ^ toggle if changed & (1 << bit) else mask
                     for bit, mask in enumerate(masks)]
            permutation[a], permutation[b] = permutation[b], permutation[a]
            score += improvement
        if score > best_score:
            best, best_score = tuple(permutation), score
    return best


def search_blink_preserving(variants):
    """Exhaust 720 assignments preserving pens 0/2 and the default pen|4 blink."""
    weights = Counter()
    for variant in variants:
        weights[variant.pen_mask] += variant.weight
    free = [pen for pen in range(16) if not pen & 4 and pen not in (0, 2)]
    best, best_score = tuple(range(16)), -1
    for order in permutations(free):
        mapping = list(range(16))
        for old, new in zip(free, order):
            mapping[old], mapping[old | 4] = new, new | 4
        score = sum(weight * constant_planes(pens, mapping) for pens, weight in weights.items())
        if score > best_score:
            best, best_score = tuple(mapping), score
    return best


def describe(variants, permutation, heading):
    print(heading)
    print("house       family              opaque colours  constant planes  mean launches")
    for house, name in enumerate(HOUSES):
        for family in PHASES:
            subset = [v for v in variants if v.house == house and v.family == family]
            if not subset:
                continue
            colours = sorted({v.pen_mask.bit_count() for v in subset})
            constants = sorted({constant_planes(v.pen_mask, permutation) for v in subset})
            launches = sum(8 - constant_planes(v.pen_mask, permutation) for v in subset) / len(subset)
            print(f"{name:11s} {family:19s} {str(colours):15s} {str(constants):16s} {launches:.3f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pak", type=Path, default=ROOT / "DUNE.PAK")
    parser.add_argument("--selected", action="store_true", help="Include the selection-ring layer")
    parser.add_argument("--house", choices=HOUSES, help="Optimize and report only this house")
    parser.add_argument("--preserve-blink", action="store_true",
                        help="Exhaust the 720 assignments preserving pens 0/2/4/6 and default blink")
    args = parser.parse_args()
    files = read_pak(args.pak)
    sprites = load_sprites(files)
    variants = build_variants(sprites, palette_lookup(files["IBM.PAL"]), args.selected)
    if args.house is not None:
        variants = [v for v in variants if HOUSES[v.house] == args.house]
    print(f"{len(variants)} states; selected={args.selected}; opacity preserved separately from pen zero")
    describe(variants, tuple(range(16)), "\nCurrent palette")
    searches = ((0, 2, 4, 6),) if args.preserve_blink else ((), (0, 2, 4))
    for pinned in searches:
        permutation = (search_blink_preserving(variants) if args.preserve_blink
                       else search_permutation(variants, pinned))
        method = "Exact blink-preserving restricted" if args.preserve_blink else "Heuristic"
        describe(variants, permutation, f"\n{method} candidate; pinned old pens={pinned}")
        print("old pen -> new pen:", permutation)
        weight = sum(v.weight for v in variants)
        old = sum(v.weight * (8 - constant_planes(v.pen_mask)) for v in variants)
        new = sum(v.weight * (8 - constant_planes(v.pen_mask, permutation)) for v in variants)
        ceiling = sum(v.weight * (8 - individual_ceiling(v.pen_mask)) for v in variants)
        print(f"row-word weighted launches: {old / weight:.4f} -> {new / weight:.4f}; "
              f"reduction {(old - new) / old:.2%}; independent-state lower bound {ceiling / weight:.4f}")
    print("\nCandidates are not unrestricted global optima or runtime-safe palette changes.")
    print("Equal weight per house/family before rectangle row-word weighting; not profile frequencies.")


if __name__ == "__main__":
    main()
