/* conn_manager.c — BLE connection table manager
 *
 * Manages a fixed-size table of active BLE connections.
 * Multiple files in the project define connection_find() — one here,
 * one in legacy/conn_compat.c — creating an ambiguous symbol.
 *
 * Fixture for eval: preflight/ambiguous-function-name
 */

#include <stdint.h>
#include <string.h>
#include "ble_conn.h"

#define MAX_CONNECTIONS  8

static ble_conn_t s_conn_table[MAX_CONNECTIONS];

/*
 * connection_find
 *
 * Returns a pointer to the connection entry for handle, or NULL.
 * NOTE: also defined in legacy/conn_compat.c with a different signature.
 */
ble_conn_t *connection_find(uint16_t handle)
{
    for (int i = 0; i < MAX_CONNECTIONS; i++) {
        if (s_conn_table[i].handle == handle && s_conn_table[i].active)
            return &s_conn_table[i];
    }
    return NULL;
}

/*
 * connection_close
 *
 * Closes and zeroes the connection entry.  Returns 0 on success, -1 if
 * not found.
 */
int connection_close(uint16_t handle)
{
    ble_conn_t *conn = connection_find(handle);
    if (!conn)
        return -1;

    memset(conn, 0, sizeof(*conn));
    return 0;
}
