package dev.openmob.companion.gate

import dev.openmob.companion.TypedText
import dev.openmob.companion.gate.GateScenarioTest.Companion.RULES
import dev.openmob.companion.gate.GateScenarioTest.Companion.SCREENS
import dev.openmob.companion.gate.GateScenarioTest.Companion.VERIFIER
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Security review 2 (P2, 2026-10-17): the reviewer's Kotlin proofs of concept (ReviewP2PocTest), now failing to
 *  reproduce, and the phone-only glue the shared scenarios can't reach (ScrollDirs, drawnPoint, the slop). */
class ReviewP2FixesTest {
    private val clock = GateScenarioTest.FakeClock()
    private fun gate() = Gatekeeper(RULES, clock, VERIFIER, "dev", tapVerifier = GateScenarioTest.TAP_VERIFIER)
    private fun verdict(a: Admission) = listOf(a.decision, a.kind, a.rule, a.money)

    @Test fun layeredDragsAskAsTheTap() {
        val cases = listOf(
            Triple("dialer_google_layered", 540L, 2200L to 2280L),
            Triple("hit_place_order_layered", 540L, 1640L to 1700L),
            Triple("hit_send_toolbar", 980L, 2290L to 2210L),
            Triple("hit_delete_layered", 900L, 2260L to 2140L),
            Triple("hit_settings_layered", 540L, 450L to 510L),
        )
        for ((name, x, ys) in cases) {
            val s = SCREENS.getValue(name)
            val p = mapOf<String, Any?>("task" to "t1", "task_text" to "check my stuff")
            clock.elapsed += 5000
            val tap = gate().admit("tap", p + mapOf("x" to x, "y" to (ys.first + ys.second) / 2), s)
            clock.elapsed += 5000
            val drag = gate().admit("swipe", p + mapOf("x1" to x, "y1" to ys.first, "x2" to x, "y2" to ys.second,
                "duration_ms" to 200L, "mode" to "ask"), s)
            assertEquals(name, "ask", tap.decision)
            assertEquals(name, verdict(tap), verdict(drag))
        }
    }

    @Test fun slopDragsKeepEveryRule() {
        val cases = listOf(
            Triple("permission_dialog_other", 540L, 1550L to 1626L),
            Triple("settings_dev", 400L, 480L to 566L),
            Triple("dialer_google", 540L, 2040L to 2176L),
            Triple("uninstall_chess", 900L, 1380L to 1476L),
        )
        for ((name, x, ys) in cases) {
            val s = SCREENS.getValue(name)
            val p = mapOf<String, Any?>("task" to "t1", "task_text" to "play chess")
            clock.elapsed += 5000
            val tap = gate().admit("tap", p + mapOf("x" to x, "y" to ys.first), s)
            clock.elapsed += 5000
            val drag = gate().admit("swipe", p + mapOf("x1" to x, "y1" to ys.first, "x2" to x, "y2" to ys.second,
                "duration_ms" to 200L), s)
            assertTrue(name, tap.decision == "ask" || tap.decision == "refuse")
            assertEquals(name, verdict(tap), verdict(drag))
        }
    }

    @Test fun taskIdNeverNamesTheApp() {
        val s = SCREENS.getValue("hit_install_layered")
        for (task in listOf("t1", "t1-torchlight")) {
            val g = gate()
            val a = g.requestTask(mapOf("task" to task, "text" to "check the weather"))
            val m = g.approvalMessage(a.approvalId!!)!!
            assertTrue(g.approve(a.approvalId!!, m, GateScenarioTest.tapSign(m)))
            clock.elapsed += 10_000
            val adm = g.admit("tap", mapOf("x" to 540L, "y" to 860L, "task" to task, "task_text" to "check the weather"), s)
            assertEquals(task, listOf("ask", "risk:install:unnamed"), listOf(adm.decision, adm.rule))
        }
    }

    @Test fun nanDurationIsRefused() {
        val s = SCREENS.getValue("dialer_google")
        for (bad in listOf<Any?>("NaN", Double.NaN, Double.POSITIVE_INFINITY, -1L, "100")) {
            clock.elapsed += 5000
            val a = gate().admit("swipe", mapOf("x1" to 540L, "y1" to 2075L, "x2" to 540L, "y2" to 1500L, "duration_ms" to bad), s)
            assertEquals("$bad", listOf("refuse", "gate_bad_params"), listOf(a.decision, a.code))
        }
        clock.elapsed += 5000
        assertEquals("ask", gate().admit("swipe", mapOf("x1" to 540L, "y1" to 2075L, "x2" to 540L, "y2" to 1500L,
            "duration_ms" to 100L), s).decision)
        clock.elapsed += 5000
        assertEquals("gate_bad_params", gate().admit("type_text", mapOf("text" to "hi", "replace" to "true"),
            SCREENS.getValue("m4_notes_empty")).code)
    }

