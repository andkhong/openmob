package dev.openmob.companion.gate

/**
 * The backstop behind the gate's blocked-app checks (2026-10-18: a task opened Google Authenticator by tapping its
 * home-screen icon, which no check before the tap caught). An agent's act can open an app however it gets there: an
 * icon on a launcher the rules don't know, a Recents card, a notification, a store's Open button. While an act runs,
 * and for [WINDOW_MS] after it ends, a blocked app's window (built in or owner-blocked) coming up is the agent's doing:
 * the phone goes Home at once ([onWindows] says when), and the agent's next call is refused ([takeNotice]). The owner's
 * own use of a blocked app outside that window is never touched; inside it (within seconds of an agent's act), it is
 * sent Home too.
 *
 * Pure (the caller passes the clock), so it is unit-tested; GateHost wires it to window events and acts.
 */
class BlockedAppWatch {
    private var active = 0
    private var until = Long.MIN_VALUE
    private var notice: String? = null

    @Synchronized fun actStarted() { active++ }

    @Synchronized fun actEnded(now: Long) {
        if (active > 0) active--
        until = maxOf(until, now + WINDOW_MS)
    }

    /** The windows on screen changed: the blocked package to leave (the caller presses Home), or null. */
    @Synchronized fun onWindows(now: Long, windows: List<GWindow>, blocked: (String) -> Boolean,
                                home: Set<String> = emptySet()): String? {
        if (active == 0 && now > until) return null
        // Never for OpenMob's own windows, the Home app or System UI (review 5 P5-L1, N3): pressing Home there could
        // only loop or lock the owner out, even if a stored list (from before that rule) names one.
        val pkg = windows.firstOrNull { it.type == "application" && it.pkg.isNotEmpty() && blocked(it.pkg) &&
            !BlockedList.protectedPackage(it.pkg, home) }?.pkg ?: return null
        notice = pkg
        return pkg
    }

    /** The blocked app an act opened since the agent last heard (once), or null. */
    @Synchronized fun takeNotice(): String? = notice.also { notice = null }

    companion object {
        /** An app's first window can take a few seconds after the tap on a cold start. */
        const val WINDOW_MS = 8_000L
    }
}
