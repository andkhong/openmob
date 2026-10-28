package dev.openmob.companion.ui.state

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import dev.openmob.companion.AppState
import dev.openmob.companion.Approvals
import dev.openmob.companion.ConnectionService
import dev.openmob.companion.ControlIndicator
import dev.openmob.companion.FasterMode
import dev.openmob.companion.OpenMobAccessibilityService
import dev.openmob.companion.Settings
import dev.openmob.companion.gate.GateHost

/*
 * The redesign's view of the phone: one read of the same in-process state MainActivity renders from (AppState,
 * Settings, ConnectionService, Approvals, FasterMode, ControlIndicator), and the owner's actions, each calling the
 * existing code path. Nothing here decides anything: the ViewModels map a snapshot to what a screen shows.
 */

/** A pending approval, as Home shows it (the answer itself always goes through ApprovalActivity or Approvals). */
data class PendingApproval(val id: String, val question: String, val requester: String)

/** Everything the Home and Settings screens show, read at one moment. */
data class PhoneSnapshot(
    /** Paired by account (device key) or developer token: MainActivity.isPaired. */
    val paired: Boolean = false,
    val accessibilityOn: Boolean = false,
    val notificationsOn: Boolean = false,
    val batteryUnrestricted: Boolean = false,
    /** The connection service runs (connecting, connected or retrying): MainActivity's Connect/Disconnect switch. */
    val running: Boolean = false,
    val connected: Boolean = false,
    /** AppState.connection: "Connected to …", "Connecting to …", "… Retrying in 3 s…", "Disconnected". */
    val connectionText: String = "Disconnected",
    val serverHost: String = "",
    val email: String = "",
    /** Who the server says drives the phone ("" for nobody). */
    val controller: String = "",
    /** ControlIndicator: an admitted action ran recently (the phone's own knowledge). */
    val agentActive: Boolean = false,
    /** Newest first, as AppState keeps them. */
    val events: List<AppState.Event> = emptyList(),
    val approvals: List<PendingApproval> = emptyList(),
    val fasterOn: Boolean = false,
    /** FasterMode.serverScope: "session", "phone" or "off". */
    val fasterScope: String = "off",
    /** Don't ask is on until this unix time (seconds); 0: off. From the phone's own signed window. */
    val neverUntil: Long = 0,
    /** The last app the agent was in (package), for "Back to <app> to watch"; "" if none. */
    val lastAppPackage: String = "",
    /** The owner's signed standing mode (GateHost.ceilingOrNull): "ask", "plan", "auto", "trusted"; null: unknown. */
    val mode: String? = null,
    /** The server's own mode for this phone, when it differs: shown only labelled as the server's (not enforced here). */
    val serverMode: String? = null,
    /** The server sends task_state (its welcome said so): Home reads [task], not event text. */
    val taskProtocol: Boolean = false,
    /** The running task as the server reports it (task_state); null: none (or an older server). */
    val task: AppState.TaskState? = null,
    /** The phone's own task history (TaskHistory; newest first): Home's "Latest" and the ask counts. */
    val history: List<dev.openmob.companion.TaskLog.Record> = emptyList(),
    val lastAppLabel: String = "",
    /** The server's model list and this phone's pick (§3.5); null: an older server, no model chip. */
    val models: AppState.ModelState? = null,
    /** The server answers chat messages (§3.6); false: Home's thread comes from [history]. */
    val chatsSupported: Boolean = false,
    /** The chat new tasks go into; null: a new chat. */
    val currentChat: String? = null,
    val chatList: List<dev.openmob.companion.Chats.Summary> = emptyList(),
    val chatThread: dev.openmob.companion.Chats.Thread? = null,
    /** A one-off line about chats ("Stop the current task first…"), as a string resource. */
    val chatNotice: Int? = null,
    val chatListMore: Boolean = false,
    /** Only chats with this phone are listed: it isn't trusted for the account yet. */
    val chatsThisPhoneOnly: Boolean = false,
    /** The drawer's server-side title search: the query sent, and its results. */
    val chatSearchQuery: String = "",
    val chatSearchResults: List<dev.openmob.companion.Chats.Summary> = emptyList(),
    /** A page of the list or the search is on its way. */
    val chatLoading: Boolean = false,
    /** This app's versionCode and the commit it was built from (BuildConfig). */
    val appVersionCode: Int = 1,
    val appHash: String = "",
    /** The last welcome's app_update (§3.7); null: an older server, or not connected yet. */
    val update: dev.openmob.companion.UpdateInfo? = null,
    /** The highest latest the owner put off with Later or ✕. */
    val updateDismissed: Int = 0,
    /** The server closed with 4400: this app is too old for it. */
    val appTooOld: Boolean = false,
    /** Download would open something: the server named a link that is its own /download/openmob.apk. */
    val updateDownloadable: Boolean = false,
) {
    /** The four setup checks MainActivity's checklist shows (screen sharing joins only on request). */
    val checksDone: Int get() = listOf(paired, accessibilityOn, notificationsOn, batteryUnrestricted).count { it }
}

