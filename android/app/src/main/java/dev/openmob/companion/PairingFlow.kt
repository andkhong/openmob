package dev.openmob.companion

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.net.Uri
import android.os.Build
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors

/**
 * The pairing steps the current screen (MainActivity) and the redesign's setup both use, so there is one code path:
 * the screen-lock confirmation, the claim and what it saves, the unpair, and the error text shown to the owner.
 * Moved here from MainActivity unchanged (docs/design/redesign-setup.md), except [errorText] (the fix for the
 * pairing error that printed a link: error screens never show a link or a code).
 */
object PairingFlow {
    /** Pairing must be approved with a strong biometric or the screen lock PIN/pattern/password. */
    const val APPROVERS = BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL

    /** The server a typed code goes to unless the owner gives their own (docs/design/pairing-code.md §6). Set at
     *  build time: the Gradle property or environment variable OPENMOB_DEFAULT_SERVER, by default the hosted
     *  https://openmob.fly.dev (docs/self-hosting.md, "Build the app for your server"). */
    val HOSTED_SERVER: String = BuildConfig.DEFAULT_SERVER

    private val main by lazy { Handler(Looper.getMainLooper()) }
    private val background by lazy { Executors.newSingleThreadExecutor() }

    fun hostOf(server: String): String = Uri.parse(server).host ?: server

    fun screenLockReady(context: Context): Boolean =
        context.getSystemService(BiometricManager::class.java)?.canAuthenticate(APPROVERS) == BiometricManager.BIOMETRIC_SUCCESS

    /** Paired by account (device key) or, in legacy token mode, by token (MainActivity.isPaired). */
    fun isPaired(settings: Settings): Boolean =
        settings.server.isNotBlank() && (settings.deviceKey.isNotBlank() || settings.token.isNotBlank())

