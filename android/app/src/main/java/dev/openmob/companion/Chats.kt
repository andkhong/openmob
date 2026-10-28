package dev.openmob.companion

import org.json.JSONObject

/**
 * The account's chats as the server sends them (docs/phone-protocol.md §3.6): the drawer's list and the thread Home
 * shows. In memory for this app session only; nothing here is written to storage (the Activity log is TaskHistory).
 * Display only: nothing decides anything from it.
 */
object Chats {
    data class Summary(val id: String, val title: String, val updatedMs: Long, val origin: String, val thisPhone: Boolean)

    data class Turn(
        val id: String, val request: String, val startedMs: Long, val finishedMs: Long?, val outcome: String,
        val summary: String, val steps: Int, val stepLines: List<String>, val asks: Int, val denied: Boolean,
        val stoppedByOwner: Boolean, val question: String,
        /** The owner's corrections and answers, and the agent's past questions, in order (§3.6). */
        val messages: List<Message> = emptyList(),
        /** "Used your preferences: …" / "Sending to …" lines, and proposal cards (§3.9); empty without memory. */
        val memoryLines: List<String> = emptyList(),
        val memoryCards: List<MemoryCard> = emptyList(),
    ) {
        val durationMs: Long get() = finishedMs?.let { (it - startedMs).coerceAtLeast(0) } ?: 0
    }

    /** A proposal: [text] is the server's line ("Save this? …", or a placeholder); Save / Not now only while [status]
     *  is "proposed" (else "active": saved; "gone": deleted, answered, or this phone isn't trusted). */
    data class MemoryCard(val noteId: String, val text: String, val status: String, val origin: String = "")

    /** kind: correction | answer | question. */
    data class Message(val kind: String, val text: String, val atMs: Long)

    data class Thread(val chatId: String, val title: String, val updatedMs: Long, val thisPhone: Boolean,
                      val turns: List<Turn>, val first: Int, val more: Boolean)

    /** Reopen the last chat only if it was used in the last 30 minutes (owner, 2026-10-17); else a new chat. */
    const val REOPEN_MS = 30 * 60_000L

    fun shouldStartNew(lastUsedMs: Long?, nowMs: Long): Boolean = lastUsedMs == null || nowMs - lastUsedMs > REOPEN_MS

    /** The server answers chat messages (its welcome said so). */
    @Volatile var supported: Boolean = false
        private set
    /** The chat new tasks go into (null: a new chat, made with the next task). */
    @Volatile var current: String? = null
        private set
    @Volatile var list: List<Summary> = emptyList()
        private set
    @Volatile var listMore: Boolean = false
        private set
    /** The server lists only chats with this phone: it isn't trusted for the account yet (§3.6, review 3 K3-M3). */
    @Volatile var thisPhoneOnly: Boolean = false
        private set
    /** The drawer's title search over all of this account's chats (server side, §3.6): its query and results. */
    @Volatile var searchQuery: String = ""
        private set
    @Volatile var searchResults: List<Summary> = emptyList()
        private set
    @Volatile var searchMore: Boolean = false
        private set
    /** A page was asked for and hasn't come yet (the list, the search, or the thread's older turns). */
    @Volatile var loading: Boolean = false
        private set
    @Volatile var threadLoading: Boolean = false
        private set
    /** The thread Home shows (the current chat, or another phone's chat opened read only). */
    @Volatile var thread: Thread? = null
        private set
    /** A one-off line for Home ("Stop the current task first…"), as a string resource; cleared when shown. */
    @Volatile var notice: Int? = null
        private set
    private var reopenChecked = false

    fun clearNotice() { notice = null; AppState.notifyListeners() }

    fun reset() {
        supported = false; current = null; list = emptyList(); listMore = false; thread = null; thisPhoneOnly = false
        searchQuery = ""; searchResults = emptyList(); searchMore = false; loading = false; threadLoading = false
        AppState.notifyListeners()
    }

    // --- from the server ------------------------------------------------------------------------------------------

