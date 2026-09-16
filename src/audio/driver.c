/** @file src/audio/driver.c %Driver functions. */

#include <assert.h>
#include <string.h>
#include <stdlib.h>
#include "types.h"
#include "../os/math.h"
#include "../os/strings.h"
#include "../os/error.h"

#include "driver.h"

#include "dsp.h"
#include "mt32mpu.h"
#include "../config.h"
#include "../file.h"
#include "../timer.h"
#include "../inifile.h"

static bool s_driverInstalled[16];
static bool s_driverLoaded[16];

static Driver s_driverMusic;
static Driver s_driverSound;
static Driver s_driverVoice;

static MSBuffer s_bufferMusic;
static MSBuffer s_bufferSound[4];

Driver *g_driverMusic = &s_driverMusic;
Driver *g_driverSound = &s_driverSound;
Driver *g_driverVoice = &s_driverVoice;

MSBuffer *g_bufferMusic = &s_bufferMusic;
MSBuffer *g_bufferSound[4] = { &s_bufferSound[0], &s_bufferSound[1], &s_bufferSound[2], &s_bufferSound[3] };

static uint8 s_bufferSoundIndex;

static void Driver_Init(uint16 driver)
{
	if (driver >= 16) return;

	s_driverLoaded[driver] = true;
}

static void Driver_Uninstall(uint16 driver)
{
	if (driver >= 16) return;

	s_driverInstalled[driver] = false;
}

static void Driver_Uninit(uint16 driver)
{
	if (driver >= 16 || !s_driverLoaded[driver]) return;
	s_driverLoaded[driver] = false;
}

static void Drivers_Uninit(Driver *driver)
{
	if (driver == NULL) return;

	Driver_Uninit(driver->index);

	Driver_Uninstall(driver->index);

	driver->index = 0xFFFF;
}

static uint16 Driver_Install(void)
{
	uint16 index;

	for (index = 0; index < 16; index++) {
		if (!s_driverInstalled[index]) break;
	}
	if (index == 16) return 0xFFFF;
	s_driverInstalled[index] = true;

	return index;
}

static bool Drivers_Init(Driver *driver, const char *extension)
{
	driver->index = Driver_Install();
	if (driver->index == 0xFFFF) return false;

	Driver_Init(driver->index);

	strncpy(driver->extension, extension, 3);
	driver->extension[3] = '\0';

	return true;
}

static bool Drivers_SoundMusic_Init(bool enable)
{
	Driver *sound;
	Driver *music;
	uint32 size;
	uint8 i;

	sound  = g_driverSound;
	music  = g_driverMusic;

	sound->index = 0xFFFF;
	music->index = 0xFFFF;

	if (!enable) return false;

	if (!MPU_Init()) return false;

#ifdef MUNT
	if (!Drivers_Init(sound, (IniFile_GetInteger("mt32midi", 1) != 0) ? "XMI" : "C55")) return false;
#else
	if (!Drivers_Init(sound, (IniFile_GetInteger("mt32midi", 0) != 0) ? "XMI" : "C55")) return false;
#endif
	memcpy(music, sound, sizeof(Driver));

#if defined(_WIN32)
	MPU_StartThread(1000000 / 120);
#else
	Timer_Add(MPU_Interrupt, 1000000 / 120, false);
#endif

	size = MPU_GetDataSize();

	for (i = 0; i < 4; i++) {
		MSBuffer *buf = g_bufferSound[i];

		buf->buffer = calloc(1, size);
		buf->index  = 0xFFFF;
	}
	s_bufferSoundIndex = 0;

	g_bufferMusic->buffer = calloc(1, size);
	g_bufferMusic->index  = 0xFFFF;

	return true;
}

static bool Drivers_Voice_Init(bool enable)
{
	Driver *voice;

	voice = g_driverVoice;

	voice->index = 0xFFFF;

	if (!enable) return false;

	if (!DSP_Init()) return false;

	if (!Drivers_Init(voice, "VOC")) return false;

	return true;
}

