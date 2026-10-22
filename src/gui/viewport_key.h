/** @file src/gui/viewport_key.h Opaque viewport sprite identity storage. */

#ifndef GUI_VIEWPORT_KEY_H
#define GUI_VIEWPORT_KEY_H

typedef struct ViewportCompositeKey {
	uint32 main;
	uint32 tail[2]; /* Defined only when the main word's variable-layer prefix is nonzero. */
} ViewportCompositeKey;

static inline void ViewportCompositeKey_Clear(ViewportCompositeKey *key)
{
	key->main = 0;
}

#endif
