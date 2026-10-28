package dev.openmob.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import dev.openmob.companion.gate.ModeChange
import org.json.JSONObject

/**
 * Phone approvals for risky actions (docs/phone-protocol.md, section 3.3). The server asks with
 * `approval_request`, and only the person holding the phone answers, never the calling model:
 * Deny needs nothing, Approve needs the screen lock (ApprovalActivity). Each request is answered
 * at most once. With no answer it expires after [EXPIRY_MS]: the notification goes away and
 * nothing is sent, so the server's own timeout counts it as a no.
 *
 * Everything here runs on the main thread.
 */
object Approvals {
    /**
     * "Always allow this": the trusted grant an approval may also make (only offered on the phone that
     * would act). `text` says what it allows ("Agents could send any WhatsApp message as you for 30
     * days"); `confirmTwice` (payments) asks a second time before granting.
     */
    data class Always(val app: String, val kind: String, val days: Double, val text: String, val confirmTwice: Boolean)

    /**
     * `deviceName`: the phone that would act, when the server says (it may be another of the owner's phones).
     * `kind`: action (a risky tap) | step (ask-every-step mode) | plan | mode_change (agents would ask less).
     */
    /**
     * `action`: the action's fields as the server sent them ([ActionDigest.FIELDS]); `digest`: the server's
     * digest of them. The app shows [actionLine] and signs only if its own digest of `action` matches
     * ([consistent]). `signatureRequired`: the server accepts only signed approvals (accounts mode).
     * `canApprove` false: this phone can only decline (no approval key registered yet), for
     * `cannotApproveReason`.
     */
    data class Request(
        val id: String, val taskId: String, val question: String, val requester: String, val deviceName: String = "",
        val kind: String = "action", val plan: List<String> = emptyList(), val always: Always? = null,
        val action: Map<String, String> = emptyMap(), val digest: String = "", val signatureRequired: Boolean = false,
        val canApprove: Boolean = true, val cannotApproveReason: String = "",
        /** `gate`: the gatekeeper's own prompt (worded by this phone from what it sees; [crop] shows the target). */
        val gate: Boolean = false, val crop: ByteArray? = null, val serverSays: String = "",
        /** A gate prompt's confirmation level: tap (Allow/Deny, no screen lock) or fingerprint. */
        val level: String = "fingerprint",
        /** When this phone received it (SystemClock.uptimeMillis, the clock the expiry timer runs on); 0: unknown. */
        val receivedAt: Long = 0,
    ) {
        /** Uptime ms when it expires unanswered ([EXPIRY_MS] after it arrived), or 0 if unknown. */
        val expiresAt: Long get() = if (receivedAt > 0) receivedAt + EXPIRY_MS else 0
        /** The phone's own words: a gate prompt as worded by the gatekeeper, a permission change described from the
         *  signed change itself (the server's question is only "Server says"), else the question. */
        private val asked: String get() = when {
            gate -> question
            kind == "mode_change" && action["input"].orEmpty().contains('\n') -> ModeChange.describe(action["input"].orEmpty())
            else -> ActionDigest.signedQuestion(action).ifEmpty { question }
        }

        /** The screen-lock sheet's text: short, so the PIN field stays reachable (PromptText). A permission change
         *  gets its own summary (ModeChange.lockText: for Faster mode the scope and the warning's first sentence). */
        val lockText: String get() =
            if (!gate && kind == "mode_change" && action["input"].orEmpty().contains('\n')) ModeChange.lockText(action["input"].orEmpty())
            else PromptText.short(shownQuestion)

        /** "On Pixel 9: Send message to Mom?", or just the question when the phone isn't named. */
        val shownQuestion: String get() = if (deviceName.isEmpty()) asked else "On $deviceName: $asked"

        /** A permission change that also allows purchases without asking: confirmed a second time. */
        // Read from the change exactly as the phone will apply it (N2), and from the raw text as before.
        val allowsMoney: Boolean get() = ActionDigest.allowsMoney(action) ||
            (kind == "mode_change" && ModeChange.allowsMoney(action["input"].orEmpty()))

        /** What exactly will happen, from the action's own fields (empty for an older server). A permission change is
         *  worded only from the change itself (its signed input, parsed here: ModeChange.lockText), never from its
         *  `text`/`desc`, which the server chooses freely and which change nothing (review 3, P3-M2). */
        val actionLine: String get() = when {
            action.isEmpty() -> ""
            kind == "mode_change" || action["tool"] == "mode_change" ->
                action["input"].orEmpty().let { if (it.contains('\n')) ModeChange.lockText(it) else ActionDigest.describe(action) }
            else -> ActionDigest.describe(action)
        }

        /** The digest the server sent is the digest of the action shown. */
        val consistent: Boolean get() = digest.isNotEmpty() && ActionDigest.of(action) == digest
    }

