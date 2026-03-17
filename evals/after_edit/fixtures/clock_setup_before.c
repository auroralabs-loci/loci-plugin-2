/* clock_setup_before.c — BEFORE version
 *
 * Prescaler set to /15 → tick ≈ 15 ns.
 * Saved as before-state by loci-preflight.
 */

#include <stdint.h>
#include "clock_regs.h"
#include "ble_config.h"

#define HFCLK_FREQ_HZ   32000000UL
#define TARGET_TICK_NS  15

volatile uint32_t g_tick_count = 0;

int clock_setup(void)
{
    CLOCK_CTRL &= ~CLOCK_ENABLE_BIT;

    uint32_t prescaler = HFCLK_FREQ_HZ / (1000000000UL / TARGET_TICK_NS);
    CLOCK_PRESCALER = prescaler;

    CLOCK_CTRL |= CLOCK_ENABLE_BIT;

    uint32_t timeout = 3200;
    while (!(CLOCK_STATUS & CLOCK_READY_BIT) && timeout--)
        ;

    if (!(CLOCK_STATUS & CLOCK_READY_BIT))
        return -1;

    g_tick_count = 0;
    return 0;
}
