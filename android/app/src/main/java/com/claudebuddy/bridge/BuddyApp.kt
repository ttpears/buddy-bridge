package com.claudebuddy.bridge

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager

class BuddyApp : Application() {
    companion object {
        const val CHANNEL_ID = "buddy_bridge_service"
    }

    override fun onCreate() {
        super.onCreate()
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Buddy Bridge",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "BLE relay to Claude Buddy device"
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }
}
