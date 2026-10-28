package dev.openmob.companion

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * The phone's own short task history for the redesign's Activity screen and Home's "Latest" (docs/design/
 * redesign-activity.md). Built only from what the phone already receives: the server's `task_state` messages (task
 * id, request, outcome) and the phone's own approval events while a task runs. Display only: nothing decides anything
 * from it.
 *
 * Privacy: it keeps the request (as the server sent it, already redacted), the outcome, times and counts, and a short
 * failure line; never step texts, typed text or screen contents. At most [MAX] tasks and [KEEP_MS] (7 days), in
 * app-private storage; cleared on unpair and when the phone pairs with another account or server.
 *
 * It also keeps the owner's answers to Faster mode requests made in Settings ([KIND_FASTER] entries: the scope,
 * approved or denied, and when), which belong to no task. Same 7 days and the same clearing, with their own cap of
 * [MAX_FASTER] so they never push tasks out of the 50.
 */
class TaskLog(private val store: Store, private val patterns: Patterns, private val clock: () -> Long = System::currentTimeMillis) {
    interface Store {
        fun read(): String?
        fun write(json: String)
    }

    /** How the phone's own approval events read ("<who> asks: …", "Denied: …"): built from its string resources. */
    class Patterns(val asked: List<Regex>, val denied: List<Regex>, val stoppedByOwner: Set<String>)

    data class Record(
        val id: String,
        val request: String,
        val startedAt: Long,
        val endedAt: Long = 0,
        /** done | failed | stopped; "" while it runs. */
        val outcome: String = "",
        val steps: Int = 0,
        /** The phone asked the owner this many times during the task (its prompts). */
        val asks: Int = 0,
        /** The owner denied one of those. */
        val denied: Boolean = false,
        /** The owner tapped Stop on this phone during it. */
        val stoppedByOwner: Boolean = false,
        /** For a failed task: the result line, short. */
        val reason: String = "",
        /** [KIND_TASK], or [KIND_FASTER] for a Faster mode answer (request: its scope; outcome: approved | denied). */
        val kind: String = KIND_TASK,
    ) {
        val running: Boolean get() = outcome.isEmpty()
        val durationMs: Long get() = if (endedAt > 0) endedAt - startedAt else 0
    }

    private val records = ArrayList<Record>() // newest first
    private var loaded = false

    @Synchronized fun records(): List<Record> { load(); prune(); return records.toList() }

    @Synchronized fun onTaskState(state: String, id: String, text: String, steps: Int, outcome: String, summary: String) {
        if (id.isEmpty()) return
        load()
        val now = clock()
        val i = records.indexOfFirst { it.id == id }
        when (state) {
            "started", "step" -> {
                if (i < 0) {
                    records.add(0, Record(id, text.trim().take(MAX_REQUEST), now, steps = steps.coerceAtLeast(0)))
                } else {
                    val r = records[i]
                    records[i] = r.copy(steps = maxOf(r.steps, steps), request = r.request.ifEmpty { text.trim().take(MAX_REQUEST) })
                }
            }
            "ended" -> {
                val base = if (i >= 0) records[i] else Record(id, "", now)
                val o = when (outcome) { "done", "failed", "stopped" -> outcome; else -> "failed" }
                val ended = base.copy(endedAt = now, outcome = o, steps = maxOf(base.steps, steps),
                                      reason = if (o == "failed") summary.trim().take(MAX_REASON) else "")
                if (i >= 0) records[i] = ended else records.add(0, ended)
            }
            else -> return
        }
        prune()
        save()
    }

    /** One of the phone's own events: an approval asked or denied, or the owner's Stop, counts for the running task. */
    @Synchronized fun onEvent(kind: String, message: String, currentTaskId: String?) {
        if (currentTaskId.isNullOrEmpty()) return
        load()
        val i = records.indexOfFirst { it.id == currentTaskId && it.running }
        if (i < 0) return
        val r = records[i]
        records[i] = when {
            kind == "approval" && patterns.asked.any { it.matches(message) } -> r.copy(asks = r.asks + 1)
            kind == "approval" && patterns.denied.any { it.matches(message) } -> r.copy(denied = true)
            kind == "status" && message in patterns.stoppedByOwner -> r.copy(stoppedByOwner = true)
            else -> return
        }
        save()
    }