static void Drivers_Reset(void)
{
	memset(s_driverInstalled, 0, sizeof(s_driverInstalled));
	memset(s_driverLoaded, 0, sizeof(s_driverLoaded));
}

void Drivers_All_Init(void)
{
	Drivers_Reset();

	// Must call SDL_InitSubSystem() before enabling MIDI.
	g_enableVoices = Drivers_Voice_Init(g_enableVoices);
	g_enableSoundMusic = Drivers_SoundMusic_Init(g_enableSoundMusic);
}

bool Driver_Music_IsPlaying(void)
{
	MSBuffer *buffer = g_bufferMusic;

	if (g_driverMusic->index == 0xFFFF) return false;
	if (buffer->index == 0xFFFF) return false;

	return MPU_IsPlaying(buffer->index) == 1;
}

bool Driver_Voice_IsPlaying(void)
{
	if (g_driverVoice->index == 0xFFFF) return false;
	return DSP_GetStatus() == 2;
}

void Driver_Sound_Play(int16 index, int16 volume)
{
	Driver *sound = g_driverSound;
	MSBuffer *soundBuffer = g_bufferSound[s_bufferSoundIndex];

	if (index < 0 || index >= 120) return;

	if (g_gameConfig.sounds == 0 && index > 1) return;

	if (sound->index == 0xFFFF) return;

	if (soundBuffer->index != 0xFFFF) {
		MPU_Stop(soundBuffer->index);
		MPU_ClearData(soundBuffer->index);
		soundBuffer->index = 0xFFFF;
	}

	soundBuffer->index = MPU_SetData(sound->content, index, soundBuffer->buffer);

	MPU_Play(soundBuffer->index);
	MPU_SetVolume(soundBuffer->index, ((volume & 0xFF) * 90) / 256, 0);

	s_bufferSoundIndex = (s_bufferSoundIndex + 1) % 4;
}

void Driver_Music_Stop(void)
{
	Driver *music = g_driverMusic;
	MSBuffer *musicBuffer = g_bufferMusic;

	if (music->index == 0xFFFF) return;
	if (musicBuffer->index == 0xFFFF) return;

	MPU_Stop(musicBuffer->index);
	MPU_ClearData(musicBuffer->index);
	musicBuffer->index = 0xFFFF;
}

void Driver_Sound_Stop(void)
{
	Driver *sound = g_driverSound;
	uint8 i;

	if (sound->index == 0xFFFF) return;

	for (i = 0; i < 4; i++) {
		MSBuffer *soundBuffer = g_bufferSound[i];
		if (soundBuffer->index == 0xFFFF) continue;

		MPU_Stop(soundBuffer->index);
		MPU_ClearData(soundBuffer->index);
		soundBuffer->index = 0xFFFF;
	}
}

/**
 * Growable, portable scratch buffer for raw file bytes read by
 * Driver_Voice_LoadFile(), shared by every voice load (preloaded or
 * ad-hoc). Ordinary heap memory -- unlike the ST-RAM DMA buffer in
 * dsp_atari.c, nothing ever needs to read this via hardware DMA, so it
 * stays plain malloc()/realloc() and portable across all DSP backends.
 * Grows (rounded to 4KB, mirroring DSP_GrowStRamBuffer()'s policy) to fit
 * the largest file seen so far; never shrinks back down during a session.
 */
static uint8 *s_voiceLoadBuffer;
static uint32 s_voiceLoadBufferSize;

static bool Driver_GrowVoiceLoadBuffer(uint32 needed)
{
	uint8 *newBuffer;

	if (needed <= s_voiceLoadBufferSize) return true;

	needed = (needed + 0x0FFF) & ~0x0FFFUL;

	newBuffer = (uint8 *)realloc(s_voiceLoadBuffer, needed);
	if (newBuffer == NULL) {
		Warning("Driver_GrowVoiceLoadBuffer: realloc(%u) failed.\n", (unsigned int)needed);
		return false;
	}
	s_voiceLoadBuffer = newBuffer;
	s_voiceLoadBufferSize = needed;
	return true;
}

