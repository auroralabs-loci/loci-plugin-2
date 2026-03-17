/* conn_quality_before.c — BEFORE version
 *
 * Original Connection_assessConnQuality with signed/unsigned cast issue.
 * Saved as before-state by loci-preflight.
 */

#include <stdint.h>
#include "ble_conn.h"

#define RSSI_MIN      (-100)
#define RSSI_MAX      (-30)
#define QUALITY_MAX   100

int Connection_assessConnQuality(int rssi_dbm, uint32_t per_ppm, uint32_t retx_count)
{
    int rssi_score = (rssi_dbm - RSSI_MIN) * 100 / (RSSI_MAX - RSSI_MIN);

    if (rssi_score < 0)   rssi_score = 0;
    if (rssi_score > 100) rssi_score = 100;

    int per_penalty = per_ppm / 1000;   /* implicit uint32_t → int */
    int retx_penalty = (int)retx_count * 5;

    int quality = rssi_score - per_penalty - retx_penalty;

    if (quality < 0)   quality = 0;
    if (quality > 100) quality = QUALITY_MAX;

    return quality;
}
