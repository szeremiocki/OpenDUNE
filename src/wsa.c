/** @file src/wsa.c WSA routines. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "types.h"
#include "os/math.h"
#include "os/endian.h"
#include "os/error.h"
#include "gfx.h"

#include "wsa.h"

#include "codec/format40.h"
#include "codec/format80.h"
#include "file.h"
#include "gui/widget.h"
#ifdef TOS
#include "video/video.h"
#endif


/**
 * The flags of a WSA Header.
 */
typedef struct WSAFlags {
	BIT_U8 notmalloced:1;                                   /*!< If the WSA is in memory of the caller. */
	BIT_U8 malloced:1;                                      /*!< If the WSA is malloc'd by us. */
	BIT_U8 dataOnDisk:1;                                    /*!< Only the header is in the memory. Rest is on disk. */
	BIT_U8 dataInMemory:1;                                  /*!< The whole WSA is in memory. */
	BIT_U8 displayInBuffer:1;                               /*!< The output display is in the buffer. */
	BIT_U8 noAnimation:1;                                   /*!< If the WSA has animation or not. */
	BIT_U8 hasNoFirstFrame:1;                               /*!< The WSA is the continuation of another one. */
	BIT_U8 hasPalette:1;                                    /*!< Indicates if the WSA has a palette stored. */
}  WSAFlags;

/**
 * The header of a WSA file that is being read.
 */
typedef struct WSAHeader {
	uint16 frameCurrent;                                    /*!< Current frame displaying. */
	uint16 frames;                                          /*!< Total frames in WSA. */
	uint16 width;                                           /*!< Width of WSA. */
	uint16 height;                                          /*!< Height of WSA. */
	uint16 bufferLength;                                    /*!< Length of the buffer. */
	uint8 *buffer;                                          /*!< The buffer. */
	uint8 *fileContent;                                     /*!< The content of the file. */
	char   filename[13];                                    /*!< Filename of WSA. */
	WSAFlags flags;                                         /*!< Flags of WSA. */
	uint16 lengthHeader;									/*!< length of file header (8 or 10) */
#ifdef TOS
	struct WSAPlanarRecording *planar;
#endif
} WSAHeader;

#ifdef TOS
typedef struct WSAPlanarRecording {
	uint16 **frames;
	uint16 *pixels;
	uint16 *composed;
	uint16 groups;
	uint32 dirty[SCREEN_HEIGHT];
} WSAPlanarRecording;

static void WSA_FreePlanar(WSAPlanarRecording *recording, uint16 frames)
{
	uint16 i;

	if (recording == NULL) return;
	if (recording->frames != NULL) {
		for (i = 0; i <= frames; i++) free(recording->frames[i]);
	}
	free(recording->frames);
	free(recording->pixels);
	free(recording->composed);
	free(recording);
}

static uint32 WSA_EncodePlanarDelta(uint16 *dst, const uint16 *previous,
                                   const uint16 *next, uint16 groups, uint16 height)
{
	uint16 group = 0, end = 0, total = groups * height;
	uint32 words = 0;

	while (group < total) {
		uint16 first, count, i;

		if (memcmp(previous + group * 4, next + group * 4, 8) == 0) {
			group++;
			continue;
		}
		first = group;
		do {
			group++;
		} while (group < total && group % groups != 0 &&
		         memcmp(previous + group * 4, next + group * 4, 8) != 0);
		count = group - first;
		if (dst != NULL) {
			dst[words] = first - end;
			dst[words + 1] = count;
			for (i = 0; i < count * 4; i++)
				dst[words + 2 + i] = previous[first * 4 + i] ^ next[first * 4 + i];
		}
		words += 2 + count * 4;
		end = group;
	}
	if (dst != NULL) dst[words] = dst[words + 1] = 0;
	return (words + 2) * sizeof(uint16);
}

static void WSA_ApplyPlanarDelta(WSAPlanarRecording *recording, uint16 frame)
{
	const uint16 *src = recording->frames[frame];
	uint16 group = 0;

	while (true) {
		uint16 count, row, first, words;
		uint16 *dst;

		group += *src++;
		count = *src++;
		if (count == 0) break;
		row = group / recording->groups;
		first = group % recording->groups;
		recording->dirty[row] |= ((1UL << count) - 1) << first;
		dst = recording->pixels + group * 4;
		words = count * 4;
		do {
			*dst++ ^= *src++;
		} while (--words != 0);
		group += count;
	}
}

static bool WSA_PlanarFilename(const char *filename, char name[13])
{
	const char *extension = strrchr(filename, '.');
	size_t length = extension != NULL ? (size_t)(extension - filename) : strlen(filename);

	if (length == 0 || length > 8 || strchr(filename, '/') != NULL ||
	    strchr(filename, '\\') != NULL) return false;
	memcpy(name, filename, length);
	memcpy(name + length, ".PWS", 5);
	return true;
}

static uint32 WSA_PlanarDeltaLength(const uint16 *src)
{
	const uint16 *start = src;
	while (src[1] != 0) src += 2 + src[1] * 4;
	return (uint32)(src + 2 - start) * sizeof(*src);
}

