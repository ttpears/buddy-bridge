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
import com.claudebuddy.bridge.data.SettingsRepository
import com.claudebuddy.bridge.service.BuddyService
import com.claudebuddy.bridge.ui.BridgeScreen
import com.claudebuddy.bridge.ui.theme.BuddyBridgeTheme
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private val serviceRef = mutableStateOf<BuddyService?>(null)
    private val isRunning = mutableStateOf(false)
    private var bound = false

    private lateinit var settings: SettingsRepository

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            val svc = (binder as BuddyService.LocalBinder).service
            serviceRef.value = svc
            isRunning.value = true
            bound = true
            // Push persisted settings onto the service
            CoroutineScope(Dispatchers.Main).launch {
                svc.ownerName = settings.ownerName.first()
                svc.buddyToken = settings.buddyToken.first()
            }
            Log.i("MainActivity", "service bound")
        }
        override fun onServiceDisconnected(name: ComponentName) {
            serviceRef.value = null
            isRunning.value = false
            bound = false
        }
    }

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        Log.i("MainActivity", "permissions: $results")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        settings = SettingsRepository(applicationContext)
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

                val ownerName by settings.ownerName.collectAsState(initial = "")
                val buddyToken by settings.buddyToken.collectAsState(initial = "")
                val scope = rememberCoroutineScope()

                BridgeScreen(
                    isRunning = running,
                    bleState = bleState,
                    bleDeviceName = bleDeviceName,
                    httpRunning = httpRunning,
                    ownerName = ownerName,
                    onOwnerNameChange = { name ->
                        svc?.ownerName = name
                        scope.launch { settings.setOwnerName(name) }
                    },
                    buddyToken = buddyToken,
                    onBuddyTokenChange = { token ->
                        svc?.buddyToken = token
                        scope.launch { settings.setBuddyToken(token) }
                    },
                    onToggle = {
                        if (running) {
                            try {
                                unbindService(connection)
                            } catch (_: Exception) {}
                            bound = false
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

    override fun onStart() {
        super.onStart()
        // Rebind to the service if it's still running (activity was recreated)
        if (!bound) {
            val intent = Intent(this, BuddyService::class.java)
            val ok = try {
                bindService(intent, connection, 0)  // don't auto-create, just attach if running
            } catch (e: Exception) {
                Log.d("MainActivity", "rebind failed: ${e.message}")
                false
            }
            if (!ok) {
                // Service is not running — clear any stale state
                serviceRef.value = null
                isRunning.value = false
            }
        }
    }

    override fun onStop() {
        if (bound) {
            try { unbindService(connection) } catch (_: Exception) {}
            bound = false
            // Don't clear serviceRef/isRunning — service may still be running,
            // we'll rebind in onStart() when the activity comes back.
        }
        super.onStop()
    }

    override fun onDestroy() {
        // bound flag is already cleared in onStop()
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
