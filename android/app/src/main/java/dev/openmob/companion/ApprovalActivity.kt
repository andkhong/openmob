package dev.openmob.companion

import androidx.activity.ComponentActivity
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.platform.ComposeView
import dev.openmob.companion.ui.approval.ApprovalScreen
import dev.openmob.companion.ui.theme.OpenMobTheme
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import android.os.Bundle
import android.os.CancellationSignal
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.view.WindowInsets
import android.view.WindowManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/**
 * Review one approval request (see [Approvals]): who is asking and what. Approving needs the
 * phone's screen lock, the same check as pairing, so the AI driving the phone can't approve its
 * own purchase or send. Denying needs nothing.
 *
 * FLAG_SECURE keeps this screen out of screenshots and the live view, so the agent can't read it.
 *
 * Kinds (docs/phone-protocol.md): a risky action, a step (ask-every-step mode), a plan (plan-first
 * mode) or a mode_change (agents would ask less on this phone). "Always allow this" (off by default)
 * also grants the offered trusted entry; for payments it asks a second time. It is signed too. A
 * mode_change that also allows purchases ("Also allow purchases" with Don't ask) asks a second time
 * as well, before the screen lock.
 */
class ApprovalActivity : ComponentActivity() {
    private companion object {
        const val APPROVERS = BiometricManager.Authenticators.BIOMETRIC_STRONG or
            BiometricManager.Authenticators.DEVICE_CREDENTIAL
    }

    private var requestId = ""
    private var shown: Approvals.Request? = null // kept after it's answered, to keep showing it
    private var unsubscribe: (() -> Unit)? = null
    private var prompt: CancellationSignal? = null

    private lateinit var alwaysBox: CheckBox
    private lateinit var approveButton: Button

    /** The screen (redesign step 6: the only approval UI): Compose draws it from [screen], and embeds the two original
     *  Android controls, Approve and "Always allow", with their own flags (docs/design/redesign-approval.md). */
    private val screen = mutableStateOf<ApprovalScreenState?>(null)
    private val status = mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        // No other app's overlay may cover part of the question while the owner answers (review L2; API 31+).
        if (android.os.Build.VERSION.SDK_INT >= 31) window.setHideOverlayWindows(true)
        requestWindowFeature(Window.FEATURE_NO_TITLE)
        buildControls()
        setContentView(buildCompose())
        open(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        open(intent)
    }

    override fun onResume() {
        super.onResume()
        unsubscribe = AppState.listen { render() }
        render()
    }

    override fun onPause() {
        unsubscribe?.invoke()
        unsubscribe = null
        super.onPause()
    }

    /** A gate prompt the system interrupted (request id, "always" ticked): shown again when the screen is back. */
    private var resumeAuth: Pair<String, Boolean>? = null

