/** @file src/opendune.h Gameloop and other main definitions. */

#ifndef OPENDUNE_H
#define OPENDUNE_H

typedef enum GameMode {
	GM_MENU      = 0,
	GM_NORMAL    = 1,
	GM_RESTART   = 2,
	GM_PICKHOUSE = 3
} GameMode;

/** X and Y coordinate. */
typedef struct XYPosition {
	uint16 x; /*!< X coordinate. */
	uint16 y; /*!< Y coordinate. */
} XYPosition;

extern const char *window_caption;
extern bool g_dune2_enhanced;
extern bool g_starPortEnforceUnitLimit;
extern bool g_unpackSHPonLoad;

extern uint32 g_hintsShown1;
extern uint32 g_hintsShown2;
extern GameMode g_gameMode;
extern uint16 g_campaignID;
extern uint16 g_scenarioID;
extern uint16 g_activeAction;
extern uint32 g_tickScenarioStart;
extern bool   g_debugGame;
extern bool   g_debugScenario;
extern bool   g_debugSkipDialogs;

extern uint16 g_validateStrictIfZero;
extern bool g_running;
extern uint16 g_selectionType;
extern uint16 g_selectionTypeNew;
extern bool g_viewport_forceRedraw;
extern bool g_viewport_fadein;

extern int16 g_musicInBattle;

/**
 * Size of g_readBuffer, the general-purpose scratch buffer used for
 * decompressed strings, INI parsing and, most demandingly, for staging a
 * voice sample before it is handed to the sound driver.
 *
 * This is a single fixed size, allocated once at startup and never freed
 * or resized while the game runs. The original code reallocated this
 * buffer to several different sizes (12000/20000/28000) depending on the
 * part of the game and whether voices were enabled; that churn fragmented
 * the heap for no real benefit, and the 28000-byte intro variant was
 * actually too small: on TOS every VOC is resampled to DMASOUND_FREQ at
 * load time, which *upsamples* the low-rate sound effects, so
 * WIND2BP.VOC grows from 26241 bytes to 31729 bytes and overran the
 * buffer, corrupting the heap.
 *
 * 32KB covers that worst-case resampled sample and matches
 * DMASOUND_BUFFER_SIZE, the ST RAM DMA buffer it is copied into. The
 * margin is real but thin (31729 of 32768 bytes, ~1KB spare), and it
 * only holds for the current DMASOUND_FREQ of 6258Hz: raising that
 * frequency scales every resampled sample proportionally, so 12517Hz
 * would need ~64KB here. dsp_atari.c static-asserts the two sizes stay
 * consistent; if that assert fires, raise this value.
 */
#define READ_BUFFER_SIZE 32768

extern void *g_readBuffer;
extern uint32 g_readBufferSize;

extern void Game_Prepare(void);
extern void Game_Init(void);
extern void Game_LoadScenario(uint8 houseID, uint16 scenarioID);
extern void GameLoop_Uninit(void);
extern void PrepareEnd(void);

#endif /* OPENDUNE_H */
