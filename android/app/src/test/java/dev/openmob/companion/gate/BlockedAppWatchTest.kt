package dev.openmob.companion.gate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** The backstop (2026-10-18): a blocked app an agent's act opened, however it got there, is left at once. */
class BlockedAppWatchTest {
    private val auth = "com.google.android.apps.authenticator2"
    private val home = "com.sec.android.app.launcher"
    private fun win(pkg: String, type: String = "application") = GWindow(1, type, 1, pkg, "", IntArray(4), null)
    private val gate = GateScenarioTest.newGate(GateScenarioTest.FakeClock()).also { it.ownerBlocked = setOf("com.whatsapp") }
    private val blocked: (String) -> Boolean = { gate.isBlocked(it) }

    @Test fun aBlockedAppComingUpDuringAnActOrJustAfterIsLeftAndTheAgentHearsOnce() {
        val w = BlockedAppWatch()
        w.actStarted()
        assertNull(w.onWindows(1_000, listOf(win(home)), blocked))
        assertEquals(auth, w.onWindows(1_100, listOf(win(auth)), blocked))
        w.actEnded(1_200)
        assertEquals(auth, w.takeNotice())
        assertNull(w.takeNotice())
        // Cold start: the app's window shows up seconds after the gesture ended.
        assertEquals(auth, w.onWindows(1_200 + BlockedAppWatch.WINDOW_MS, listOf(win(home), win(auth)), blocked))
    }

    @Test fun anOwnerBlockedAppIsLeftToo() {
        val w = BlockedAppWatch()
        w.actStarted(); w.actEnded(1_000)
        assertEquals("com.whatsapp", w.onWindows(2_000, listOf(win("com.whatsapp")), blocked))
        assertEquals("com.whatsapp", w.takeNotice())
        assertNull(w.onWindows(2_100, listOf(win("com.whatsapp.w4b")), blocked)) // exact names only
    }

    @Test fun theOwnersOwnUseAwayFromAnyActIsNeverTouched() {
        val w = BlockedAppWatch()
        assertNull(w.onWindows(5_000, listOf(win(auth)), blocked))
        w.actStarted(); w.actEnded(10_000)
        assertNull(w.onWindows(10_001 + BlockedAppWatch.WINDOW_MS, listOf(win(auth)), blocked))
        assertNull(w.takeNotice())
    }

    @Test fun ordinaryAppsAndNonAppWindowsDontCount() {
        val w = BlockedAppWatch()
        w.actStarted()
        assertNull(w.onWindows(1_000, listOf(win("com.amazon.mShop.android.shopping"), win(auth, type = "system")), blocked))
        assertNull(w.onWindows(1_000, listOf(win("com.whatsapp.w4b")), blocked))
        assertNull(w.takeNotice())
    }

    @Test fun theNextCallIsRefusedWithTheRightRule() {
        val owner = gate.openedRefusal("com.whatsapp", "screenshot", emptyMap())
        assertEquals("gate_blocked_app", owner.code)
        assertEquals(Gatekeeper.OWNER_BLOCKED_OPENED, owner.rule)
        assertEquals("builtin:sensitive_app_opened", gate.openedRefusal(auth, "tap", emptyMap()).rule)
    }
}