    /** The action's fields as strings (bounds as "l,t,r,b"; JSON null as empty). */
    private fun actionFields(json: JSONObject?): Map<String, String> {
        if (json == null) return emptyMap()
        return ActionDigest.FIELDS.associateWith { name ->
            when {
                !json.has(name) || json.isNull(name) -> ""
                json.optJSONArray(name) != null -> json.getJSONArray(name).let { list ->
                    (0 until list.length()).joinToString(",") { list.optLong(it).toString() }
                }
                else -> json.optString(name)
            }
        }
    }

    const val EXTRA_ID = "dev.openmob.APPROVAL_ID"
    const val ACTION_DENY = "dev.openmob.APPROVAL_DENY"
    private const val CHANNEL = "approvals"
    private const val NOTIFICATION_ID = 2 // one per request, told apart by tag (the request id)
    const val EXPIRY_MS = 2 * 60 * 1000L
    private const val REMEMBERED = 200

    private val pending = LinkedHashMap<String, Request>()
    private val finished = LinkedHashSet<String>() // answered or expired: never shown or sent again
    private val modeChangePrompts = mutableListOf<Long>() // when permission-change prompts were shown (N1)
    private val main = Handler(Looper.getMainLooper())

    fun pending(): List<Request> = pending.values.toList()

    /**
     * Display only (Settings' "Limit reached" line): ms until the N1 limit below would let another permission-change
     * prompt show, 0 if one would show now. Reads the same window; changes nothing and admits nothing.
     */
    fun modeChangeRetryInMs(now: Long = android.os.SystemClock.elapsedRealtime()): Long =
        // A copy of the list (it may change on another thread; a failed read just shows the usual toast).
        runCatching { retryInMs(modeChangePrompts.toList(), now) }.getOrDefault(0)

    /** N1's numbers as `request` uses them (its literals are left as they are): 2 prompts per hour. */
    private const val MODE_CHANGE_LIMIT = 2
    private const val MODE_CHANGE_WINDOW_MS = 3_600_000L

    /** The N1 window's arithmetic, pure for tests: with [times] (when prompts showed), ms until fewer than 2 count. */
    internal fun retryInMs(times: List<Long>, now: Long): Long {
        val inWindow = times.filter { now - it < MODE_CHANGE_WINDOW_MS }.sorted()
        if (inWindow.size < MODE_CHANGE_LIMIT) return 0
        // The prompt that must age out for the count to drop below the limit.
        return (inWindow[inWindow.size - MODE_CHANGE_LIMIT] + MODE_CHANGE_WINDOW_MS - now).coerceAtLeast(1)
    }

    fun get(id: String): Request? = pending[id]

