# Atari ST/STE DMA Sound: load-time resample+sign-conversion

This documents a set of changes to `src/audio/dsp_atari.c`,
`src/audio/atari_dma_sound.s`, `src/audio/driver.c`, `src/audio/dsp.h`
and `src/audio/sound.c` that moved VOC sample rate-conversion and
sign-conversion from *every single play* to a *one-time step at load*,
and along the way fixed a hardware/software playback-rate mismatch bug
and reduced permanent (resident) voice memory usage.

## Background: what was wrong

Dune II's original VOC sample files were recorded at a wide range of
sample rates -- a code comment already noted "the frequency of the VOC
files are all over the place" -- while STE/TT/Falcon DMA sound hardware
can only play back at one of four fixed rates (50066/25033/12517/6258Hz).
The original Atari port handled this the straightforward way:

- `DSP_Play()` parses the VOC file's first Sound Data block to find its
  source frequency and 8-bit-unsigned PCM payload.
- `DSP_ConvertAudio()` ran, **on every single play**, a per-sample linear
  resampling loop (nearest/duplicate-sample scaling, no interpolation)
  from the source frequency to a fixed hardware target frequency
  (`DMASOUND_FREQ`, originally always 12517Hz), while also XORing every
  byte with `0x80` to convert unsigned PCM to the signed PCM the DMA
  hardware expects.
- The result was written into a dedicated ST RAM scratch buffer
  (`s_stRamBuffer`, required because the DMA controller can only read
  real ST RAM) and handed to `set_dma_sound()`.

Two problems with this, found while investigating gameplay audio
stutter:

1. **The resampling+sign-conversion cost was paid on every play**, even
   for voices preloaded once and replayed dozens of times per session
   (most voices -- see `Voice_LoadVoices()` in `sound.c`). The converted
   result itself was never cached, only the raw unsigned source was.
2. **A separate, independent hardware/software rate mismatch bug**: the
   DMA hardware's playback-rate-select register (`$FFFF8921`, written by
   `setdma` in `atari_dma_sound.s`) was **hardcoded** to mode 1 (12517Hz),
   completely independent of whatever `DMASOUND_FREQ` the C code targeted
   when building the buffer. Any attempt to build the software buffer at
   a different rate was silently played back at the wrong speed by the
   hardware regardless.

## Rate choice: why 6258Hz, not 12517Hz

An experiment (`DSP_ATARI_NO_RESAMPLE_ENABLE`) was tried first: skip
resampling entirely and play source PCM directly at a fixed hardware
rate, keeping only the sign conversion. Between the two rates available
on STE that could plausibly work for ~8kHz-ish speech, 6258Hz was
initially guessed as the better fit (relative to an assumed ~8000Hz
source, 6258Hz is a factor 0.782, roughly -4.3 semitones, vs 12517Hz's
factor 1.565, roughly +7.7 semitones -- half the deviation in musical/
log2 terms, and slowed-down speech is usually judged less jarring than
sped-up "chipmunk" speech).

That assumption was checked directly with an ad-hoc `error.log` survey
(`DSP_ATARI_FREQ_STATS_ENABLE`, see below) of every VOC file's actual
encoded frequency across a real play session. The result: **most of the
game's speech samples are recorded far above 8kHz** -- 82 of 119
surveyed samples (69%) are at 11235Hz or 14705Hz, not ~8000Hz. Only a
handful of short low-rate sound effects (gunshots, explosions, clanks)
sit in the 4000-8000Hz range. This explains why the initial 6258Hz
no-resample experiment sounded much more dragged-down/deepened than the
semitone estimate predicted (the estimate assumed an 8kHz source; the
actual median source is closer to ~11-12kHz).

Despite that, **6258Hz was kept as the permanent target rate**, not
reverted to 12517Hz, for a memory reason unrelated to pitch: resident
voice data at ~40 preloaded samples was measured at roughly **1.4MB raw**
(original VOC rates), which would be **~1.6MB if upsampled to 12517Hz**
but only **~0.8MB when downsampled to 6258Hz**. On stock ST/STE RAM
budgets, halving resident audio memory was judged more valuable than the
pitch/tempo fidelity 12517Hz would have preserved. (The largest single
converted sample was confirmed to be ~31.7KB at 6258Hz -- informs the
ST-RAM scratch buffer sizing, see below.)

## Fix 1: hardware/software rate mismatch (`atari_dma_sound.s`)

- `dsp_atari.c`: added a `DMASOUND_MODE` macro (0=6258Hz, 1=12517Hz,
  2=25033Hz, 3=50066Hz), derived from `DMASOUND_FREQ` via `#if`/`#elif`,
  with a `#error` if `DMASOUND_FREQ` is ever set to an unsupported value.
