package dev.openmob.companion.gate

import dev.openmob.companion.gate.GateScenarioTest.Companion.RULES
import dev.openmob.companion.gate.GateScenarioTest.Companion.SCREENS
import dev.openmob.companion.gate.GateScenarioTest.Companion.VERIFIER
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The hidden-dialog check (ocr_nodes on ui_elements, current_app, the owner-dialog watch) reads only the trees of
 * windows that could be the dialog (latency, 2026-10-20: each tree read costs 200-600 ms while an app redraws).
 * Skipping the others must never change what the check answers.
 */
class DialogReadTest {
    private fun gk() = Gatekeeper(RULES, GateScenarioTest.FakeClock(), VERIFIER, "dev", tapVerifier = GateScenarioTest.TAP_VERIFIER)

    private fun dialogNodes(g: Gatekeeper, s: GScreen): List<String>? =
        g.ocrPreview(s).windows.firstOrNull { it.root?.cls == "OCRDialog" }?.root?.children?.map { "${it.id}|${it.text}|${it.clickable}" }

    @Test fun everyFixtureScreenGetsTheSameAnswerWithoutTheTreesItSkips() {
        val full = gk()
        val pruned = gk()
        for ((name, screen) in SCREENS) {
            val lean = pruned.ocrRelevant(screen)
            assertEquals(name, full.ocrCandidate(screen)?.id, pruned.ocrCandidate(lean)?.id)
            assertEquals(name, full.ocrWindow(screen)?.id, pruned.ocrWindow(lean)?.id)
            assertEquals(name, full.ownerDialog(screen), pruned.ownerDialog(lean))
            assertEquals(name, dialogNodes(full, screen), dialogNodes(pruned, lean))
        }
    }

    @Test fun onlyApplicationWindowsWithNoPackageOrAPermissionControllerAreRead() {
        val g = gk()
        assertTrue(g.ocrMayRead("application", ""))
        assertTrue(g.ocrMayRead("application", "com.android.permissioncontroller"))
        assertTrue(g.ocrMayRead("application", "com.google.android.permissioncontroller"))
        assertFalse(g.ocrMayRead("application", "com.google.android.deskclock"))
        assertFalse(g.ocrMayRead("system", ""))
        assertFalse(g.ocrMayRead("input_method", "com.android.permissioncontroller"))
    }

    @Test fun aTextlessAppWindowAboveAHiddenDialogStillLetsTheDialogThrough() {
        // A canvas app (no text in its tree) on top, then the unreadable dialog window: the check moves past the app
        // whether or not its tree was read, and finds the dialog.
        fun node(text: String = "") = GNode(text = text, cls = "View", bounds = intArrayOf(0, 0, 1080, 2400))
        val canvas = GWindow(9, "application", 9, "com.example.game", "", intArrayOf(0, 0, 1080, 2400), node(), since = 1)
        val dialog = GWindow(7, "application", 7, "", "", intArrayOf(0, 0, 1080, 2400), null, since = 1)
        val worded = GWindow(9, "application", 9, "com.example.app", "", intArrayOf(0, 0, 1080, 2400),
            GNode(cls = "View", bounds = intArrayOf(0, 0, 1080, 2400), children = listOf(node("Hello"))), since = 1)
        val g = gk()
        for (top in listOf(canvas, worded)) {
            val s = GScreen(listOf(top, dialog))
            assertEquals(7, g.ocrCandidate(s)?.id)
            assertEquals(7, g.ocrCandidate(g.ocrRelevant(s))?.id)
            assertNull(g.ocrRelevant(s).windows.first().root) // the app's tree isn't needed
            assertNotNull(g.ocrRelevant(GScreen(listOf(dialog.let {
                GWindow(it.id, it.type, it.layer, "com.android.permissioncontroller", "", it.bounds, node("Allow"), 1)
            }))).windows.single().root) // a permission controller's tree is kept
        }
    }
}
