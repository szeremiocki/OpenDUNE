#!/usr/bin/env python3
"""Compare Hatari CPU profiles without trusting their embedded Field regexp.

Usage:
    python3 tools/hatari_profile_compare.py before.txt after.txt
    python3 tools/hatari_profile_compare.py before.txt after.txt \
        --match 'Mouse|Cursor|Planar|c2p' --json comparison.json

Accepts CRLF/LF and both '$address :' and plain-address disassembly formats.
Cycle totals are exclusive instruction costs. Local assembly labels are folded
into the preceding underscore-prefixed function, while memory regions prevent
ROM instructions from inheriting the last application symbol. Duplicate or
truncated symbol names are aggregated, with entry addresses retained in JSON.
Entry executions are not necessarily calls (tail jumps and partial captures).
Caller totals are retained separately; inclusive costs must not be summed across
functions because that double-counts descendants. CPU-equivalent seconds are
not wall time. The optional TOS clock estimate counts the ROM's 200 Hz tick
instruction and is applicable only to captures using that TOS ROM address.
"""

import argparse
import bisect
import json
import re
from pathlib import Path


INSTRUCTION = re.compile(
    r"^\$?([0-9a-fA-F]+)\s*:?\s+.*?%\s+\(([\d,\s]+)\)\s*$"
)
REGION = re.compile(r"^(\w+):\s+0x([0-9a-fA-F]+)-0x([0-9a-fA-F]+)$")
CALLER = re.compile(
    r"^0x([0-9a-fA-F]+)\s*=\s*(\d+)\s+([a-z]+)"
    r"(?:\s+(\d+(?:/\d+)+))?(?:\s+(\d+(?:/\d+)+))?$"
)


def parse_profile(path):
    """Return exclusive symbol costs, instruction counters and caller records."""
    profile = {
        "path": str(path), "cycles_per_second": None, "fields": [],
        "regions": {}, "functions": {}, "instructions": {}, "callers": [],
    }
    owner = "<unlabelled>"
    pending_entry = False
    call_lines = []
    tick_address = None
    with Path(path).open(encoding="utf-8-sig") as stream:
        for number, raw in enumerate(stream, 1):
            line = raw.strip()
            if line.startswith("Cycles/second:"):
                profile["cycles_per_second"] = int(line.split(":", 1)[1])
            elif line.startswith("Field names:"):
                profile["fields"] = [
                    field.strip() for field in line.split(":", 1)[1].split(",")
                ]
            elif REGION.fullmatch(line):
                match = REGION.fullmatch(line)
                profile["regions"][match[1]] = [int(match[2], 16), int(match[3], 16)]
            elif line.startswith("0x") and ": " in line:
                call_lines.append((number, line))
            elif line.endswith(":") and not line.startswith("#"):
                if line.startswith("_"):
                    owner = line[:-1]
                    pending_entry = True
            else:
                match = INSTRUCTION.fullmatch(line)
                if match is None:
                    if re.match(r"^\$?[0-9a-fA-F]+\s", line) and "% (" in line:
                        raise ValueError(f"{path}:{number}: invalid instruction counters")
                    continue
                values = [int(value.strip()) for value in match[2].split(",")]
                if len(values) != len(profile["fields"]):
                    raise ValueError(f"{path}:{number}: instruction field count mismatch")
                address = int(match[1], 16)
                if address == 0xe007e2 and re.search(r"ADDQ.*\$04ba", line, re.I):
                    tick_address = address
                if address in profile["instructions"]:
                    raise ValueError(f"{path}:{number}: duplicate instruction address")
                metrics = dict(zip(profile["fields"], values))
                region = address_region(profile, address)
                name = owner if region == "PROGRAM_TEXT" else f"<{region}>"
                stats = profile["functions"].setdefault(
                    name, {"cycles": 0, "instructions": 0,
                           "entry_executions": 0, "entries": []}
                )
                stats["cycles"] += metrics["Used cycles"]
                stats["instructions"] += metrics["Executed instructions"]
                if pending_entry and region == "PROGRAM_TEXT":
                    stats["entries"].append(address)
                    stats["entry_executions"] += metrics["Executed instructions"]
                    pending_entry = False
                profile["instructions"][address] = {"symbol": name, **metrics}

    if not profile["instructions"] or not profile["cycles_per_second"]:
        raise ValueError(f"{path}: missing instruction data or cycle frequency")
    addresses = sorted(profile["instructions"])
    for number, line in call_lines:
        callee, rest = line.split(": ", 1)
        parts = [part.strip() for part in rest.split(",")]
        if not parts[-1].startswith("0x"):
            parts.pop()  # Display name, often truncated to 20 characters.
        for part in parts:
            match = CALLER.fullmatch(part)
            if match is None:
                raise ValueError(f"{path}:{number}: invalid caller record: {part}")
            caller_address = int(match[1], 16)
            callee_address = int(callee, 16)
            profile["callers"].append({
                "caller_address": caller_address, "callee_address": callee_address,
                "caller": instruction_owner(profile, addresses, caller_address),
                "callee": instruction_owner(profile, addresses, callee_address),
                "calls": int(match[2]), "types": match[3],
                "inclusive": [int(n) for n in match[4].split("/")] if match[4] else None,
                "exclusive": [int(n) for n in match[5].split("/")] if match[5] else None,
            })
    profile["total_cycles"] = sum(
        stats["cycles"] for stats in profile["functions"].values()
    )
    profile["cpu_seconds"] = profile["total_cycles"] / profile["cycles_per_second"]
    tick = profile["instructions"].get(tick_address)
    profile["tos_clock_seconds"] = tick["Executed instructions"] / 200 if tick else None
    return profile


