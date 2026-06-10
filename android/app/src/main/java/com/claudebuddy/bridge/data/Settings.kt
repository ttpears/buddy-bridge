package com.claudebuddy.bridge.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "buddy_settings")

object SettingsKeys {
    val OWNER_NAME = stringPreferencesKey("owner_name")
    val HTTP_PORT = intPreferencesKey("http_port")
    val DEVICE_PREFIX = stringPreferencesKey("device_prefix")
}

class SettingsRepository(private val context: Context) {

    val ownerName: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[SettingsKeys.OWNER_NAME] ?: ""
    }

    val httpPort: Flow<Int> = context.dataStore.data.map { prefs ->
        prefs[SettingsKeys.HTTP_PORT] ?: 8787
    }

    val devicePrefix: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[SettingsKeys.DEVICE_PREFIX] ?: "Claude"
    }

    suspend fun setOwnerName(name: String) {
        context.dataStore.edit { it[SettingsKeys.OWNER_NAME] = name }
    }

    suspend fun setHttpPort(port: Int) {
        context.dataStore.edit { it[SettingsKeys.HTTP_PORT] = port }
    }

    suspend fun setDevicePrefix(prefix: String) {
        context.dataStore.edit { it[SettingsKeys.DEVICE_PREFIX] = prefix }
    }
}
