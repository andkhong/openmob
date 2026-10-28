package dev.openmob.companion.ui.home

import dev.openmob.companion.AppState
import dev.openmob.companion.Chats
import dev.openmob.companion.TaskLog
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/** One line of Home's thread (canvas Main / HomeWorking, rev 6). */
sealed interface ThreadItem {
    val key: String

    /** "Today", "Yesterday", or a date: before the first item of each day. */
    data class Day(override val key: String, val day: LocalDate) : ThreadItem
    /** The owner's request: a right-aligned bubble. */
    data class Request(override val key: String, val text: String, val atMs: Long,
                       /** A caption over a later message of the owner's ("Correction", "Your answer"); null: the request. */
                       val caption: Int? = null) : ThreadItem
    /** The agent's reply: left-aligned text, its steps collapsed under "Done · 6 steps · 12 s". */
    data class Reply(override val key: String, val outcome: String, val text: String, val steps: Int,
                     val durationMs: Long, val stepLines: List<String>) : ThreadItem
    /** "Stopped by you" / "Denied by you": a system line (icon plus word). */
    data class System(override val key: String, val denied: Boolean, val atMs: Long,
                      /** The turn never ended (the server restarted mid-task, say): "Didn't finish". */
                      val interrupted: Boolean = false) : ThreadItem
    /** The agent's question (from the server, not checked by the phone): the blue card. */
    data class Question(override val key: String, val text: String,
                        /** A past question (answered, or its task ended): the card without "Answer in the box below". */
                        val readOnly: Boolean = false) : ThreadItem
    /** "Used your preferences: …" / "Sending to …": a small line (§3.9). */
    data class MemoryLine(override val key: String, val text: String) : ThreadItem
    /** A proposal: "Save this? …" with Save / Not now while [status] is "proposed". */
    data class MemoryCard(override val key: String, val noteId: String, val text: String, val status: String,
                          val origin: String = "") : ThreadItem
    /** The live step of the running task: always the last item while working. */
    data class Live(override val key: String, val progress: TaskProgress) : ThreadItem
}

/** The pure mapping from the server's chat (or, from an older server, the phone's own task log) to the thread. */
object ThreadMapper {
    fun map(
        thread: Chats.Thread?,
        supported: Boolean,
        history: List<TaskLog.Record>,
        task: TaskProgress?,
        taskId: String?,
        ask: HomeAsk?,
        zone: ZoneId = ZoneId.systemDefault(),
        nowMs: Long = System.currentTimeMillis(),
    ): List<ThreadItem> {
        val out = ArrayList<ThreadItem>()
        var lastDay: LocalDate? = null
        fun day(atMs: Long) {
            if (atMs <= 0) return
            val d = Instant.ofEpochMilli(atMs).atZone(zone).toLocalDate()
            if (d != lastDay) { out += ThreadItem.Day("day-$d", d); lastDay = d }
        }
        var liveShown = false
        if (supported) {
            for (t in thread?.turns.orEmpty()) {
                day(t.startedMs)
                if (t.request.isNotEmpty()) out += ThreadItem.Request("req-${t.id}", t.request, t.startedMs)
                // The owner's corrections and answers (right, captioned) and the agent's past questions, in order.
                val pending = if (t.outcome == "running" && ask is HomeAsk.Question) t.messages.indexOfLast { it.kind == "question" } else -1
                t.messages.forEachIndexed { i, m ->
                    when (m.kind) {
                        "correction" -> out += ThreadItem.Request("cor-${t.id}-$i", m.text, m.atMs, dev.openmob.companion.R.string.rd_thread_correction)
                        "answer" -> out += ThreadItem.Request("ans-${t.id}-$i", m.text, m.atMs, dev.openmob.companion.R.string.rd_thread_your_answer)
                        "question" -> if (i != pending) out += ThreadItem.Question("pq-${t.id}-$i", m.text, readOnly = true)
                    }
                }
                t.memoryLines.forEachIndexed { i, l -> out += ThreadItem.MemoryLine("ml-${t.id}-$i", l) }
                t.memoryCards.forEach { out += ThreadItem.MemoryCard("mc-${t.id}-${it.noteId}", it.noteId, it.text, it.status, it.origin) }
                if (t.outcome == "interrupted") {
                    if (t.steps > 0) out += ThreadItem.Reply("rep-${t.id}", t.outcome, "", t.steps, 0, t.stepLines)
                    out += ThreadItem.System("sys-${t.id}", false, t.startedMs, interrupted = true)
                    continue
                }
                if (t.outcome == "running" && t.id == taskId && task != null) {
                    liveMemory(out, t.id, task, t.memoryLines)
                    out += ThreadItem.Live("live-${t.id}", task); liveShown = true; continue
                }
                if (t.outcome == "running") continue // not ours to show live (another phone's chat, or not yet ended)
                val reply = if (t.stoppedByOwner || t.denied) "" else t.summary
                out += ThreadItem.Reply("rep-${t.id}", t.outcome, reply, t.steps, t.durationMs, t.stepLines)
                if (t.stoppedByOwner || t.denied) out += ThreadItem.System("sys-${t.id}", t.denied, t.finishedMs ?: t.startedMs)
            }
        } else {
            // An older server: one thread from what this phone recorded (task_state), oldest first.
            for (r in history.filter { it.kind == TaskLog.KIND_TASK }.reversed()) {
                day(r.startedAt)
                if (r.request.isNotEmpty()) out += ThreadItem.Request("req-${r.id}", r.request, r.startedAt)
                if (r.running) {
                    if (r.id == taskId && task != null) {
                        liveMemory(out, r.id, task, emptyList())
                        out += ThreadItem.Live("live-${r.id}", task); liveShown = true
                    }
                    continue
                }
                val system = (r.outcome == "stopped" && r.stoppedByOwner) || r.denied
                out += ThreadItem.Reply("rep-${r.id}", r.outcome, if (system) "" else r.reason, r.steps, r.durationMs, emptyList())
                if (system) out += ThreadItem.System("sys-${r.id}", r.denied, if (r.endedAt > 0) r.endedAt else r.startedAt)
            }
        }
        // A task the thread doesn't have yet (the server's chat refreshes when it ends).
        if (task != null && !liveShown) {
            val key = taskId ?: "current"
            task.request?.let { out += ThreadItem.Request("req-$key", it, nowMs) }
            liveMemory(out, key, task, emptyList())
            out += ThreadItem.Live("live-$key", task)
        }
        if (ask is HomeAsk.Question) out += ThreadItem.Question("q-${taskId ?: "current"}", ask.text)
        return out
    }

