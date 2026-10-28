package dev.openmob.companion.gate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Security review 5 (2026-10-21), the gatekeeper's phone-only parts. The shared scenarios (tag review5) run the
 *  same rules in both engines: the paired server's pages (H1), notifications and widgets of blocked apps (P5-M1). */
class Review5GateTest {
    private val clock = GateScenarioTest.FakeClock()
    private fun gate() = GateScenarioTest.newGate(clock)

    // --- H1: the paired server's host -------------------------------------------------------------------------------

    @Test fun hostOfReadsAHostAsABrowserWould() {
        val cases = mapOf(
            "https://openmob.example/memory" to "openmob.example",
            "openmob.example/memory" to "openmob.example",
            "HTTPS://User@OpenMob.Example:8443/x?y#z" to "openmob.example",
            "www.openmob.example" to "openmob.example",
            "openmob.example." to "openmob.example",
            "https:/openmob.example/" to "openmob.example",
            "https://openmob.example\\@example.com/" to "openmob.example", // a backslash is a slash to a browser
            "https://example.com\\@openmob.example/" to "example.com",
            "https://openmob%2eexample/" to "openmob.example",
            "openmob．example" to "openmob.example", // a full-width dot
            "wss://openmob.example" to "openmob.example",
            "http://192.168.1.5:8765/dashboard" to "192.168.1.5",
            "\topenmob.example\n" to "openmob.example",
            // Re-review 1: percent-decoded, NFKC (ideographic and full-width dots, full-width letters), IDNA.
            "https://%6Fpenmob.example/" to "openmob.example",
            "https://%6f%70%65%6e%6d%6f%62%2Eexample/" to "openmob.example",
            "https://openmob\u3002example/" to "openmob.example",
            "https://openmob\uff61example./x" to "openmob.example",
            "https://\uff4f\uff50\uff45\uff4emob.example/" to "openmob.example",
            "https://open\u00admob.example/" to "openmob.example", // a soft hyphen: IDNA drops it, as browsers do
            "https://openmob.example%2Eevil.com/" to "openmob.example.evil.com",
            "https://b\u00fccher.example/" to "xn--bcher-kva.example",
        )
        for ((url, host) in cases) assertEquals(url, host, Gatekeeper.hostOf(url))
        for (none in listOf("", "Search or type URL", "javascript:alert(1)", "mailto:me@openmob.example", "about:blank",
                            "https://openmob.example%2F/", "https://openmob%20example/")) {
            assertNull(none, Gatekeeper.hostOf(none))
        }
    }

    @Test fun theServerIsItsHostAndItsSubdomainsNothingElse() {
        val g = gate()
        assertFalse(g.isServerHost("https://openmob.example/")) // no pairing known: nothing is the server
        g.serverHosts = setOfNotNull(Gatekeeper.hostOf("https://openmob.example"))
        for (yes in listOf("https://openmob.example/", "app.openmob.example/x", "WWW.OPENMOB.EXAMPLE")) assertTrue(yes, g.isServerHost(yes))
        for (no in listOf("https://openmob.example.evil.com/", "notopenmob.example", "https://example.com/?u=openmob.example",
                          "https://evil.com/openmob.example")) assertFalse(no, g.isServerHost(no))
    }

    // --- P5-M1: notifications ---------------------------------------------------------------------------------------

    private fun shade(app: String) = GWindow(9, "system", 9, "com.android.systemui", "Notification shade", intArrayOf(0, 0, 1080, 2400),
        GNode(cls = "android.widget.FrameLayout", bounds = intArrayOf(0, 0, 1080, 2400), children = listOf(
            GNode(text = app, id = "android:id/app_name_text", bounds = intArrayOf(140, 320, 400, 370)),
            GNode(text = "Your code is 123456", id = "android:id/text", bounds = intArrayOf(140, 440, 900, 490)))))

