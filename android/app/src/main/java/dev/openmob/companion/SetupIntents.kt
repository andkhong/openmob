package dev.openmob.companion

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings as AndroidSettings

/**
 * The system screens setup opens, shared by MainActivity and the redesign's setup (moved here from MainActivity
 * unchanged). Accessibility is only ever opened after the owner agreed to the disclosure (the caller's job: MainActivity's
 * dialog, the redesign's consent screen).
 */
object SetupIntents {
    /**
     * Open Android's supported Accessibility screen and highlight OpenMob where supported.
     * ACCESSIBILITY_DETAILS_SETTINGS requires a system/installer-only permission, so ordinary
     * apps cannot rely on it. Never try to enter a protected fragment by another route.
     * Once enabled, the service returns to OpenMob (AppState.returnAfterAccessibility).
     */
    fun openAccessibilitySettings(activity: Activity) {
        AppState.returnAfterAccessibility = true
        val service = ComponentName(activity, OpenMobAccessibilityService::class.java)
        val key = service.flattenToString()
        val attempts = buildList {
            add(Intent(AndroidSettings.ACTION_ACCESSIBILITY_SETTINGS)
                .putExtra(":settings:fragment_args_key", key)
                .putExtra(":settings:show_fragment_args", Bundle().apply { putString(":settings:fragment_args_key", key) }))
            add(Intent(AndroidSettings.ACTION_SETTINGS))
        }
        for (intent in attempts) {
            try {
                activity.startActivity(intent)
                return
            } catch (e: ActivityNotFoundException) {
                // this phone's Settings doesn't have that screen: try the next one
            } catch (e: SecurityException) {
                // some phones keep the per-service screen to themselves
            }
        }
    }

    /** Android 13+ blocks Accessibility for sideloaded apps until "Allow restricted settings" (read only; moved from
     *  the old MainActivity). NEEDS_APPROVAL: App info is the only place to allow it. */
    fun accessibilityRestriction(context: android.content.Context): AccessibilitySetup.Restriction {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return AccessibilitySetup.Restriction.NONE
        val mode = runCatching {
            context.getSystemService(android.app.AppOpsManager::class.java)
                .unsafeCheckOpNoThrow("android:access_restricted_settings", context.applicationInfo.uid, context.packageName)
        }.getOrNull()
        return AccessibilitySetup.restriction(Build.VERSION.SDK_INT, mode)
    }

    /** Samsung's battery settings (Background usage limits › Never sleeping apps), else the app's own page. */
    fun openSamsungSleepingApps(activity: Activity): Boolean {
        val attempts = listOf(
            Intent().setComponent(ComponentName("com.samsung.android.lool", "com.samsung.android.sm.battery.ui.BatteryActivity")),
            Intent().setComponent(ComponentName("com.samsung.android.sm", "com.samsung.android.sm.battery.ui.BatteryActivity")),
            Intent(AndroidSettings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${activity.packageName}")),
        )
        for (intent in attempts) {
            try {
                activity.startActivity(intent)
                return true
            } catch (e: ActivityNotFoundException) {
                // not on this phone: try the next one
            } catch (e: SecurityException) {
                // not exported on this One UI version
            }
        }
        return false
    }

    fun openAppInfo(activity: Activity) {
        activity.startActivity(
            Intent(AndroidSettings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${activity.packageName}"))
        )
    }

    fun openNotificationSettings(activity: Activity) {
        activity.startActivity(
            Intent(AndroidSettings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(AndroidSettings.EXTRA_APP_PACKAGE, activity.packageName)
        )
    }

    /** Straight to Android's own "Let app always run in background?" prompt (one tap: Allow). */
    @SuppressLint("BatteryLife") // a constant connection is the app's core function, not a convenience
    fun requestBatteryExemption(activity: Activity) {
        try {
            activity.startActivity(
                Intent(AndroidSettings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${activity.packageName}"))
            )
        } catch (e: ActivityNotFoundException) {
            activity.startActivity(Intent(AndroidSettings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
    }
}
