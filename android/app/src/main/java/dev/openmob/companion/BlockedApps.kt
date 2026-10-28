package dev.openmob.companion

import android.app.Activity
import android.content.Context
import android.hardware.biometrics.BiometricPrompt
import android.os.CancellationSignal
import dev.openmob.companion.gate.BlockedList
import dev.openmob.companion.gate.GateHost
import org.json.JSONArray
import org.json.JSONObject

/**
 * The owner's blocked apps on this phone (owner, 2026-10-20; docs/design/blocked-apps.md). The phone is the
 * authority: the list lives here (app-private, never backed up: review 4 L7) and the gatekeeper enforces it
 * ([dev.openmob.companion.gate.Gatekeeper.ownerBlocked]) in every mode.
 *
 * Plain app-private storage, not Keystore-encrypted: a decrypt failure would empty the list, which loosens; a package
 * list isn't a credential. Adding comes from the phone's own UI or a server `block_apps` request ([BlockedList] only
 * adds); removing only from [unblockAfterScreenLock], which the unblock sheet calls from Android's screen-lock prompt.
 */
object BlockedApps {
    private const val PREFS = "openmob_blocked_apps"
    private const val KEY = "packages"

    @Volatile private var cached: List<String>? = null
    private val listeners = mutableListOf<() -> Unit>()
    /** Told after every change (ConnectionService sends the phone's report, `blocked_apps`). */
    @Volatile var onChanged: (() -> Unit)? = null

    private fun prefs(context: Context) = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun list(context: Context): List<String> = cached ?: synchronized(this) {
        cached ?: BlockedList.parse(runCatching {
            val a = JSONArray(prefs(context).getString(KEY, "[]"))
            (0 until a.length()).map { a.getString(it) }
        }.getOrDefault(emptyList())).also { cached = it }
    }

    @Synchronized private fun save(context: Context, next: List<String>) {
        // commit, not apply: an added block must be on disk before anything relies on it.
        prefs(context).edit().putString(KEY, JSONArray(next).toString()).commit()
        cached = next
        GateHost.setOwnerBlocked(next.toSet())
        listeners.toList().forEach { it() }
        onChanged?.invoke()
    }

    /** The owner picked apps on this phone (no lock: a tightening). False if refused (malformed, or past the cap). */
    @Synchronized fun block(context: Context, packages: List<String>): Boolean {
        val next = BlockedList.with(list(context), packages, home(context)) ?: return false
        if (next != list(context)) save(context, next)
        return true
    }

    /** A server's `block_apps` request: added, never removed. False (nothing changes) if refused. */
    @Synchronized fun onServerRequest(context: Context, message: JSONObject): Boolean {
        val packages = message.optJSONArray("packages")?.let { a -> (0 until a.length()).map { a.opt(it) } }
        val next = BlockedList.withServerRequest(list(context), mapOf("packages" to packages), home(context)) ?: return false
        if (next != list(context)) save(context, next)
        return true
    }

    /** The phone's default Home app (never blockable: [BlockedList.protectedPackage]); empty when none is set. */
    fun home(context: Context): Set<String> = runCatching {
        val intent = android.content.Intent(android.content.Intent.ACTION_MAIN).addCategory(android.content.Intent.CATEGORY_HOME)
        setOfNotNull(context.packageManager.resolveActivity(intent, android.content.pm.PackageManager.MATCH_DEFAULT_ONLY)
            ?.activityInfo?.packageName?.takeIf { it != "android" })
    }.getOrDefault(emptySet())

    /** Only from the unblock sheet's screen-lock success ([confirmUnblock]). */
    @Synchronized fun unblockAfterScreenLock(context: Context, pkg: String) {
        val next = BlockedList.without(list(context), pkg)
        if (next != list(context)) save(context, next)
    }

    /** The phone's report for the server (the dashboard shows it; owner-only there): `blocked_apps`. `packages` as
     *  before (older servers read only that), and `apps`: each with its label as this phone shows it ("" when the app
     *  isn't installed), cut to one line of 60 characters. Labels are for display; matching is by package only. */
    fun report(context: Context): JSONObject {
        val packages = list(context)
        val apps = JSONArray(packages.map { JSONObject().put("package", it).put("label", label(context, it)) })
        return JSONObject().put("type", "blocked_apps").put("packages", JSONArray(packages)).put("apps", apps)
    }

    /** One printable line of at most 60 characters (as the server cleans it again), or "". */
    fun cleanLabel(raw: CharSequence?): String =
        (raw ?: "").map { if (it.isWhitespace()) ' ' else it }.filter { !Character.isISOControl(it) && Character.getType(it) != Character.FORMAT.toInt() }
            .joinToString("").split(' ').filter { it.isNotEmpty() }.joinToString(" ").take(60)

    private fun label(context: Context, pkg: String): String = runCatching {
        val pm = context.packageManager
        cleanLabel(pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)))
    }.getOrDefault("")

    fun listen(listener: () -> Unit): () -> Unit {
        synchronized(listeners) { listeners.add(listener) }
        return { synchronized(listeners) { listeners.remove(listener) } }
    }

    const val CHANNEL = "blocked_app"
    const val NOTIFICATION_ID = 10

    /** "Task stopped · It reached an app you've blocked. Open OpenMob to see which." Fixed text: never the app's name
     *  or the task (review 4 M3: notifications reach the lock screen, watches and listeners). */
    fun notification(app: Context): android.app.Notification {
        val title = app.getString(R.string.blocked_hit_title)
        val text = app.getString(R.string.blocked_hit_text)
        val open = android.app.PendingIntent.getActivity(app, NOTIFICATION_ID,
            android.content.Intent(app, MainActivity::class.java), android.app.PendingIntent.FLAG_IMMUTABLE)
        return android.app.Notification.Builder(app, CHANNEL)
            .setSmallIcon(R.drawable.ic_openmob_tile)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(android.app.Notification.BigTextStyle().bigText(text))
            .setContentIntent(open).setAutoCancel(true)
            .setVisibility(android.app.Notification.VISIBILITY_PRIVATE)
            .setPublicVersion(NotificationPrivacy.publicVersion(app, CHANNEL, title))
            .build()
    }

    /** The task stopped at a blocked app: tell the owner (notifications off: nothing shows, nothing fails). */
    fun notifyStopped(context: Context) {
        val app = context.applicationContext
        runCatching {
            val manager = app.getSystemService(android.app.NotificationManager::class.java) ?: return
            if (manager.getNotificationChannel(CHANNEL) == null) {
                manager.createNotificationChannel(android.app.NotificationChannel(CHANNEL,
                    app.getString(R.string.blocked_channel), android.app.NotificationManager.IMPORTANCE_DEFAULT))
            }
            manager.notify(NOTIFICATION_ID, notification(app))
        }
    }

    /** Android's own screen-lock prompt (strong biometric or PIN/pattern/password, as pairing). [onOk] only on
     *  success; a cancel or error changes nothing. */
    fun confirmUnblock(activity: Activity, label: String, onOk: () -> Unit) {
        if (!PairingFlow.screenLockReady(activity)) {
            android.widget.Toast.makeText(activity, R.string.blocked_needs_lock, android.widget.Toast.LENGTH_LONG).show()
            return
        }
        BiometricPrompt.Builder(activity)
            .setTitle(activity.getString(R.string.blocked_unblock_title, label))
            .setDescription(activity.getString(R.string.blocked_unblock_prompt))
            .setAllowedAuthenticators(PairingFlow.APPROVERS)
            .build()
            .authenticate(CancellationSignal(), activity.mainExecutor, object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult?) = onOk()
            })
    }
}