- `atari_dma_sound.s`'s `_set_dma_sound` now takes a third argument
  (`mode`) instead of hardcoding `moveq.l #1,d0` (mode 1 / 12517Hz)
  before writing the STE rate-select register `$FFFF8921`. The call site
  in `dsp_atari.c` passes `DMASOUND_MODE`, keeping hardware and software
  rate always in sync regardless of what `DMASOUND_FREQ` is set to.

## Fix 2: load-time resample + sign-conversion (`DSP_ConvertSample`)

New function `DSP_ConvertSample()` in `dsp_atari.c`, called once per
sample load from `Driver_Voice_LoadFile()` in `driver.c` (the single
choke point every VOC load -- preloaded or the ad-hoc `'?'`-prefixed
path -- goes through):

- Walks the VOC container's blocks (mirroring the header-skip and
  block-type/length parsing `DSP_Play()` already did -- kept in sync,
  update both if VOC parsing logic ever changes).
- Copies the header and any non-sound-data blocks verbatim.
- For each Block Type 1 (Sound data) block: resamples the payload from
  its recorded rate to `DMASOUND_FREQ` (same linear/duplicate-sample
  algorithm `DSP_ConvertAudio()` used to run per-play) and XORs it to
  signed PCM in the same pass, then rewrites that block's 3-byte length
  field and 1-byte frequency-divisor byte (`DMASOUND_VOC_DIVISOR`, the
  VOC divisor byte that decodes closest to `DMASOUND_FREQ` -- 96 for
  6258Hz, which decodes back to 6250Hz) to describe the new payload.
- The VOC container format itself is preserved (not flattened to raw
  PCM) -- `DSP_Play()` is otherwise unchanged and still parses/plays the
  (now already-converted) first block exactly as before.

Because the resampled size can differ from the original (most of this
game's samples are >6258Hz source and shrink; the handful of <6258Hz
short sound effects grow slightly), the result is **not** written back
into the input buffer -- it's built into `s_stRamBuffer`, the same
ST-RAM DMA scratch buffer `DSP_Play()` itself uses for playback (grown
as needed via a shared `DSP_GrowStRamBuffer()` helper, 4KB-rounded to
avoid repeated resize calls for near-identical sample sizes). The
function returns a pointer into that scratch buffer plus the converted
length via an out-parameter; the caller must copy the result out before
the next conversion or play (since the buffer is shared/reused), and
must ensure nothing is currently DMA-playing from it first (the caller
calls `Driver_Voice_Stop()` before converting).

`DSP_ConvertAudio()` (the old per-play runtime resampler) is still
present as a fallback code path but is effectively dead in the current
(`DSP_ATARI_NO_RESAMPLE_ENABLE`, permanently defined) configuration --
`DSP_Play()` now always receives data that's already at `DMASOUND_FREQ`
and already signed, so its job is just a flat copy into the DMA buffer.

## Fix 3: buffer ownership restructure (`driver.c`, `sound.c`)

To realize the RAM savings from downsampling (not just make resampling
correct), buffer allocation was restructured so **permanent/resident**
voice buffers are sized to the *converted* (usually smaller) length, not
the original file size:

- `driver.c` gained its own portable, grow-only scratch buffer
  (`s_voiceLoadBuffer`, plain `malloc`/`realloc`, 4KB-rounded growth,
  freed at `Drivers_Voice_Uninit()`) to hold raw file bytes as they're
  read from disk. This is ordinary heap memory, not ST-RAM -- nothing
  reads it via DMA, so it stays fully portable across DSP backends.
- `Driver_Voice_LoadFile(filename, uint32 *outLength)` was rewritten to
  own the whole load: it queries the file size itself, grows its own
  scratch buffer, reads the file, and (on TOS) converts via
  `DSP_ConvertSample()`. It returns a pointer to the loaded (and, on
  TOS, already-converted) data plus its length; the returned pointer is
  only valid until the next call.
- `Sound_LoadVoc()` (the preload path, `sound.c`) now allocates its
  permanent resident buffer sized to the *returned* (converted) length
  and copies the result in -- this is where the ~1.4MB-to-~0.8MB
  resident-memory reduction is actually realized, not just theoretically
  possible.
- The ad-hoc `'?'`-prefixed path (`Sound_StartSound()`) no longer copies
  through the shared `g_readBuffer` at all -- it plays directly from
  whatever `Driver_Voice_LoadFile()` returns, since that data doesn't
  need to persist beyond one playback.

## Buffer growth policy