/** Reads the phone's state and tells when it changes. */
interface PhoneSource {
    fun snapshot(): PhoneSnapshot
    /** [onChange] runs on the main thread after any AppState change. Returns an unsubscribe function. */
    fun listen(onChange: () -> Unit): () -> Unit
}

/** The owner's actions from the redesign's screens: each is the call MainActivity or the Stop pill makes. */
interface OwnerControls {
    /** The task-only Stop (task_stop): the Stop pill's path. Stays connected. */
    fun stopTask()
    /** Disconnect: the connection, every permit and prompt go (ConnectionService.stop). */
    fun disconnect()
    /** Connect with the saved pairing (MainActivity.connect). */
    fun connect()
    /** A typed or spoken request. False if not connected. */
    fun sendCommand(text: String): Boolean
    /** Deny a pending approval (MainActivity's Deny). False if offline and still pending. */
    fun deny(id: String): Boolean
    /** Ask the server for a Faster mode approval ("session" or "phone"); the screen-lock prompt follows. */
    fun requestFaster(scope: String): Boolean
    /** Display only: ms until the phone would show another permission-change prompt (its 2-an-hour limit); 0 now. */
    fun fasterRetryInMs(): Long = 0
    /** The model sheet's pick (§3.5). False if not connected. */
    fun setModel(model: String, effort: String): Boolean = false
    /** The drawer: open a chat on Home, or start a new one (§3.6). False if not connected. */
    fun openChat(chatId: String): Boolean = false
    fun newChat(): Boolean = false
    fun renameChat(chatId: String, title: String): Boolean = false
    /** Paging and search (§3.6): the drawer's next page, the thread's older turns, a title search. */
    fun moreChats() {}
    fun olderTurns() {}
    fun searchChats(query: String) {}
    /** A proposal card's Save (true) or Not now (false); the thread is re-read after (§3.9). */
    fun memoryAnswer(noteId: String, save: Boolean) {}
    fun deleteChat(chatId: String): Boolean = false
    fun clearChatNotice() {}
    /** Faster mode off, here and on the server (one tap). */
    fun turnOffFaster()
    /** Download update: the browser opens the paired server's own APK (checked first). False: nothing opened. */
    fun downloadUpdate(): Boolean = false
    /** Later or ✕ on Home's update card: hidden until the server offers something newer than [latest]. */
    fun dismissUpdate(latest: Int) {}
}

/** The real source: the same reads as MainActivity.render. */
class AppPhoneSource(context: Context) : PhoneSource {
    private val app = context.applicationContext
    private val settings = Settings(app)

    override fun snapshot(): PhoneSnapshot {
        FasterMode.load(app)
        val server = settings.server
        val lastApp = runCatching { GateHost.lastAppOrEmpty() }.getOrDefault("").takeIf { it != app.packageName }.orEmpty()
        return PhoneSnapshot(
            paired = server.isNotBlank() && (settings.deviceKey.isNotBlank() || settings.token.isNotBlank()),
            accessibilityOn = OpenMobAccessibilityService.instance != null,
            notificationsOn = notificationsAllowed(),
            batteryUnrestricted = app.getSystemService(PowerManager::class.java)?.isIgnoringBatteryOptimizations(app.packageName) == true,
            running = ConnectionService.isRunning,
            connected = AppState.connected,
            connectionText = AppState.connection,
            serverHost = if (server.isBlank()) "" else Uri.parse(server).host ?: server,
            email = settings.email,
            controller = AppState.controller,
            agentActive = ControlIndicator.agentActive(),
            events = AppState.events(),
            approvals = Approvals.pending().map { PendingApproval(it.id, it.shownQuestion, it.requester) },
            fasterOn = FasterMode.isOn,
            fasterScope = FasterMode.serverScope,
            neverUntil = AppState.neverUntil,
            lastAppPackage = lastApp,
            lastAppLabel = if (lastApp.isEmpty()) "" else appLabel(lastApp),
            mode = AppState.shownMode(runCatching { GateHost.ceilingOrNull }.getOrNull(), AppState.serverMode),
            serverMode = AppState.serverModeShown(runCatching { GateHost.ceilingOrNull }.getOrNull(), AppState.serverMode),
            taskProtocol = AppState.taskProtocol,
            task = AppState.task,
            history = dev.openmob.companion.TaskHistory.init(app).records(),
            models = AppState.models,
            chatsSupported = dev.openmob.companion.Chats.supported,
            currentChat = dev.openmob.companion.Chats.current,
            chatList = dev.openmob.companion.Chats.list,
            chatThread = dev.openmob.companion.Chats.thread,
            chatNotice = dev.openmob.companion.Chats.notice,
            chatListMore = dev.openmob.companion.Chats.listMore,
            chatsThisPhoneOnly = dev.openmob.companion.Chats.thisPhoneOnly,
            chatSearchQuery = dev.openmob.companion.Chats.searchQuery,
            chatSearchResults = dev.openmob.companion.Chats.searchResults,
            chatLoading = dev.openmob.companion.Chats.loading,
            appVersionCode = dev.openmob.companion.AppUpdates.current,
            appHash = dev.openmob.companion.AppUpdates.hash,
            update = dev.openmob.companion.AppUpdates.info,
            updateDismissed = dev.openmob.companion.AppUpdates.dismissed(app),
            appTooOld = dev.openmob.companion.AppUpdates.tooOld,
            updateDownloadable = dev.openmob.companion.AppUpdates.downloadUrl(app) != null,
        )
    }

