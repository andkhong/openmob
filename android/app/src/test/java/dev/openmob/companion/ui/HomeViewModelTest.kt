package dev.openmob.companion.ui

import dev.openmob.companion.AppState
import dev.openmob.companion.R
import dev.openmob.companion.ui.home.HomeAsk
import dev.openmob.companion.ui.home.HomeMapper
import dev.openmob.companion.ui.home.HomeStatus
import dev.openmob.companion.ui.home.HomeViewModel
import dev.openmob.companion.ui.state.OwnerControls
import dev.openmob.companion.ui.state.PendingApproval
import dev.openmob.companion.ui.state.PhoneSnapshot
import dev.openmob.companion.ui.state.PhoneSource
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class FakeSource(var snap: PhoneSnapshot = PhoneSnapshot()) : PhoneSource {
    var listener: (() -> Unit)? = null
    var unsubscribed = false
    override fun snapshot() = snap
    override fun listen(onChange: () -> Unit): () -> Unit { listener = onChange; return { unsubscribed = true } }
    fun change(s: PhoneSnapshot) { snap = s; listener?.invoke() }
}

class FakeControls(var connected: Boolean = true, var retryInMs: Long = 0) : OwnerControls {
    override fun fasterRetryInMs(): Long = retryInMs
    val calls = mutableListOf<String>()
    override fun stopTask() { calls += "stopTask" }
    override fun disconnect() { calls += "disconnect" }
    override fun connect() { calls += "connect" }
    override fun sendCommand(text: String): Boolean { calls += "send:$text"; return connected }
    override fun deny(id: String): Boolean { calls += "deny:$id"; return connected }
    override fun requestFaster(scope: String): Boolean { calls += "faster:$scope"; return connected }
    override fun turnOffFaster() { calls += "fasterOff" }
}

/** Home's states from the phone's state (HomeMapper through HomeViewModel), and its actions' calls. */
@OptIn(ExperimentalCoroutinesApi::class)
class HomeViewModelTest {
    private val now = 1_800_000_000_000L
    private fun ev(kind: String, message: String, secondsAgo: Long = 0) = AppState.Event(kind, message, now - secondsAgo * 1000)
    private val ready = PhoneSnapshot(
        paired = true, accessibilityOn = true, notificationsOn = true, batteryUnrestricted = true,
        running = true, connected = true, connectionText = "Connected to home-server.local", serverHost = "home-server.local",
    )
    private val stopNote = "You stopped the agent with the Stop button."

    private lateinit var source: FakeSource
    private lateinit var controls: FakeControls
    private fun vm(s: PhoneSnapshot): HomeViewModel {
        source = FakeSource(s); controls = FakeControls()
        return HomeViewModel(source, controls, setOf(stopNote), clock = { now })
    }

    @Before fun setUp() { Dispatchers.setMain(StandardTestDispatcher()) }
    @After fun tearDown() { Dispatchers.resetMain() }

    @Test fun notSetUpWhenUnpairedOrAccessibilityOff() {
        assertEquals(HomeStatus.NotSetUp, vm(PhoneSnapshot()).state.value.status)
        assertEquals(HomeStatus.NotSetUp, vm(PhoneSnapshot(paired = true)).state.value.status)
        val s = vm(PhoneSnapshot(paired = true, notificationsOn = true)).state.value
        assertEquals(2, s.checksDone)
        assertTrue(s.canConnect) // paired: MainActivity allows Connect even before Accessibility
    }

    @Test fun disconnectedOffersConnect() {
        val v = vm(ready.copy(running = false, connected = false, connectionText = "Disconnected"))
        assertEquals(HomeStatus.Disconnected, v.state.value.status)
        assertTrue(v.state.value.canConnect)
        assertFalse(v.state.value.canAsk)
        v.connect()
        assertEquals(listOf("connect"), controls.calls)
    }

    @Test fun connectingWhileTheServiceRunsButNotConnected() {
        val v = vm(ready.copy(connected = false, connectionText = "Connection failed. Retrying in 3 s…"))
        assertEquals(HomeStatus.Connecting, v.state.value.status)
        assertEquals("Connection failed. Retrying in 3 s…", v.state.value.connectionText)
        assertFalse(v.state.value.canConnect)
        v.connect() // nothing: already running
        assertTrue(controls.calls.isEmpty())
    }