static bool WSA_ValidatePlanarDelta(const uint16 *src, uint32 bytes, uint16 groups, uint16 height)
{
	uint32 words = bytes / 2, position = 0, group = 0;
	uint32 total = (uint32)groups * height;

	while (words - position >= 2) {
		uint16 skip = src[position++], count = src[position++];
		if (count == 0) return skip == 0 && position == words;
		if (skip > total - group) return false;
		group += skip;
		if (count > total - group || count > groups - group % groups ||
		    (uint32)count * 4 > words - position) return false;
		position += (uint32)count * 4;
		group += count;
	}
	return false;
}

/* Plane words and commands are stored big-endian, matching native ST memory. */
static bool WSA_WritePlanarWords(FILE *file, const uint16 *src, uint32 bytes)
{
#if __BYTE_ORDER == __LITTLE_ENDIAN
	uint16 swapped[256];
	while (bytes != 0) {
		uint16 i, count = min(bytes / 2, sizeof(swapped) / sizeof(*swapped));
		for (i = 0; i < count; i++) swapped[i] = (src[i] >> 8) | (src[i] << 8);
		if (fwrite(swapped, 2, count, file) != count) return false;
		src += count;
		bytes -= (uint32)count * 2;
	}
	return true;
#else
	return fwrite(src, 1, bytes, file) == bytes;
#endif
}

static void WSA_SavePlanar(WSAHeader *header, const char *name)
{
	WSAPlanarRecording *recording = header->planar;
	FILE *file = fopendatadir(SEARCHDIR_PERSONAL_DATA_DIR, name, "wb");
	uint16 frame;
	bool saved;

	if (file == NULL) {
		Warning("Planar WSA %s: cannot create %s; using in-memory recording\n", header->filename, name);
		return;
	}
	saved = fwrite("PWS4", 1, 4, file) == 4 &&
	    fwrite_le_uint16(header->frames, file) &&
	    fwrite_le_uint16(header->width, file) &&
	    fwrite_le_uint16(header->height, file) &&
	    fwrite_le_uint16((header->flags.noAnimation ? 1 : 0) |
	        (header->flags.hasNoFirstFrame ? 2 : 0), file);
	for (frame = 0; saved && frame <= header->frames; frame++) {
		uint32 bytes = frame == 0 ? (uint32)recording->groups * header->height * 8 :
		    WSA_PlanarDeltaLength(recording->frames[frame]);
		saved = fwrite_le_uint32(bytes, file) && WSA_WritePlanarWords(file, recording->frames[frame], bytes);
	}
	if (fclose(file) != 0) saved = false;
	if (!saved) {
		File_Delete_Personal(name);
		Warning("Planar WSA %s: writing %s failed; using in-memory recording\n", header->filename, name);
	}
}

static void *WSA_LoadPlanar(const char *filename, const char *name, void *wsa, uint32 wsaSize)
{
	FILE *file = fopendatadir(SEARCHDIR_PERSONAL_DATA_DIR, name, "rb");
	WSAPlanarRecording *recording = NULL;
	WSAHeader *header;
	uint16 frames = 0, width, height, flags, frame;
	uint32 remaining, imageBytes;
	long size;
	char magic[4];
	const char *failure = "invalid or incomplete recording";

	if (file == NULL) {
		if (errno != ENOENT)
			Warning("Planar WSA %s: cannot read %s; loading original\n", filename, name);
		return NULL;
	}
	if (fseek(file, 0, SEEK_END) != 0 || (size = ftell(file)) < 12 ||
	    (unsigned long)size > 0xffffffffUL ||
	    fseek(file, 0, SEEK_SET) != 0 ||
	    fread(magic, 1, 4, file) != 4 || memcmp(magic, "PWS4", 4) != 0 ||
	    !fread_le_uint16(&frames, file) || !fread_le_uint16(&width, file) ||
	    !fread_le_uint16(&height, file) || !fread_le_uint16(&flags, file) ||
	    frames == 0 || frames > 0x7fff || width == 0 || width > SCREEN_WIDTH ||
	    height == 0 || height > SCREEN_HEIGHT || flags > 3) goto fail;
	remaining = (uint32)size - 12;
	if (wsa != NULL && wsaSize > 1 && wsaSize < sizeof(WSAHeader)) {
		failure = "caller buffer too small";
		goto fail;
	}
	recording = calloc(1, sizeof(*recording));
	if (recording == NULL) goto memory_fail;
	recording->groups = (width + 15) >> 4;
	imageBytes = (uint32)recording->groups * height * 8;
	recording->frames = calloc((uint32)frames + 1, sizeof(*recording->frames));
	recording->pixels = malloc(imageBytes);
	recording->composed = malloc(imageBytes);
	if (recording->frames == NULL || recording->pixels == NULL || recording->composed == NULL)
		goto memory_fail;
	for (frame = 0; frame <= frames; frame++) {
		uint32 bytes;
		if (remaining < 4 || !fread_le_uint32(&bytes, file)) goto fail;
		remaining -= 4;
		if ((bytes & 1) != 0 || bytes > remaining ||
		    (frame == 0 ? bytes != imageBytes :
		        bytes < 4 || bytes > (uint32)recording->groups * height * 12 + 4)) goto fail;
		recording->frames[frame] = malloc(bytes);
		if (recording->frames[frame] == NULL) goto memory_fail;
		if (fread(recording->frames[frame], 1, bytes, file) != bytes) goto fail;
		remaining -= bytes;
#if __BYTE_ORDER == __LITTLE_ENDIAN
		{
			uint32 word;
			for (word = 0; word < bytes / 2; word++) {
				uint16 value = recording->frames[frame][word];
				recording->frames[frame][word] = (value >> 8) | (value << 8);
			}
		}
#endif
		if (frame != 0 && !WSA_ValidatePlanarDelta(recording->frames[frame], bytes,
		        recording->groups, height)) goto fail;
	}
	if (remaining != 0) goto fail;
	if (fclose(file) != 0) {
		file = NULL;
		goto fail;
	}
	file = NULL;
	header = wsa != NULL ? wsa : malloc(sizeof(*header));
	if (header == NULL) goto memory_fail;
	memset(header, 0, sizeof(*header));
	header->frames = frames;
	header->frameCurrent = frames;
	header->width = width;
	header->height = height;
	header->flags.malloced = wsa == NULL;
	header->flags.notmalloced = wsa != NULL;
	header->flags.noAnimation = (flags & 1) != 0;
	header->flags.hasNoFirstFrame = (flags & 2) != 0;
	header->planar = recording;
	strncpy(header->filename, filename, sizeof(header->filename) - 1);
	return header;

memory_fail:
	failure = "out of memory";
fail:
	if (file != NULL) fclose(file);
	WSA_FreePlanar(recording, frames);
	Warning("Planar WSA %s: %s in %s; loading original\n", filename, failure, name);
	return NULL;
}
#endif

