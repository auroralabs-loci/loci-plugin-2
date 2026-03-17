/* ble_irq_handler.c — BLE radio interrupt handler
 *
 * Services the BLE radio event interrupt.  Must complete within the
 * inter-frame space (IFS ≈ 150 µs) to avoid missing the next PDU.
 *
 * Fixture for eval: preflight/control-flow-complexity
 *                   preflight/resource-lifetime
 */

#include <stdint.h>
#include "ble_ll.h"
#include "radio_regs.h"

/* Heap-allocated receive buffer reused across events */
static ble_pdu_t *s_rx_buf = NULL;

/*
 * BLE_RadioIRQHandler
 *
 * Called directly from the vector table — no RTOS context.
 * Must not call any blocking or sleeping function.
 */
void BLE_RadioIRQHandler(void)
{
    uint32_t events = RADIO_EVENTS;
    RADIO_EVENTS = 0;   /* clear all pending */

    if (events & RADIO_EVENT_RX_DONE) {
        /* Allocate new buffer for next receive window */
        ble_pdu_t *pdu = ble_pdu_alloc();

        if (!pdu) {
            /* Allocation failed — drop event */
            return;   /* ← RESOURCE FIXTURE: s_rx_buf not restored */
        }

        /* Process the completed PDU */
        ble_ll_process_rx(s_rx_buf);

        /* Free old buffer, swap in new */
        ble_pdu_free(s_rx_buf);   /* free old */
        s_rx_buf = pdu;

        /* CONTROL-FLOW FIXTURE: if ble_ll_process_rx throws / longjmps,
           the free above already ran — potential double-free on re-entry */
    }

    if (events & RADIO_EVENT_TX_DONE) {
        ble_ll_tx_complete();

        /* Stale pointer read after potential free in RX branch above */
        if (s_rx_buf && s_rx_buf->flags & PDU_FLAG_ACK_PENDING) {
            ble_ll_send_ack(s_rx_buf);  /* ← may use freed s_rx_buf */
        }
    }
}
