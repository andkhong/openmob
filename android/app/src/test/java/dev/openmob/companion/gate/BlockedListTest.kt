package dev.openmob.companion.gate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Owner-added blocked apps (docs/design/blocked-apps.md): a server can only add; the gate refuses a blocked app in
 *  every mode and blacks it out; matches are exact package names. The shared scenarios (tag blocked_apps) cover the
 *  same rule in both engines; these are the phone-only parts. */
class BlockedListTest {
    private val gmail = "com.google.android.gm"

    @Test fun aServerRequestOnlyAdds() {
        val now = listOf("com.whatsapp", gmail)
        assertEquals(now + "org.thoughtcrime.securesms",
            BlockedList.withServerRequest(now, mapOf("type" to "block_apps", "packages" to listOf("org.thoughtcrime.securesms"))))
        // Removal-shaped requests change nothing: an empty list, "remove"/"unblock"/"replace" fields, no packages.
        assertNull(BlockedList.withServerRequest(now, mapOf("packages" to emptyList<String>())))
        assertNull(BlockedList.withServerRequest(now, mapOf("unblock" to listOf(gmail))))
        assertEquals(now, BlockedList.withServerRequest(now, mapOf("packages" to listOf(gmail), "remove" to listOf(gmail),
                                                                   "replace" to true)))
        assertNull(BlockedList.withServerRequest(now, mapOf("packages" to "com.whatsapp")))
    }

    @Test fun aMalformedOrOversizedRequestIsRefusedWhole() {
        val now = listOf("com.whatsapp")
        for (bad in listOf(listOf("com"), listOf("com.what sapp"), listOf(gmail, "../x"), listOf("cоm.whatsapp"),
                           listOf("com." + "a".repeat(300)), listOf(gmail, 3L))) {
            assertNull(bad.toString(), BlockedList.withServerRequest(now, mapOf("packages" to bad)))
        }
        val many = (0 until 200).map { "com.example.app$it" }
        assertNull(BlockedList.withServerRequest(now, mapOf("packages" to many))) // 201 with the one already there
        assertEquals(200, BlockedList.withServerRequest(emptyList(), mapOf("packages" to many))!!.size)
        assertNull(BlockedList.withServerRequest(emptyList(), mapOf("packages" to many + "com.example.more")))
    }

    @Test fun storedListsAreCleanedNeverLoosenedPastTheValidEntries() {
        assertEquals(listOf("com.whatsapp", gmail), BlockedList.parse(listOf("com.whatsapp", "bad", gmail, "com.whatsapp")))
        assertEquals(listOf(gmail), BlockedList.without(listOf("com.whatsapp", gmail), "com.whatsapp"))
    }

    private fun gate(): Gatekeeper {
        val clock = GateScenarioTest.FakeClock()
        return GateScenarioTest.newGate(clock).also { it.ownerBlocked = setOf("com.whatsapp") }
    }

    private val launcher by lazy { GateScenarioTest.SCREENS.getValue("launcher") }
    private val whatsapp by lazy { GateScenarioTest.SCREENS.getValue("whatsapp_chat") }

    @Test fun aBlockedAppIsRefusedInEveryModeAndItsReadsAreBlack() {
        val g = gate()
        for (mode in listOf("ask", "plan", "auto", "trusted")) {
            val a = g.admit("launch_app", mapOf("package" to "com.whatsapp", "mode" to mode), launcher)
            assertEquals(mode, "gate_blocked_app", a.code)
            assertEquals(Gatekeeper.OWNER_BLOCKED, a.rule)
        }
        // Don't ask (a signed never window) doesn't lift it either.
        val record = mapOf<String, Any?>("type" to "never", "duration_ms" to 3_600_000L, "allow_money" to true)
        val m = "gk1|policy|" + Gatekeeper.canon(record)
        assertTrue(g.addPolicy(record, PolicyProof(m, GateScenarioTest.sign(m))))
        assertEquals("gate_blocked_app", g.admit("launch_app", mapOf("package" to "com.whatsapp"), launcher).code)
        val shot = g.admit("screenshot", emptyMap(), whatsapp)
        assertEquals("redact", shot.decision)
        assertEquals("com.whatsapp", shot.pkg) // the phone's stop names it in the app, never in a notification
        assertEquals("gate_blocked_app", g.admit("stream_start", emptyMap(), whatsapp).code)
        assertEquals(Gatekeeper.OWNER_BLOCKED, g.hidden(whatsapp))
    }

    @Test fun exactPackageNamesOnly() {
        val g = gate()
        assertFalse(g.isBlocked("com.whatsapp.w4b"))
        assertFalse(g.isBlocked("whatsapp"))
        assertTrue(g.isBlocked("com.whatsapp"))
        assertEquals("allow", g.admit("launch_app", mapOf("package" to "com.whatsapp.w4b"), launcher).decision)
    }
}
