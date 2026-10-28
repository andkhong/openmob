package dev.openmob.companion.ui.setup

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import dev.openmob.companion.R
import dev.openmob.companion.ServerPolicy
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * The redesign's setup and typed-code pairing (docs/design/redesign-setup.md). The steps are the existing ones
 * (PairingFlow, shared with MainActivity): the screen lock must be set up before anything is checked; one screen-lock
 * confirmation names the account and server; the claim saves the pairing only once it succeeded. QR and link pairing
 * are not here: they stay on MainActivity, unchanged.
 */
class SetupViewModel(
    private val backend: SetupBackend,
    private val io: CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {
    private val _state = MutableStateFlow(SetupUiState(phone = backend.phone(), server = backend.defaultServer()))
    val state: StateFlow<SetupUiState> = _state.asStateFlow()
    private val unsubscribe = backend.listen { refresh() }

    fun refresh() { _state.value = _state.value.copy(phone = backend.phone()) }

    private fun set(f: SetupUiState.() -> SetupUiState) { _state.value = _state.value.f() }

    // ---------------------------------------------------------------- typed code

    fun setCode(text: String) = set { copy(code = text.take(16), codeError = null) }

    /** More options › Your own server: https only, plain http only to this phone or the local network (ServerPolicy). */
    fun setServer(text: String) = set { copy(serverInput = text.take(200), serverError = null) }

    /** The code entry's Continue: a local shape check, the screen lock check, then /api/pair/check. */
    fun submitCode(fromMore: Boolean = false) {
        val s = _state.value
        if (s.busy) return
        var target = s.server
        if (fromMore) {
            val typed = s.serverInput.trim().trimEnd('/')
            if (!ServerPolicy.isAllowed(typed)) return set { copy(serverError = R.string.ui_invalid_server) }
            target = typed
        }
        val code = TypedCode.normalize(s.code)
            ?: return set { copy(codeError = SetupError.Local(R.string.rd_setup_code_shape)) }
        // Checked first, so nobody gets as far as the prompt only to be refused afterwards (MainActivity's order).
        if (!backend.screenLockReady()) return set { copy(codeError = SetupError.Local(R.string.ui_need_screen_lock)) }
        set { copy(busy = true, codeError = null, server = target) }
        viewModelScope.launch {
            val result = withContext(io) { runCatching { backend.check(target, code) } }
            result.onSuccess { email ->
                val p = backend.phone()
                // A phone pairs with one account at a time: already paired elsewhere, unpair first (SetupPairReplace).
                val replace = p.paired && (p.server != target || p.email != email)
                set { copy(busy = false, checked = Checked(target, code, email), next = if (replace) SetupNext.Replace else SetupNext.Confirm) }
            }.onFailure { e ->
                set { copy(busy = false, codeError = SetupError.Shown(backend.errorText(e))) }
            }
        }
    }

    // ---------------------------------------------------------------- sign-in fallback and developer token

    /** "Sign in on this phone": sign in, make a code, sign out (PairingFlow.signInForCode), then the same confirm as a
     *  typed code. The screen lock must be set up first, as before. */
    fun signIn(server: String, email: String, password: String, invite: String, create: Boolean) {
        if (_state.value.busy) return
        val target = server.trim().trimEnd('/')
        when {
            !ServerPolicy.isAllowed(target) -> return set { copy(formError = SetupError.Local(R.string.ui_invalid_server)) }
            email.isBlank() || password.isEmpty() -> return set { copy(formError = SetupError.Local(R.string.ui_signin_missing)) }
            create && invite.isBlank() -> return set { copy(formError = SetupError.Local(R.string.ui_invite_missing)) }
            !backend.screenLockReady() -> return set { copy(formError = SetupError.Local(R.string.ui_need_screen_lock)) }
        }
        set { copy(busy = true, formError = null) }
        viewModelScope.launch {
            val result = withContext(io) { runCatching { backend.signInForCode(target, email.trim(), password, create, invite.trim()) } }
            result.onSuccess { (code, account) ->
                val p = backend.phone()
                val replace = p.paired && (p.server != target || p.email != account)
                set { copy(busy = false, server = target, checked = Checked(target, code, account),
                           next = if (replace) SetupNext.Replace else SetupNext.Confirm) }
            }.onFailure { e -> set { copy(busy = false, formError = SetupError.Shown(backend.errorText(e))) } }
        }
    }

    /** Developer token: the address and token are checked, then "Connect to <host>?" (the screen shows it). */
    fun submitToken(server: String, token: String) {
        val target = server.trim().trimEnd('/')
        when {
            !ServerPolicy.isAllowed(target) -> return set { copy(formError = SetupError.Local(R.string.ui_invalid_server)) }
            token.isBlank() -> return set { copy(formError = SetupError.Local(R.string.ui_missing_token)) }
        }
        set { copy(formError = null, tokenPending = target to token.trim()) }
    }

    fun cancelToken() = set { copy(tokenPending = null, notice = R.string.ui_pair_cancelled) }

    /** "Connect": replacing an existing pairing needs the screen lock (as before); a fresh one goes straight on. */
    fun confirmToken() {
        val (server, token) = _state.value.tokenPending ?: return
        if (backend.phone().paired) {
            if (!backend.screenLockReady()) return set { copy(tokenPending = null, formError = SetupError.Local(R.string.ui_need_screen_lock)) }
            return set { copy(lock = LockRequest.Token) }
        }
        saveToken(server, token)
    }

    private fun saveToken(server: String, token: String) {
        backend.saveToken(server, token, backend.phone().running)
        val p = backend.phone()
        set { copy(tokenPending = null, phone = p, notice = R.string.ui_paired_token,
                   next = if (p.accessibilityOn) SetupNext.Ready else SetupNext.Consent) }
    }

    fun noticeShown() = set { copy(notice = null) }

    fun notificationsAsked() = set { copy(notificationsAsked = true) }

    // ---------------------------------------------------------------- connection

    fun setSmoothLiveView(on: Boolean) { backend.setSmoothLiveView(on); refresh() }
    fun connect() { backend.connect(); refresh() }
    fun disconnect() { backend.disconnect(); refresh() }
    /** Unpair (no screen lock: it only removes access), after the screen's confirm dialog. */
    fun unpairNow() { backend.unpair(); set { copy(phone = backend.phone(), notice = R.string.ui_unpaired) } }

    // ---------------------------------------------------------------- confirm, replace, claim

    /** "Pair with this account": the screen lock (PairingFlow.confirmPrompt), shown by the screen. */
    fun confirm() {
        if (_state.value.checked == null || _state.value.busy) return
        if (!backend.screenLockReady()) return set { copy(confirmError = SetupError.Local(R.string.ui_need_screen_lock)) }
        set { copy(lock = LockRequest.Pair, confirmError = null) }
    }

    /** SetupPairReplace's "Unpair with screen lock". */
    fun unpairForReplace() {
        if (_state.value.checked == null) return
        if (!backend.screenLockReady()) return set { copy(confirmError = SetupError.Local(R.string.ui_need_screen_lock)) }
        set { copy(lock = LockRequest.Unpair, confirmError = null) }
    }

    /** The screen showed the prompt it asked for (so it isn't shown twice). */
    fun lockShown() = set { copy(lock = null) }

    /** The owner passed the screen lock for [request]. */
    fun lockPassed(request: LockRequest) {
        if (request == LockRequest.Token) {
            val (server, token) = _state.value.tokenPending ?: return
            return saveToken(server, token)
        }
        val c = _state.value.checked ?: return
        when (request) {
            LockRequest.Token -> Unit
            LockRequest.Unpair -> {
                backend.unpair()
                set { copy(phone = backend.phone(), next = SetupNext.Confirm) }
            }
            LockRequest.Pair -> {
                val wasRunning = backend.phone().running
                set { copy(busy = true) }
                viewModelScope.launch {
                    val result = withContext(io) { runCatching { backend.claim(c.server, c.code, c.email) } }
                    result.onSuccess {
                        backend.afterPaired(c.server, c.email, wasRunning)
                        val p = backend.phone()
                        set { copy(busy = false, phone = p, paired = c.email, checked = null, code = "",
                                   next = if (p.accessibilityOn) SetupNext.Ready else SetupNext.Consent) }
                    }.onFailure { e ->
                        // The existing pairing is untouched (nothing is saved before the claim succeeds).
                        set { copy(busy = false, confirmError = SetupError.Shown(backend.errorText(e))) }
                    }
                }
            }
        }
    }

    /** The prompt ended without a yes: cancelled by the owner, or an error. Nothing changes. */
    fun lockFailed(cancelled: Boolean, message: String?) = set {
        copy(confirmError = if (cancelled || message.isNullOrBlank()) SetupError.Local(R.string.ui_pair_cancelled)
                            else SetupError.Shown(message))
    }

    /** "This isn't me" / "Keep current pairing": back to the code (it stays unused; the owner can cancel it). */
    fun notMe() = set { copy(checked = null, confirmError = null, next = SetupNext.Code) }

    /** The screen moved to [next]. */
    fun navigated() = set { copy(next = null) }

    override fun onCleared() { unsubscribe() }

    companion object {
        fun factory(context: Context): ViewModelProvider.Factory {
            val app = context.applicationContext
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T = SetupViewModel(AppSetupBackend(app)) as T
            }
        }
    }
}