MSVC_PACKED_BEGIN
/**
 * The header of a WSA file as on the disk.
 */
typedef struct WSAFileHeader {
	/* 0000(2)   */ uint16 frames;                     /*!< Amount of animation frames in this WSA. */
	/* 0002(2)   */ uint16 width;                      /*!< Width of WSA. */
	/* 0004(2)   */ uint16 height;                     /*!< Height of WSA. */
	/* 0006(2)   */ uint16 requiredBufferSize;         /*!< The size the buffer has to be at least to process this WSA. */
	/* 0008(2)   */ uint16 hasPalette;                 /*!< Indicates if the WSA has a palette stored. */
	/* 000A(4)   */ uint32 firstFrameOffset;           /*!< Offset where animation starts. */
	/* 000E(4)   */ uint32 secondFrameOffset;          /*!< Offset where animation ends. */
} WSAFileHeader;

/**
 * Get the amount of frames a WSA has.
 */
uint16 WSA_GetFrameCount(void *wsa)
{
	WSAHeader *header = (WSAHeader *)wsa;

	if (header == NULL) return 0;
	return header->frames;
}

WSAFrameFormat WSA_GetFrameFormat(void *wsa)
{
#ifdef TOS
	const WSAHeader *header = wsa;
	if (header != NULL && header->planar != NULL) return WSA_FRAME_PLANAR;
#else
	VARIABLE_NOT_USED(wsa);
#endif
	return WSA_FRAME_CHUNKY;
}

/**
 * Get the offset in the fileContent which stores the animation data for a
 *  given frame.
 * @param header The header of the WSA.
 * @param frame The frame of animation.
 * @return The offset for the animation from the beginning of the fileContent.
 */
static uint32 WSA_GetFrameOffset_FromMemory(WSAHeader *header, uint16 frame)
{
	uint16 lengthAnimation = 0;
	uint32 animationFrame;
	uint32 animation0;

	animationFrame = READ_LE_UINT32(header->fileContent + frame * 4);

	if (animationFrame == 0) return 0;

	animation0 = READ_LE_UINT32(header->fileContent);
	if (animation0 != 0) {
		lengthAnimation = READ_LE_UINT32(header->fileContent + 4) - animation0;
	}

	return animationFrame - lengthAnimation - header->lengthHeader;
}

/**
 * Get the offset in the file which stores the animation data for a given
 *  frame.
 * @param fileno The fileno of an opened WSA.
 * @param frame The frame of animation.
 * @return The offset for the animation from the beginning of the file.
 */
static uint32 WSA_GetFrameOffset_FromDisk(uint8 fileno, uint16 frame, uint16 lengthHeader)
{
	uint32 offset;

	File_Seek(fileno, frame * 4 + lengthHeader, 0);
	offset = File_Read_LE32(fileno);

	return offset;
}

/**
 * Go to the next frame in the animation.
 * @param wsa WSA pointer.
 * @param frame Frame number to go to.
 * @param dst Destination buffer to write the animation to.
 * @return 1 on success, 0 on failure.
 */
