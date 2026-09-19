# VOC resampling and direct ST-RAM playback

## Current implementation (2026-09-19)

The assessment below is historical, not the current playback design.
Resampling and unsigned-to-signed conversion now happen once per load in
`DSP_ConvertSample()`, including on-demand speech, at 6258 Hz.

Resident converted VOCs are now allocated through `DSP_AllocSample()` using
`Mxalloc(..., MX_STRAM)` and freed through `DSP_FreeSample()`/`Mfree()`.
`DSP_Play()` reads the retained VOC header and programs DMA directly with
the PCM payload pointer: no per-play resampling or copying. On TOS,
`Voice_PlayAtTile()` also bypasses `g_readBuffer`, eliminating the other
whole-sample copy for gameplay effects. Other audio backends are unchanged.

The 32 KiB ST-RAM buffer remains conversion scratch and the playback source
for non-preloaded speech. `Driver_Voice_LoadFile()` stops playback before
reusing it. Resident samples are copied out only once, when loaded.
The DSP tracks the current source VOC; freeing that sample stops DMA before
releasing its allocation. Freeing an unrelated resident sample does not.

Odd VOC headers are padded and their data offsets updated to make the first
PCM payload word-aligned. Odd converted PCM lengths receive one zero
(signed-silence) byte, included in the block length, so DMA start and end
addresses are even. Original disk files remain unchanged.

This deliberately pins retained audio in ST-RAM on Alt-RAM machines.
Ordinary static/BSS storage is not a substitute: it follows executable
placement and does not guarantee DMA access. On plain ST without DMA sound,
the existing sound-hardware detection still disables this backend.

Expected benefit: less synchronous work when sounds trigger, especially
repeated combat effects. No measured hardware speedup is claimed yet.

## Historical investigation

## Symptom
`DSP_Play` costs **1,010,617 cycles/call** (`opendune_prof5.txt`) — by far the
highest per-call cost in the whole profile. At ~8 MHz that is a **~126 ms
synchronous stall**, i.e. roughly 8 dropped frames the instant a sound
triggers. Because it runs at only ~0.01 calls/frame it is just 2.62% of total
runtime, so it does **not** stand out in a percentage-sorted profile — but it
is felt as a hitch exactly when combat/action starts.

## Where the cost is
Not the DMA hardware — playback is autonomous once `set_dma_sound()` hands the
buffer to the chip. All the time goes into software sample-rate conversion in
`DSP_ConvertAudio()` (`src/audio/dsp_atari.c:75`):

```c
for (i = 1, j = 0; i <= len; i++) {
    sample = (*src++) ^ 0x80;          /* unsigned -> signed for STE DMA */
    while (j < i * DMASOUND_FREQ) {    /* nearest-neighbour duplication */
        *w++ = sample;
        j += freq;
    }
}
```

Per-instruction profile confirms it: 417,066 executions of the inner
`BCS.B` / `MOVE.B D2,(A0)+` / `ADD.L D3,D1` triple against 324,958 of the
outer body — ~3.1 cycles per output byte, one byte at a time.

Two incidental defects visible in the same loop:
- `LEA.L (A1,$30e5)` is recomputed **324,958 times** inside the loop for what
  is a constant address (~2.6M cycles of pure waste).
- `Mshrink()` is used at `dsp_atari.c:86` to **grow** the buffer past its
  original `Mxalloc` size. `Mshrink` only shrinks; this is a latent bug,
  currently masked because `DMASOUND_BUFFER_SIZE` (64 KB) is usually enough.

## Why it is synchronous
`Sound_StartSound` (`src/audio/sound.c:333`) -> `Driver_Voice_Play`
(`src/audio/driver.c`) -> `DSP_Play` -> `DSP_ConvertAudio`. No deferral, no
worker, no queue — it runs on the main thread in the middle of the game loop.

## Key enabling fact: loading is completely rate-agnostic
This was verified by tracing the whole path:

- `Sound_LoadVoc` (`src/audio/sound.c:439`) is a plain
  `malloc` + `Driver_Voice_LoadFile` byte slurp.
- `Driver_Voice_LoadFile` (`src/audio/driver.c:245`) just calls
  `File_ReadBlockFile`.
- **Nothing** in the load path parses VOC structure.

The *only* two lines in the entire TOS build that interpret sample rate are in
`DSP_Play` (`src/audio/dsp_atari.c:112` and `:135`):

```c
data += READ_LE_UINT16(data + 20);   /* skip Creative VOC header */
freq = 1000000 / (256 - data[0]);    /* divisor byte -> Hz */
```

So the VOC rate is an entirely local concern. Changing the stored rate cannot
break anything upstream.

## There is no Falcon special case (checked)
Worth recording, because it is a natural assumption that Falcon's more capable
audio avoids this:

- `dsp_atari.c` is the single TOS backend for **all** Atari machines
  (`source.list:9`). There is no `C__MCH` / machine-type branch anywhere in
  `src/audio/`.
- The only runtime detection is `Getcookie(C__SND, &snd_cookie) & 2`
  (`dsp_atari.c:46`, tested at `:50`), which tests for *DMA presence*, not
  machine type.
- `DMASOUND_FREQ` is a hardcoded `#define` (12517) at `dsp_atari.c:20`.
- Falcon does not help anyway: its DAC is not free-running. It offers the same
  fixed divisor series (50066 / 25033 / 12517, minus 6258) plus some
  48 kHz-family rates — it cannot clock an arbitrary 8 kHz VOC. Dune 2's VOC
  files are, per the comment at `dsp_atari.c:68`, "all over the place", so
  resampling is unavoidable on *every* Atari.

The real reason this sits in the playback path is simply that it is a faithful
port of the DOS design, where `DSP_Play` took a raw VOC pointer.

## Options

### A. Offline conversion (recommended)
Rewrite the VOC files once, offline, so the stored rate is at or just above
`DMASOUND_FREQ`.

**Careful — the VOC divisor byte is coarse and cannot express 12517 exactly.**
`freq = 1000000 / (256 - divisor)`, so the nearest usable values are:

| divisor | freq (Hz) | effect in `DSP_ConvertAudio` |
|---------|-----------|------------------------------|
| 175     | 12345     | `freq < 12517` -> still duplicates |
| 176     | 12500     | `freq < 12517` -> still duplicates (only just) |
| **177** | **12658** | `freq >= 12517` -> inner `while` runs exactly once |

The inner `while` emits one byte per input byte only when
`freq >= DMASOUND_FREQ`, so **divisor 177 is the one to target**. It gives
`newlen = len * 12517 / 12658 = 0.9889 * len`, i.e. a very slight decimation
rather than duplication — safe, and it never grows the buffer.

Do **not** assume divisor 176 works: at 12500 Hz the condition still fails and
the duplication loop still runs.

With divisor-177 data in place the existing code already degenerates to a
1:1 pass, so most of the win needs **no code change — data only**.

Then optionally add an early-out to remove even that pass:

```c
if (freq >= DMASOUND_FREQ) { /* copy + XOR 0x80 only, or plain memcpy if
                                the sign flip is also done offline */ }
```

Advantages:
- No extra memory. Files stay on disk; only the currently-playing sample
  occupies the existing 64 KB ST RAM buffer.
- Offline you can use **proper interpolation** instead of the runtime's
  nearest-neighbour duplication, so audio quality *improves* rather than
  merely getting faster.

### B. Convert at load time, cache to disk
Convert once during scenario load into `g_voiceData[]`
(`src/audio/sound.c:24`, populated by `Sound_LoadVoc` at `:259` / `:288`),
optionally writing a `.RAW` next to the original and reusing it on later runs.

Preferable if the game data must remain unmodified. But see the memory caveat.

### MEMORY CAVEAT (constrains option B)
Converted audio **must live in ST RAM**: the DMA chip cannot read TT/alt-RAM,
which is why the buffer is `Mxalloc(s_stRamBufferSize, MX_STRAM)`
(`dsp_atari.c:57`). Note the binary is flagged `0x07` (Fastload + TT-RAM load
+ TT-RAM malloc), so ordinary `malloc` goes to fast RAM on machines that have
it — but that is exactly the memory the DMA cannot use.

8 kHz -> 12517 Hz is ~1.56x expansion, so caching *all* voices in ST RAM could
be tight on a 1 MB STE. This is the main argument for option A over B.

## Cannot be removed entirely — keep a fallback
Two paths still need runtime conversion:
- `src/audio/sound.c:349` — the `'?'` house-prefix filenames are loaded on
  demand into `g_readBuffer`, not preloaded into `g_voiceData[]`.
- Robustness: a missing converted file, or one with an unexpected divisor.

So `DSP_ConvertAudio` should stay as a fallback; it would simply almost never
run.

## Suggested order
1. Add the `freq >= DMASOUND_FREQ` fast path (small, safe, no data changes).
2. Write the offline converter; ship converted VOCs.
3. Optionally pre-flip the sign (`^ 0x80`) offline so the fast path is a bare
   `memcpy`.
4. While in there: hoist the `LEA.L` out of the loop and fix the `Mshrink`
   misuse noted above.

## Expected gain
- Removes a ~126 ms stall at sound trigger (the main user-visible benefit).
- ~2.62% of total runtime (`opendune_prof5.txt`, measured per-frame).
- Better audio quality if offline interpolation is used.