    @Test fun aBlockedAppsNotificationBlacksOutReadsOnlyWhenThePhoneKnowsItsLabel() {
        val g = gate()
        val chase = "com.chase.sig.android"
        // GateScreens.windowPackages passes the blocked apps' labels with System UI's tree; without them, nothing to match.
        assertEquals("", g.hidden(GScreen(listOf(shade("Chase")))))
        assertEquals(Gatekeeper.BLOCKED_NOTIFICATION, g.hidden(GScreen(listOf(shade("Chase")), labels = mapOf(chase to "Chase"))))
        assertEquals("", g.hidden(GScreen(listOf(shade("Messages")), labels = mapOf(chase to "Chase"))))
        // A blacked-out notification doesn't stop the task (it can pop up over anything); an act on it does.
        assertFalse(Gatekeeper.ownerBlockRule(Gatekeeper.BLOCKED_NOTIFICATION))
        assertTrue(Gatekeeper.ownerBlockRule(Gatekeeper.OWNER_BLOCKED_NOTIFICATION))
    }

    // --- P5-L1: what can't be blocked, and never pressing Home for it -----------------------------------------------

    @Test fun onlyOpenMobTheHomeAppAndSystemUiCantBeBlocked() {
        // Re-review 1 N3 (owner's tighten-only rule): exactly these three, by exact package name.
        assertTrue(BlockedList.protectedPackage("dev.openmob.companion"))
        assertTrue(BlockedList.protectedPackage("com.android.systemui"))
        assertTrue(BlockedList.protectedPackage("com.example.home", setOf("com.example.home"))) // the default Home app
        for (p in listOf("com.google.android.apps.nexuslauncher", "com.sec.android.app.launcher", "com.epicgames.launcher",
                         "com.android.settings", "com.samsung.android.lool", "com.google.android.permissioncontroller",
                         "com.android.permissioncontroller", "com.google.android.packageinstaller",
                         "com.samsung.android.packageinstaller", "com.android.systemui.plugin", "dev.openmob.companion.x",
                         "com.whatsapp", "com.google.android.gm")) {
            assertFalse(p, BlockedList.protectedPackage(p))
        }
        // Another launcher than the default Home app can be blocked too.
        assertFalse(BlockedList.protectedPackage("com.sec.android.app.launcher", setOf("com.google.android.apps.nexuslauncher")))
        // A server's request keeps the rest; the owner's own pick too.
        assertEquals(listOf("com.whatsapp", "com.sec.android.app.launcher", "com.android.settings"),
            BlockedList.withServerRequest(emptyList(), mapOf("packages" to listOf(
                "dev.openmob.companion", "com.whatsapp", "com.sec.android.app.launcher", "com.android.settings", "com.android.systemui"))))
        assertEquals(emptyList<String>(), BlockedList.with(emptyList(), listOf("com.example.home"), setOf("com.example.home")))
        // Malformed still refuses the whole request.
        assertNull(BlockedList.withServerRequest(emptyList(), mapOf("packages" to listOf("dev.openmob.companion", "bad"))))
    }

    @Test fun theActWatchNeverSendsHomeForOpenMobOrTheHomeApp() {
        fun win(pkg: String) = GWindow(1, "application", 1, pkg, "", IntArray(4), null)
        val w = BlockedAppWatch()
        w.actStarted()
        // Even if a list stored before this rule names them.
        assertNull(w.onWindows(1_000, listOf(win("dev.openmob.companion")), { true }))
        assertNull(w.onWindows(1_000, listOf(win("com.example.home")), { true }, setOf("com.example.home")))
        assertNull(w.onWindows(1_000, listOf(win("com.android.systemui")), { true }))
        // A launcher that isn't the Home app, or Settings, blocked by the owner: left like any blocked app.
        assertEquals("com.epicgames.launcher", w.onWindows(1_000, listOf(win("com.epicgames.launcher")), { true }, setOf("com.example.home")))
        assertEquals("com.android.settings", w.onWindows(1_000, listOf(win("com.android.settings")), { true }))
        val auth = "com.google.android.apps.authenticator2"
        assertEquals(auth, w.onWindows(1_000, listOf(win("dev.openmob.companion"), win(auth)), { true }))
    }
}