static uint16 WSA_GotoNextFrame(void *wsa, uint16 frame, uint8 *dst)
{
	WSAHeader *header = (WSAHeader *)wsa;
	uint16 lengthPalette;
	uint8 *buffer;

#ifdef TOS
	if (header->planar != NULL) {
		WSA_ApplyPlanarDelta(header->planar, frame);
		return 1;
	}
#endif
	lengthPalette = (header->flags.hasPalette) ? 0x300 : 0;

	buffer = header->buffer;

	if (header->flags.dataInMemory) {
		uint32 positionStart;
		uint32 positionEnd;
		uint32 length;
		uint8 *positionFrame;

		positionStart = WSA_GetFrameOffset_FromMemory(header, frame);
		positionEnd = WSA_GetFrameOffset_FromMemory(header, frame + 1);
		length = positionEnd - positionStart;

		positionFrame = header->fileContent + positionStart;
		buffer += header->bufferLength - length;

		memmove(buffer, positionFrame, length);
	} else if (header->flags.dataOnDisk) {
		uint8 fileno;
		uint32 positionStart;
		uint32 positionEnd;
		uint32 length;
		uint32 res;

		fileno = File_Open(header->filename, FILE_MODE_READ);

		positionStart = WSA_GetFrameOffset_FromDisk(fileno, frame, header->lengthHeader);
		positionEnd = WSA_GetFrameOffset_FromDisk(fileno, frame + 1, header->lengthHeader);
		length = positionEnd - positionStart;

		if (positionStart == 0 || positionEnd == 0 || length == 0) {
			File_Close(fileno);
			return 0;
		}

		buffer += header->bufferLength - length;

		File_Seek(fileno, positionStart + lengthPalette, 0);
		res = File_Read(fileno, buffer, length);
		File_Close(fileno);

		if (res != length) return 0;
	}

	Format80_Decode(header->buffer, buffer, header->bufferLength);

	if (header->flags.displayInBuffer) {
		Format40_Decode(dst, header->buffer);
	} else {
		Format40_Decode_XorToScreen(dst, header->buffer, header->width);
	}

	return 1;
}

/**
 * Load a WSA file.
 * @param filename Name of the file.
 * @param wsa Data buffer for the WSA.
 * @param wsaSize Current size of buffer.
 * @param reserveDisplayFrame True if we need to reserve the display frame.
 * @return Address of loaded WSA file, or NULL.
 */
