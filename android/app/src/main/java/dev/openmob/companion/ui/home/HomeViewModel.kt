package dev.openmob.companion.ui.home

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import dev.openmob.companion.R
import dev.openmob.companion.ui.state.AppOwnerControls
import dev.openmob.companion.ui.state.AppPhoneSource
import dev.openmob.companion.ui.state.OwnerControls
import dev.openmob.companion.ui.state.PhoneSource
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Home's state: the phone's state mapped by [HomeMapper], refreshed on every AppState change and once a second while
 * a task runs (the elapsed time, and the indicator's own hold running out). Actions call [OwnerControls] only.
 */
class HomeViewModel(
    private val source: PhoneSource,
    private val controls: OwnerControls,
    private val stopNotes: Set<String> = emptySet(),
    private val clock: () -> Long = System::currentTimeMillis,
) : ViewModel() {
    private val _state = MutableStateFlow(HomeMapper.map(source.snapshot(), clock(), stopNotes))
    val state: StateFlow<HomeUiState> = _state.asStateFlow()

    /** A one-off message for the owner (a string resource), shown once then cleared with [noticeShown]. */
    private val _notice = MutableStateFlow<Int?>(null)
    val notice: StateFlow<Int?> = _notice.asStateFlow()

    private val unsubscribe = source.listen { refresh() }
    private var ticker: Job? = null

    init { tick() }

    fun refresh() {
        _state.value = HomeMapper.map(source.snapshot(), clock(), stopNotes)
        tick()
    }

    private fun tick() {
        val live = _state.value.status == HomeStatus.Working || _state.value.status == HomeStatus.Asking
        if (!live) { ticker?.cancel(); ticker = null; return }
        if (ticker?.isActive == true) return
        ticker = viewModelScope.launch {
            while (isActive) {
                delay(1_000)
                _state.value = HomeMapper.map(source.snapshot(), clock(), stopNotes)
                if (_state.value.status != HomeStatus.Working && _state.value.status != HomeStatus.Asking) break
            }
        }
    }

    /** Stop task: the Stop pill's task_stop path; the connection stays. */
    fun stopTask() { controls.stopTask(); refresh() }

    /** "Disconnected · Reconnect": shown after the owner disconnects, until they reconnect or it times out. */
    private val _disconnectedBar = MutableStateFlow(false)
    val disconnectedBar: StateFlow<Boolean> = _disconnectedBar.asStateFlow()

    /** Disconnect (the status sheet's second tap): the connection and every permit end; a running task stops. */
    fun disconnect() { controls.disconnect(); _disconnectedBar.value = true; refresh() }

    /** Connect / Reconnect: one tap, no screen lock. It only reconnects with the saved pairing: no permit (a task
     *  grant, Don't ask, Faster mode) comes back; each needs approving again (owner, 2026-10-17). */
    fun connect() { _disconnectedBar.value = false; if (_state.value.canConnect) controls.connect(); refresh() }

    fun disconnectedBarShown() { _disconnectedBar.value = false }

    /** The drawer: a chat on Home (new tasks go into it), or a new chat. */
    fun openChat(id: String) { if (!controls.openChat(id)) _notice.value = R.string.ui_not_connected }

    fun newChat() { if (!controls.newChat()) _notice.value = R.string.ui_not_connected }

    /** The drawer's long-press menu: rename, or delete after its confirmation (no screen lock: history only). */
    fun renameChat(id: String, title: String) { if (title.isNotBlank() && !controls.renameChat(id, title)) _notice.value = R.string.ui_not_connected }

    fun moreChats() = controls.moreChats()
    fun olderTurns() = controls.olderTurns()
    fun searchChats(query: String) = controls.searchChats(query)
    fun memoryConfirm(id: String) = controls.memoryAnswer(id, true)
    fun memoryDismiss(id: String) = controls.memoryAnswer(id, false)

    fun deleteChat(id: String) { if (!controls.deleteChat(id)) _notice.value = R.string.ui_not_connected }

    fun chatNoticeShown() = controls.clearChatNotice()

    /** True when it went (the field clears); otherwise a "not connected" notice. */
    fun send(text: String): Boolean {
        val t = text.trim()
        if (t.isEmpty()) return false
        val sent = controls.sendCommand(t)
        if (!sent) _notice.value = R.string.ui_not_connected
        return sent
    }

    /** The model sheet's pick, sent to the server (it checks it against its own list). */
    fun setModel(model: String, effort: String) {
        if (!controls.setModel(model, effort)) _notice.value = R.string.ui_not_connected
    }

    /** Yes / No to the agent's question: sent as a request, as the current screen does. */
    fun answerQuestion(yes: Boolean) { send(if (yes) "yes" else "no") }

    fun deny(id: String) {
        if (!controls.deny(id)) _notice.value = R.string.approval_offline
        refresh()
    }

    /** Download update: the browser opens the paired server's own APK; anything else is refused (and logged). */
    fun downloadUpdate() { if (!controls.downloadUpdate()) _notice.value = R.string.update_link_refused }

    /** Later or ✕: the card stays away until the server offers a higher version. */
    fun dismissUpdate(latest: Int) { controls.dismissUpdate(latest); refresh() }

    fun noticeShown() { _notice.value = null }

    override fun onCleared() { unsubscribe() }

    companion object {
        fun factory(context: Context): ViewModelProvider.Factory {
            val app = context.applicationContext
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T = HomeViewModel(
                    AppPhoneSource(app),
                    AppOwnerControls(app),
                    setOf(app.getString(R.string.indicator_stopped_event), app.getString(R.string.indicator_stopped_offline)),
                ) as T
            }
        }
    }
}