    @Test fun connectedAndIdleShowsTheLatestTask() {
        val v = vm(ready.copy(events = listOf(
            ev("result", "Found three open nearby (6 steps)", 720),
            ev("action", "tap: Tapped “Search”", 760),
            ev("status", "Working on: Find three coffee shops open now", 800),
        )))
        val s = v.state.value
        assertEquals(HomeStatus.Connected, s.status)
        assertNull(s.task)
        assertEquals("Find three coffee shops open now", s.latest?.request)
        assertEquals(true, s.latest?.succeeded)
        assertEquals(12L, s.latest?.minutesAgo)
    }

    @Test fun workingShowsOnlyTheCurrentStep() {
        val v = vm(ready.copy(events = listOf(
            ev("action", "type_text: Typing “jazz”", 1),
            ev("thought", "Searching Spotify for jazz…", 3),
            ev("action", "tap: Tapped Search", 6),
            ev("action", "open_app: Opened Spotify", 10),
            ev("status", "Working on: Play some relaxed jazz", 14),
            ev("result", "Done earlier (2 steps)", 600),
        )))
        val s = v.state.value
        assertEquals(HomeStatus.Working, s.status)
        val t = s.task!!
        assertEquals("Play some relaxed jazz", t.request)
        assertEquals("Searching Spotify for jazz…", t.headline)
        assertEquals(3, t.step)
        assertEquals("Typing “jazz”", t.stepText)
        assertEquals(14L, t.elapsedSeconds)
        assertNull(s.latest)
    }

    @Test fun aMidTaskActionErrorDoesNotEndTheTask() {
        val v = vm(ready.copy(events = listOf(
            ev("error", "tap: nothing at that point"),
            ev("status", "Working on: Open the camera", 5),
        )))
        assertEquals(HomeStatus.Working, v.state.value.status)
        assertEquals("nothing at that point", v.state.value.task?.stepText)
    }

    @Test fun aFinalErrorOrTheOwnersStopEndsTheTask() {
        assertEquals(HomeStatus.Connected, vm(ready.copy(events = listOf(
            ev("error", "Couldn't find it (4 steps)"), ev("status", "Working on: x", 5)))).state.value.status)
        assertEquals(HomeStatus.Connected, vm(ready.copy(events = listOf(
            ev("status", stopNote), ev("action", "tap: a", 1), ev("status", "Working on: x", 5)))).state.value.status)
    }

    @Test fun anAgentActingWithoutATaskLineStillCountsAsWorking() {
        val drive = vm(ready.copy(controller = "Claude", events = listOf(ev("controller", "Claude is using your phone"))))
        assertEquals(HomeStatus.Working, drive.state.value.status)
        assertNull(drive.state.value.task?.request)
        assertEquals("Claude", drive.state.value.task?.controller)
        assertEquals(HomeStatus.Working, vm(ready.copy(agentActive = true)).state.value.status)
    }

    @Test fun askingForAnApprovalComesFirst() {
        val v = vm(ready.copy(
            approvals = listOf(PendingApproval("gk1", "Send “On my way”?", "This phone"), PendingApproval("gk2", "b", "c")),
            events = listOf(ev("approval", "asked"), ev("status", "Working on: Text Sam", 4)),
        ))
        val s = v.state.value
        assertEquals(HomeStatus.Asking, s.status)
        val ask = s.ask as HomeAsk.Approval
        assertEquals("gk1", ask.approval.id)
        assertEquals(1, ask.more)
        assertEquals("Text Sam", s.task?.request) // the task and its Stop stay on screen while asking
        v.deny("gk1")
        assertEquals(listOf("deny:gk1"), controls.calls)
    }

    @Test fun anAgentQuestionIsAnAskAnsweredYesOrNo() {
        val v = vm(ready.copy(events = listOf(ev("question", "Play “Jazz Classics”?"), ev("status", "Working on: jazz", 3))))
        assertEquals(HomeAsk.Question("Play “Jazz Classics”?"), v.state.value.ask)
        v.answerQuestion(true)
        assertEquals(listOf("send:yes"), controls.calls)
    }

    @Test fun noAskOnceDisconnected() {
        val v = vm(ready.copy(running = false, connected = false, approvals = listOf(PendingApproval("a", "q", "r"))))
        assertEquals(HomeStatus.Disconnected, v.state.value.status)
        assertNull(v.state.value.ask)
    }

