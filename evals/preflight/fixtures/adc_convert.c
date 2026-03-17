/* adc_convert.c — 12-bit ADC raw → millivolt conversion
 *
 * Converts a raw 12-bit ADC sample to millivolts given a reference voltage.
 * Called frequently from the sensor polling loop.
 *
 * Fixture for eval: preflight/integer-overflow
 */

#include <stdint.h>
#include "adc_config.h"

#define ADC_RESOLUTION_BITS  12
#define ADC_FULL_SCALE       4095   /* 2^12 - 1 */

/*
 * adc_raw_to_mv
 *
 * raw       — 12-bit ADC sample [0, 4095]
 * vref_mv   — reference voltage in millivolts (e.g. 3300 for 3.3 V)
 *
 * Returns millivolts as uint16_t.
 *
 * OVERFLOW FIXTURE:
 *   raw * vref_mv can reach 4095 * 3300 = 13,513,500
 *   which overflows int16_t (max 32767) and even int32_t if vref is large.
 *   The intermediate multiplication must be done in uint32_t.
 */
uint16_t adc_raw_to_mv(uint16_t raw, uint16_t vref_mv)
{
    /* BUG: intermediate product is computed as uint16_t before dividing */
    return (raw * vref_mv) / ADC_FULL_SCALE;  /* ← overflows when raw > 9 */
}

/*
 * adc_batch_average
 *
 * Averages N ADC samples.  N is caller-supplied and assumed > 0.
 * UNSIGNED WRAP FIXTURE: if count == 0, size_t subtraction wraps.
 */
uint16_t adc_batch_average(const uint16_t *samples, size_t count)
{
    uint32_t sum = 0;
    for (size_t i = 0; i < count; i++)
        sum += samples[i];

    /* BUG: if count is 0 this is divide-by-zero; caller must guard */
    return (uint16_t)(sum / count);
}
