package dev.openmob.companion.gate

import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Rect
import android.net.Uri
import android.os.SystemClock
import android.provider.Settings
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import dev.openmob.companion.OpenMobAccessibilityService
import dev.openmob.companion.Nodes
import dev.openmob.companion.Perf

/**
 * What the gatekeeper sees (docs/design/phone-gatekeeper.md §2.2), read from the accessibility tree on act
 * calls only: every window in z-order with its node tree (visible nodes, bounded), the keyguard, how long the
 * screen has been quiet, and, for launches and links, the app Android would open (PackageManager), never what
 * the server says.
 */
object GateScreens {
    private const val MAX_NODES = 1500
    private const val MAX_DEPTH = 60
    private const val SYSTEM_UI = "com.android.systemui"

    fun typeName(type: Int) = when (type) {
        AccessibilityWindowInfo.TYPE_APPLICATION -> "application"
        AccessibilityWindowInfo.TYPE_INPUT_METHOD -> "input_method"
        AccessibilityWindowInfo.TYPE_SYSTEM -> "system"
        AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY -> "accessibility_overlay"
        AccessibilityWindowInfo.TYPE_SPLIT_SCREEN_DIVIDER -> "split_screen_divider"
        else -> "magnification_overlay"
    }

    /** Just the packages showing in any window (for reads: is a blocked app visible anywhere?). A window whose
     *  root can't be read yet (an app still starting) is kept with an empty package: reads treat it as unknown.
     *  [blockedLabels]: the installed blocked apps' labels; when there are any, System UI's trees are read too (a
     *  bounded walk), so a blocked app's notification in the shade or a heads-up blacks out reads (review 5 P5-M1). */
    fun windowPackages(service: OpenMobAccessibilityService, blockedLabels: Map<String, String> = emptyMap()): GScreen =
        Perf.time("read windowPackages") { GScreen(
        windows = runCatching { service.windows }.getOrDefault(emptyList()).map { w ->
            val root = w.root
            val pkg = root?.packageName?.toString().orEmpty()
            val tree = root?.takeIf { blockedLabels.isNotEmpty() && pkg == SYSTEM_UI }
                ?.let { TreeWalk(ADAPTER, emptyList(), budget = 400, maxDepth = 30).read(it) }
            @Suppress("DEPRECATION") root?.recycle()
            GWindow(w.id, typeName(w.type), w.layer, pkg, w.title?.toString().orEmpty(), IntArray(4), tree,
                service.windowSince[w.id] ?: 0L)
        },
        labels = blockedLabels,
        // A permission dialog Android hides is identified by its window-state event (reads may show it).
        eventPackage = service.lastEventPackage, eventText = service.lastEventText, eventAt = service.lastEventAt,
    ) }

    /** What the owner-dialog check needs, cheaply: every window with a shallow read of its tree, and the last
     *  window-state event. Only the trees [Gatekeeper.ocrMayRead] says the check can use are read: the rest would
     *  change nothing it answers (Gatekeeper.ocrRelevant), and on a screen that keeps redrawing each read is slow. */
    fun dialogScreen(service: OpenMobAccessibilityService, g: Gatekeeper): GScreen = Perf.time("read dialogScreen") {
        val legacy = Perf.legacy()
        GScreen(
        windows = runCatching { service.windows }.getOrDefault(emptyList()).map { w ->
            val root = w.root
            val pkg = root?.packageName?.toString().orEmpty()
            val tree = root?.takeIf { legacy || g.ocrMayRead(typeName(w.type), pkg) }
                ?.let { TreeWalk(ADAPTER, emptyList(), budget = 80, maxDepth = 12).read(it) }
            GWindow(w.id, typeName(w.type), w.layer, pkg, w.title?.toString().orEmpty(), IntArray(4), tree,
                service.windowSince[w.id] ?: 0L)
        },
        eventPackage = service.lastEventPackage, eventText = service.lastEventText, eventAt = service.lastEventAt,
    ) }

