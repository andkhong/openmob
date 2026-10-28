package dev.openmob.companion.ui.home

import dev.openmob.companion.AppState
import dev.openmob.companion.ui.state.PendingApproval
import dev.openmob.companion.ui.state.PhoneSnapshot

/** Which Home the owner sees. */
enum class HomeStatus { NotSetUp, Disconnected, Connecting, Connected, Working, Asking }

/** The running task, as Home shows it: the request, the agent's latest note and the current step only (owner
 *  decision 2026-10-17: no list of steps). */
data class TaskProgress(
    /** What was asked ("Play some relaxed jazz"), from the server's "Working on: …"; null for a drive session. */
    val request: String?,
    /** The agent's latest thought, as the headline; null before the first one. */
    val headline: String?,
    /** Actions so far (1-based for the current one); 0 before the first. */
    val step: Int,
    /** The current step, as the phone heard it ("Typing “jazz”"); null before the first. */
    val stepText: String?,
    /** Who drives the phone, when the server says ("Claude"); "" for a request from this phone or the dashboard. */
    val controller: String,
    /** Seconds since the task started on this phone (null: unknown, e.g. a drive session's start wasn't seen). */
    val elapsedSeconds: Long?,
    /** How often the phone asked the owner during this task (from the task history); null: unknown. */
    val asks: Int? = null,
    /** This task's preferences lines, oldest first ("Sending to …", "Used your preferences: …"), as the server pushed
     *  them live (rendered for this phone): shown before the send, not only when the chat is read at the end. */
    val memoryLines: List<String> = emptyList(),
)

/** What the phone is asking the owner. Amber, a polite live region. */
sealed interface HomeAsk {
    /** An approval prompt (a gatekeeper prompt, or a permission change such as Faster mode): answered on the
     *  review screen behind the screen lock, or denied here. [more]: how many others wait behind it. */
    data class Approval(val approval: PendingApproval, val more: Int) : HomeAsk
    /** The agent asked a question in words ("question" event): answered yes or no, as the current screen does. */
    data class Question(val text: String) : HomeAsk
}

/** The newest finished task, for "Latest". */
data class LatestTask(val request: String?, val summary: String, val succeeded: Boolean, val minutesAgo: Long,
                      /** How often it asked the owner (task history); null: unknown (an older server). */
                      val asks: Int? = null,
                      /** Stopped rather than failed (Activity's wording): 1 by the owner, 2 otherwise, 0 not stopped. */
                      val stopped: Int = 0)

