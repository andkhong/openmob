package dev.openmob.companion.ui

import dev.openmob.companion.AppState
import dev.openmob.companion.TaskLog
import dev.openmob.companion.ui.activity.ActivityFilter
import dev.openmob.companion.ui.activity.ActivityMapper
import dev.openmob.companion.ui.activity.ActivitySamples
import dev.openmob.companion.ui.activity.ActivityViewModel
import dev.openmob.companion.ui.activity.RowKind
import dev.openmob.companion.ui.home.HomeMapper
import dev.openmob.companion.ui.state.PhoneSnapshot
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.LocalDate

/** The Activity screen and Home's Latest from the phone's task history: by day, the kinds, filters, asks, empty. */
@OptIn(ExperimentalCoroutinesApi::class)
class ActivityViewModelTest {
    @Before fun setUp() { Dispatchers.setMain(StandardTestDispatcher()) }
    @After fun tearDown() { Dispatchers.resetMain() }

    @Test fun groupedByDayNewestFirst() {
        val s = ActivitySamples.full()
        assertEquals(listOf(LocalDate.of(2026, 10, 17), LocalDate.of(2026, 10, 16), LocalDate.of(2026, 10, 15)), s.groups.map { it.day })
        assertEquals(listOf("t7", "t6", "t5", "t4"), s.groups[0].rows.map { it.id })
        assertEquals(7, s.total)
    }

    @Test fun eachTaskGetsItsKind() {
        val kinds = ActivitySamples.full().groups.flatMap { it.rows }.associate { it.id to it.kind }
        assertEquals(RowKind.Running, kinds["t7"])
        assertEquals(RowKind.StoppedByYou, kinds["t6"])
        assertEquals(RowKind.Denied, kinds["t5"])
        assertEquals(RowKind.Done, kinds["t4"])
        assertEquals(RowKind.Failed, kinds["t2"])
        assertEquals(RowKind.Interrupted, kinds["t1"]) // never ended, and not the running task
    }

    @Test fun theRunningRowCountsFromItsStart() {
        val r = ActivitySamples.full().groups[0].rows[0]
        assertEquals(14_000L, r.durationMs)
        assertEquals(3, r.steps)
    }

    @Test fun filters() {
        assertEquals(setOf("t6", "t5"), ActivitySamples.full(ActivityFilter.Asked).groups.flatMap { it.rows }.map { it.id }.toSet())
        assertEquals(setOf("t6", "t5"), ActivitySamples.full(ActivityFilter.StoppedOrDenied).groups.flatMap { it.rows }.map { it.id }.toSet())
        val plainStop = listOf(TaskLog.Record("x", "a", ActivitySamples.NOW - 1000, ActivitySamples.NOW, "stopped"))
        assertEquals(RowKind.Stopped, ActivityMapper.map(plainStop, null, ActivityFilter.StoppedOrDenied, ActivitySamples.NOW,
                                                         ActivitySamples.ZONE).groups.single().rows.single().kind)
    }

    @Test fun emptyHistory() {
        val s = ActivitySamples.empty()
        assertEquals(0, s.total)
        assertTrue(s.groups.isEmpty())
    }

    @Test fun theViewModelFollowsChangesAndTheFilter() {
        var records = emptyList<TaskLog.Record>()
        var listener: (() -> Unit)? = null
        val vm = ActivityViewModel({ records }, { null }, { cb -> listener = cb; {} }, { ActivitySamples.NOW }, ActivitySamples.ZONE)
        assertEquals(0, vm.state.value.total)
        records = ActivitySamples.records.drop(1)
        listener!!.invoke()
        assertEquals(6, vm.state.value.total)
        vm.setFilter(ActivityFilter.Asked)
        assertEquals(ActivityFilter.Asked, vm.state.value.filter)
        assertEquals(2, vm.state.value.groups.sumOf { it.rows.size })
    }

    // --- Home: Latest and "Asked you N times" from the task history ---

    private val ready = PhoneSnapshot(paired = true, accessibilityOn = true, running = true, connected = true, taskProtocol = true)

    @Test fun homeLatestComesFromTheHistoryWithItsAskCount() {
        val s = HomeMapper.map(ready.copy(history = listOf(
            TaskLog.Record("t2", "Buy headphones", ActivitySamples.NOW - 600_000, ActivitySamples.NOW - 540_000, "stopped",
                           asks = 1, denied = true))), ActivitySamples.NOW)
        assertEquals("Buy headphones", s.latest?.request)
        assertEquals(1, s.latest?.asks)
        assertEquals(false, s.latest?.succeeded)
        assertEquals(9L, s.latest?.minutesAgo)
    }

    @Test fun fasterAnswersAreTheirOwnRowsAndNeverHomesLatest() {
        val t0 = ActivitySamples.NOW - 600_000
        val recs = listOf(
            TaskLog.Record("a2", "phone", t0 + 2, t0 + 2, "denied", kind = TaskLog.KIND_FASTER),
            TaskLog.Record("a1", "session", t0 + 1, t0 + 1, "approved", kind = TaskLog.KIND_FASTER),
            TaskLog.Record("t1", "Play jazz", t0, t0 + 1, "done"),
        )
        val rows = ActivityMapper.map(recs, null, ActivityFilter.All, ActivitySamples.NOW, ActivitySamples.ZONE).groups.flatMap { it.rows }
        assertEquals(listOf(RowKind.FasterDenied, RowKind.FasterApproved, RowKind.Done), rows.map { it.kind })
        fun ids(f: ActivityFilter) = ActivityMapper.map(recs, null, f, ActivitySamples.NOW, ActivitySamples.ZONE).groups.flatMap { g -> g.rows.map { it.id } }
        assertEquals(listOf("a2", "a1"), ids(ActivityFilter.Asked))
        assertEquals(listOf("a2"), ids(ActivityFilter.StoppedOrDenied))
        assertEquals("Play jazz", HomeMapper.map(ready.copy(history = recs), ActivitySamples.NOW).latest?.request)
    }

    // E2E finding (step 6): Home said "Didn't finish" with a warning where Activity said "Stopped by you".
    @Test fun homeLatestSaysStoppedLikeActivity() {
        fun latest(r: TaskLog.Record) = HomeMapper.map(ready.copy(history = listOf(r)), ActivitySamples.NOW).latest
        val t0 = ActivitySamples.NOW - 120_000
        assertEquals(1, latest(TaskLog.Record("a", "wait", t0, t0 + 60_000, "stopped", stoppedByOwner = true))?.stopped)
        assertEquals(2, latest(TaskLog.Record("b", "wait", t0, t0 + 60_000, "stopped"))?.stopped)
        assertEquals(0, latest(TaskLog.Record("c", "wait", t0, t0 + 60_000, "stopped", asks = 1, denied = true))?.stopped)
        assertEquals(0, latest(TaskLog.Record("d", "wait", t0, t0 + 60_000, "failed"))?.stopped)
    }

    @Test fun homeWorkingShowsTheRunningTasksAsks() {
        val task = AppState.TaskState("t3", "Pay the bill", "", 1, ActivitySamples.NOW - 5_000)
        val s = HomeMapper.map(ready.copy(task = task, history = listOf(
            TaskLog.Record("t3", "Pay the bill", task.at, asks = 2))), ActivitySamples.NOW)
        assertEquals(2, s.task?.asks)
    }
}