    override fun listen(onChange: () -> Unit): () -> Unit = AppState.listen(onChange)

    private fun notificationsAllowed(): Boolean {
        val permission = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            app.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        return permission && app.getSystemService(NotificationManager::class.java)?.areNotificationsEnabled() == true
    }

    private fun appLabel(pkg: String): String = runCatching {
        val pm = app.packageManager
        pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
    }.getOrDefault("")
}

/** The real actions: the calls MainActivity and the Stop pill make, unchanged. */
class AppOwnerControls(context: Context) : OwnerControls {
    private val app = context.applicationContext

    override fun stopTask() {
        ControlIndicator.init(app)
        ControlIndicator.ownerStopTask()
    }

    override fun disconnect() { ConnectionService.stop(app) }

    override fun connect() { ConnectionService.start(app) }

    override fun sendCommand(text: String): Boolean = ConnectionService.sendCommand(text)

    override fun deny(id: String): Boolean = Approvals.answer(app, id, false) || Approvals.get(id) == null

    override fun requestFaster(scope: String): Boolean = ConnectionService.requestFaster(scope)
    override fun setModel(model: String, effort: String): Boolean = ConnectionService.setModel(model, effort)
    override fun openChat(chatId: String): Boolean = ConnectionService.sendChat(dev.openmob.companion.Chats.openRequest(chatId))
    override fun newChat(): Boolean = ConnectionService.sendChat(dev.openmob.companion.Chats.newRequest())
    override fun clearChatNotice() = dev.openmob.companion.Chats.clearNotice()
    override fun renameChat(chatId: String, title: String): Boolean =
        ConnectionService.sendChat(dev.openmob.companion.Chats.renameRequest(chatId, title))
    override fun moreChats() { dev.openmob.companion.Chats.moreChats()?.let { ConnectionService.sendChat(it) } }
    override fun olderTurns() { dev.openmob.companion.Chats.olderTurns()?.let { ConnectionService.sendChat(it) } }
    override fun memoryAnswer(noteId: String, save: Boolean) {
        ConnectionService.sendMemory(if (save) dev.openmob.companion.MemoryNotes.confirmRequest(noteId) else dev.openmob.companion.MemoryNotes.dismissRequest(noteId))
        // In order on the socket: the re-read follows the answer, so the card shows its new state.
        dev.openmob.companion.Chats.current?.let { ConnectionService.sendChat(dev.openmob.companion.Chats.readRequest(it)) }
    }
    override fun searchChats(query: String) { dev.openmob.companion.Chats.search(query)?.let { ConnectionService.sendChat(it) } }
    override fun deleteChat(chatId: String): Boolean = ConnectionService.sendChat(dev.openmob.companion.Chats.deleteRequest(chatId))
    override fun fasterRetryInMs(): Long = dev.openmob.companion.Approvals.modeChangeRetryInMs()

    override fun turnOffFaster() { ConnectionService.turnOffFaster(app, "app") }

    override fun downloadUpdate(): Boolean = dev.openmob.companion.AppUpdates.openDownload(app)
    override fun dismissUpdate(latest: Int) = dev.openmob.companion.AppUpdates.dismiss(app, latest)
}
