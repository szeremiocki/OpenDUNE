# Compiled tiles and sprites for the ST/STE CPU path

Design note, not an implemented renderer. Target: plain 68000, ST-Low,
320x200, four interleaved bitplanes and a 160-byte screen row stride.
The aim is to accelerate cached planar publication on ST, and the CPU
publication option on STE, without relying on a BLiTTER.

The follow-up publication API and its prerequisites are recorded in
`ATARI_DISPLAY_LIST.md`, under "Planned: explicit publication context,
independent of backend". CPU/BLITTER kernel selection at preparation is
separate from immediate/display-list scheduling at publication.

## Core idea: the sprite or tile is code

Instead of feeding a generic copy/masked-copy loop with cached pixels,
compile the already-quantized planar asset into instructions that perform
its particular writes. The destination address remains dynamic, but pixel
values, opacity, row offsets and eligible alignment can be known when
building the cache entry.

Compilation should consume the existing shared palette-mapping/c2p
output, not introduce another quantizer. For sprites it should follow
composition, so shadows, selection marks, house variants and other layers
are already resolved in their existing painter order.

Potential savings come from specializing the operation:

- Eliminate source-loop control and repeated row/address calculations.
- Skip transparent words altogether.
- Replace fully opaque words instead of reading and masking them.
- For partially opaque words, emit the exact clear/insert operations.
- Omit an OR when the inserted colour bits are zero, but still clear
  opacity-covered destination bits: opaque hardware pen 0 is not
  transparency.
- Load repeated pixel values or masks into registers once and reuse them.

Unrolling alone is not a guaranteed win. Instruction fetches also use
memory bandwidth, and the existing CPU publisher already has optimized
loops. Measure complete publication, including dispatch, clipping and
cursor handling, rather than only the generated body.

## Immediate pixels: data embedded in the instructions

An opaque write can contain the tile/sprite pixels directly:

```asm
        move.l  #$12345678,160(a1)
```

Here the asset really is executable code: the immediate operand is the
pixel data, with no separate source-pointer walk. Immediate masks can
likewise specialize partial sprite writes.

Advantages:

- No source address register is needed for embedded pixels.
- No separate pixel-data load or source-pointer initialization.
- Each instruction directly describes the required write.
- The generated body can be moved without fixing embedded source
  addresses, provided its control transfers are also relocatable.

This is a good starting point for unique, fixed pixel values. Repeated
values may be cheaper in a register. Zero or all-one regions can sometimes
use specialized instructions, but actual 68000 timings and bus accesses
must decide; for example, CLR to memory is not a read-free store on 68000.

## PC-relative data: code and ordinary asset data together

A cache entry can instead contain a generated body followed by planar
pixels and opacity, accessible directly from the code:

```asm
        move.l  pixels(pc),160(a1)
        ; Further generated writes and a return precede the data.
pixels:
        dc.l    $12345678
```

This is a code-plus-data asset, rather than encoding every pixel solely
as an instruction operand.

Advantages:

- The generated body and nearby data relocate together.
- PC-relative reads do not require a source-pointer register, reducing
  register pressure/clobbering compared with a conventional source walk.
- Multiple instructions can reference the same stored data.
- Retained ordinary planar pixels and masks remain available to clipping,
  fallback publication and cursor/placement handling.
- Code can obtain a nearby data address with LEA when a helper needs a
  pointer, rather than storing an absolute pointer in the generated body.

This is not a speed advantage over immediate operands. Both approaches
can avoid a source register; PC-relative reads add an operand-memory
access. Nor is retaining a full data image alongside generated code free:
account for both in cache memory usage.

Simple PC-relative displacement on 68000 is signed 16-bit. Each reference
must reach its data from that instruction's PC base. PC-relative addressing
is legal for sources, not memory destinations; the screen address still
belongs in an address register. Generation must keep code, data and
word/long destinations even-aligned.

## Timing comparison

Plain-68000 cycles, including instruction and operand accesses, before
machine-specific contention:

| Instruction | Cycles |
|---|---:|
| `move.l #value,offset(a1)` | 24 |
| `move.l (a0)+,offset(a1)` | 24 |
| `move.l value(pc),offset(a1)` | 28 |
| `move.l d0,offset(a1)` | 16 |
| `lea value(pc),a0` | 8 |

For a complete opaque 16x16 four-plane tile, 128 bytes means 32 longword
writes. The moves alone cost 768 cycles with immediates or `(a0)+`, versus
896 with PC-relative reads. This excludes dispatch and any source setup;
it is not a comparison against the complete existing tile publisher.
Repeated-value register reuse can change the result substantially.

Reference: [68000 instruction timing tables](https://md.railgun.works/index.php?title=68k_Instruction_Reference).

## Minimal private calling convention

The intended generated routines do **not** use a full C call protocol or
an ordinary function stack frame. They are private assembly kernels with
an explicitly agreed register contract.

A practical initial contract is:

- One address register holds the destination origin.
- Another holds the generated entry address for indirect dispatch.
- Only a small declared scratch-register set may be clobbered.
- No LINK/UNLK, stack arguments or blanket MOVEM save/restore.
- No calls to C or general helpers inside the generated drawing body.
- Return with RTS; CCR is clobbered.

For example, `jsr (a0)` followed by the generated body's RTS costs 32
cycles on plain 68000 and uses only a four-byte return address on the
stack. No additional call frame is required. Register preparation and
any preservation required at the outer C/assembly boundary are separate.

Place dispatch inside an assembly publication wrapper so scratch
registers can be reused across draws. Preserve the public ABI at that
outer boundary, not independently around every generated tile or sprite.
An inline-assembly caller must declare all actual clobbers, including
condition codes and memory; a bare C function-pointer call is not a
substitute for this private convention.

A jump-based continuation is another possible design, but consumes a
continuation register or needs patched control flow. Start with the small
JSR/RTS contract and justify alternatives by measurement. Avoid a shared
mutable destination literal or return slot: it complicates reentrancy and
code publication for little initial benefit.

## Integration constraints

Opaque tiles are the simplest first experiment: fixed geometry and no
sprite opacity merge. Start with unclipped eligible tiles, leaving fog,
mixed composition and unsupported cases on the existing CPU path.

Sprites require more care. The current CPU cache retains screen-X-phase
variants; compiled code could follow that scheme, but sixteen variants
can multiply code size. Clip-specific bodies would multiply it further.
Initially compile only the full eligible cached image and keep existing
publication for clipped or protected cases, rather than generating every
combination.

Compilation must not change terrain repair-on-first-touch, painter order,
dirty tracking or the currently selected destination buffer. Existing
cursor backup refresh needs the exact opacity-written bits, including
opaque black; whole-word backup copying is not valid for masked writes.
Placement protection must likewise remain intact. Keep ordinary masks or
equivalent exact coverage metadata until those surfaces are explicitly
wired to compiled publication.

Build code on cache fill, finalize it before exposing the entry, and free
it with the asset/cache lifetime. Plain 68000 has no instruction cache;
accelerated machines require an appropriate instruction-coherency policy
before executing newly generated code. Only 68000 instructions belong in
the baseline implementation.

## Suggested experiment

Compare three bounded implementations of the same opaque tiles: the
existing CPU copy, immediate-encoded writes, and a code-plus-PC-relative
data variant. Include repeated-value register reuse where profitable.
Measure cache-build cost, generated bytes and complete hit-publication
cycles with the same assets and workload.

Then extend to phase-specific composed sprites, specializing transparent,
opaque and partial words while retaining the existing clipping/overlay
fallback. The goal is fewer actual publication cycles, not code generation
for its own sake or an assumed promise of matching BLiTTER performance.
