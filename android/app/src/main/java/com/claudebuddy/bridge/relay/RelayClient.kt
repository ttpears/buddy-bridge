package com.claudebuddy.bridge.relay

import android.util.Log
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

/**
 * Outbound client of a remote buddyhub's relay stream — the phone-as-relay path.
 * Reads GET {hub}/relay/stream (chunked newline-JSON) and feeds each line to the
 * BLE writer; POSTs A/B presses back to {hub}/button. Mirrors relay.py.
 */
class RelayClient(
    private val hubUrl: String,
    private val token: String,
    private val onLine: (String) -> Unit,    // heartbeat line -> write to BLE
) {
    companion object { private const val TAG = "RelayClient" }

    private val base = hubUrl.trimEnd('/')
    @Volatile private var running = false
    private var job: Job? = null

    fun start(scope: CoroutineScope) {
        running = true
        job = scope.launch(Dispatchers.IO) {
            while (running) {
                try { streamOnce() }
                catch (e: Exception) { Log.i(TAG, "stream error: ${e.message}") }
                if (running) delay(5000)     // supervise: reconnect with backoff
            }
        }
    }

    fun stop() { running = false; job?.cancel() }

    private fun streamOnce() {
        val conn = (URL("$base/relay/stream").openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 10_000
            readTimeout = 0                  // infinite — it's a long-lived stream
            if (token.isNotEmpty()) setRequestProperty("X-Buddy-Token", token)
        }
        try {
            if (conn.responseCode != 200) { Log.i(TAG, "stream HTTP ${conn.responseCode}"); return }
            BufferedReader(InputStreamReader(conn.inputStream)).use { r ->
                while (running) {
                    val line = r.readLine() ?: break
                    if (line.isNotBlank()) onLine(line)
                }
            }
        } finally { conn.disconnect() }
    }

    /** Device pressed A/B — relay the decision to the hub. Call off the main thread. */
    fun postButton(id: String, decision: String) {
        try {
            val conn = (URL("$base/button").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = 5_000; readTimeout = 5_000
                setRequestProperty("Content-Type", "application/json")
                if (token.isNotEmpty()) setRequestProperty("X-Buddy-Token", token)
            }
            try {
                val body = JSONObject().put("id", id).put("decision", decision).toString()
                conn.outputStream.use { it.write(body.toByteArray()) }
                conn.inputStream.use { it.readBytes() }
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) { Log.i(TAG, "button POST failed: ${e.message}") }
    }
}