    /** A new `approval_request` from the server. Repeats of a known id are ignored. */
    fun request(context: Context, message: JSONObject) {
        // S3 / D9: this phone owns approval for actions. A server-worded prompt behind the screen lock would be
        // phishing, so only permission changes are taken, and those are worded from the signed change itself.
        if (message.optString("kind") != "mode_change") return
        val id = message.optString("id")
        // "gk…" ids are the gatekeeper's own prompts: the server can never raise or answer one through this path.
        if (id.isEmpty() || id.startsWith("gk") || id in pending || id in finished) return
        val now = android.os.SystemClock.elapsedRealtime()
        // Review M2: a Faster mode change mixed with anything else (Don't ask, purchases, grants...) or in a scope the
        // owner didn't just tap here is declined unseen: one screen lock must sign exactly what the owner asked for.
        val input = message.optJSONObject("action")?.optString("input").orEmpty()
        ModeChange.fasterRefusal(input, FasterMode.requested, now)?.let { why ->
            finished.add(id)
            ConnectionService.sendApproval(id, false)
            AppState.addEvent("status", context.getString(
                if (why == "mixed") R.string.faster_declined_mixed else R.string.faster_declined_unasked))
            return
        }
        if (ModeChange.fasterScope(input) != null) FasterMode.takeRequest()
        // N1: at most 2 permission-change prompts an hour (a route toward Don't ask by wearing the owner down).
        modeChangePrompts.removeAll { now - it >= 3_600_000L }
        if (modeChangePrompts.size >= 2) {
            AppState.addEvent("status", context.getString(R.string.gate_mode_change_limited))
            return
        }
        modeChangePrompts.add(now)
        val app = context.applicationContext
        val request = Request(
            id = id,
            taskId = message.optString("task_id"),
            question = message.optString("question").trim().ifEmpty { app.getString(R.string.approval_no_question) },
            requester = message.optString("requester").trim().ifEmpty { app.getString(R.string.approval_unknown_requester) },
            deviceName = message.optString("device_name").trim(),
            kind = message.optString("kind").ifEmpty { "action" },
            plan = message.optJSONArray("plan")?.let { list -> (0 until list.length()).map { list.optString(it) } } ?: emptyList(),
            always = message.optJSONObject("always")?.let {
                Always(it.optString("app"), it.optString("kind"), it.optDouble("days", 30.0), it.optString("text"),
                       it.optBoolean("confirm_twice"))
            }?.takeIf { it.app.isNotEmpty() && it.kind.isNotEmpty() && it.text.isNotEmpty() },
            action = actionFields(message.optJSONObject("action")),
            digest = message.optString("digest"),
            signatureRequired = message.optBoolean("signature_required"),
            canApprove = message.optBoolean("can_approve", true),
            cannotApproveReason = message.optString("cannot_approve_reason").trim(),
            receivedAt = android.os.SystemClock.uptimeMillis(),
        )
        pending[id] = request
        main.postDelayed({ expire(app, id) }, id, EXPIRY_MS)
        notify(app, request)
        AppState.addEvent("approval", app.getString(R.string.approval_event_asked, request.requester, request.shownQuestion))
    }

    /**
     * Sends the owner's answer, once. False if the request is gone (answered or expired) or the
     * phone is offline; in the offline case it stays pending so the owner can try again.
     */
    fun answer(
        context: Context, id: String, approved: Boolean, signature: String? = null, timestamp: Long = 0,
        always: Boolean = false,
    ): Boolean {
        val request = pending[id] ?: return false
        // A gate prompt: this path only denies. A yes is the signed one in ApprovalActivity (no unsigned fallback).
        if (request.gate) return !approved && answerGate(context, id, false)
        if (!ConnectionService.sendApproval(id, approved, signature, timestamp, always && approved)) return false
        finish(context, id)
        val app = context.applicationContext
        // Display only (Activity): a Faster mode answer, after it was sent. Nothing reads this back to decide anything.
        if (request.kind == "mode_change") {
            ModeChange.fasterScope(request.action["input"].orEmpty())?.let { scope ->
                runCatching { TaskHistory.init(app).onFasterAnswer(id, scope, approved) }
            }
        }
        AppState.addEvent(
            "approval",
            app.getString(if (approved) R.string.approval_event_approved else R.string.approval_event_denied, request.question),
        )
        return true
    }