    /** `welcome`: returns the messages to send now (the list, the current chat's turns). */
    fun onWelcome(json: JSONObject): List<JSONObject> {
        supported = json.optBoolean("chats", false)
        if (!supported) { current = null; list = emptyList(); thread = null; AppState.notifyListeners(); return emptyList() }
        current = if (json.isNull("chat")) null else json.optString("chat").takeIf { it.isNotEmpty() }
        // A thread from before (another chat, or none now) is stale: clear it; the right one is read below.
        if (thread?.chatId != current) thread = null
        loading = true
        AppState.notifyListeners()
        return buildList {
            add(listRequest())
            current?.let { add(readRequest(it)) }
        }
    }

    /** `chats`: the list page. On the first list after the app started, the 30-minute reopen rule may ask for a
     *  new chat (returned as the message to send). */
    fun onChats(json: JSONObject, nowMs: Long = System.currentTimeMillis()): JSONObject? {
        loading = false
        // Not answered (`rate_limited`, `bad_request`: review 3 S3-L1/L2): keep what is shown.
        if (json.has("error")) { notice = errorNotice(json.optString("error")); AppState.notifyListeners(); return null }
        val page = parseList(json)
        val q = json.optString("q")
        if (q.isNotEmpty()) {
            // A search answer: kept apart from the list; an answer to an older query is dropped.
            if (q == searchQuery) {
                searchResults = if (json.optInt("offset", 0) == 0) page else (searchResults + page).distinctBy { it.id }
                searchMore = json.optBoolean("more", false)
            }
            AppState.notifyListeners()
            return null
        }
        list = if (json.optInt("offset", 0) == 0) page else (list + page).distinctBy { it.id }
        listMore = json.optBoolean("more", false)
        thisPhoneOnly = json.optBoolean("this_phone_only", false)
        if (json.has("current")) current = if (json.isNull("current")) null else json.optString("current").takeIf { it.isNotEmpty() }
        AppState.notifyListeners()
        if (!reopenChecked) {
            reopenChecked = true
            val cur = current ?: return null
            if (shouldStartNew(list.firstOrNull { it.id == cur }?.updatedMs, nowMs)) return newRequest()
        }
        return null
    }

    /** `chat`: a page of a chat's turns. */
    fun onChat(json: JSONObject) {
        threadLoading = false
        if (json.has("error")) {
            if (json.optString("error") in setOf("rate_limited", "bad_request")) notice = R.string.rd_chat_try_again // nothing dropped
            else if (thread?.chatId == json.optString("chat_id")) thread = null
            AppState.notifyListeners(); return
        }
        val page = parseThread(json) ?: return
        val old = thread
        thread = if (old != null && old.chatId == page.chatId && page.first + page.turns.size <= old.first) {
            page.copy(turns = page.turns + old.turns) // an older page, above what is shown
        } else page
        AppState.notifyListeners()
    }

    /** `chat_opened`: returns the message to send next (the opened chat's turns), if any. */
    fun onOpened(json: JSONObject): JSONObject? {
        val id = json.optString("chat_id").takeIf { it.isNotEmpty() && it != "null" }
        if (json.optBoolean("ok")) {
            current = id
            thread = null
            AppState.notifyListeners()
            return id?.let { readRequest(it) }
        }
        notice = when (json.optString("error")) {
            "busy" -> R.string.rd_chat_busy
            "other_phone" -> R.string.rd_chat_other_phone
            "rate_limited", "bad_request" -> R.string.rd_chat_try_again
            else -> R.string.rd_chat_unknown
        }
        // Gone on the server (deleted on the web, say): drop the stale row and reload the list.
        if (json.optString("error") == "unknown" && id != null) { forget(id); return listRequest() }
        AppState.notifyListeners()
        // Another phone's chat: read it here, but new tasks keep going into the current chat.
        return if (json.optString("error") == "other_phone" && id != null) readRequest(id) else null
    }

