package dev.openmob.companion.ui.setup

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ApplicationInfo
import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalContext
import java.util.WeakHashMap

/**
 * FLAG_SECURE on the window while a screen that shows or holds a pairing code is on it (owner, 2026-10-17): no
 * screenshot, screen recording or live view of it, so a server already paired can't read a newly typed code. Counted
 * per window, so moving between two such screens never lets it drop in between.
 */
object SecureWindow {
    private val holds = WeakHashMap<Activity, Int>()

    fun hold(activity: Activity) {
        val n = (holds[activity] ?: 0) + 1
        holds[activity] = n
        if (n == 1) activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
    }

    fun release(activity: Activity) {
        val n = (holds[activity] ?: 0) - 1
        if (n <= 0) {
            holds.remove(activity)
            activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        } else {
            holds[activity] = n
        }
    }
}

/** The activity behind a Compose context: itself, or the end of a ContextWrapper chain (a themed wrapper, a
 *  dialog's context). Null: none. */
tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

/**
 * Keeps the window secure while this composable is shown. False when there is no activity window to secure: the
 * caller must not show what it protects then (cleanup review, 2026-10-18: `as? Activity ?: return` skipped
 * FLAG_SECURE silently for a ContextWrapper). Debug builds throw, so a screen moved behind a wrapper fails loudly.
 */
@Composable
fun SecureWhileShown(): Boolean {
    val context = LocalContext.current
    val activity = context.findActivity()
    if (activity == null) {
        check(context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE == 0) {
            "SecureWhileShown: no Activity behind ${context.javaClass.name}; FLAG_SECURE can't be set"
        }
        return false
    }
    DisposableEffect(activity) {
        SecureWindow.hold(activity)
        onDispose { SecureWindow.release(activity) }
    }
    return true
}