void *WSA_LoadFile(const char *filename, void *wsa, uint32 wsaSize, bool reserveDisplayFrame, bool allowPlanar)
{
	WSAFlags flags;
	WSAFileHeader fileheader;
	WSAHeader *header;
	uint32 bufferSizeMinimal;
	uint32 bufferSizeOptimal;
	uint16 lengthHeader = 10;
	uint16 lengthOffsets;
	uint8 fileno;
	uint16 lengthPalette;
	uint16 lengthFirstFrame;
	uint32 lengthFileContent;
	uint32 displaySize;
	uint8 *buffer;
#ifdef TOS
	char planarFilename[13];
	allowPlanar = allowPlanar && Video_Atari_CursorDirect();
	if (allowPlanar) {
		void *prepared;
		if (!WSA_PlanarFilename(filename, planarFilename)) {
			Warning("Planar WSA %s: unsupported cache filename; loading original\n", filename);
			allowPlanar = false;
		} else {
			prepared = WSA_LoadPlanar(filename, planarFilename, wsa, wsaSize);
			if (prepared != NULL) return prepared;
		}
	}
#else
	VARIABLE_NOT_USED(allowPlanar);
#endif

	memset(&flags, 0, sizeof(flags));

	fileno = File_Open(filename, FILE_MODE_READ);
	fileheader.frames = File_Read_LE16(fileno);
	fileheader.width = File_Read_LE16(fileno);
	fileheader.height = File_Read_LE16(fileno);
	fileheader.requiredBufferSize = File_Read_LE16(fileno);
	fileheader.hasPalette = File_Read_LE16(fileno);		/* has palette */
	Debug("%s : %u %ux%u %u %x\n", filename, fileheader.frames, fileheader.width, fileheader.height, fileheader.requiredBufferSize, fileheader.hasPalette);
	fileheader.firstFrameOffset = File_Read_LE32(fileno);	/* Offset of 1st frame */
	fileheader.secondFrameOffset = File_Read_LE32(fileno);	/* Offset of 2nd frame (end of 1st frame) */
	if (fileheader.firstFrameOffset != (uint32)lengthHeader + 8 + 4 * fileheader.frames
	    && fileheader.secondFrameOffset != (uint32)lengthHeader + 8 + 4 * fileheader.frames) {
		/* Old format from Dune v1.0 */
		lengthHeader = 8;
		fileheader.hasPalette = 0;
		File_Seek(fileno, -10, 1);
		fileheader.firstFrameOffset = File_Read_LE32(fileno);
		fileheader.secondFrameOffset = File_Read_LE32(fileno);
	}
	Debug("               %08x %08x\n", fileheader.firstFrameOffset, fileheader.secondFrameOffset);
	if (fileheader.requiredBufferSize < 33) {
		Warning("WSA %s: invalid decoder workspace size\n", filename);
		File_Close(fileno);
		return NULL;
	}

	lengthPalette = 0;
	if (fileheader.hasPalette) {
		flags.hasPalette = true;

		lengthPalette = 0x300;	/* length of a 256 color RGB palette */
	}

	lengthFileContent = File_Seek(fileno, 0, 2);

	lengthFirstFrame = 0;
	if (fileheader.firstFrameOffset != 0) {
		lengthFirstFrame = fileheader.secondFrameOffset - fileheader.firstFrameOffset;
	} else {
		flags.hasNoFirstFrame = true;	/* is the continuation of another WSA */
	}

	lengthFileContent -= lengthPalette + lengthFirstFrame + lengthHeader;

	displaySize = 0;
	if (reserveDisplayFrame) {
		flags.displayInBuffer = true;
		displaySize = fileheader.width * fileheader.height;
	}

	bufferSizeMinimal = displaySize + fileheader.requiredBufferSize - 33 + sizeof(WSAHeader);
	bufferSizeOptimal = bufferSizeMinimal + lengthFileContent;

	if (wsaSize > 1 && wsaSize < bufferSizeMinimal) {
		File_Close(fileno);

		return NULL;
	}
	if (wsaSize == 0) wsaSize = bufferSizeOptimal;
	if (wsaSize == 1) wsaSize = bufferSizeMinimal;

	if (wsa == NULL) {
		if (wsaSize == 0) {
			wsaSize = bufferSizeOptimal;
		} else if (wsaSize == 1) {
			wsaSize = bufferSizeMinimal;
		} else if (wsaSize >= bufferSizeOptimal) {
			wsaSize = bufferSizeOptimal;
		} else {
			wsaSize = bufferSizeMinimal;
		}

		wsa = calloc(1, wsaSize);
		if (wsa == NULL) {
			Warning("WSA %s: out of memory\n", filename);
			File_Close(fileno);
			return NULL;
		}
		flags.malloced = true;
	} else {
		flags.notmalloced = true;
	}

	header = (WSAHeader *)wsa;
	buffer = (uint8 *)wsa + sizeof(WSAHeader);

	header->flags = flags;
	header->lengthHeader = lengthHeader;

	if (reserveDisplayFrame) {
		memset(buffer, 0, displaySize);
	}

	buffer += displaySize;

	if ((fileheader.frames & 0x8000) != 0) {
		fileheader.frames &= 0x7FFF;
	}

	header->frameCurrent = fileheader.frames;
	header->frames       = fileheader.frames;
	header->width        = fileheader.width;
	header->height       = fileheader.height;
	/* The file's workspace size includes its historical 33-byte header. */
	header->bufferLength = fileheader.requiredBufferSize - 33;
	header->buffer       = buffer;
#ifdef TOS
	header->planar       = NULL;
#endif
	strncpy(header->filename, filename, sizeof(header->filename) - 1);
	header->filename[sizeof(header->filename) - 1] = '\0';

	lengthOffsets = (fileheader.frames + 2) * 4;

	if (wsaSize >= bufferSizeOptimal) {
		header->fileContent = buffer + header->bufferLength;

		File_Seek(fileno, lengthHeader, 0);
		File_Read(fileno, header->fileContent, lengthOffsets);
		File_Seek(fileno, lengthFirstFrame + lengthPalette, 1);
		File_Read(fileno, header->fileContent + lengthOffsets, lengthFileContent - lengthOffsets);

		header->flags.dataInMemory = true;
		if (WSA_GetFrameOffset_FromMemory(header, header->frames + 1) == 0) header->flags.noAnimation = true;
	} else {
		header->flags.dataOnDisk = true;
		if (WSA_GetFrameOffset_FromDisk(fileno, header->frames + 1, header->lengthHeader) == 0) header->flags.noAnimation = true;
	}

	{
		uint8 *b;
		b = buffer + header->bufferLength - lengthFirstFrame;

		File_Seek(fileno, lengthHeader + lengthOffsets + lengthPalette, 0);
		File_Read(fileno, b, lengthFirstFrame);
		File_Close(fileno);

		if (!header->flags.hasNoFirstFrame)
			Format80_Decode(buffer, b, header->bufferLength);
	}
#ifdef TOS
	if (allowPlanar && !header->flags.hasNoFirstFrame &&
	    WSA_PreparePlanar(wsa, header->width, header->height))
		WSA_SavePlanar(header, planarFilename);
#endif
	return wsa;
}

