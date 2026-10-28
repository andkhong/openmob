package dev.openmob.companion

import android.content.Context
import android.os.Handler
import android.os.Looper
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList

/** In-process state shared by the connection service and the UI. Listeners run on the main thread. */
object AppState {
    /** [at]: when the phone received it (unix ms), for the redesign's elapsed time and "12 min ago". */
    data class Event(val kind: String, val message: String, val at: Long = System.currentTimeMillis())

    /** The app sent the owner to Accessibility settings: once the service is on, bring the app back
     *  (OpenMobAccessibilityService.onServiceConnected) instead of making them navigate back. */
    @Volatile var returnAfterAccessibility: Boolean = false

    @Volatile var connection: String = "Disconnected"
        private set
    @Volatile var connected: Boolean = false
        private set
    /** Someone opened this phone's live view on the dashboard while it had no screen sharing: the
     *  setup checklist then offers it (screen sharing is never asked for at setup). */
    @Volatile var liveViewRequested: Boolean = false
    /** The connection holds a screen-sharing approval right now (smooth video on the dashboard). */
    @Volatile var screenSharing: Boolean = false

    /** Who the server says is driving the phone right now (e.g. "Claude"); "" for nobody. */
    @Volatile var controller: String = ""
        private set
    /** Agents may act without asking until this unix time (seconds); 0: they ask as usual. */
    @Volatile var neverUntil: Long = 0
        private set
    /** While never is on: purchases also run without asking ("Also allow purchases"). */
    @Volatile var neverMoney: Boolean = false
        private set

    /**
     * The running task as the server reports it (`task_state`, docs/phone-protocol.md §3.4), for Home. Display only:
     * nothing decides anything from it. [at] is when this phone heard it started (unix ms).
     */
    data class TaskState(val id: String, val text: String, val step: String, val steps: Int, val at: Long)

    /** The connected server sends task_state (its welcome said so); otherwise Home reads event text. */
    @Volatile var taskProtocol: Boolean = false
        private set
    @Volatile var task: TaskState? = null
        private set

    fun setTaskProtocol(on: Boolean) { taskProtocol = on; if (!on) task = null; notifyListeners() }

    /** A task_state message: "started" / "step" set the open task, "ended" clears it (if it's that task). */
    fun onTaskState(state: String, id: String, text: String, step: String, steps: Int, now: Long = System.currentTimeMillis()) {
        if (id.isEmpty()) return
        val current = task
        task = when (state) {
            "started", "step" -> TaskState(id, text.take(300), step.take(200), steps.coerceAtLeast(0),
                                           if (current?.id == id) current.at else now)
            "ended" -> if (current?.id == id) null else current
            else -> current
        }
        notifyListeners()
    }

    /** The server's standing mode for this phone (its `permissions` push, set on the dashboard); null: unknown. Display
     *  only, labelled as the server's ([serverModeShown]): the phone enforces only its signed ceiling ([shownMode]). */
    @Volatile var serverMode: String? = null
        private set

    fun setServerMode(mode: String?) {
        serverMode = mode?.takeIf { it in MODES }
        notifyListeners()
    }

    private val MODES = listOf("ask", "plan", "auto", "trusted", "never")

    /** The mode the phone shows as its own: its signed ceiling, the most it allows agents (null: not loaded yet). Never
     *  the server's mode: a stricter server mode isn't enforced here (each call may ask for up to the ceiling), so
     *  showing it as the phone's would claim more than the gate does (review 3 P3-L1). */
    fun shownMode(ceiling: String?, @Suppress("UNUSED_PARAMETER") server: String?): String? = ceiling?.takeIf { it in MODES }

    /** The server's mode, shown labelled as the server's, when it says something the ceiling doesn't; else null. */
    fun serverModeShown(ceiling: String?, server: String?): String? =
        server?.takeIf { it in MODES && it != ceiling }

    /** The connection went (or a new one starts): nothing is known to run until the server says so again. */
    fun clearTask() { task = null; notifyListeners() }

    /** One model the server offers this phone (docs/phone-protocol.md §3.5): what the model sheet shows. */
    data class PhoneModel(val id: String, val label: String, val description: String, val speed: String,
                          val group: String, val effort: Boolean)

    /** The server's model list and this phone's current pick; null: an older server (the chip is hidden). */
    data class ModelState(val models: List<PhoneModel>, val model: String, val effort: String) {
        val current: PhoneModel? get() = models.firstOrNull { it.id == model }
    }

    @Volatile var models: ModelState? = null
        private set

    /** A `model_state` object (in `welcome` or on its own); null or unusable clears it. Display only. */
    fun setModels(json: org.json.JSONObject?) {
        models = json?.let { parseModels(it) }
        notifyListeners()
    }

    fun parseModels(json: org.json.JSONObject): ModelState? {
        val arr = json.optJSONArray("models") ?: return null
        val list = (0 until arr.length()).mapNotNull { i ->
            val o = arr.optJSONObject(i) ?: return@mapNotNull null
            val id = o.optString("id").takeIf { it.isNotEmpty() } ?: return@mapNotNull null
            PhoneModel(id, o.optString("label").ifEmpty { id }.take(40), o.optString("description").take(80),
                       o.optString("speed").ifEmpty { "medium" }, o.optString("group").ifEmpty { "main" },
                       o.optBoolean("effort", false))
        }
        if (list.isEmpty()) return null
        val effort = json.optString("effort").takeIf { it in setOf("auto", "low", "medium", "high") } ?: "auto"
        return ModelState(list, json.optString("model").ifEmpty { list.first().id }, effort)
    }

