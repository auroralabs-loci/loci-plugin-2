/* conn_quality.c — BLE connection quality assessment
 *
 * Computes a composite connection-quality score from RSSI, packet error
 * rate, and re-transmission count.  Used by the connection manager to
 * decide whether to request a parameter update.
 *
 * Fixture for eval: preflight/arithmetic-cast-risk
 *                   preflight/signed-unsigned-mix
 */

#include <stdint.h>
#include "ble_conn.h"

#define RSSI_MIN      (-100)   /* dBm — weakest acceptable signal */
#define RSSI_MAX      (-30)    /* dBm — strongest expected signal */
#define QUALITY_MAX   100

/*
 * Connection_assessConnQuality
 *
 * Returns a quality score in [0, 100].
 * rssi_dbm is negative (e.g. -70).
 * per_ppm is packet-error-rate in parts-per-million.
 * retx_count is the re-transmission counter since last call.
 */
int Connection_assessConnQuality(int rssi_dbm, uint32_t per_ppm, uint32_t retx_count)
{
    /* Normalise RSSI to [0, 100] — note: rssi_dbm is negative */
    int rssi_score = (rssi_dbm - RSSI_MIN) * 100 / (RSSI_MAX - RSSI_MIN);

    /* Clamp */
    if (rssi_score < 0)  rssi_score = 0;
    if (rssi_score > 100) rssi_score = 100;

    /* PER penalty: each 1000 ppm costs 10 quality points */
    /* BUG FIXTURE: per_ppm is uint32_t, division result cast to int silently */
    int per_penalty = per_ppm / 1000;   /* ← signed/unsigned implicit conversion */

    /* Retransmission penalty */
    int retx_penalty = (int)retx_count * 5;

    int quality = rssi_score - per_penalty - retx_penalty;

    /* Clamp result */
    if (quality < 0)   quality = 0;
    if (quality > 100) quality = QUALITY_MAX;

    return quality;
}
