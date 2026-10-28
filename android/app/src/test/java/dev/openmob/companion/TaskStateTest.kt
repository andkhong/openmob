package dev.openmob.companion

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** AppState's task_state (docs/phone-protocol.md §3.4): started, step, ended, and a new connection forgets it. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class TaskStateTest {
    @After fun tearDown() { AppState.setTaskProtocol(false) }

    @Test fun startedStepEnded() {
        AppState.setTaskProtocol(true)
        assertTrue(AppState.taskProtocol)
        AppState.onTaskState("started", "t1", "Play jazz", "", 0, now = 1_000)
        assertEquals(AppState.TaskState("t1", "Play jazz", "", 0, 1_000), AppState.task)
        AppState.onTaskState("step", "t1", "Play jazz", "tap: Search", 1, now = 5_000)
        assertEquals(1_000L, AppState.task?.at) // still timed from its start
        assertEquals("tap: Search", AppState.task?.step)
        AppState.onTaskState("ended", "other", "", "", 0)
        assertEquals("t1", AppState.task?.id) // another task's end doesn't end this one
        AppState.onTaskState("ended", "t1", "", "", 4)
        assertNull(AppState.task)
    }

    @Test fun aStepForANewTaskReplacesTheOld() {
        AppState.setTaskProtocol(true)
        AppState.onTaskState("started", "t1", "a", "", 0, now = 1)
        AppState.onTaskState("step", "t2", "b", "x", 1, now = 9)
        assertEquals("t2", AppState.task?.id)
        assertEquals(9L, AppState.task?.at)
    }

    @Test fun losingTheConnectionForgetsIt() {
        AppState.setTaskProtocol(true)
        AppState.onTaskState("started", "t1", "a", "", 0)
        AppState.clearTask()
        assertNull(AppState.task)
        AppState.onTaskState("started", "t1", "a", "", 0)
        AppState.setTaskProtocol(false)
        assertFalse(AppState.taskProtocol)
        assertNull(AppState.task)
    }

    @Test fun ignoresMessagesWithoutATaskIdAndCapsText() {
        AppState.onTaskState("started", "", "a", "", 0)
        assertNull(AppState.task)
        AppState.onTaskState("started", "t1", "x".repeat(500), "y".repeat(500), -3)
        assertEquals(300, AppState.task?.text?.length)
        assertEquals(200, AppState.task?.step?.length)
        assertEquals(0, AppState.task?.steps)
    }
}