    @Test fun stopIsTheTaskOnlyStopAndDisconnectIsSeparate() {
        val v = vm(ready.copy(events = listOf(ev("status", "Working on: x"))))
        v.stopTask()
        v.disconnect()
        assertEquals(listOf("stopTask", "disconnect"), controls.calls)
    }

    @Test fun followsAppStateChanges() {
        val v = vm(ready)
        assertEquals(HomeStatus.Connected, v.state.value.status)
        source.change(ready.copy(events = listOf(ev("status", "Working on: Call Mom"))))
        assertEquals(HomeStatus.Working, v.state.value.status)
        source.change(ready.copy(running = false, connected = false))
        assertEquals(HomeStatus.Disconnected, v.state.value.status)
    }

    @Test fun sendTrimsAndReportsOffline() {
        val v = vm(ready)
        assertFalse(v.send("   "))
        assertTrue(v.send("  open maps "))
        assertEquals(listOf("send:open maps"), controls.calls)
        controls.connected = false
        assertFalse(v.send("again"))
        assertEquals(R.string.ui_not_connected, v.notice.value)
        v.noticeShown()
        assertNull(v.notice.value)
    }

    @Test fun neverShowsOnlyWhileItRuns() {
        assertEquals(0L, vm(ready.copy(neverUntil = now / 1000 - 5)).state.value.neverUntil)
        assertEquals(now / 1000 + 600, vm(ready.copy(neverUntil = now / 1000 + 600)).state.value.neverUntil)
    }

    @Test fun theSignedModeReachesHomeAndItsChip() {
        assertEquals("trusted", vm(ready.copy(mode = "trusted")).state.value.mode)
        assertNull(vm(ready).state.value.mode)
        assertEquals(R.string.rd_home_mode_auto, dev.openmob.companion.ui.home.modeChipLabel("auto"))
        assertNull(dev.openmob.companion.ui.home.modeChipLabel("never")) // shown by its own "until" chip
        assertNull(dev.openmob.companion.ui.home.modeChipLabel(null))
    }

    // --- task_state (docs/phone-protocol.md §3.4): a server that sends it is read, not event text ---

    private fun task(text: String, step: String = "", steps: Int = 0, secondsAgo: Long = 0) =
        AppState.TaskState("t1", text, step, steps, now - secondsAgo * 1000)

    @Test fun structuredTaskStateDrivesWorking() {
        val v = vm(ready.copy(taskProtocol = true, task = task("Play jazz", "type_text: Typing “jazz”", 3, 14),
            events = listOf(ev("thought", "Searching Spotify…", 2))))
        val s = v.state.value
        assertEquals(HomeStatus.Working, s.status)
        assertEquals("Play jazz", s.task?.request)
        assertEquals("Typing “jazz”", s.task?.stepText)
        assertEquals(3, s.task?.step)
        assertEquals(14L, s.task?.elapsedSeconds)
        assertEquals("Searching Spotify…", s.task?.headline)
    }

    @Test fun withTaskStateEventTextNoLongerStartsATask() {
        // A "Working on:" event with no task_state: not working (the server would have said).
        val v = vm(ready.copy(taskProtocol = true, task = null, events = listOf(ev("status", "Working on: x", 3))))
        assertEquals(HomeStatus.Connected, v.state.value.status)
    }

    @Test fun anOlderServerFallsBackToEventText() {
        val v = vm(ready.copy(taskProtocol = false, events = listOf(ev("status", "Working on: Call Mom", 3))))
        assertEquals(HomeStatus.Working, v.state.value.status)
        assertEquals("Call Mom", v.state.value.task?.request)
    }

    @Test fun aThoughtFromBeforeTheTaskIsNotItsHeadline() {
        val v = vm(ready.copy(taskProtocol = true, task = task("New task", secondsAgo = 5),
            events = listOf(ev("thought", "Old task's thought", 60))))
        assertNull(v.state.value.task?.headline)
        assertNull(v.state.value.task?.stepText)
    }

    @Test fun stepLabelDropsTheToolName() {
        assertEquals("Opened Spotify", HomeMapper.stepLabel("open_app: Opened Spotify (replayed)"))
        assertEquals("Typed it: carefully", HomeMapper.stepLabel("Typed it: carefully"))
    }
}