    /** [points]: where the call touches; nodes under them are always read in full (TreeWalk). */
    fun capture(service: OpenMobAccessibilityService, urls: List<String> = emptyList(),
                labelsFor: Collection<String> = emptyList(), points: List<Pair<Double, Double>> = emptyList()): GScreen =
        Perf.time("read capture") { captureNow(service, urls, labelsFor, points) }

    private fun captureNow(service: OpenMobAccessibilityService, urls: List<String>,
                           labelsFor: Collection<String>, points: List<Pair<Double, Double>>): GScreen {
        val windows = mutableListOf<GWindow>()
        // The live input focus (where typing and ENTER go) is pinned like a tap point, so its field and its
        // ancestors are always read, however deep (review R1). If it still isn't read, the gate refuses.
        val focus = runCatching { service.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) }.getOrNull()
        val focusPoint = focus?.let { f ->
            Rect().also(f::getBoundsInScreen).let { r -> r.exactCenterX().toDouble() to r.exactCenterY().toDouble() }
        }
        // The focused node itself, and its parent chain: a Jetpack Compose field (Google Messages) can be missing
        // from the walk from the root, but findFocus resolves it.
        val focusWindow = focus?.windowId
        val focusNode = focus?.let { runCatching { ADAPTER.leaf(it, emptyList(), false) }.getOrNull() }
        val focusAncestors = mutableListOf<GNode>()
        var up = runCatching { focus?.parent }.getOrNull()
        while (up != null && focusAncestors.size < 40) {
            runCatching { ADAPTER.leaf(up, emptyList(), false) }.getOrNull()?.let { focusAncestors.add(0, it) }
            val next = runCatching { up.parent }.getOrNull()
            @Suppress("DEPRECATION") up.recycle()
            up = next
        }
        @Suppress("DEPRECATION") focus?.recycle()
        val pinned = points + listOfNotNull(focusPoint)
        Nodes.refresh()
        for (w in runCatching { service.windows }.getOrDefault(emptyList())) {
            val root = Nodes.root(w)
            val bounds = Rect().also(w::getBoundsInScreen)
            val pkg = root?.packageName?.toString().orEmpty()
            val tree = root?.let { TreeWalk(ADAPTER, pinned, budget = MAX_NODES, maxDepth = MAX_DEPTH).read(it) }
            val gw = GWindow(w.id, typeName(w.type), w.layer, pkg, w.title?.toString().orEmpty(),
                intArrayOf(bounds.left, bounds.top, bounds.right, bounds.bottom), tree, service.windowSince[w.id] ?: 0L)
            // OpenMob's own overlays (keep-awake, the agent indicator): only whether they catch touches matters.
            windows.add(if (w.type == AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY && pkg == service.packageName)
                GateScreen.ownOverlayView(gw) else gw)
        }
        val keyguard = service.getSystemService(android.app.KeyguardManager::class.java)
        val pm = service.packageManager
        // An uninstall dialog or an app-info page names an app by its label: the launchable apps' labels let the gate
        // tell which (and refuse OpenMob or a blocked app).
        val naming = windows.any { "packageinstaller" in it.pkg || it.pkg == "com.android.settings" }
        val pkgs = (windows.map { it.pkg } + labelsFor + GateHost.lastAppOrEmpty() + (if (naming) launchable(pm) else emptyList()))
            .filter { it.isNotEmpty() }.toSet()
        return GScreen(
            windows = windows,
            keyguardLocked = keyguard.isKeyguardLocked, keyguardSecure = keyguard.isKeyguardSecure,
            quietMs = SystemClock.uptimeMillis() - service.lastChangeAt,
            activity = service.currentActivity.orEmpty(),
            autofillService = runCatching {
                Settings.Secure.getString(service.contentResolver, "autofill_service")?.substringBefore('/')
            }.getOrNull().orEmpty(),
            resolve = urls.associateWith { resolve(pm, it) },
            labels = labels(pm, pkgs) + GateHost.blockedLabels(pm),
            // The owner's own names, for "self" recipients (the paired account's email; Note to self and You are built in).
            owner = listOfNotNull(dev.openmob.companion.Settings(service).email.takeIf { it.isNotEmpty() }),
            focusExpected = focusPoint != null,
            focusWindow = focusWindow, focusNode = focusNode, focusAncestors = focusAncestors,
            eventPackage = service.lastEventPackage, eventText = service.lastEventText, eventAt = service.lastEventAt,
            // Android's own touch slop on this display (review 2 M1): a drag within it still clicks.
            touchSlop = runCatching { android.view.ViewConfiguration.get(service).scaledTouchSlop }.getOrDefault(0),
        )
    }

    private val ADAPTER = object : TreeWalk.Adapter<AccessibilityNodeInfo> {
        override fun bounds(n: AccessibilityNodeInfo) = Rect().also(n::getBoundsInScreen).let { intArrayOf(it.left, it.top, it.right, it.bottom) }
        override fun visible(n: AccessibilityNodeInfo) = n.isVisibleToUser
        override fun childCount(n: AccessibilityNodeInfo) = n.childCount
        override fun child(n: AccessibilityNodeInfo, i: Int): AccessibilityNodeInfo? = Nodes.child(n, i)
        @Suppress("DEPRECATION") override fun release(n: AccessibilityNodeInfo) = n.recycle()
        override fun leaf(n: AccessibilityNodeInfo, children: List<GNode>, truncated: Boolean): GNode {
            val acceptsText = n.isEditable || n.actionList.any {
                it.id == AccessibilityNodeInfo.ACTION_SET_TEXT || it.id == AccessibilityNodeInfo.ACTION_PASTE
            }
            return GNode(
                text = n.text?.toString().orEmpty(), desc = n.contentDescription?.toString().orEmpty(),
                id = n.viewIdResourceName.orEmpty(), cls = n.className?.toString().orEmpty(),
                bounds = bounds(n), clickable = n.isClickable,
                longClickable = n.isLongClickable, editable = acceptsText, password = n.isPassword,
                hint = n.hintText?.toString().orEmpty(), checked = if (n.isCheckable) n.isChecked else null,
                focused = n.isFocused && (acceptsText || n.isPassword), children = children, truncated = truncated,
                scroll = scrollDirs(n),
                // Where typing goes (review 2 L2): the gate judges the text as the phone will insert it.
                selStart = if (acceptsText) n.textSelectionStart else -1, selEnd = if (acceptsText) n.textSelectionEnd else -1,
            )
        }
    }

    /** Which way [n]'s content can scroll now (review H1): only a scrollable node with a scroll action left counts. */
    private fun scrollDirs(n: AccessibilityNodeInfo): Set<String> {
        if (!n.isScrollable) return emptySet()
        val names = mutableSetOf<String>()
        for (a in n.actionList) when (a.id) {
            AccessibilityNodeInfo.ACTION_SCROLL_FORWARD -> names.add("forward")
            AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD -> names.add("backward")
            AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_UP.id -> names.add("up")
            AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_DOWN.id -> names.add("down")
            AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_LEFT.id -> names.add("left")
            AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_RIGHT.id -> names.add("right")
        }
        val info = n.collectionInfo
        return ScrollDirs.of(true, names, info?.rowCount ?: -1, info?.columnCount ?: -1, n.className?.toString().orEmpty())
    }

    @Suppress("DEPRECATION")
    fun resolve(pm: PackageManager, url: String): Pair<String, List<String>> = runCatching {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        val chosen = pm.resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY)?.activityInfo?.packageName
        val candidates = pm.queryIntentActivities(intent, PackageManager.MATCH_DEFAULT_ONLY).map { it.activityInfo.packageName }.distinct()
        (chosen?.takeIf { it != "android" }.orEmpty()) to candidates
    }.getOrDefault("" to emptyList())

    @Suppress("DEPRECATION")
    private fun launchable(pm: PackageManager): List<String> = runCatching {
        pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .map { it.activityInfo.packageName }.distinct()
    }.getOrDefault(emptyList())

    fun labels(pm: PackageManager, pkgs: Collection<String>): Map<String, String> = pkgs.associateWith { p ->
        runCatching { pm.getApplicationLabel(pm.getApplicationInfo(p, 0)).toString() }.getOrDefault("")
    }.filterValues { it.isNotEmpty() }
}