#ifdef TOS
static bool WSA_PreparePlanarSeeded(void *wsa, uint16 width, uint16 height, const uint8 *seed)
{
	WSAHeader *header = wsa;
	WSAPlanarRecording *recording = NULL;
	uint8 *chunky = NULL, *saved = NULL;
	uint16 *next = NULL;
	uint32 bytes, recordedBytes = 0;
	uint16 frame;
	bool ready = false;

	if (header == NULL || !Video_Atari_CursorDirect()) return false;
	if (header->planar != NULL && header->width == width && header->height == height) return true;
	if (header->width != width || header->height != height || width == 0 ||
	    width > SCREEN_WIDTH || height == 0 || height > SCREEN_HEIGHT ||
	    header->frames == 0 || header->frameCurrent != header->frames ||
	    (header->flags.hasNoFirstFrame && seed == NULL)) {
		Warning("Planar WSA %s: unsupported window or initial state\n", header->filename);
		return false;
	}

	recording = calloc(1, sizeof(*recording));
	if (recording == NULL) goto cleanup;
	recording->groups = (width + 15) >> 4;
	bytes = (uint32)recording->groups * height * 8;
	recording->frames = calloc((uint32)header->frames + 1, sizeof(*recording->frames));
	recording->pixels = malloc(bytes);
	recording->composed = malloc(bytes);
	chunky = calloc(SCREEN_WIDTH, height);
	saved = malloc(header->bufferLength);
	next = malloc(bytes);
	if (recording->frames == NULL || recording->pixels == NULL ||
	    recording->composed == NULL || chunky == NULL || saved == NULL || next == NULL) goto cleanup;
	recording->frames[0] = malloc(bytes);
	if (recording->frames[0] == NULL) goto cleanup;

	memcpy(saved, header->buffer, header->bufferLength);
	if (seed != NULL) memcpy(chunky, seed, (uint32)SCREEN_WIDTH * height);
	if (!header->flags.hasNoFirstFrame)
		Format40_Decode_ToScreen(chunky, header->buffer, width);
	Video_Atari_EncodePlanarStrided(chunky, SCREEN_WIDTH, recording->pixels,
	                              recording->groups * 16, height);
	memcpy(recording->frames[0], recording->pixels, bytes);
	recordedBytes = bytes;
	for (frame = 1; frame <= header->frames; frame++) {
		uint32 length;
		const uint16 *target = recording->frames[0];
		if (frame < header->frames) {
			bool reserved = header->flags.displayInBuffer;
			bool decoded;
			header->flags.displayInBuffer = false;
			decoded = WSA_GotoNextFrame(wsa, frame, chunky);
			header->flags.displayInBuffer = reserved;
			if (!decoded) break;
			Video_Atari_EncodePlanarStrided(chunky, SCREEN_WIDTH, next,
			                              recording->groups * 16, height);
			target = next;
		}
		length = WSA_EncodePlanarDelta(NULL, recording->pixels, target, recording->groups, height);
		recording->frames[frame] = malloc(length);
		if (recording->frames[frame] == NULL) break;
		WSA_EncodePlanarDelta(recording->frames[frame], recording->pixels, target,
		                     recording->groups, height);
		memcpy(recording->pixels, target, bytes);
		recordedBytes += length;
	}
	memcpy(header->buffer, saved, header->bufferLength);
	if (frame > header->frames) {
		header->planar = recording;
		ready = true;
		Debug("Planar WSA %s: %u frames, %lu recording bytes\n",
		      header->filename, header->frames, (unsigned long)recordedBytes);
	}
cleanup:
	free(chunky);
	free(saved);
	free(next);
	if (!ready) {
		WSA_FreePlanar(recording, header->frames);
		Warning("Planar WSA %s: preparation failed; retaining original playback\n", header->filename);
	}
	return ready;
}

bool WSA_PreparePlanar(void *wsa, uint16 width, uint16 height)
{
	return WSA_PreparePlanarSeeded(wsa, width, height, NULL);
}

bool WSA_IsContinuation(void *wsa)
{
	WSAHeader *header = wsa;
	return header != NULL && header->flags.hasNoFirstFrame;
}

bool WSA_PreparePlanarContinuation(void *wsa, const char *const *predecessors, uint16 count)
{
	WSAHeader *header = wsa;
	uint8 *seed;
	uint16 source;
	bool ready = false;
	char cache[13];

	if (header == NULL || !header->flags.hasNoFirstFrame || predecessors == NULL ||
	    count == 0 || !WSA_PlanarFilename(header->filename, cache) ||
	    header->width == 0 || header->width > SCREEN_WIDTH ||
	    header->height == 0 || header->height > SCREEN_HEIGHT) {
		Warning("Planar WSA: invalid continuation source chain\n");
		return false;
	}
	if (header->planar != NULL) return true;
	seed = calloc(SCREEN_WIDTH, header->height);
	if (seed == NULL) {
		Warning("Planar WSA %s: cannot allocate continuation seed\n", header->filename);
		return false;
	}
	for (source = 0; source < count; source++) {
		WSAHeader *previous;
		uint16 frame;
		if (!File_Exists(predecessors[source])) {
			Warning("Planar WSA %s: missing predecessor %s\n", header->filename, predecessors[source]);
			goto cleanup;
		}
		previous = WSA_LoadFile(predecessors[source], NULL, 1, false, false);
		if (previous == NULL) goto cleanup;
		if (previous->width != header->width || previous->height != header->height ||
		    (source == 0 && previous->flags.hasNoFirstFrame)) {
			Warning("Planar WSA %s: incompatible predecessor %s\n", header->filename, predecessors[source]);
			WSA_Unload(previous);
			goto cleanup;
		}
		if (!previous->flags.hasNoFirstFrame) {
			memset(seed, 0, (uint32)SCREEN_WIDTH * header->height);
			Format40_Decode_ToScreen(seed, previous->buffer, previous->width);
		}
		for (frame = 1; frame < previous->frames; frame++) {
			if (!WSA_GotoNextFrame(previous, frame, seed)) break;
		}
		if (frame < previous->frames) {
			Warning("Planar WSA %s: cannot decode predecessor %s\n", header->filename, predecessors[source]);
			WSA_Unload(previous);
			goto cleanup;
		}
		WSA_Unload(previous);
	}
	ready = WSA_PreparePlanarSeeded(wsa, header->width, header->height, seed);
	if (ready) WSA_SavePlanar(header, cache);
cleanup:
	free(seed);
	return ready;
}