data class HomeUiState(
    val status: HomeStatus = HomeStatus.NotSetUp,
    val connectionText: String = "",
    val serverHost: String = "",
    val email: String = "",
    val paired: Boolean = false,
    val accessibilityOn: Boolean = false,
    val checksDone: Int = 0,
    val checksTotal: Int = 4,
    /** Connect is possible (paired, not running). */
    val canConnect: Boolean = false,
    /** The ask field works (connected). */
    val canAsk: Boolean = false,
    val fasterOn: Boolean = false,
    val neverUntil: Long = 0,
    /** The signed standing mode (the most this phone allows), or null when unknown. */
    val mode: String? = null,
    /** The server's mode when it differs, labelled as the server's. */
    val serverMode: String? = null,
    val task: TaskProgress? = null,
    val ask: HomeAsk? = null,
    val latest: LatestTask? = null,
    val backToAppPackage: String = "",
    val backToAppLabel: String = "",
    /** The server's model list and this phone's pick (§3.5); null: no model chip. */
    val models: AppState.ModelState? = null,
    // --- rev 6: Home is the current chat's thread --------------------------------------------------------------
    val notificationsOn: Boolean = true,
    val backgroundOk: Boolean = true,
    /** The thread, oldest first; the live step last while working. */
    val thread: List<ThreadItem> = emptyList(),
    val chatTitle: String = "",
    val chatsSupported: Boolean = false,
    val currentChat: String? = null,
    val chatList: List<dev.openmob.companion.Chats.Summary> = emptyList(),
    /** The thread shown is another phone's chat: read only here. */
    val readOnlyChat: Boolean = false,
    val chatListMore: Boolean = false,
    /** Only chats with this phone are listed (an untrusted phone): the drawer says so. */
    val chatsThisPhoneOnly: Boolean = false,
    val chatSearchQuery: String = "",
    val chatSearchResults: List<dev.openmob.companion.Chats.Summary> = emptyList(),
    val chatLoading: Boolean = false,
    /** The thread has older turns on the server (paged in when it is scrolled to the top). */
    val threadMore: Boolean = false,
    val chatNotice: Int? = null,
    // --- app updates (§3.7) ------------------------------------------------------------------------------------
    /** Available (Home's blue card), Required (Home's body), TooOld (after a 4400), or None. */
    val update: dev.openmob.companion.UpdateState = dev.openmob.companion.UpdateState.None,
    /** This app's versionCode, for "You have 47" and the table. */
    val currentVersion: Int = 1,
    /** Download would open the paired server's own APK; false: no button (the server has none to give). */
    val updateDownloadable: Boolean = false,
) {
    /** Below the server's minimum while connected: the pill reads "Update needed" and the composer is off. */
    val updateRequired: Boolean get() = update is dev.openmob.companion.UpdateState.Required &&
        status in setOf(HomeStatus.Connected, HomeStatus.Working, HomeStatus.Asking)
    val issues: List<Issue> get() = issuesOf(accessibilityOn, notificationsOn, backgroundOk)
    val pill: PillState get() = when (status) {
        HomeStatus.NotSetUp -> PillState.NotSetUp
        HomeStatus.Disconnected -> PillState.Disconnected
        HomeStatus.Connecting -> PillState.Connecting
        else -> PillState.Connected
    }
}

/**
 * The pure mapping from what the phone knows to what Home shows. Events come newest first and carry no task id,
 * so the task is read from the server's own markers: "Working on: …" starts one; a "result", a final "error" (the
 * runner's "… (N steps)" or "Cancelled before it started."), the owner's Stop or the controller leaving ends it.
 * The phone's own knowledge (an admitted action in the last seconds, or a controller) also counts as working.
 */
object HomeMapper {
    const val WORKING_ON = "Working on: "
    private val FINAL_ERROR = Regex("""\(\d+ steps?\)\s*$""")
    private const val CANCELLED = "Cancelled before it started."
    private val TOOL_PREFIX = Regex("""^[a-z_]+: """)
    private val REPLAYED = Regex("""\s*\(replayed\)\s*$""")