/**
 * Load a voice file's raw bytes and, on TOS, convert them to already
 * signed and resampled-to-DMASOUND_FREQ PCM (see DSP_ConvertSample() in
 * dsp_atari.c).
 *
 * This function owns all buffer management: it reads the raw file into
 * its own growable scratch buffer (s_voiceLoadBuffer) and, on TOS, then
 * converts that into the DSP's own ST RAM scratch buffer. The returned
 * pointer is only valid until the next call to this function (or, on
 * TOS, the next DSP_Play()) -- callers that need to keep the data around
 * (preloaded voices) must copy it out into their own, correctly-sized
 * allocation right away; see Sound_LoadVoc() in sound.c, which sizes its
 * permanent allocation to the returned (already resampled, usually
 * smaller) length instead of the original file size.
 *
 * @param filename The name of the file to load.
 * @param outLength Set to the number of valid bytes in the returned
 * buffer, or 0 on failure.
 * @return Pointer to the loaded (and, on TOS, converted) sample data, or
 * NULL on failure (outLength is 0 in that case).
 */
const void *Driver_Voice_LoadFile(const char *filename, uint32 *outLength)
{
	uint32 fileSize;
	uint32 readLength;

	*outLength = 0;

	if (filename == NULL) return NULL;
	if (g_driverVoice->index == 0xFFFF) return NULL;

	if (!File_Exists_GetSize(filename, &fileSize)) return NULL;
	fileSize += 1;
	fileSize &= 0xFFFFFFFE;

	if (!Driver_GrowVoiceLoadBuffer(fileSize)) return NULL;

	readLength = File_ReadBlockFile(filename, s_voiceLoadBuffer, fileSize);

#ifdef TOS
	{
		uint32 convLength;
		const uint8 *converted;

		/* DSP_ConvertSample() builds its result in a scratch ST RAM
		 * buffer shared with DMA playback (see dsp_atari.c); make
		 * sure nothing is currently playing from it. */
		Driver_Voice_Stop();

		converted = DSP_ConvertSample(s_voiceLoadBuffer, readLength, &convLength, filename);
		if (converted == NULL || convLength == 0) {
			Warning("Driver_Voice_LoadFile: DSP_ConvertSample() failed for '%s'.\n", filename);
			return NULL;
		}

		*outLength = convLength;
		return converted;
	}
#else
	*outLength = readLength;
	return s_voiceLoadBuffer;
#endif
}

void Driver_Voice_Play(const uint8 *data, int16 priority)
{
	static int16 l_currentPriority = -1;	/* priority of sound currently playing */

	Driver *voice = g_driverVoice;

	if (!g_gameConfig.sounds || voice->index == 0xFFFF) return;

	if (data == NULL) {
		priority = 0x100;
	} else if (priority >= 0x100) {
		priority = 0xFF;
	}

	if (!Driver_Voice_IsPlaying()) l_currentPriority = -1;

	if (priority < l_currentPriority) return;

	Driver_Voice_Stop();

	if (data == NULL) return;

	l_currentPriority = priority;

	if (data == NULL) return;

	DSP_Play(data);
}

void Driver_Voice_Stop(void)
{
	Driver *voice = g_driverVoice;

	if (Driver_Voice_IsPlaying()) DSP_Stop();

	if (voice->contentMalloced) {
		free(voice->content);
		voice->contentMalloced = false;
	}

	voice->content = NULL;
}

void Driver_Sound_LoadFile(const char *musicName)
{
	Driver *sound = g_driverSound;
	Driver *music = g_driverMusic;

	Driver_Sound_Stop();

	if (sound->index == 0xFFFF) return;

	if (sound->content == music->content) {
		sound->content         = NULL;
		sound->filename[0]     = '\0';
		sound->contentMalloced = false;
	} else {
		Driver_UnloadFile(sound);
	}

	if (music->filename[0] != '\0') {
		char *filename;

		filename = Drivers_GenerateFilename(musicName, sound);

		if (filename != NULL && strcasecmp(filename, music->filename) == 0) {
			sound->content         = music->content;
			memcpy(sound->filename, music->filename, sizeof(music->filename));
			sound->contentMalloced = music->contentMalloced;
			return;
		}
	}

	Driver_LoadFile(musicName, sound);
}