    /**
     * The gatekeeper's own prompt (D5): worded by this phone from what it sees, with a crop of the target. Approving
     * signs the gatekeeper's message with the screen-lock key and mints a one-shot permit here; nothing is sent to
     * the server but a `gate_event`. The prompt opens right away (the accessibility service may start it), with a
     * notification as well.
     */
    fun requestGate(context: Context, id: String, wording: String, serverSays: String, crop: ByteArray?, always: Always?,
                    level: String = "fingerprint") {
        if (id in pending || id in finished) return
        val app = context.applicationContext
        val request = Request(
            id = id, taskId = "", question = wording, requester = app.getString(R.string.gate_requester),
            kind = "gate", always = always, gate = true, crop = crop, serverSays = serverSays.take(200), level = level,
            receivedAt = android.os.SystemClock.uptimeMillis(),
        )
        pending[id] = request
        main.postDelayed({ expire(app, id); dev.openmob.companion.gate.GateHost.cancel(id) }, id, EXPIRY_MS)
        notify(app, request)
        AppState.addEvent("approval", app.getString(R.string.gate_event_asked, wording))
        runCatching {
            (OpenMobAccessibilityService.instance ?: app).startActivity(
                Intent(app, ApprovalActivity::class.java).putExtra(EXTRA_ID, id).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }

    /** The owner answered a gate prompt on this phone (approve: already signed and accepted by the gatekeeper). */
    fun answerGate(context: Context, id: String, approved: Boolean): Boolean {
        val request = pending[id] ?: return false
        if (!approved) dev.openmob.companion.gate.GateHost.deny(id)
        finish(context, id)
        AppState.addEvent("approval", context.applicationContext.getString(
            if (approved) R.string.approval_event_approved else R.string.approval_event_denied, request.question))
        return true
    }

    /** Stop: drop every gate prompt (their permits are gone too). */
    fun clearGate(context: Context) {
        pending.values.filter { it.gate }.map { it.id }.forEach { finish(context, it) }
        AppState.notifyListeners()
    }

    /** The server withdrew a request (answered on another phone, or the task moved on): drop it unanswered. */
    fun cancel(context: Context, id: String) {
        if (pending[id] == null) return
        finish(context, id)
        AppState.notifyListeners()
    }

    /** The connection was closed by the owner: drop every pending request without answering. */
    fun clear(context: Context) {
        pending.keys.toList().forEach { dismiss(context, it) }
        pending.clear()
        AppState.notifyListeners()
    }

    private fun expire(context: Context, id: String) {
        val request = pending[id] ?: return
        finish(context, id)
        AppState.addEvent("approval", context.getString(R.string.approval_event_expired, request.question))
    }

    private fun finish(context: Context, id: String) {
        pending.remove(id)
        finished.add(id)
        while (finished.size > REMEMBERED) finished.remove(finished.first())
        dismiss(context, id)
    }

    private fun dismiss(context: Context, id: String) {
        main.removeCallbacksAndMessages(id)
        context.getSystemService(NotificationManager::class.java).cancel(id, NOTIFICATION_ID)
    }

    /** High priority so it shows heads-up. It never carries the question (security review 4, M3): that can quote the
     *  screen, and a notification reaches the lock screen, watches and notification listeners. Review shows it,
     *  behind FLAG_SECURE, and approving needs the screen lock (ApprovalActivity). */
    private fun notify(context: Context, request: Request) {
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, context.getString(R.string.approval_channel), NotificationManager.IMPORTANCE_HIGH)
                    .apply { description = context.getString(R.string.approval_channel_description) }
            )
        }
        val code = request.id.hashCode()
        val review = PendingIntent.getActivity(
            context, code,
            Intent(context, ApprovalActivity::class.java)
                .setIdentifier(request.id) // a distinct PendingIntent per request
                .putExtra(EXTRA_ID, request.id)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val deny = PendingIntent.getBroadcast(
            context, code,
            Intent(context, ApprovalReceiver::class.java).setAction(ACTION_DENY)
                .setIdentifier(request.id)
                .putExtra(EXTRA_ID, request.id),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        // The redesign's words (step 6). A gate prompt is this phone's own; a server's names who asks. Still only Deny
        // and Review: approving always goes through ApprovalActivity's screen lock.
        val text = if (request.gate) context.getString(R.string.approval_notification_text_gate)
                   else context.getString(R.string.approval_notification_text, request.requester)
        val title = context.getString(R.string.approval_notification_public)
        val notification = Notification.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_openmob_tile)
            .setColor(0xFFFFB300.toInt()) // the approval amber
            .setSubText(context.getString(R.string.approval_notification_sub))
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setCategory(Notification.CATEGORY_REMINDER)
            .setVisibility(Notification.VISIBILITY_PRIVATE)
            .setPublicVersion(NotificationPrivacy.publicVersion(context, CHANNEL, title))
            .setTimeoutAfter(EXPIRY_MS) // also dismisses it if this process is gone by then
            .setContentIntent(review)
            .addAction(Notification.Action.Builder(null, context.getString(R.string.approval_deny), deny).build())
            .addAction(Notification.Action.Builder(null, context.getString(R.string.approval_review), review).build())
            .build()
        manager.notify(request.id, NOTIFICATION_ID, notification)
    }
}

/** The notification's Deny button. Denying needs no screen lock. */
class ApprovalReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Approvals.ACTION_DENY) return
        val id = intent.getStringExtra(Approvals.EXTRA_ID) ?: return
        if (Approvals.get(id) != null && !Approvals.answer(context, id, false)) {
            Toast.makeText(context, R.string.approval_offline, Toast.LENGTH_SHORT).show()
        }
    }
}
