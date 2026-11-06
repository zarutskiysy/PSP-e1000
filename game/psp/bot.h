/* bot.h — scripted PSP player (host tests / headless runs): starts, pings, solves locks. */
#ifndef BW_BOT_H
#define BW_BOT_H
#include "console.h"
/* Returns the button state for this frame. Presses are edge-triggered, so the bot alternates
 * press / release frames. ping_ms = active ping period. */
uint16_t bw_bot_buttons(const bw_console_t *c, uint32_t frame, uint32_t now_ms, uint32_t ping_ms);
#endif
