/** @file src/pool/structure.h %Structure pool definitions. */

#ifndef POOL_STRUCTURE_H
#define POOL_STRUCTURE_H

enum {
	STRUCTURE_INDEX_MAX_SOFT = 79,                          /*!< The highest possible index for normal Structure. */
	STRUCTURE_INDEX_MAX_HARD = 82,                          /*!< The highest possible index for any Structure. */

	STRUCTURE_INDEX_WALL     = 79,                          /*!< All walls are are put under index 79. */
	STRUCTURE_INDEX_SLAB_2x2 = 80,                          /*!< All 2x2 slabs are put under index 80. */
	STRUCTURE_INDEX_SLAB_1x1 = 81,                          /*!< All 1x1 slabs are put under index 81. */

	STRUCTURE_INDEX_INVALID  = 0xFFFF
};

struct PoolFindStruct;

#ifdef TOS
extern struct Structure *g_structureFindArray[STRUCTURE_INDEX_MAX_SOFT];
extern uint16 g_structureFindCount;
#endif

#ifndef TOS
extern struct Structure *Structure_Get_ByIndex(uint16 index);
#endif
extern struct Structure *Structure_Find(struct PoolFindStruct *find);

#ifdef TOS
extern uint16 g_structureEpoch; /*!< Bumped whenever structure existence, house or on-map state may change. */
#endif

extern void Structure_Init(void);
extern void Structure_Recount(void);
extern struct Structure *Structure_Allocate(uint16 index, uint8 type);
extern void Structure_Free(struct Structure *s);

#endif /* POOL_STRUCTURE_H */