Both scratch buffers (`s_stRamBuffer` in `dsp_atari.c`,
`s_voiceLoadBuffer` in `driver.c`) use the same *grow-only, 4KB-rounded,
never-shrink* policy: a request that exceeds the current size grows the
buffer to `(needed + 4095) & ~4095`, and the buffer stays at that size
for the rest of the session (no repeated resizing once it stabilizes at
the largest sample seen). `DSP_Init()`'s initial `s_stRamBuffer`
allocation (`DMASOUND_BUFFER_SIZE`) is derived from `DMASOUND_FREQ`
(scaled off the old fixed 64KB@12517Hz reference, ~32KB at 6258Hz after
4KB rounding) instead of a flat hardcoded constant, so it already fits
the observed largest converted sample without an immediate first-load
grow.

## Frequency survey (`DSP_ATARI_FREQ_STATS_ENABLE`)

A debug-only build flag, `-DDSP_ATARI_FREQ_STATS_ENABLE` (off by
default, this project's build system has no `EXTRACFLAGS`-style hook --
toggle via editing the `#define` in `dsp_atari.c` and running a plain
`make`), logs one line per loaded VOC sample-data block to `error.log`
via `Error()`: `FREQSTATS <filename> freq=<Hz> len=<bytes>`. This is
what produced the real-world frequency distribution described above. It
remains in the tree as a debugging aid in case source data or frequency
assumptions ever need re-checking, but is not needed for normal builds.

## Verified

- `dsp_atari.c`, `driver.c`, `sound.c` compile clean (`m68k-atari-mint-gcc`,
  project's real TOS `-DTOS` flags) both with and without
  `-DDSP_ATARI_FREQ_STATS_ENABLE`.
- Full project `make -j4` builds and links `opendune.tos` clean.
- `atari_dma_sound.s` assembles clean with vasm; disassembly-checked
  stack-offset and register/dataflow correctness for the added `mode`
  argument.
- Host-side differential test (2,000 synthetic multi-scenario VOC
  buffers, both hardware rates) confirmed the split-out sign-conversion
  produces byte-identical results to the original single-pass inline-XOR
  reference.
- Post-refactor CPU profile (`opendune_audio.txt`, 146s capture, no voice
  loads during the capture window) confirms the intended effect at
  steady state: `DSP_Play` itself costs ~52K cycles across the entire
  capture (~0.002% of 2.337B total cycles); the whole audio subsystem
  (DSP/Driver_Voice/Driver_Sound/MPU/Sound_/Voice_) totals ~1.36%, down
  from ~3.19-3.76% in earlier captures before this work (not a
  cycle-for-cycle apples-to-apples comparison across differently-sized
  captures, but consistent with removing per-play resample+sign-convert
  work entirely). This capture did not include a voice-load/house-switch
  event, so it does not exercise `DSP_ConvertSample()`'s one-time
  load-time cost -- a future profile spanning a level/house transition
  would be needed to characterize that cost directly.

## Known open question: Falcon's missing 6258Hz mode

STE and TT support 6258Hz; **Falcon does not** (its DMA sound hardware
only supports 12517/25033/50066Hz-class rates in this mode-select
scheme). Since resampling now happens once at load time and is baked
permanently into each sample's stored VOC block (not decided per-play),
a build targeting Falcon needs a different `DMASOUND_FREQ`/
`DMASOUND_MODE`/`DMASOUND_VOC_DIVISOR` than an ST/STE build -- this
hasn't been addressed yet, since this effort's stated scope is ST/STE
only (see `AGENTS.md`). Two approaches were discussed for a future
Falcon-inclusive build:

1. **Compile-time**: a separate build configuration/target symbol per
   machine family (matching how `--cpu=68000|...` already selects CPU
   variants in `config.lib`), picking `DMASOUND_FREQ` at compile time.
2. **Run-time**: detect the machine once at startup via the `_MCH`
   cookie (the same mechanism `Detect_Machine()` in `video_atari.c`
   already uses for `MCH_ST`/`MCH_STE`/`MCH_MEGA_STE`/`MCH_TT`/
   `MCH_FALCON`), and choose the resample target frequency dynamically
   before any sample is ever loaded/converted -- since the machine type
   is fixed for the life of a running session, this is a one-time
   decision, not a per-frame one.

Not yet decided or implemented -- out of scope for the current ST/STE
effort, tracked here for whoever picks up Falcon support later.

**Note:** a real build already effectively differentiates by CPU target
today -- stock ST/STE requires `--cpu=68000`, while Falcon/TT realistically
build for `--cpu=68030` (`config.lib`'s default). So a compile-time
`DMASOUND_FREQ`/`DMASOUND_MODE` choice keyed off the selected `--cpu`
value (68000 => 6258Hz, 68020+ => a Falcon-compatible rate) would piggyback
on a build-configuration axis that already exists and is already required
to differ between these targets, rather than introducing a new one --
worth keeping in mind if/when this is revisited, as it may be simpler than
either of the two options above.
