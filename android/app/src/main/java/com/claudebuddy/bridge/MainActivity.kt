package com.claudebuddy.bridge

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import androidx.core.content.ContextCompat
import com.claudebuddy.bridge.ble.BleState
import com.claudebuddy.bridge.service.BuddyService
import com.claudebuddy.bridge.ui.BridgeScreen
import com.claudebuddy.bridge.ui.theme.BuddyBridgeTheme

class MainActivity : ComponentActivity() {

    private val serviceRef = mutableStateOf<BuddyService?>(null)
    private val isRunning = mutableStateOf(false)

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            val svc = (binder as BuddyService.LocalBinder).service
            serviceRef.value = svc
            isRunning.value = true
            Log.i("MainActivity", "service bound")
        }
        override fun onServiceDisconnected(name: ComponentName) {
            serviceRef.value = null
            isRunning.value = false
        }
    }

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        Log.i("MainActivity", "permissions: $results")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        requestPermissions()

        setContent {
            BuddyBridgeTheme {
                val svc by serviceRef
                val running by isRunning

                val bleState by svc?.bleState?.collectAsState()
                    ?: remember { mutableStateOf(BleState.DISCONNECTED) }
                val bleDeviceName by svc?.bleDeviceName?.collectAsState()
                    ?: remember { mutableStateOf<String?>(null) }
                val httpRunning by svc?.httpRunning?.collectAsState()
                    ?: remember { mutableStateOf(false) }

                var ownerName by remember { mutableStateOf("") }
                var buddyToken by remember { mutableStateOf("") }

                BridgeScreen(
                    isRunning = running,
                    bleState = bleState,
                    bleDeviceName = bleDeviceName,
                    httpRunning = httpRunning,
                    ownerName = ownerName,
                    onOwnerNameChange = { name ->
                        ownerName = name
                        svc?.ownerName = name
                    },
                    buddyToken = buddyToken,
                    onBuddyTokenChange = { token ->
                        buddyToken = token
                        svc?.buddyToken = token
                    },
                    onToggle = {
                        if (running) {
                            try {
                                unbindService(connection)
                            } catch (_: Exception) {}
                            stopService(Intent(this, BuddyService::class.java))
                            serviceRef.value = null
                            isRunning.value = false
                        } else {
                            try {
                                val intent = Intent(this, BuddyService::class.java)
                                ContextCompat.startForegroundService(this, intent)
                                bindService(intent, connection, Context.BIND_AUTO_CREATE)
                            } catch (e: Exception) {
                                Log.e("MainActivity", "failed to start service", e)
                            }
                        }
                    }
                )
            }
        }
    }

    override fun onDestroy() {
        if (serviceRef.value != null) {
            try { unbindService(connection) } catch (_: Exception) {}
        }
        super.onDestroy()
    }

    private fun requestPermissions() {
        val needed = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= 31) {
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED)
                needed.add(Manifest.permission.BLUETOOTH_SCAN)
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED)
                needed.add(Manifest.permission.BLUETOOTH_CONNECT)
        } else {
            if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED)
                needed.add(Manifest.permission.ACCESS_FINE_LOCATION)
        }
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                needed.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (needed.isNotEmpty()) {
            permissionLauncher.launch(needed.toTypedArray())
        }
    }
}
