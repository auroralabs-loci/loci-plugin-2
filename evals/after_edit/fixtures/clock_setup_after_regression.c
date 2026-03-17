/* clock_setup_after_regression.c — AFTER version (regression)
 *
 * Attempted to set prescaler to /3 → tick ≈ 3.3 ns.
 * Added an extra busy-wait loop that was not present before.
 * Net result: function executes more cycles; stabilisation time longer.
 *
 * Expected after-edit report:
 *   clock_setup: tick period 15 ns → 3.3 ns  (-78%)  [goal achieved]
 *   BUT: execution cycles 12 → 28  (+133%)  [REGRESSION in setup cost]
 *   Overall: MIXED — tick period improved but setup overhead increased
 */

#include <stdint.h>
#include "clock_regs.h"
#include "ble_config.h"

#define HFCLK_FREQ_HZ   32000000UL
#define TARGET_TICK_NS  3

volatile uint32_t g_tick_count = 0;

int clock_setup(void)
{
    CLOCK_CTRL &= ~CLOCK_ENABLE_BIT;

    uint32_t prescaler = HFCLK_FREQ_HZ / (1000000000UL / TARGET_TICK_NS);
    CLOCK_PRESCALER = prescaler;

    /* Extra stabilisation loop added to handle faster oscillator start */
    for (volatile uint32_t i = 0; i < 64; i++)  /* ← adds ~64 cycles */
        __asm__("nop");

    CLOCK_CTRL |= CLOCK_ENABLE_BIT;

    uint32_t timeout = 6400;  /* doubled timeout for faster clock */
    while (!(CLOCK_STATUS & CLOCK_READY_BIT) && timeout--)
        ;

    if (!(CLOCK_STATUS & CLOCK_READY_BIT))
        return -1;

    g_tick_count = 0;
    return 0;
}