    /** `chat_renamed` (this phone's own, or pushed from another of the account's phones). */
    fun onRenamed(json: JSONObject): JSONObject? {
        val id = json.optString("chat_id")
        if (!json.optBoolean("ok")) {
            notice = errorNotice(json.optString("error"))
            if (json.optString("error") == "unknown" && id.isNotEmpty()) { forget(id); return listRequest() }
            AppState.notifyListeners(); return null
        }
        val title = json.optString("title").take(120)
        list = list.map { if (it.id == id) it.copy(title = title) else it }
        thread?.let { if (it.chatId == id) thread = it.copy(title = title) }
        AppState.notifyListeners()
        return null
    }

    /** `chat_deleted`: gone from the list; if Home showed it, Home is a new chat. Returns a message to send, if any. */
    fun onDeleted(json: JSONObject): JSONObject? {
        val id = json.optString("chat_id")
        // "unknown": it was already gone on the server (deleted on the web, say), which is what was asked: drop the
        // stale row quietly and reload the list in case others are stale too.
        if (!json.optBoolean("ok") && json.optString("error") == "unknown" && id.isNotEmpty()) { forget(id); return listRequest() }
        if (!json.optBoolean("ok")) { notice = errorNotice(json.optString("error")); AppState.notifyListeners(); return null }
        forget(id)
        return null
    }

    /** A chat that no longer exists: out of the list, and off Home if Home showed it. */
    private fun forget(id: String) {
        list = list.filter { it.id != id }
        if (current == id) current = null
        if (thread?.chatId == id) thread = null
        AppState.notifyListeners()
    }

    private fun errorNotice(error: String): Int = when (error) {
        "busy" -> R.string.rd_chat_busy
        "bad_title" -> R.string.rd_chat_bad_title
        "rate_limited", "bad_request" -> R.string.rd_chat_try_again
        else -> R.string.rd_chat_unknown
    }

    /** `task_state`: a task started in [chat] (it may be a chat the server just made). Returns messages to send. */
    fun onTaskStarted(chat: String?): List<JSONObject> {
        if (!supported || chat.isNullOrEmpty()) return emptyList()
        // Already the current chat, and Home shows it: nothing to do. Showing another phone's chat (read only): back to
        // the current chat's thread, where the task runs.
        if (chat == current && thread?.chatId == chat) return emptyList()
        val wasCurrent = chat == current
        current = chat
        if (thread?.chatId != chat) thread = null
        AppState.notifyListeners()
        return if (wasCurrent) listOf(readRequest(chat)) else listOf(readRequest(chat), listRequest())
    }

    // --- paging and search (the drawer's end, the thread's top, the search field) ------------------------------------

    /** The drawer reached its end: the next page, if there is one and none is on its way. */
    fun moreChats(): JSONObject? {
        if (!supported || loading) return null
        return if (searchQuery.isNotEmpty()) {
            if (!searchMore) null else { loading = true; AppState.notifyListeners(); listRequest(searchResults.size, searchQuery) }
        } else {
            if (!listMore) null else { loading = true; AppState.notifyListeners(); listRequest(list.size) }
        }
    }

    /** The thread was scrolled to its top: the older turns, if there are some and none are on their way. */
    fun olderTurns(): JSONObject? {
        val t = thread ?: return null
        if (!supported || !t.more || threadLoading) return null
        threadLoading = true
        AppState.notifyListeners()
        return readRequest(t.chatId, before = t.first)
    }

    /** The search field's text (already debounced): a query to send, or null for the normal list (empty). */
    fun search(query: String): JSONObject? {
        val q = query.trim().take(100)
        searchQuery = q
        searchResults = emptyList(); searchMore = false
        if (q.isEmpty() || !supported) { loading = false; AppState.notifyListeners(); return null }
        loading = true
        AppState.notifyListeners()
        return listRequest(0, q)
    }

    /** A task ended: refresh the thread and the list (new title, new time). */
    fun onTaskEnded(): List<JSONObject> = if (!supported) emptyList() else listOfNotNull(current?.let { readRequest(it) }, listRequest())

    // --- to the server ----------------------------------------------------------------------------------------------

