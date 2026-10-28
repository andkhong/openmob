package dev.openmob.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The phone's task history (docs/design/redesign-activity.md): grouping by task id, asks, the caps. Robolectric for org.json. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class TaskLogTest {
    private class MemStore : TaskLog.Store {
        var json: String? = null
        override fun read() = json
        override fun write(json: String) { this.json = json }
    }

    private var now = 1_800_000_000_000L
    private val store = MemStore()
    private val patterns = TaskLog.Patterns(
        asked = listOf(TaskLog.formatRegex("%1\$s asks: %2\$s"), TaskLog.formatRegex("Asked on this phone: %1\$s")),
        denied = listOf(TaskLog.formatRegex("Denied: %1\$s")),
        stoppedByOwner = setOf("You stopped the agent with the Stop button."),
    )
    private fun log() = TaskLog(store, patterns) { now }

    @Test fun formatRegexMatchesFilledInMessages() {
        assertTrue(TaskLog.formatRegex("%1\$s asks: %2\$s").matches("Claude asks: Send it?"))
        assertTrue(TaskLog.formatRegex("Denied: %1\$s").matches("Denied: Buy (now)?"))
        assertFalse(TaskLog.formatRegex("Denied: %1\$s").matches("Approved: x"))
    }

    // Owner, 2026-10-17: Faster mode answers from Settings are kept as their own rows, with their own cap of 10, the
    // same 7 days, cleared with the rest; they never push tasks out of the 50.
    @Test fun fasterAnswersHaveTheirOwnCapAndTheSamePrivacyRules() {
        val l = log()
        repeat(TaskLog.MAX) { i -> l.onTaskState("ended", "t$i", "Task $i", 1, "done", ""); now += 1_000 }
        repeat(TaskLog.MAX_FASTER + 3) { i -> l.onFasterAnswer("a$i", "session", approved = i % 2 == 0); now += 1_000 }
        l.onFasterAnswer("a12", "session", approved = false) // a repeat answer for the same id is ignored
        val all = l.records()
        assertEquals(TaskLog.MAX, all.count { it.kind == TaskLog.KIND_TASK })
        assertEquals(TaskLog.MAX_FASTER, all.count { it.kind == TaskLog.KIND_FASTER })
        val newest = all.first()
        assertEquals("a12", newest.id); assertEquals("session", newest.request); assertEquals("approved", newest.outcome)
        // Survives a reload (the kind is stored); old entries go after 7 days; unpair clears them.
        assertEquals(TaskLog.KIND_FASTER, log().records().first().kind)
        now += TaskLog.KEEP_MS + 1
        assertEquals(0, log().records().size)
        l.onFasterAnswer("b", "phone", true)
        l.clear()
        assertEquals(0, log().records().size)
    }

    @Test fun aTaskFromStartToEnd() {
        val l = log()
        l.onTaskState("started", "t1", "Play jazz", 0, "", "")
        now += 5_000
        l.onTaskState("step", "t1", "Play jazz", 2, "", "")
        now += 10_000
        l.onTaskState("ended", "t1", "", 3, "done", "Playing (3 steps)")
        val r = l.records().single()
        assertEquals("Play jazz", r.request)
        assertEquals("done", r.outcome)
        assertEquals(3, r.steps)
        assertEquals(15_000L, r.durationMs)
        assertEquals("", r.reason) // only a failed task keeps its line
    }

    @Test fun asksDenialsAndTheOwnersStopCountForTheRunningTaskOnly() {
        val l = log()
        l.onTaskState("started", "t1", "Buy headphones", 0, "", "")
        l.onEvent("approval", "Asked on this phone: Buy now · \$249?", "t1")
        l.onEvent("approval", "Claude asks: Pay?", "t1")
        l.onEvent("approval", "Denied: Pay?", "t1")
        l.onEvent("status", "You stopped the agent with the Stop button.", "t1")
        l.onEvent("approval", "Asked on this phone: other", "t9") // another task id: not this one
        l.onEvent("action", "tap: x", "t1")                        // not an ask
        val r = l.records().single()
        assertEquals(2, r.asks)
        assertTrue(r.denied)
        assertTrue(r.stoppedByOwner)
        l.onTaskState("ended", "t1", "", 0, "stopped", "")
        l.onEvent("approval", "Asked on this phone: late", "t1") // ended: no longer counted
        assertEquals(2, l.records().single().asks)
    }

    @Test fun anUnknownOutcomeIsAFailureAndKeepsAShortReason() {
        val l = log()
        l.onTaskState("ended", "t2", "", 0, "weird", "x".repeat(500))
        val r = l.records().single()
        assertEquals("failed", r.outcome)
        assertEquals(TaskLog.MAX_REASON, r.reason.length)
    }

    @Test fun keptAtMost50TasksAnd7Days() {
        val l = log()
        repeat(60) { i -> now += 1_000; l.onTaskState("started", "t$i", "task $i", 0, "", "") }
        assertEquals(TaskLog.MAX, l.records().size)
        assertEquals("t59", l.records().first().id)
        now += TaskLog.KEEP_MS + 1
        assertTrue(l.records().isEmpty())
    }

    @Test fun survivesARestartAndIsClearedOnUnpair() {
        log().apply { onTaskState("started", "t1", "a", 0, ""); onTaskState("ended", "t1", "", 1, "done", "") }
        val again = log()
        assertEquals("t1", again.records().single().id)
        again.clear()
        assertTrue(log().records().isEmpty())
    }

    @Test fun keepsNoStepText() {
        val l = log()
        l.onTaskState("step", "t1", "Log in", 1, "", "")
        assertFalse(store.json!!.contains("type_text"))
        assertFalse(store.json!!.contains("\"step\""))
    }

    private fun TaskLog.onTaskState(state: String, id: String, text: String, steps: Int, outcome: String) =
        onTaskState(state, id, text, steps, outcome, "")
}