    /** [stopNotes]: the phone's own "You stopped the agent…" lines (strings), which end the task on Home at once. */
    fun map(s: PhoneSnapshot, nowMs: Long, stopNotes: Set<String> = emptySet()): HomeUiState {
        // A server that sends task_state says what runs; only an older one is read from event text (the fallback).
        val structured = s.taskProtocol
        val start = if (structured) null else taskStartIndex(s.events, stopNotes, s.controller)
        val ask = askFor(s)
        val open = if (structured) s.task != null else start != null
        val working = s.connected && (open || s.controller.isNotEmpty() || s.agentActive)
        val status = when {
            !s.running && (!s.paired || !s.accessibilityOn) -> HomeStatus.NotSetUp
            !s.running -> HomeStatus.Disconnected
            !s.connected -> HomeStatus.Connecting
            ask != null -> HomeStatus.Asking
            working -> HomeStatus.Working
            else -> HomeStatus.Connected
        }
        val update = dev.openmob.companion.UpdateLogic.state(s.appVersionCode, s.update, s.updateDismissed, s.appTooOld)
        val task = if (status == HomeStatus.Working || (status == HomeStatus.Asking && working)) {
            if (structured) structuredProgress(s, nowMs) else progress(s, start, nowMs)
        } else {
            null
        }
        return HomeUiState(
            status = status,
            connectionText = s.connectionText,
            serverHost = s.serverHost,
            email = s.email,
            paired = s.paired,
            accessibilityOn = s.accessibilityOn,
            checksDone = s.checksDone,
            canConnect = s.paired && !s.running,
            // Below the server's minimum nothing would run: the composer is off (the server refuses it too).
            canAsk = s.connected && update !is dev.openmob.companion.UpdateState.Required,
            models = s.models,
            fasterOn = s.fasterOn,
            neverUntil = if (s.neverUntil * 1000 > nowMs) s.neverUntil else 0,
            mode = s.mode,
            serverMode = s.serverMode,
            task = task,
            ask = ask,
            latest = if (task == null) latestFromHistory(s, nowMs) ?: latest(s.events, nowMs) else null,
            backToAppPackage = if (task != null && s.lastAppLabel.isNotEmpty()) s.lastAppPackage else "",
            backToAppLabel = if (task != null) s.lastAppLabel else "",
            notificationsOn = s.notificationsOn,
            backgroundOk = s.batteryUnrestricted,
            thread = if (status in setOf(HomeStatus.Connected, HomeStatus.Working, HomeStatus.Asking))
                ThreadMapper.map(s.chatThread, s.chatsSupported, s.history, task, s.task?.id, ask,
                                 nowMs = nowMs - (task?.elapsedSeconds ?: 0) * 1000) else emptyList(),
            chatTitle = s.chatThread?.title.orEmpty(),
            chatsSupported = s.chatsSupported,
            currentChat = s.currentChat,
            chatList = s.chatList,
            readOnlyChat = s.chatsSupported && s.chatThread != null && !s.chatThread.thisPhone,
            chatNotice = s.chatNotice,
            chatListMore = s.chatListMore,
            chatsThisPhoneOnly = s.chatsThisPhoneOnly,
            chatSearchQuery = s.chatSearchQuery,
            chatSearchResults = s.chatSearchResults,
            chatLoading = s.chatLoading,
            threadMore = s.chatsSupported && s.chatThread?.more == true,
            update = update,
            currentVersion = s.appVersionCode,
            updateDownloadable = s.updateDownloadable,
        )
    }

    private fun askFor(s: PhoneSnapshot): HomeAsk? {
        if (!s.running) return null // Disconnect drops every prompt (Approvals.clear)
        s.approvals.firstOrNull()?.let { return HomeAsk.Approval(it, s.approvals.size - 1) }
        // A question only while connected and while it is the newest event: the same notion as the phone's question
        // notification, its ongoing "Waiting for your answer" and the indicator's asking state (AgentQuestion.open).
        return dev.openmob.companion.AgentQuestion.open(s.connected, approvalsPending = false, s.events)?.let { HomeAsk.Question(it) }
    }

    fun isEnd(e: AppState.Event, stopNotes: Set<String>): Boolean = when (e.kind) {
        "result" -> true
        "error" -> FINAL_ERROR.containsMatchIn(e.message) || e.message.trim() == CANCELLED
        "status" -> e.message in stopNotes
        else -> false
    }

    private fun isStart(e: AppState.Event) = e.kind == "status" && e.message.startsWith(WORKING_ON)

    /** Index (newest first) of the open task's "Working on: …", or null when the newest marker is an end. */
    fun taskStartIndex(events: List<AppState.Event>, stopNotes: Set<String> = emptySet(), controller: String = ""): Int? {
        for ((i, e) in events.withIndex()) {
            if (isStart(e)) return i
            if (isEnd(e, stopNotes)) return null
            // "X stopped using your phone" after a drive session: the controller line cleared.
            if (e.kind == "controller" && controller.isEmpty()) return null
        }
        return null
    }