    /** When this screen last gained focus: Allow ignores taps for a moment after (B1: a tap admitted just before the
     *  prompt appeared must not land on it). */
    private var focusedAt = Long.MAX_VALUE

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        focusedAt = if (hasFocus) android.os.SystemClock.uptimeMillis() else Long.MAX_VALUE
        val (id, always) = resumeAuth ?: return
        if (!hasFocus || prompt != null) return
        resumeAuth = null
        Approvals.get(id)?.takeIf { it.gate && id == requestId }?.let { authenticate(it, always) }
    }

    override fun onDestroy() {
        prompt?.cancel()
        prompt = null
        super.onDestroy()
    }

    private fun open(intent: Intent?) {
        prompt?.cancel()
        prompt = null
        requestId = intent?.getStringExtra(Approvals.EXTRA_ID).orEmpty()
        shown = Approvals.get(requestId)
        status.value = null
        render()
    }

    private fun render() {
        Approvals.get(requestId)?.let { shown = it }
        val request = shown
        val open = Approvals.get(requestId) != null
        // The owner sees this gate prompt now: only prompts actually shown count toward the prompt limit.
        if (open && request?.gate == true && !isFinishing) dev.openmob.companion.gate.GateHost.markShown(requestId)
        // The same state for both UIs (ApprovalScreenState: this render's logic, moved there unchanged).
        // Typed on this phone, or only approved here in a task grant (then the server's wording, labelled so: P3-M1).
        val held = if (request?.gate == true) dev.openmob.companion.gate.GateHost.attestedTaskText(requestId) else null
        val st = ApprovalScreenState.of(request, open, { id, args -> getString(id, *args) }, ::appLabel,
            taskText = held?.takeIf { it.typedHere }?.text, grantTaskText = held?.takeIf { !it.typedHere }?.text)
        alwaysBox.visibility = if (st.alwaysVisible) View.VISIBLE else View.GONE
        if (request?.always != null) alwaysBox.text = st.alwaysText
        val blocker = st.blocker
        if (!open && request != null) showStatus(getString(R.string.approval_gone))
        else if (blocker != null) showStatus(blocker)
        // A phone that can't sign this approval can only deny it.
        approveButton.isEnabled = st.approveEnabled
        approveButton.alpha = if (approveButton.isEnabled) 1f else 0.45f
        // The label says what Approve needs (owner, 2026-10-17): "Allow" for a one-tap prompt, else the screen lock.
        approveButton.text = getString(if (st.gate && st.level == "tap") R.string.rd_approval_allow else R.string.rd_approval_with_lock)
        // Hidden (not just disabled) once answered or expired (UX review 2, B1). Its flags and click path are unchanged.
        approveButton.visibility = if (st.approveVisible && st.open) View.VISIBLE else View.GONE
        screen.value = st
    }

    /** Why this request can't be approved on this phone (it can still be denied), or null. */
    private fun blocker(request: Approvals.Request): String? =
        ApprovalScreenState.blocker(request) { id, args -> getString(id, *args) }

    private fun onApprove() {
        val request = Approvals.get(requestId) ?: return render()
        // Its 2 minutes are up by the phone's own clock: never approved, even in the moment before the expiry timer runs.
        if (request.expiresAt > 0 && android.os.SystemClock.uptimeMillis() >= request.expiresAt) {
            return showStatus(getString(R.string.approval_gone))
        }
        blocker(request)?.let { return showStatus(it) }
        if (request.gate && android.os.SystemClock.uptimeMillis() - focusedAt < 500) return // too soon after it appeared
        if (request.gate && request.level == "tap") return approveWithTap(request)
        // Don't ask including purchases: a second, explicit yes for the money part before the screen lock.
        if (request.allowsMoney) {
            AlertDialog.Builder(this)
                .setTitle(R.string.approval_money_confirm_title)
                .setMessage(R.string.approval_money_confirm_body)
                .setPositiveButton(R.string.approval_money_confirm_yes) { _, _ -> authenticate(request, false) }
                .setNegativeButton(R.string.approval_money_confirm_no, null)
                .show()
            return
        }
        val always = request.always
        // "Always allow" for payments needs a second, explicit yes before the screen lock.
        if (alwaysBox.isChecked && always != null && always.confirmTwice) {
            AlertDialog.Builder(this)
                .setTitle(R.string.approval_always_confirm_title)
                .setMessage(getString(R.string.approval_always_confirm_body, always.text))
                .setPositiveButton(R.string.approval_always_confirm_yes) { _, _ -> authenticate(request, true) }
                .setNegativeButton(R.string.approval_always_confirm_no) { _, _ ->
                    alwaysBox.isChecked = false
                    authenticate(request, false)
                }
                .show()
            return
        }
        authenticate(request, alwaysBox.isChecked && always != null)
    }

    /** A tap-level gate prompt (three confirmation levels): the owner's tap on Allow, in this window, signed with the
     *  tap key. No screen lock: agents can't tap OpenMob's windows (the gate refuses them, builtin:own_window), and
     *  Approve ignores touches through overlays. */
    private fun approveWithTap(request: Approvals.Request) {
        val grantAlways = alwaysBox.isChecked && request.always != null
        val message = dev.openmob.companion.gate.GateHost.approvalMessage(request.id, grantAlways)
        val signature = message?.let { TapKeys.sign(it) }
        if (message == null || signature == null || !dev.openmob.companion.gate.GateHost.approve(request.id, message, signature)) {
            showStatus(getString(if (message == null) R.string.approval_gone else R.string.approval_not_confirmed))
            return
        }
        Approvals.answerGate(this, request.id, true)
        Toast.makeText(this, R.string.approval_sent_approved, Toast.LENGTH_SHORT).show()
        finish()
    }

    private fun authenticate(request: Approvals.Request, grantAlways: Boolean) {
        val lock = getSystemService(BiometricManager::class.java)?.canAuthenticate(APPROVERS)
        if (lock != BiometricManager.BIOMETRIC_SUCCESS) {
            showStatus(getString(R.string.approval_need_lock))
            return
        }
        prompt?.cancel()
        val cancel = CancellationSignal().also { prompt = it }
        // The approval key only signs once this prompt is passed: that signature is what the server
        // trusts, so nothing else on the phone (or holding its device key) can approve.
        // Gate prompts are verified on this phone alone (GateHost), so the key is made here if the phone never got
        // one: developer-token pairing doesn't create it (only account pairing and its hello do).
        val signer = ApprovalKeys.signer() ?: if (request.gate && ApprovalKeys.publicKey() != null) ApprovalKeys.signer() else null
        if (signer == null && (request.signatureRequired || request.gate)) {
            // A gate permit is minted only from the screen-lock signature: there is no unsigned fallback (D5).
            // Without the key there is nothing the server would accept: never send an unsigned yes.
            showStatus(getString(R.string.approval_no_key))
            return
        }
        val built = BiometricPrompt.Builder(this)
            .setTitle(getString(when (request.kind) {
                "mode_change" -> R.string.approval_prompt_title_mode
                "plan" -> R.string.approval_prompt_title_plan
                else -> R.string.approval_prompt_title
            }))
            .setSubtitle(getString(R.string.approval_requester, request.requester))
            // Short: a long description pushes the PIN field under the keyboard (PromptText). The full text is on
            // this screen, which the owner just read.
            // A permission change's action line is its lock text (both from the parsed change): shown once.
            .setDescription(listOf(PromptText.short(request.lockText), request.actionLine).filter { it.isNotEmpty() }
                .distinct().joinToString("\n"))
            .setAllowedAuthenticators(APPROVERS) // no negative button allowed with DEVICE_CREDENTIAL
            .build()
        val callback = object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult?) {
                    if (prompt === cancel) prompt = null
                    val unlocked = result?.cryptoObject?.signature
                    if (request.gate) {
                        // Sign the gatekeeper's own message (this device, this prompt, this exact action and crop),
                        // which it verifies before minting the one-shot permit.
                        val message = dev.openmob.companion.gate.GateHost.approvalMessage(request.id, grantAlways)
                        val signature = if (unlocked == null || message == null) null
                        else runCatching { ApprovalKeys.signRaw(unlocked, message) }.getOrNull()
                        if (signature == null || !dev.openmob.companion.gate.GateHost.approve(request.id, message!!, signature)) {
                            showStatus(getString(if (message == null) R.string.approval_gone else R.string.approval_not_confirmed))
                            return
                        }
                        Approvals.answerGate(this@ApprovalActivity, request.id, true)
                        Toast.makeText(this@ApprovalActivity, R.string.approval_sent_approved, Toast.LENGTH_SHORT).show()
                        finish()
                        return
                    }
                    if (unlocked == null) {
                        // No approval key: only a server that doesn't require signatures (token/dev mode)
                        // takes an unsigned yes; accounts mode refused this above.
                        if (request.signatureRequired) showStatus(getString(R.string.approval_no_key))
                        else send(approved = true)
                        return
                    }
                    val now = System.currentTimeMillis() / 1000
                    val signature = runCatching {
                        ApprovalKeys.sign(unlocked, request.id, request.taskId, request.digest, now, grantAlways)
                    }.getOrNull()
                    if (signature == null) {
                        showStatus(getString(R.string.approval_not_confirmed))
                        return
                    }
                    send(approved = true, signature = signature, timestamp = now, always = grantAlways)
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence?) {
                    if (prompt === cancel) prompt = null
                    if (isDestroyed) return
                    if (request.gate) {
                        when (PromptOutcome.classify(errorCode)) {
                            // The owner cancelled the screen lock themselves: that's their no.
                            PromptOutcome.Kind.DECLINED -> return send(approved = false)
                            // The system interrupted it (a notification, a call, the screen going off): keep the
                            // request and bring the prompt back once this screen has focus again.
                            PromptOutcome.Kind.INTERRUPTED -> {
                                resumeAuth = request.id to grantAlways
                                showStatus(getString(R.string.gate_prompt_interrupted))
                                return
                            }
                        }
                    }
                    showStatus(getString(R.string.approval_not_confirmed))
                }
                // onAuthenticationFailed (one wrong finger) needs nothing: the prompt stays up.
            }
        if (signer != null) {
            built.authenticate(BiometricPrompt.CryptoObject(signer), cancel, mainExecutor, callback)
        } else {
            built.authenticate(cancel, mainExecutor, callback)
        }
    }

    private fun send(approved: Boolean, signature: String? = null, timestamp: Long = 0, always: Boolean = false) {
        val request = Approvals.get(requestId)
        if (Approvals.answer(this, requestId, approved, signature, timestamp, always)) {
            // A permission change the owner just signed becomes this phone's own policy (the gatekeeper enforces
            // the ceiling and `never`; the server's copy is only for its dashboard).
            if (approved && signature != null && request?.kind == "mode_change") {
                dev.openmob.companion.gate.GateHost.applyModeChange(request.id, request.taskId, request.action,
                                                                    timestamp, always, signature)
            }
            // Faster mode: the owner read the warning and passed the screen lock; the phone keeps that choice, and
            // shows "Faster mode is on" only once the server applies exactly it (FasterMode.onServerPush).
            if (approved && request?.kind == "mode_change") {
                FasterMode.grantFrom(request.action["input"].orEmpty(), request.id, request.taskId, signature, timestamp)
                    ?.let { FasterMode.approve(this, it) }
            }
            Toast.makeText(
                this, if (approved) R.string.approval_sent_approved else R.string.approval_sent_denied, Toast.LENGTH_SHORT,
            ).show()
            finish()
            return
        }
        // Still pending means the answer couldn't be sent; otherwise it expired meanwhile.
        showStatus(getString(if (Approvals.get(requestId) != null) R.string.approval_offline else R.string.approval_gone))
        render()
    }

    @Suppress("DEPRECATION")
    private fun appLabel(pkg: String): String =
        runCatching { packageManager.getApplicationLabel(packageManager.getApplicationInfo(pkg, 0)).toString() }
            .getOrDefault(pkg)

    private fun showStatus(message: String) {
        status.value = message
    }

    /** Compose draws everything but Approve and "Always allow", which are the original Android views ([buildControls],
     *  with filterTouchesWhenObscured and accessibility data-sensitive), embedded as they are. Deny calls send(false). */
    private fun buildCompose(): View {
        ApprovalScreen.styleApprove(approveButton)
        ApprovalScreen.styleAlways(alwaysBox)
        return ComposeView(this).apply {
            setContent {
                OpenMobTheme {
                    ApprovalScreen.Content(
                        state = screen.value,
                        status = status.value,
                        serverHost = Settings(this@ApprovalActivity).server.let { android.net.Uri.parse(it).host ?: it },
                        approveView = approveButton,
                        alwaysView = alwaysBox,
                        onDeny = { send(approved = false) },
                        onClose = { finish() },
                    )
                }
            }
        }
    }

    // ---------------------------------------------------------------- the two original controls

    /** Approve and "Always allow": the original Android views and flags, unchanged (step 3 embedded them; step 6 keeps
     *  only them). Their look comes from ApprovalScreen.styleApprove/styleAlways. */
    private fun buildControls() {
        // Off by default: granting more than this one action is a deliberate choice.
        alwaysBox = CheckBox(this).apply {
            isChecked = false
            setTextColor(getColor(R.color.om_text))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            filterTouchesWhenObscured = true
            if (Build.VERSION.SDK_INT >= 34) setAccessibilityDataSensitive(View.ACCESSIBILITY_DATA_SENSITIVE_YES)
            visibility = View.GONE
        }
        approveButton = Button(this).apply {
            text = getString(R.string.approval_approve)
            isAllCaps = false
            setOnClickListener { onApprove() }
            filterTouchesWhenObscured = true // no taps through an overlay drawn on top
            // Android 14+: hidden from accessibility services, including the one the agent drives.
            if (Build.VERSION.SDK_INT >= 34) setAccessibilityDataSensitive(View.ACCESSIBILITY_DATA_SENSITIVE_YES)
        }
    }
}