    /** The owner answered a Faster mode request on this phone (`scope`: session | phone). Display only. */
    @Synchronized fun onFasterAnswer(id: String, scope: String, approved: Boolean) {
        if (id.isEmpty()) return
        load()
        if (records.any { it.id == id && it.kind == KIND_FASTER }) return
        val now = clock()
        records.add(0, Record(id, scope, now, now, if (approved) "approved" else "denied", kind = KIND_FASTER))
        prune()
        save()
    }

    @Synchronized fun clear() { records.clear(); loaded = true; store.write("[]") }

    private fun prune() {
        val cutoff = clock() - KEEP_MS
        records.removeAll { it.startedAt < cutoff }
        // Tasks and Faster mode answers have separate caps (the newest are kept).
        cap(KIND_TASK, MAX)
        cap(KIND_FASTER, MAX_FASTER)
    }

    private fun cap(kind: String, max: Int) {
        var seen = 0
        val it = records.iterator() // newest first
        while (it.hasNext()) if (it.next().kind == kind && ++seen > max) it.remove()
    }

    private fun load() {
        if (loaded) return
        loaded = true
        val arr = runCatching { JSONArray(store.read() ?: "[]") }.getOrNull() ?: return
        for (k in 0 until arr.length()) {
            val o = arr.optJSONObject(k) ?: continue
            records.add(Record(o.optString("id"), o.optString("request"), o.optLong("started"), o.optLong("ended"),
                o.optString("outcome"), o.optInt("steps"), o.optInt("asks"), o.optBoolean("denied"),
                o.optBoolean("stopped_by_owner"), o.optString("reason"), o.optString("kind").ifEmpty { KIND_TASK }))
        }
    }

    private fun save() {
        val arr = JSONArray()
        for (r in records) arr.put(JSONObject().put("id", r.id).put("request", r.request).put("started", r.startedAt)
            .put("ended", r.endedAt).put("outcome", r.outcome).put("steps", r.steps).put("asks", r.asks)
            .put("denied", r.denied).put("stopped_by_owner", r.stoppedByOwner).put("reason", r.reason).put("kind", r.kind))
        store.write(arr.toString())
    }

    companion object {
        const val MAX = 50
        const val MAX_FASTER = 10
        const val KIND_TASK = "task"
        const val KIND_FASTER = "faster"
        const val KEEP_MS = 7 * 86_400_000L
        const val MAX_REQUEST = 300
        const val MAX_REASON = 120

        /** "%1$s asks: %2$s" → a regex for any filled-in message. */
        fun formatRegex(format: String): Regex =
            Regex(format.split(Regex("%\\d+\\\$s")).joinToString(".*") { Regex.escape(it) }, RegexOption.DOT_MATCHES_ALL)
    }
}

/** The app's one [TaskLog], in app-private SharedPreferences. */
object TaskHistory {
    @Volatile private var log: TaskLog? = null

    fun init(context: Context): TaskLog {
        log?.let { return it }
        synchronized(this) {
            log?.let { return it }
            val app = context.applicationContext
            val prefs = app.getSharedPreferences("openmob_activity", Context.MODE_PRIVATE)
            val patterns = TaskLog.Patterns(
                asked = listOf(R.string.approval_event_asked, R.string.gate_event_asked).map { TaskLog.formatRegex(app.getString(it)) },
                denied = listOf(TaskLog.formatRegex(app.getString(R.string.approval_event_denied))),
                stoppedByOwner = setOf(app.getString(R.string.indicator_stopped_event), app.getString(R.string.indicator_stopped_offline)),
            )
            return TaskLog(object : TaskLog.Store {
                override fun read() = prefs.getString("tasks", null)
                override fun write(json: String) { prefs.edit().putString("tasks", json).apply() }
            }, patterns).also { log = it }
        }
    }

    /** Null until something initialized it (the connection service, or a redesign screen). */
    fun orNull(): TaskLog? = log

    fun clear(context: Context) = init(context).clear()
}