    /** "tap: Tapped “Search”" → "Tapped “Search”"; "(replayed)" dropped. Display only. */
    fun stepLabel(message: String): String = message.replace(TOOL_PREFIX, "").replace(REPLAYED, "").trim()

    /** From task_state: the request, the current step and its count as the server said; the headline is the newest
     *  thought since the task started (display only). */
    private fun structuredProgress(s: PhoneSnapshot, nowMs: Long): TaskProgress {
        val t = s.task
        return TaskProgress(
            request = t?.text?.takeIf { it.isNotBlank() },
            headline = t?.let { task -> s.events.firstOrNull { it.kind == "thought" && it.at >= task.at } }
                ?.message?.trim()?.lineSequence()?.firstOrNull(),
            step = t?.steps ?: 0,
            stepText = t?.step?.takeIf { it.isNotBlank() }?.let { stepLabel(it) },
            controller = s.controller,
            elapsedSeconds = t?.let { ((nowMs - it.at) / 1000).coerceAtLeast(0) },
            asks = t?.let { task -> s.history.firstOrNull { it.id == task.id }?.asks },
            memoryLines = t?.let { task -> memoryLines(s.events.filter { it.at >= task.at }) }.orEmpty(),
        )
    }

    /** The newest finished task the phone recorded (task_state): with its ask count. */
    private fun latestFromHistory(s: PhoneSnapshot, nowMs: Long): LatestTask? {
        val r = s.history.firstOrNull { !it.running && it.kind == dev.openmob.companion.TaskLog.KIND_TASK } ?: return null
        val summary = when (r.outcome) { "failed" -> r.reason; else -> "" }
        return LatestTask(r.request.ifEmpty { null }, summary, r.outcome == "done" && !r.denied,
                          ((nowMs - (if (r.endedAt > 0) r.endedAt else r.startedAt)) / 60_000).coerceAtLeast(0), r.asks,
                          stopped = if (r.outcome != "stopped" || r.denied) 0 else if (r.stoppedByOwner) 1 else 2)
    }

    private fun progress(s: PhoneSnapshot, start: Int?, nowMs: Long): TaskProgress {
        val since = if (start == null) emptyList() else s.events.subList(0, start)
        val actions = since.filter { it.kind == "action" || it.kind == "jev" }
        // A failed step ("error" mid-task) is the current step too; it isn't counted as a step done.
        val current = since.firstOrNull {
            it.kind == "action" || it.kind == "jev" || it.kind == "error" ||
                (it.kind == "status" && !it.message.startsWith(WORKING_ON))
        }
        return TaskProgress(
            request = start?.let { s.events[it].message.removePrefix(WORKING_ON).trim() },
            headline = since.firstOrNull { it.kind == "thought" }?.message?.trim()?.lineSequence()?.firstOrNull(),
            step = actions.size,
            stepText = current?.let { if (it.kind == "status") it.message.trim() else stepLabel(it.message) },
            controller = s.controller,
            elapsedSeconds = start?.let { ((nowMs - s.events[it].at) / 1000).coerceAtLeast(0) },
            memoryLines = memoryLines(since),
        )
    }

    /** The live "memory" events among [events] (newest first), oldest first; an empty one is never shown. */
    fun memoryLines(events: List<AppState.Event>): List<String> =
        events.filter { it.kind == "memory" && it.message.isNotBlank() }.map { it.message.trim() }.reversed()

    private fun latest(events: List<AppState.Event>, nowMs: Long): LatestTask? {
        val end = events.indexOfFirst { it.kind == "result" || (it.kind == "error" && isEnd(it, emptySet())) }
        if (end < 0) return null
        val e = events[end]
        val request = events.drop(end + 1).firstOrNull { isStart(it) }?.message?.removePrefix(WORKING_ON)?.trim()
        return LatestTask(request, e.message.trim(), e.kind == "result", ((nowMs - e.at) / 60_000).coerceAtLeast(0))
    }
}
