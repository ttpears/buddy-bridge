package com.claudebuddy.bridge.hub

import kotlinx.coroutines.CompletableDeferred
import java.util.UUID

/**
 * A permission prompt awaiting a decision from the device.
 * Port of buddyhub.py Pending class.
 */
class Pending(
    val machine: String,
    val session: String,
    val tool: String,
    val hint: String
) {
    val id: String = "req_" + UUID.randomUUID().toString().replace("-", "").take(10)
    val createdMs: Long = System.nanoTime() / 1_000_000
    var decision: String? = null   // "once" | "deny" | "timeout"
    val event = CompletableDeferred<Unit>()
}
