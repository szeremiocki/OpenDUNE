#ifndef GUI_SIDEBAR_H
#define GUI_SIDEBAR_H

#ifdef TOS
#include "font.h"
#include "../os/error.h"
#include "../unit.h"
#include "../video/atari_sidebar.h"

struct Widget;
struct Structure;

typedef struct SidebarAsset {
	const uint16 *code;
	int16 dx, dy;
	uint16 width, height;
	bool ready;
} SidebarAsset;

extern struct SidebarCaptions {
	SidebarAsset action[ACTION_MAX][3];
	SidebarAsset repair[2], repairing[3], upgrade[3], upgrading[3], cancel[3];
	SidebarAsset production[7][2], productionPercent[2], productionUpgradePercent[2];
	SidebarAsset title[3], power, starport;
} g_sidebarCaptions;

extern bool GUI_Sidebar_Active(void);
extern bool GUI_Sidebar_FlatButtons(const struct Widget *w);
extern bool GUI_Sidebar_Valid(void);
extern void GUI_Sidebar_Invalidate(void);
extern void GUI_Sidebar_Free(void);
extern void GUI_Sidebar_Preload(void);
extern void GUI_Sidebar_Begin(bool force);
extern void GUI_Sidebar_End(void);
extern bool GUI_Sidebar_WidgetBegin(const struct Widget *w);
extern bool GUI_Sidebar_WidgetBorder(uint16 widgetIndex, uint16 borderType, bool pressed);
extern bool GUI_Sidebar_ButtonFrame(const struct Widget *w, bool down);
extern bool GUI_Sidebar_ProductionImage(const struct Widget *w, const struct Structure *s);
extern void GUI_Sidebar_ProductionPercent(const struct Widget *w, bool upgrading);
extern bool GUI_Sidebar_PortraitFrame(const struct Widget *w, bool down);
extern bool GUI_Sidebar_Separator(void);
extern void GUI_Sidebar_CaptionBegin(SidebarAsset *image, const struct Widget *w);
#define GUI_Sidebar_UseCaption(member) \
	GUI_Sidebar_CaptionBegin(&(member), NULL)
#define GUI_Sidebar_UseButtonCaption(member, w) \
	GUI_Sidebar_CaptionBegin(&(member), (w))
extern void GUI_Sidebar_CaptionEnd(void);
extern bool GUI_Sidebar_DamageGauge(void);
extern bool GUI_Sidebar_Progressbar(uint16 width, uint8 colour, uint8 background);
extern void GUI_Sidebar_Fill(int16 left, int16 top, int16 right, int16 bottom, uint8 colour);
/* Write-only bordered rectangle: colours are the 4 border schema entries. The edge groups are
 * sampled once and must repeat vertically over the rectangle's rows (caller's contract). */
extern bool GUI_Sidebar_Border(int16 left, int16 top, uint16 width, uint16 height, const uint8 colours[4], bool fill);
extern bool GUI_Sidebar_Text(const char *string, int16 left, int16 top, const uint8 colours[16]);
extern void GUI_Sidebar_Char(unsigned char c, uint16 x, uint16 y, const uint8 colours[16]);
extern void GUI_Sidebar_Sprite(const uint8 *sprite, uint16 spriteID, int16 x, int16 y,
                               int flags, const uint8 *remap, uint16 remapCount);
#endif

#endif