bool WSA_PresentPlanarRegion(void *wsa, uint16 x, uint16 y,
                            uint16 left, uint16 top, uint16 width, uint16 height)
{
	WSAHeader *header = wsa;
	if (header == NULL || header->planar == NULL ||
	    (uint32)left + width > header->width || (uint32)top + height > header->height ||
	    (uint32)x + header->width > SCREEN_WIDTH || (uint32)y + header->height > SCREEN_HEIGHT)
		return false;
	return Video_Atari_PresentPlanarSubRect(
	    header->planar->pixels + (uint32)top * header->planar->groups * 4,
	    header->planar->groups * 8, left, x + left, y + top, width, height);
}

bool WSA_PresentPlanar(void *wsa, uint16 x, uint16 y,
                       const uint16 *overlay, const uint16 *masks, bool force)
{
	WSAHeader *header = wsa;
	WSAPlanarRecording *recording;
	uint16 row = 0, stride;

	if (header == NULL || header->planar == NULL ||
	    (uint32)x + header->width > SCREEN_WIDTH ||
	    (uint32)y + header->height > SCREEN_HEIGHT ||
	    (overlay == NULL) != (masks == NULL)) return false;
	recording = header->planar;
	stride = recording->groups * 8;
	/* SCREEN_1 holds WSA data, not a shadow of this retained planar window. */
	for (row = 0; row < header->height; row++) {
		uint32 dirty = g_dirty_blocks[y + row] >> (x >> 4);
		if ((x & 15) != 0) dirty |= dirty >> 1;
		recording->dirty[row] |= dirty & ((1UL << recording->groups) - 1);
	}
	row = 0;
	while (row < header->height) {
		uint32 dirty = force ? (1UL << recording->groups) - 1 : recording->dirty[row];
		uint16 bottom = row + 1, first = 0;

		while (bottom < header->height &&
		       (force || recording->dirty[bottom] == dirty)) bottom++;
		while (dirty != 0) {
			uint16 end, line, group;
			while ((dirty & (1UL << first)) == 0) first++;
			end = first + 1;
			while (end < recording->groups && (dirty & (1UL << end)) != 0) end++;
			dirty &= ~(((1UL << (end - first)) - 1) << first);
			for (line = row; line < bottom; line++) {
				for (group = first; group < end; group++) {
					uint16 index = line * recording->groups + group, plane;
					uint16 mask = masks != NULL ? masks[index] : 0;
					for (plane = 0; plane < 4; plane++) {
						uint16 word = index * 4 + plane;
						recording->composed[word] = (recording->pixels[word] & (uint16)~mask) |
						    (overlay != NULL ? overlay[word] & mask : 0);
					}
				}
			}
			if (!Video_Atari_PresentPlanarRect(recording->composed + (row * recording->groups + first) * 4,
			        stride, x + first * 16, y + row,
			        min((end - first) * 16, header->width - first * 16), bottom - row)) return false;
			first = end;
		}
		while (row < bottom) recording->dirty[row++] = 0;
	}
	return true;
}
#endif

/**
 * Unload the WSA.
 * @param wsa The pointer to the WSA.
 */
void WSA_Unload(void *wsa)
{
	WSAHeader *header = (WSAHeader *)wsa;

	if (wsa == NULL) return;
#ifdef TOS
	WSA_FreePlanar(header->planar, header->frames);
	header->planar = NULL;
#endif
	if (!header->flags.malloced) return;

	free(wsa);
}

/**
 * Draw a frame on the buffer.
 * @param x The X-position to start drawing.
 * @param y The Y-position to start drawing.
 * @param width The width of the image.
 * @param height The height of the image.
 * @param windowID The windowID.
 * @param screenID the screen to write to
 * @param src The source for the frame.
 */
static void WSA_DrawFrame(int16 x, int16 y, int16 width, int16 height, uint16 windowID, uint8 *src, Screen screenID)
{
	int16 left;
	int16 right;
	int16 top;
	int16 bottom;
	int16 skipBefore;
	int16 skipAfter;
	uint8 *dst;

	dst = GFX_Screen_Get_ByIndex(screenID);

	left   = g_widgetProperties[windowID].xBase << 3;
	right  = left + (g_widgetProperties[windowID].width << 3);
	top    = g_widgetProperties[windowID].yBase;
	bottom = top + g_widgetProperties[windowID].height;

	if (y - top < 0) {
		if (y - top + height <= 0) return;
		height += y - top;
		src += (top - y) * width;
		y += top - y;
	}

	if (bottom - y <= 0) return;
	height = min(bottom - y, height);

	skipBefore = 0;
	if (x - left < 0) {
		skipBefore = left - x;
		x += skipBefore;
		width -= skipBefore;
	}

	skipAfter = 0;
	if (right - x <= 0) return;
	if (right - x < width) {
		skipAfter = width - right + x;
		width = right - x;
	}

	dst += y * SCREEN_WIDTH + x;


	while (height-- != 0) {
		src += skipBefore;
		memcpy(dst, src, width);
		src += width + skipAfter;
		dst += SCREEN_WIDTH;
	}
}