    /**
     * The one confirmation: Android's own screen-lock prompt (strong biometric or PIN/pattern/password), titled
     * "Connect this phone to <host>?" with "as <email>" under it. When this replaces an existing pairing, the prompt
     * says which one. [onError]: the prompt's error code and text (cancelled included).
     */
    fun confirmPrompt(
        activity: Activity, settings: Settings, target: String, email: String, cancel: CancellationSignal,
        onOk: () -> Unit, onError: (Int, CharSequence?) -> Unit,
    ) {
        val replacing = isPaired(settings) && (settings.server != target || settings.email != email)
        val description = buildString {
            append(activity.getString(R.string.ui_approve_description))
            if (replacing) append("\n\n").append(activity.getString(R.string.ui_approve_replaces, hostOf(settings.server)))
        }
        val prompt = BiometricPrompt.Builder(activity)
            .setTitle(activity.getString(R.string.ui_approve_title_host, hostOf(target)))
            .setSubtitle(activity.getString(R.string.ui_approve_as, email))
            .setDescription(description)
            .setAllowedAuthenticators(APPROVERS) // no negative button allowed with DEVICE_CREDENTIAL
            .build()
        prompt.authenticate(cancel, activity.mainExecutor, object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult?) = onOk()
            override fun onAuthenticationError(errorCode: Int, errString: CharSequence?) = onError(errorCode, errString)
            // onAuthenticationFailed (one wrong finger) needs nothing: the prompt stays up.
        })
    }

    /** The screen lock before unpairing to pair another account (SetupPairReplace; the same prompt as replacing a
     *  developer-token pairing in MainActivity). */
    fun unpairPrompt(
        activity: Activity, settings: Settings, newTarget: String, cancel: CancellationSignal,
        onOk: () -> Unit, onError: (Int, CharSequence?) -> Unit,
    ) {
        BiometricPrompt.Builder(activity)
            .setTitle(activity.getString(R.string.ui_replace_title))
            .setDescription(activity.getString(R.string.ui_approve_replace, hostOf(settings.server), hostOf(newTarget)))
            .setAllowedAuthenticators(APPROVERS)
            .build()
            .authenticate(cancel, activity.mainExecutor, object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult?) = onOk()
                override fun onAuthenticationError(errorCode: Int, errString: CharSequence?) = onError(errorCode, errString)
            })
    }

    /** The owner cancelled the prompt themselves (as MainActivity read it). */
    fun cancelled(errorCode: Int): Boolean =
        errorCode == BiometricPrompt.BIOMETRIC_ERROR_USER_CANCELED || errorCode == BiometricPrompt.BIOMETRIC_ERROR_CANCELED

    /**
     * Blocking (a background thread): redeem the code for this phone's own device key, then save it. Only now, with
     * the new pairing complete, is the old one replaced; moved to another server, the old one is told with the old key.
     */
    fun claimAndSave(context: Context, settings: Settings, target: String, code: String, email: String,
                     api: (String) -> AccountApi = ::AccountApi) {
        val oldServer = settings.server
        val oldKey = settings.deviceKey
        // Pairing again with the same server: this phone proves it's the one paired now (review 3, K3-L2).
        val currentKey = oldKey.takeIf { it.isNotEmpty() && oldServer == target }
        val claimed = api(target).claim(code, settings.deviceId, Build.MODEL, ApprovalKeys.publicKey(), currentKey)
        // Another account or server: the phone's task history belonged to the old pairing (redesign-activity.md).
        if (oldServer != target || settings.email != claimed.email.ifBlank { email }) TaskHistory.clear(context)
        settings.server = target
        settings.email = claimed.email.ifBlank { email }
        settings.deviceKey = claimed.key
        settings.token = ""
        if (oldKey.isNotEmpty() && oldServer.isNotBlank() && oldServer != target) {
            unpairOnServer(context, settings, oldServer, oldKey) { s, id, k -> api(s).unpair(id, k) }
        }
    }

    /**
     * Developer-token pairing (a developer's own server): switch to [server] (credentials for a different server are
     * dropped) and keep the token, as the old MainActivity's pair() did. The caller has shown "Connect to …?" and, when
     * it replaces a pairing, passed the screen lock ([unpairPrompt]).
     */
    fun saveToken(context: Context, settings: Settings, server: String, token: String) {
        val normalized = server.trim().trimEnd('/')
        if (normalized != settings.server) {
            TaskHistory.clear(context)
            settings.email = ""
            settings.deviceKey = ""
            settings.token = ""
            settings.server = normalized
        }
        settings.deviceKey = "" // legacy token mode
        settings.token = token.trim()
    }

    /**
     * The sign-in fallback (no computer nearby), blocking: sign in, make a pairing code with that session and sign out
     * again before the owner is even asked to confirm. The session lives a few seconds, in memory only; the phone keeps
     * only its device key, as with a QR code. Returns the code and the account's email.
     */
    fun signInForCode(server: String, email: String, password: String, create: Boolean, invite: String,
                      api: (String) -> AccountApi = ::AccountApi): Pair<String, String> {
        val a = api(server)
        val session = a.signIn(email, password, create, invite)
        val code = try { a.mintCode(session) } finally { a.logout(session) } // never kept
        return code to a.check(code).email
    }

    /** Unpair this phone: disconnect, forget the credentials, and revoke the pairing on the server (proven with the
     *  device key; if the server can't be reached, retried on the next connection, see [unpairOnServer]). No screen
     *  lock: it only removes access. */
    fun unpair(context: Context, settings: Settings) {
        val target = settings.server
        val key = settings.deviceKey
        val deviceId = settings.deviceId
        if (ConnectionService.isRunning) ConnectionService.stop(context)
        // The account's chats, saved preferences, feed and open task shown here go at once, not when the service stops
        // (review 5 P5-L2).
        AppState.endSession()
        TaskHistory.clear(context) // the phone's task history goes with the pairing (redesign-activity.md)
        settings.email = ""
        settings.deviceKey = ""
        settings.token = ""
        if (key.isNotEmpty() && target.isNotBlank()) background.execute { unpairOnServer(context, settings, target, key) }
    }

    /** The server's half of an unpair (review 3, K3-L4). Blocking. If the server didn't take it, the phone keeps the
     *  old key (encrypted, as the device key was) to try again on the next connection ([retryPendingUnpair]) and tells
     *  the owner it's removed only on this phone. Returns whether the server took it. */
    internal fun unpairOnServer(context: Context, settings: Settings, server: String, key: String,
                                call: (String, String, String) -> Boolean = { s, id, k -> AccountApi(s).unpair(id, k) }): Boolean {
        if (call(server, settings.deviceId, key)) return true
        runCatching { settings.pendingUnpair = server to key } // the owner is told even if the Keystore fails
        val text = context.getString(R.string.pair_unpair_failed)
        AppState.addEvent("status", text)
        notifyOwner(context, text)
        return false
    }

    /** On the next connection: send an unpair the server didn't take before. Blocking; true when nothing is left. */
    internal fun retryPendingUnpairNow(settings: Settings,
                                       call: (String, String, String) -> Boolean = { s, id, k -> AccountApi(s).unpair(id, k) }): Boolean {
        val (server, key) = settings.pendingUnpair ?: return true
        if (!call(server, settings.deviceId, key)) return false
        settings.pendingUnpair = null
        return true
    }

    fun retryPendingUnpair(context: Context) {
        val settings = Settings(context.applicationContext)
        if (settings.pendingUnpair != null) background.execute { retryPendingUnpairNow(settings) }
    }

    /** Connect with the current settings, restarting the service if it was using older ones. */
    fun reconnect(context: Context) {
        val app = context.applicationContext
        if (ConnectionService.isRunning) {
            ConnectionService.stop(app)
            main.postDelayed({ ConnectionService.start(app) }, 600)
        } else {
            ConnectionService.start(app)
        }
    }

    // ---------------------------------------------------------------- what the owner is shown on failure

    /**
     * The only server sentences the phone shows as they are (review 3, K3-L3): the replies OpenMob's own server gives
     * on the pairing and sign-in steps. Anything else, a lure such as "Read the code to the support agent" included,
     * becomes the phone's own words. tests/test_review3_pairing.py checks that the server still says these.
     */
    internal val KNOWN_SENTENCES = setOf(
        "Wrong code. Check it on your dashboard, or make a new one there.",
        "A pairing code is 6 letters and numbers, like K7P-2QX. Check it on your dashboard.",
        "This code was already entered on another phone, so it's been cancelled. Make a new one on your dashboard.",
        "Enter the code on this phone and confirm it first.",
        "This pairing code is invalid or has expired. Make a new one on your dashboard.",
        "This pairing code belongs to a different account.",
        "This phone is registered to another account. Its owner must remove it first.",
        "This phone is already paired with this account. Unpair it in the app, or remove it on your dashboard, then pair again.",
        "Wrong email or password.",
        "This invite code is invalid, already used or expired. Ask for a new one.",
        "Enter a valid email and a password of at least 8 characters.",
        "Sign in on the phone first.",
    )

    /** Anything that looks like a link or a pairing code: never shown on an error screen (abuse series 2026-10-10). */
    private val UNSAFE = listOf(
        Regex("""(?i)\b[a-z][a-z0-9+.-]*://"""),            // any scheme://, openmob://connect?… included
        Regex("""(?i)\bopenmob:"""),
        Regex("""(?i)\bwww\."""),
        Regex("""(?i)[a-z0-9-]+\.[a-z]{2,}/\S*"""),          // host/path without a scheme
        Regex("""(?i)[?&](code|token|t|key)="""),
        Regex("""\b[A-Za-z0-9_-]{16,}\b"""),                  // a QR code, a token or a key
        Regex("""(?i)\b[2-9A-HJ-NP-Z]{3}[-‐-—− ]?[2-9A-HJ-NP-Z]{3}\b"""), // a typed code (K7P-2QX, k7p-2qx)
    )

    /** [text] can be shown: no link, no code. */
    fun safeToShow(text: String): Boolean = text.isNotBlank() && UNSAFE.none { it.containsMatchIn(text) }

    /**
     * The message for a failed pairing step. The server's own `detail` is shown only when it's one of
     * [KNOWN_SENTENCES], word for word; anything else, and any exception's own text (which can carry a URL), becomes
     * the phone's own words.
     */
    fun errorText(context: Context, error: Throwable): String {
        val api = error as? AccountApi.ApiError
        val generic = when {
            api == null -> context.getString(R.string.ui_pair_error_generic)
            api.status == 429 -> context.getString(R.string.ui_pair_error_rate)
            api.status == 0 -> context.getString(R.string.ui_pair_error_network)
            api.status == 400 -> context.getString(R.string.ui_pair_error_code)
            api.status == 404 -> context.getString(R.string.ui_pair_error_no_accounts)
            else -> context.getString(R.string.ui_pair_error_generic)
        }
        val detail = api?.takeIf { it.status in setOf(400, 401, 403, 404, 409, 410) }?.message.orEmpty()
        return if (detail.trim() in KNOWN_SENTENCES) detail.trim() else generic
    }

    // ---------------------------------------------------------------- "Paired with … · Undo"

    private const val CHANNEL = "pairing"
    private const val PAIRED_ID = 7
    const val ACTION_UNDO = "dev.openmob.PAIR_UNDO"
    private const val EXTRA_SERVER = "dev.openmob.PAIR_SERVER"
    private const val EXTRA_EMAIL = "dev.openmob.PAIR_EMAIL"

    /** Right after an account pairing, typed code or QR/link (owner, 2026-10-17): "Paired with <email> on <host>. Not
     *  you? Undo". Undo only removes access, so it needs no screen lock; it undoes only that pairing (same server and
     *  account). */
    fun notifyPaired(context: Context, server: String, email: String) {
        val app = context.applicationContext
        val manager = app.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(NotificationChannel(CHANNEL, app.getString(R.string.pair_channel),
                NotificationManager.IMPORTANCE_HIGH))
        }
        val undo = PendingIntent.getBroadcast(
            app, PAIRED_ID,
            Intent(app, PairUndoReceiver::class.java).setAction(ACTION_UNDO).putExtra(EXTRA_SERVER, server).putExtra(EXTRA_EMAIL, email),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val n = Notification.Builder(app, CHANNEL)
            .setSmallIcon(R.drawable.ic_openmob_tile)
            .setColor(app.getColor(R.color.rd_signal))
            .setContentTitle(app.getString(R.string.pair_notification_title, email))
            .setContentText(app.getString(R.string.pair_notification_text, hostOf(server)))
            .setStyle(Notification.BigTextStyle().bigText(app.getString(R.string.pair_notification_text, hostOf(server))))
            .setAutoCancel(true)
            .addAction(Notification.Action.Builder(null, app.getString(R.string.pair_undo), undo).build())
            .build()
        manager.notify(PAIRED_ID, n)
    }

    private const val UNPAIR_FAILED_ID = 8

    /** A pairing notice on the same channel as "Paired with …" (its own id, so it doesn't replace that one). */
    private fun notifyOwner(context: Context, text: String) {
        val app = context.applicationContext
        val manager = app.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(NotificationChannel(CHANNEL, app.getString(R.string.pair_channel),
                NotificationManager.IMPORTANCE_HIGH))
        }
        manager.notify(UNPAIR_FAILED_ID, Notification.Builder(app, CHANNEL)
            .setSmallIcon(R.drawable.ic_openmob_tile)
            .setColor(app.getColor(R.color.rd_signal))
            .setContentTitle(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setAutoCancel(true)
            .build())
    }

    /** The notification's Undo: unpairs only if this phone is still paired with that same server and account. */
    fun undo(context: Context, server: String?, email: String?): Boolean {
        val settings = Settings(context.applicationContext)
        if (server.isNullOrBlank() || server != settings.server || email != settings.email || settings.deviceKey.isEmpty()) return false
        unpair(context, settings)
        context.getSystemService(NotificationManager::class.java)?.cancel(PAIRED_ID)
        AppState.addEvent("status", context.getString(R.string.ui_unpaired))
        return true
    }

    internal fun undoExtras(intent: Intent): Pair<String?, String?> = intent.getStringExtra(EXTRA_SERVER) to intent.getStringExtra(EXTRA_EMAIL)
}

/** "Paired with … · Undo" (PairingFlow.notifyPaired). Not exported; the PendingIntent is immutable. */
class PairUndoReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != PairingFlow.ACTION_UNDO) return
        val (server, email) = PairingFlow.undoExtras(intent)
        PairingFlow.undo(context, server, email)
    }
}