    /** The running task's live preferences lines (pushed as they happen: "Sending to …" comes before the send), the
     *  ones the chat already shows left out. */
    private fun liveMemory(out: MutableList<ThreadItem>, key: String, task: TaskProgress, shown: List<String>) {
        task.memoryLines.filter { it !in shown }.forEachIndexed { i, l -> out += ThreadItem.MemoryLine("lml-$key-$i", l) }
    }
}

/** Which way the header's pill reads (rev 5): connected (with how many issues), connecting, or Connect. */
enum class PillState { Connected, Connecting, Disconnected, NotSetUp }

/** A phone check that's off: Accessibility, notifications or background. */
enum class Issue { Accessibility, Notifications, Background }

fun issuesOf(accessibilityOn: Boolean, notificationsOn: Boolean, backgroundOk: Boolean): List<Issue> = buildList {
    if (!accessibilityOn) add(Issue.Accessibility)
    if (!notificationsOn) add(Issue.Notifications)
    if (!backgroundOk) add(Issue.Background)
}

/** The drawer's chat groups: Today / Yesterday / Previous 7 days / Older, newest first, filtered by title. */
enum class ChatGroup { Today, Yesterday, Week, Older }

fun groupChats(chats: List<Chats.Summary>, query: String, nowMs: Long, zone: ZoneId = ZoneId.systemDefault()):
    List<Pair<ChatGroup, List<Chats.Summary>>> {
    val today = Instant.ofEpochMilli(nowMs).atZone(zone).toLocalDate()
    val q = query.trim()
    val shown = chats.filter { q.isEmpty() || it.title.contains(q, ignoreCase = true) } // titles only (owner)
    return shown.sortedByDescending { it.updatedMs }.groupBy { c ->
        val d = Instant.ofEpochMilli(c.updatedMs).atZone(zone).toLocalDate()
        when {
            d >= today -> ChatGroup.Today
            d == today.minusDays(1) -> ChatGroup.Yesterday
            d > today.minusDays(8) -> ChatGroup.Week
            else -> ChatGroup.Older
        }
    }.toList().sortedBy { it.first.ordinal }
}

