/* packet_counter.c — BLE packet statistics counter
 *
 * Tracks per-connection packet and byte counts.
 * Designed to be updated on every RX/TX event — must be fast.
 *
 * Fixture for eval: preflight/overflow-accumulator
 *                   preflight/shift-hazard
 */

#include <stdint.h>
#include "ble_stats.h"

/*
 * stats_update
 *
 * Accumulates packet and byte counts into a 16-bit summary word.
 * pkt_len — length of the PDU in bytes
 * seq     — 4-bit sequence number [0, 15]
 *
 * SHIFT FIXTURE:
 *   seq is a 4-bit value packed into bits [15:12] of the summary.
 *   If seq arrives as 0-based and the caller passes the raw register
 *   value (which may be up to 0xFF), the shift overflows.
 *
 * OVERFLOW FIXTURE:
 *   byte_count is uint16_t; after ~65 KB of traffic it wraps silently.
 */
uint16_t stats_update(ble_stats_t *s, uint8_t pkt_len, uint8_t seq)
{
    s->pkt_count++;

    /* BUG: byte_count is uint16_t — wraps at 65535 */
    s->byte_count += pkt_len;

    /* BUG: seq is uint8_t but shift is 12 — if seq > 15, bits overflow */
    uint16_t summary = (uint16_t)(s->byte_count | (seq << 12));

    return summary;
}
