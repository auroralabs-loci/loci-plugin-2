/* clock_setup.c — BLE SoC clock configuration
 *
 * Configures the high-frequency crystal oscillator and derives the 1 MHz
 * timing reference used by the BLE link layer.  Current implementation
 * uses a /15 prescaler which produces a ~15 ns tick period.
 *
 * Fixture for eval: preflight/realistic-timing-goal
 *                   preflight/unrealistic-timing-goal
 */

#include <stdint.h>
#include "clock_regs.h"
#include "ble_config.h"

#define HFCLK_FREQ_HZ   32000000UL
#define TARGET_TICK_NS  15

/* Global reference counter — incremented by timer ISR */
volatile uint32_t g_tick_count = 0;

/*
 * clock_setup
 *
 * Programs the prescaler register and enables the HF oscillator.
 * Call once during board init before any BLE stack operations.
 *
 * Returns 0 on success, -1 if the oscillator fails to stabilise.
 */
int clock_setup(void)
{
    /* Disable before reconfiguring */
    CLOCK_CTRL &= ~CLOCK_ENABLE_BIT;

    /* Prescaler: divide 32 MHz by 15 → ~2.13 MHz, tick ≈ 15 ns (approx) */
    uint32_t prescaler = HFCLK_FREQ_HZ / (1000000000UL / TARGET_TICK_NS);
    CLOCK_PRESCALER = prescaler;

    /* Re-enable */
    CLOCK_CTRL |= CLOCK_ENABLE_BIT;

    /* Wait for oscillator ready flag (spin up to ~100 µs) */
    uint32_t timeout = 3200;  /* 32 MHz cycles → ~100 µs */
    while (!(CLOCK_STATUS & CLOCK_READY_BIT) && timeout--)
        ;

    if (!(CLOCK_STATUS & CLOCK_READY_BIT))
        return -1;

    g_tick_count = 0;
    return 0;
}
