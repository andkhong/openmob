package dev.openmob.companion

import android.os.Build
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo

/**
 * Tree reads with prefetching (Android 13+): a node fetched from the app brings its descendants along, in the order
 * the walks visit them, so a walk makes a few calls into the app instead of one per node. Same data, fewer round
 * trips; what matters on a screen that keeps redrawing, where each round trip waits for the app's busy UI thread
 * (2026-10-20, a running stopwatch). Older Android: the plain calls.
 */
object Nodes {
    private const val STRATEGY = AccessibilityNodeInfo.FLAG_PREFETCH_DESCENDANTS_DEPTH_FIRST or
        AccessibilityNodeInfo.FLAG_PREFETCH_UNINTERRUPTIBLE

    /** Off for A/B measurements only (Perf.legacy, or files/perf_noprefetch; debug builds); set at the start of each
     *  walk. */
    @Volatile var prefetch = true

    fun refresh() { prefetch = !Perf.legacy() && !Perf.legacy("perf_noprefetch") }

    fun root(w: AccessibilityWindowInfo): AccessibilityNodeInfo? =
        if (prefetch && Build.VERSION.SDK_INT >= 33) w.getRoot(STRATEGY) else w.root

    fun child(n: AccessibilityNodeInfo, i: Int): AccessibilityNodeInfo? =
        if (prefetch && Build.VERSION.SDK_INT >= 33) n.getChild(i, STRATEGY) else n.getChild(i)
}
