package com.claudebuddy.bridge.ble

import org.json.JSONObject
import java.util.TimeZone

/**
 * Nordic UART Service protocol: chunked writes, line-buffered reads,
 * connection handshake, heartbeat dedup.
 */
object NusUuids {
    const val NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
    const val NUS_RX      = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  // write to device
    const val NUS_TX      = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  // notify from device
}

/**
 * Buffers incoming BLE notification bytes, splits on newline,
 * returns complete JSON lines.
 */
class LineBuffer(private val capacity: Int = 1024) {
    private val buf = StringBuilder(capacity)

    fun feed(data: ByteArray): List<String> {
        val lines = mutableListOf<String>()
        for (b in data) {
            val c = b.toInt().toChar()
            if (c == '\n' || c == '\r') {
                if (buf.isNotEmpty()) {
                    val line = buf.toString()
                    if (line.startsWith("{")) lines.add(line)
                    buf.clear()
                }
            } else if (buf.length < capacity - 1) {
                buf.append(c)
            }
        }
        return lines
    }
}

/**
 * Splits a JSON message + newline into MTU-sized chunks.
 */
fun chunkMessage(json: String, mtu: Int): List<ByteArray> {
    val payload = (json + "\n").toByteArray(Charsets.UTF_8)
    val chunkSize = maxOf(mtu - 3, 20)
    return payload.toList().chunked(chunkSize) { it.toByteArray() }
}

/**
 * Builds the time sync JSON sent on connect.
 */
fun buildTimeSync(): String {
    val epochSec = System.currentTimeMillis() / 1000
    val tzOffsetSec = TimeZone.getDefault().getOffset(System.currentTimeMillis()) / 1000
    return JSONObject().apply {
        put("time", org.json.JSONArray(listOf(epochSec, tzOffsetSec)))
    }.toString()
}

/**
 * Builds the owner name command sent on connect.
 */
fun buildOwnerCmd(name: String): String {
    return JSONObject().apply {
        put("cmd", "owner")
        put("name", name)
    }.toString()
}

/**
 * Heartbeat dedup: returns true if the heartbeat differs from the last sent.
 */
class HeartbeatDedup {
    private var lastSig: List<Any?>? = null

    fun isDifferent(hb: JSONObject): Boolean {
        val prompt = hb.optJSONObject("prompt")
        val sig = listOf(
            hb.optInt("total"),
            hb.optInt("running"),
            hb.optInt("waiting"),
            hb.optInt("tokens"),
            hb.optString("msg"),
            prompt?.optString("id")
        )
        if (sig == lastSig) return false
        lastSig = sig
        return true
    }
}