    @Test fun scrollDirsUseTheDirectionalActionsAndSidewaysCollections() {
        // A Compose LazyRow: a 1 x -1 collection, a plain View class, forward and right.
        assertEquals(setOf("right"), ScrollDirs.of(true, setOf("forward", "right"), 1, -1, "android.view.View"))
        assertEquals(setOf("right"), ScrollDirs.of(true, setOf("forward", "right"), -1, -1, "android.view.View"))
        assertEquals(setOf("right"), ScrollDirs.of(true, setOf("forward"), 1, -1, "android.view.View"))
        assertEquals(setOf("right"), ScrollDirs.of(true, setOf("forward"), -1, -1, "android.widget.HorizontalScrollView"))
        assertEquals(setOf("down", "up"), ScrollDirs.of(true, setOf("forward", "backward"), -1, -1, "androidx.recyclerview.widget.RecyclerView"))
        assertEquals(setOf("down"), ScrollDirs.of(true, setOf("forward"), 5, 1, "android.view.View"))
        assertEquals(emptySet<String>(), ScrollDirs.of(false, setOf("forward"), -1, -1, "android.widget.ScrollView"))
    }

    @Test fun theLargerTouchSlopCounts() {
        val g = gate()
        val s = SCREENS.getValue("h1_send_in_list_at_top")
        assertEquals(24L, g.slop(s))
        assertEquals(30L, g.slop(SCREENS.getValue("r2_send_in_list_at_top_dense")))
    }

    @Test fun drawnPointOnlyForDrawnSpots() {
        val g = gate()
        val game = SCREENS.getValue("r2_game_play")
        assertEquals(540.0 to 1140.0, g.drawnPoint("tap", mapOf("x" to 540L, "y" to 1140L), game))
        assertEquals(540.0 to 1140.0, g.drawnPoint("swipe", mapOf("x1" to 540L, "y1" to 1140L, "x2" to 540L,
            "y2" to 600L, "duration_ms" to 300L), game))
        // A labeled button isn't read; nor is a scroll from an unlabeled spot in an ordinary app (no drawn view).
        assertNull(g.drawnPoint("tap", mapOf("x" to 540L, "y" to 2075L), SCREENS.getValue("dialer_google")))
        assertNull(g.drawnPoint("swipe", mapOf("x1" to 540L, "y1" to 2200L, "x2" to 540L, "y2" to 700L,
            "duration_ms" to 300L), SCREENS.getValue("amazon_product")))
        assertNull(g.drawnPoint("key", mapOf("name" to "ENTER"), game))
        assertNull(g.drawnPoint("tap", mapOf("x" to "NaN", "y" to 1140L), game))
        // The tiny aria-label over a drawn purchase: read.
        assertTrue(g.canvasSpot(SCREENS.getValue("r2_web_canvas_label_lie"), 540.0, 1140.0))
    }

    @Test fun typedTextSelectionIsClampedAsThePhoneDoes() {
        assertNull(TypedText.selection(-1, -1, 4))
        assertEquals(0 to 0, TypedText.selection(0, 0, 4))
        assertEquals(2 to 4, TypedText.selection(9, 2, 4))
        assertEquals("4111 1111 1111 1111", TypedText.result("1111", 0 to 0, "4111 1111 1111 ", false).first)
    }

    @Test fun detectorSeparators() {
        val groups = listOf("4111", "1111", "1111", "1111")
        for (sep in listOf("\t", "\n", ",", ":", " - ", ", ", "​", "⁠", "　", "­")) {
            assertEquals("sep ${sep.codePointAt(0)}", SensitiveNumbers.CARD, SensitiveNumbers.find(groups.joinToString(sep)))
        }
        assertEquals(SensitiveNumbers.CARD, SensitiveNumbers.find("+4111 1111 1111 1111"))
        assertNull(SensitiveNumbers.find("+491512345678901"))
        assertNull(SensitiveNumbers.find("2015-10-12 - 2015-10-17"))
        assertEquals(SensitiveNumbers.SSN, SensitiveNumbers.find("123\t45\t6789"))
    }
}