    fun listRequest(offset: Int = 0, q: String = ""): JSONObject = JSONObject().put("type", "chats_list").put("offset", offset)
        .put("limit", 50).apply { if (q.isNotEmpty()) put("q", q) }
    fun readRequest(chatId: String, before: Int? = null): JSONObject =
        JSONObject().put("type", "chat_read").put("chat_id", chatId).apply { if (before != null) put("before", before) }
    fun openRequest(chatId: String): JSONObject = JSONObject().put("type", "chat_open").put("chat_id", chatId)
    fun newRequest(): JSONObject = JSONObject().put("type", "chat_new")
    fun renameRequest(chatId: String, title: String): JSONObject =
        JSONObject().put("type", "chat_rename").put("chat_id", chatId).put("title", title.trim().take(120))
    fun deleteRequest(chatId: String): JSONObject = JSONObject().put("type", "chat_delete").put("chat_id", chatId)

    // --- parsing (pure) -------------------------------------------------------------------------------------------

    fun parseList(json: JSONObject): List<Summary> {
        val arr = json.optJSONArray("chats") ?: return emptyList()
        return (0 until arr.length()).mapNotNull { i ->
            val o = arr.optJSONObject(i) ?: return@mapNotNull null
            val id = o.optString("id").takeIf { it.isNotEmpty() } ?: return@mapNotNull null
            Summary(id, o.optString("title").take(120), (o.optDouble("updated", 0.0) * 1000).toLong(),
                    o.optString("origin").ifEmpty { "phone" }, o.optBoolean("this_phone", true))
        }
    }

    fun parseThread(json: JSONObject): Thread? {
        val id = json.optString("chat_id").takeIf { it.isNotEmpty() } ?: return null
        val arr = json.optJSONArray("turns")
        val turns = (0 until (arr?.length() ?: 0)).mapNotNull { i ->
            val o = arr!!.optJSONObject(i) ?: return@mapNotNull null
            val lines = o.optJSONArray("step_lines")
            Turn(
                id = o.optString("id"), request = o.optString("request").take(600),
                startedMs = (o.optDouble("started", 0.0) * 1000).toLong(),
                finishedMs = if (o.isNull("finished") || !o.has("finished")) null else (o.optDouble("finished") * 1000).toLong(),
                outcome = o.optString("outcome").ifEmpty { "running" }, summary = o.optString("summary").take(600),
                steps = o.optInt("steps"), stepLines = (0 until (lines?.length() ?: 0)).map { lines!!.optString(it).take(200) }.take(40),
                asks = o.optInt("asks"), denied = o.optBoolean("denied"), stoppedByOwner = o.optBoolean("stopped_by_owner"),
                question = o.optString("question").take(600),
                messages = o.optJSONArray("messages")?.let { m ->
                    (0 until m.length()).mapNotNull { j ->
                        val x = m.optJSONObject(j) ?: return@mapNotNull null
                        x.optString("kind").takeIf { it in setOf("correction", "answer", "question") }?.let { k ->
                            Message(k, x.optString("text").take(600), (x.optDouble("time", 0.0) * 1000).toLong())
                        }
                    }.take(30)
                }.orEmpty(),
                memoryLines = o.optJSONArray("memory")?.let { m -> (0 until m.length()).map { m.optString(it).take(600) }.take(30) }.orEmpty(),
                memoryCards = o.optJSONArray("memory_cards")?.let { m ->
                    (0 until m.length()).mapNotNull { j ->
                        val x = m.optJSONObject(j) ?: return@mapNotNull null
                        val id = x.optString("note_id").takeIf { it.isNotEmpty() } ?: return@mapNotNull null
                        MemoryCard(id, x.optString("text").take(600), x.optString("status").ifEmpty { "gone" },
                            x.optString("origin").take(200))
                    }.take(30)
                }.orEmpty(),
            )
        }
        return Thread(id, json.optString("title").take(120), (json.optDouble("updated", 0.0) * 1000).toLong(),
                      json.optBoolean("this_phone", true), turns, json.optInt("first", 0), json.optBoolean("more", false))
    }

    /** Tests: set the state directly. */
    internal fun setForTest(supported: Boolean, current: String?, list: List<Summary>, thread: Thread?) {
        this.supported = supported; this.current = current; this.list = list; this.thread = thread; reopenChecked = false
    }
}