    private val events = ArrayDeque<Event>()
    private val listeners = CopyOnWriteArrayList<() -> Unit>()
    private val main = Handler(Looper.getMainLooper())

    fun events(): List<Event> = synchronized(events) { events.toList() }

    /** Unpair or Disconnect (review 5 P5-L2, §3.9): what the account's session put on Home goes now, not at the next
     *  welcome: the event feed and the open task (its steps, memory lines and proposal cards). The chats and saved
     *  preferences go with [Chats.reset] and [MemoryNotes.reset]; [endSession] does all of it. */
    fun clearSession() {
        synchronized(events) { events.clear() }
        task = null
        notifyListeners()
    }

    /** Everything this account's session showed on the phone: chats, preferences, the feed and the open task. */
    fun endSession() {
        Chats.reset()
        MemoryNotes.reset()
        clearSession()
    }

    fun setConnection(status: String, isConnected: Boolean) {
        connection = status
        connected = isConnected
        notifyListeners()
    }

    fun setController(who: String) {
        controller = who
        notifyListeners()
    }

    fun setNeverUntil(until: Long, money: Boolean = false) {
        neverUntil = until
        neverMoney = until > 0 && money
        notifyListeners()
    }

    fun addEvent(kind: String, message: String) {
        if (message.isBlank()) return // nothing to show: never an empty line in the feed or Activity
        synchronized(events) {
            events.addFirst(Event(kind, message))
            while (events.size > 100) events.removeLast()
        }
        // The running task's asks and denials, for the Activity screen (display only).
        TaskHistory.orNull()?.onEvent(kind, message, task?.id)
        notifyListeners()
    }

    fun notifyListeners() = main.post { listeners.forEach { it() } }

    /** Returns an unsubscribe function. */
    fun listen(listener: () -> Unit): () -> Unit {
        listeners.add(listener)
        return { listeners.remove(listener) }
    }
}

/**
 * Server address, credentials, and this phone's stable id. Accounts mode uses [deviceKey] (this
 * phone's own key from pairing, kept encrypted by a Keystore key: see [SecureStore]); legacy token
 * mode uses [token]. The phone never keeps a dashboard session. Empty string means "none".
 */
class Settings(context: Context) {
    private val prefs = context.getSharedPreferences("openmob", Context.MODE_PRIVATE)

    var server: String
        get() = prefs.getString("server", "") ?: ""
        set(value) = prefs.edit().putString("server", value.trim()).apply()

    /** Legacy token mode (a developer's own server): also kept encrypted. */
    var token: String
        get() = secret("token")
        set(value) = putSecret("token", value)

    /** Email of the account this phone is paired to, for display only (not a credential). */
    var email: String
        get() = prefs.getString("email", "") ?: ""
        set(value) = prefs.edit().putString("email", value.trim()).apply()

    /** Offer screen sharing when someone opens the live view, so the web dashboard shows smooth video.
     *  Turned off when the owner declines Android's prompt, so declining is remembered. */
    var smoothLiveView: Boolean
        get() = prefs.getBoolean("smooth_live_view", true)
        set(value) = prefs.edit().putBoolean("smooth_live_view", value).apply()

    /** This phone's device key, sent in the hello message. */
    var deviceKey: String
        get() = secret("device_key")
        set(value) = putSecret("device_key", value)

    /** An unpair the server didn't take yet (server, the old device key), retried on the next connection
     *  (PairingFlow.retryPendingUnpair). The key is kept encrypted, as the device key was. */
    var pendingUnpair: Pair<String, String>?
        get() {
            val server = prefs.getString("pending_unpair_server", "") ?: ""
            val key = secret("pending_unpair_key")
            return if (server.isNotBlank() && key.isNotEmpty()) server to key else null
        }
        set(value) {
            prefs.edit().putString("pending_unpair_server", value?.first.orEmpty()).commit()
            putSecret("pending_unpair_key", value?.second.orEmpty())
        }

    private companion object {
        val decrypted = java.util.concurrent.ConcurrentHashMap<String, String>()
    }

    /** Stable across reconnects and app restarts, so the server keeps this phone's session. */
    val deviceId: String
        get() = prefs.getString("device_id", null) ?: UUID.randomUUID().toString().also {
            prefs.edit().putString("device_id", it).apply()
        }

    /**
     * A dashboard session an older version of the app kept after pairing (enough to make API keys).
     * Returned once so it can be signed out on the server, and deleted from the phone.
     */
    fun takeLegacySession(): String {
        val session = prefs.getString("session", "") ?: ""
        if (prefs.contains("session")) prefs.edit().remove("session").apply()
        return session
    }

    /** Encrypted values live under "<name>_enc"; a plaintext one from an older app is moved over once. */
    private fun secret(name: String): String {
        prefs.getString("${name}_enc", null)?.let { blob ->
            // Keystore operations take milliseconds (more with StrongBox) and the screen reads this often.
            return decrypted[blob] ?: SecureStore.decrypt(blob).orEmpty().also { if (it.isNotEmpty()) decrypted[blob] = it }
        }
        val legacy = prefs.getString(name, "") ?: ""
        if (legacy.isNotEmpty()) putSecret(name, legacy)
        return legacy
    }

    private fun putSecret(name: String, value: String) {
        val v = value.trim()
        val edit = prefs.edit().remove(name)
        if (v.isEmpty()) edit.remove("${name}_enc") else edit.putString("${name}_enc", SecureStore.encrypt(v))
        edit.commit() // written before anything connects with it
    }
}
