package dev.openmob.companion

import android.os.SystemClock
import android.util.Log

/**
 * Latency diagnostics (logcat tag OpenMobPerf, debug builds only): how long each protocol call and each tree read
 * took on the phone. Names and durations only, never screen text. `adb logcat -s OpenMobPerf` reads them.
 */
object Perf {
    const val TAG = "OpenMobPerf"
    @JvmField val enabled: Boolean = BuildConfig.DEBUG

    inline fun <T> time(what: String, block: () -> T): T {
        if (!enabled) return block()
        val start = SystemClock.uptimeMillis()
        try {
            return block()
        } finally {
            log("$what ${SystemClock.uptimeMillis() - start}ms")
        }
    }

    /** Debug builds only, for before/after measurements on one install: while the file `files/perf_legacy` exists
     *  (`adb shell run-as dev.openmob.companion touch files/perf_legacy`), the latency changes of 2026-10-20 are off.
     *  Always false in release builds. */
    fun legacy(flag: String = "perf_legacy"): Boolean = enabled && runCatching {
        java.io.File(OpenMobAccessibilityService.instance?.filesDir ?: return false, flag).exists()
    }.getOrDefault(false)

    fun log(line: String) {
        if (enabled) runCatching { Log.d(TAG, line) } // plain JVM tests have no Log
    }
}