def address_region(profile, address):
    for name in ("PROGRAM_TEXT", "ROM_TOS", "CARTRIDGE", "ST_RAM"):
        limits = profile["regions"].get(name)
        if limits and limits[0] <= address < limits[1]:
            return name
    return "unknown memory"


def instruction_owner(profile, addresses, address):
    index = bisect.bisect_right(addresses, address) - 1
    if index >= 0:
        previous = addresses[index]
        if address_region(profile, previous) == address_region(profile, address):
            return profile["instructions"][previous]["symbol"]
    return f"<{address_region(profile, address)}>"


def print_summary(profile, top):
    print(f"\n{profile['path']}")
    print(f"  {profile['total_cycles']:,} cycles; "
          f"{profile['cpu_seconds']:.3f} CPU-equivalent seconds; "
          f"{profile['cycles_per_second']:,} cycles/second")
    if profile["tos_clock_seconds"] is not None:
        print(f"  TOS 200 Hz tick estimate: {profile['tos_clock_seconds']:.3f} seconds")
    print("  Exclusive costs (local labels folded; duplicate names aggregated):")
    for name, stats in sorted(
        profile["functions"].items(), key=lambda row: -row[1]["cycles"]
    )[:top]:
        print(f"  {name:30s} {stats['cycles']:13,} "
              f"{100 * stats['cycles'] / profile['total_cycles']:7.3f}% "
              f"entries={stats['entry_executions']:,}")


def print_comparison(before, after, top, pattern):
    names = set(before["functions"]) | set(after["functions"])
    if pattern:
        names = {name for name in names if re.search(pattern, name)}
    rows = []
    for name in names:
        old = before["functions"].get(name, {}).get("cycles", 0)
        new = after["functions"].get(name, {}).get("cycles", 0)
        old_share = 100 * old / before["total_cycles"]
        new_share = 100 * new / after["total_cycles"]
        rows.append((name, old, new, old_share, new_share))
    rows.sort(key=lambda row: -abs(row[4] - row[3]))
    print("\nComparison: exclusive cycles and total-cycle shares")
    print(f"{'Symbol':30s} {'Before':>13s} {'After':>13s} "
          f"{'Before %':>9s} {'After %':>9s} {'Delta pp':>9s}")
    for name, old, new, old_share, new_share in rows[:top]:
        print(f"{name:30s} {old:13,} {new:13,} "
              f"{old_share:9.3f} {new_share:9.3f} {new_share-old_share:+9.3f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("profiles", nargs="+", type=Path)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--match", help="Regex filtering comparison symbol names")
    parser.add_argument("--json", type=Path, help="Save counters and caller records")
    args = parser.parse_args()
    if len(args.profiles) not in (1, 2) or args.top < 1:
        parser.error("provide one or two profiles and a positive --top")
    if args.match:
        try:
            re.compile(args.match)
        except re.error as error:
            parser.error(str(error))
    try:
        profiles = [parse_profile(path) for path in args.profiles]
        for profile in profiles:
            print_summary(profile, args.top)
        if len(profiles) == 2:
            print_comparison(*profiles, args.top, args.match)
        if args.json:
            args.json.write_text(json.dumps(profiles, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