char *Drivers_GenerateFilename(const char *name, Driver *driver)
{
	char * ext;
	static char filename[14];

	if (name == NULL || driver == NULL || driver->index == 0xFFFF) return NULL;

	strncpy(filename, name, sizeof(filename));
	filename[sizeof(filename) - 1] = '\0';
	/* Remove extension if there is one */
	ext = strrchr(filename, '.');
	if (ext != NULL) {
		*ext = '\0';
	} else {
		ext = filename + strlen(filename);
	}

	snprintf(ext, sizeof(filename) - (ext - filename), ".%s", driver->extension);

	if (File_Exists(filename)) return filename;

	/* try with XMI extension */
	memcpy(ext, ".XMI", 5);

	if (File_Exists(filename)) return filename;

	return NULL;
}

static void Drivers_SoundMusic_Uninit(void)
{
	Driver *sound = g_driverSound;
	Driver *music = g_driverMusic;

	if (g_enableSoundMusic) {
		uint8 i;
		MSBuffer *buffer = NULL;

		for (i = 0; i < 4; i++) {
			buffer = g_bufferSound[i];
			if (buffer->index != 0xFFFF) {
				MPU_Stop(buffer->index);
				MPU_ClearData(buffer->index);
				buffer->index = 0xFFFF;
			}
		}

		buffer = g_bufferMusic;
		if (buffer->index != 0xFFFF) {
			MPU_Stop(buffer->index);
			MPU_ClearData(buffer->index);
			buffer->index = 0xFFFF;
		}

#if defined(_WIN32)
		MPU_StopThread();
#else
		Timer_Remove(MPU_Interrupt);
#endif

		free(buffer->buffer);
		buffer->buffer = NULL;

		for (i = 0; i < 4; i++) {
			buffer = g_bufferSound[i];
			free(buffer->buffer);
			buffer->buffer = NULL;
		}
	}

	if (music->content != sound->content) Driver_UnloadFile(music);
	Driver_UnloadFile(sound);

	/* Only Uninit() sound, as music is a copy of sound. */
	Drivers_Uninit(sound);
	memcpy(music, sound, sizeof(Driver));

	MPU_Uninit();
}

static void Drivers_Voice_Uninit(void)
{
	Drivers_Uninit(g_driverVoice);

	if (s_voiceLoadBuffer != NULL) {
		free(s_voiceLoadBuffer);
		s_voiceLoadBuffer = NULL;
	}
	s_voiceLoadBufferSize = 0;

	DSP_Uninit();
}

void Drivers_All_Uninit(void)
{
	Drivers_SoundMusic_Uninit();
	Drivers_Voice_Uninit();
}

void Driver_LoadFile(const char *musicName, Driver *driver)
{
	char *filename;
	size_t len;

	filename = Drivers_GenerateFilename(musicName, driver);

	if (filename == NULL) return;

	Driver_UnloadFile(driver);

	/* String length including terminating \0 */
	len = strlen(filename) + 1;
	assert(len <= sizeof(driver->filename));
	memcpy(driver->filename, filename, len);

	driver->content = File_ReadWholeFile(filename);
	driver->contentMalloced = true;
	Debug("Driver_LoadFile(%s, %p): %s loaded\n", musicName, driver, filename);
}

void Driver_UnloadFile(Driver *driver)
{
	if (driver->contentMalloced) {
		free(driver->content);
	}

	driver->filename[0]     = '\0';
	driver->content         = NULL;
	driver->contentMalloced = false;
}

void Driver_Music_FadeOut(void)
{
	Driver *music = g_driverMusic;
	MSBuffer *musicBuffer = g_bufferMusic;

	if (music->index == 0xFFFF) return;
	if (musicBuffer->index == 0xFFFF) return;

	MPU_SetVolume(musicBuffer->index, 0, 2000);
}