/**
 * Display a frame.
 * @param wsa The pointer to the WSA.
 * @param frameNext The next frame to display.
 * @param posX The X-position of the WSA.
 * @param posY The Y-position of the WSA.
 * @param screenID The screenID to draw on.
 * @return False on failure, true on success.
 */
bool WSA_DisplayFrame(void *wsa, uint16 frameNext, uint16 posX, uint16 posY, Screen screenID)
{
	WSAHeader *header = (WSAHeader *)wsa;
	uint8 *dst;

	int16 i;
	uint16 frame;
	int16 frameDiff;
	int16 direction;
	int16 frameCount;

	if (wsa == NULL) return false;
	if (frameNext >= header->frames) return false;

	if (header->flags.displayInBuffer) {
		dst = (uint8 *)wsa + sizeof(WSAHeader);
	} else {
		dst = GFX_Screen_Get_ByIndex(screenID);
		dst += posX + posY * SCREEN_WIDTH;
	}

	if (header->frameCurrent == header->frames) {
#ifdef TOS
		if (header->planar != NULL) {
			uint16 row;
			memcpy(header->planar->pixels, header->planar->frames[0],
			       (uint32)header->planar->groups * header->height * 8);
			for (row = 0; row < header->height; row++)
				header->planar->dirty[row] = (1UL << header->planar->groups) - 1;
		} else
#endif
		{
			if (!header->flags.hasNoFirstFrame) {
				if (!header->flags.displayInBuffer) {
					Format40_Decode_ToScreen(dst, header->buffer, header->width);
				} else {
					Format40_Decode(dst, header->buffer);
				}
			}
		}

		header->frameCurrent = 0;
	}

	frameDiff = abs(header->frameCurrent - frameNext);
	direction = 1;

	if (frameNext > header->frameCurrent) {
		frameCount = header->frames - frameNext + header->frameCurrent;

		if (frameCount < frameDiff && !header->flags.noAnimation) {
			direction = -1;
		} else {
			frameCount = frameDiff;
		}
	} else {
		frameCount = header->frames - header->frameCurrent + frameNext;

		if (frameCount < frameDiff && !header->flags.noAnimation) {
		} else {
			direction = -1;
			frameCount = frameDiff;
		}
	}

	frame = header->frameCurrent;
	if (direction > 0) {
		for (i = 0; i < frameCount; i++) {
			frame += direction;

			WSA_GotoNextFrame(wsa, frame, dst);

			if (frame == header->frames) frame = 0;
		}
	} else {
		for (i = 0; i < frameCount; i++) {
			if (frame == 0) frame = header->frames;

			WSA_GotoNextFrame(wsa, frame, dst);

			frame += direction;
		}
	}

	header->frameCurrent = frameNext;

#ifdef TOS
	if (header->planar != NULL) {
		if (GFX_Screen_Get_ByIndex(screenID) == GFX_Screen_Get_ByIndex(SCREEN_0) &&
		    !WSA_PresentPlanar(wsa, posX, posY, NULL, NULL, false)) {
			Warning("Planar WSA %s: presentation failed\n", header->filename);
			return false;
		}
		return true;
	}
#endif
	if (header->flags.displayInBuffer) {
		WSA_DrawFrame(posX, posY, header->width, header->height, 0, dst, screenID);
	}

	GFX_Screen_SetDirtySource(DIRTY_SRC_WSA);
	GFX_Screen_SetDirty(screenID, posX, posY, posX + header->width, posY + header->height);
#ifdef TOS
	/* ST/STE present mode is write-through: whichever path ran above, the
	 * chunky SCREEN_0 shadow now holds the frame -- later WSAs in the same
	 * scene XOR-decode against it -- so convert it to the planar screen
	 * from there. It clears the dirty blocks it covered itself (it may
	 * widen the rectangle to whole 16px groups first, which is safe here
	 * since it is reading from SCREEN_0 itself, not a private buffer).
	 * Doing this here rather than in WSA_DrawFrame() covers the in-place
	 * decode variant too, and runs after the SetDirty above rather than
	 * before it. */
	if (GFX_Screen_Get_ByIndex(screenID) == GFX_Screen_Get_ByIndex(SCREEN_0)) {
		const uint8 *screen0 = GFX_Screen_Get_ByIndex(SCREEN_0);

		Video_Atari_PresentChunky(screen0 + posY * SCREEN_WIDTH + posX,
		                         SCREEN_WIDTH, posX, posY,
		                         header->width, header->height);
	}
#endif
	return true;
}
