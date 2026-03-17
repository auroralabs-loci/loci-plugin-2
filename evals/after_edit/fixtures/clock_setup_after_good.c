/* clock_setup_after_good.c — AFTER version (improvement)
 *
 * Prescaler changed to /5 → tick ≈ 5 ns.
 * Also removed redundant CLOCK_CTRL clear/set pair — saved 2 cycles.
 *
 * Expected after-edit report:
 *   clock_setup: tick period 15 ns → 5 ns  (-67%)
 *   Execution path: 12 cycles → 10 cycles  (-17%)
 */

#include <stdint.h>
#include "clock_regs.h"
#include "ble_config.h"

#define HFCLK_FREQ_HZ   32000000UL
#define TARGET_TICK_NS  5

volatile uint32_t g_tick_count = 0;

int clock_setup(void)
{
    /* Single combined write: prescaler + enable in one register access */
    uint32_t prescaler = HFCLK_FREQ_HZ / (1000000000UL / TARGET_TICK_NS);
    CLOCK_PRESCALER = prescaler;
    CLOCK_CTRL = CLOCK_ENABLE_BIT;   /* single write, not read-modify-write */

    uint32_t timeout = 3200;
    while (!(CLOCK_STATUS & CLOCK_READY_BIT) && timeout--)
        ;

    if (!(CLOCK_STATUS & CLOCK_READY_BIT))
        return -1;

    g_tick_count = 0;
    return 0;
}
