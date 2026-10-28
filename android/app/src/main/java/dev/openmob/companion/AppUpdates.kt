package dev.openmob.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.util.Log
import org.json.JSONObject
import java.net.URI

/** What the server said about app versions in its welcome (`app_update`, docs/phone-protocol.md §3.7). */
data class UpdateInfo(
    /** The versionCode of the APK the server serves; null: none (or none fit to serve). */
    val latest: Int?,
    /** The oldest versionCode the server lets act; 0: no minimum. */
    val minimum: Int,
    /** The download the server named; opened only after [UpdateLogic.safeDownloadUrl]. */
    val url: String?,
) {
    companion object {
        /** The welcome's `app_update` object; null (an older server, or not an object): nothing known. */
        fun parse(json: JSONObject?): UpdateInfo? {
            json ?: return null
            val latest = positive(json.opt("latest"))
            val minimum = positive(json.opt("minimum")) ?: 0
            val url = json.opt("url").let { if (it is String && it.isNotBlank()) it.take(512) else null }
            return UpdateInfo(latest, minimum, url)
        }

        /** A whole number above 0 (JSON gives Int or Long; a double, string or bool isn't one). */
        private fun positive(v: Any?): Int? = when (v) {
            is Int -> v.takeIf { it > 0 }
            is Long -> v.takeIf { it in 1..Int.MAX_VALUE.toLong() }?.toInt()
            else -> null
        }
    }
}

/** What Home and Settings › About show about updates. */
sealed interface UpdateState {
    data object None : UpdateState
    /** A newer build is on the server; the owner hasn't put this one off ("Later"). */
    data class Available(val latest: Int) : UpdateState
    /** This app is below the server's minimum: no task runs here until it is updated. */
    data class Required(val minimum: Int, val latest: Int?) : UpdateState
    /** The server closed with 4400: it speaks a protocol this app doesn't. */
    data object TooOld : UpdateState
}

/** The pure decisions (JVM-tested): which state to show, and whether a download link may be opened. */
object UpdateLogic {
    const val DOWNLOAD_PATH = "/download/openmob.apk"
    private val VERSION_QUERY = Regex("v=[0-9a-f]{1,64}")

    /** [current]: this app's versionCode; [dismissed]: the highest `latest` the owner put off with Later or ✕. */
    fun state(current: Int, info: UpdateInfo?, dismissed: Int, tooOld: Boolean): UpdateState = when {
        tooOld -> UpdateState.TooOld
        info == null -> UpdateState.None
        info.minimum > 0 && current < info.minimum -> UpdateState.Required(info.minimum, info.latest)
        info.latest != null && info.latest > current && info.latest > dismissed -> UpdateState.Available(info.latest)
        else -> UpdateState.None
    }

    /** A newer build is on the server, put off or not (Settings › About says so either way). */
    fun newer(current: Int, info: UpdateInfo?): Boolean = info?.latest?.let { it > current } == true

    private data class Origin(val scheme: String, val host: String, val port: Int, val authority: String, val prefix: String)

    /** The paired server's address ("https://openmob.example", a bare host, or ws(s)://…) as an http(s) origin. */
    private fun origin(server: String): Origin? {
        var s = server.trim().trimEnd('/')
        if (s.isEmpty()) return null
        s = when {
            s.startsWith("wss://") -> "https://" + s.removePrefix("wss://")
            s.startsWith("ws://") -> "http://" + s.removePrefix("ws://")
            "://" !in s -> "https://$s"
            else -> s
        }
        val u = runCatching { URI(s) }.getOrNull() ?: return null
        val scheme = u.scheme?.lowercase() ?: return null
        if (scheme != "https" && scheme != "http") return null
        val host = u.host?.lowercase() ?: return null
        if (u.rawUserInfo != null) return null
        val port = if (u.port == -1) (if (scheme == "https") 443 else 80) else u.port
        return Origin(scheme, host, port, u.rawAuthority ?: return null, (u.rawPath ?: "").trimEnd('/'))
    }

    /**
     * The link to open for [url], or null. Only the paired [server]'s own download: the same scheme, host and port,
     * the path exactly `/download/openmob.apk` (under the server's own path, if it has one), at most a `v=<hex>`
     * query, no user info or fragment. The link returned is rebuilt from the server's own address, so what Android
     * opens is exactly what was checked.
     */
    fun safeDownloadUrl(url: String?, server: String): String? {
        if (url.isNullOrBlank()) return null
        val o = origin(server) ?: return null
        val u = runCatching { URI(url.trim()) }.getOrNull() ?: return null
        val scheme = u.scheme?.lowercase() ?: return null
        if (scheme != o.scheme) return null
        if (u.rawUserInfo != null || u.rawFragment != null || u.isOpaque) return null
        if (u.host?.lowercase() != o.host) return null
        val port = if (u.port == -1) (if (scheme == "https") 443 else 80) else u.port
        if (port != o.port) return null
        if (u.rawPath != o.prefix + DOWNLOAD_PATH) return null
        val query = u.rawQuery
        if (query != null && !VERSION_QUERY.matches(query)) return null
        return "${o.scheme}://${o.authority}${o.prefix}$DOWNLOAD_PATH" + (query?.let { "?$it" } ?: "")
    }

    /** The server's download when no welcome named one (the 4400 case). */
    fun fallbackUrl(server: String): String? = origin(server)?.let { "${it.scheme}://${it.authority}${it.prefix}$DOWNLOAD_PATH" }
}

/** What the phone reads from an APK (a download, or itself): its package, versionCode and the SHA-256 of each
 *  certificate that signs its contents (lower-case hex). */
data class ApkFacts(val pkg: String, val versionCode: Long, val signers: Set<String>)

/** Why a downloaded update isn't handed to Android's installer (review 5 P5-L3, owner 2026-10-21). */
enum class ApkRefusal { NOT_AN_APP, OTHER_APP, UNSIGNED, OTHER_SIGNER, NOT_NEWER }

/** The in-app check of a downloaded update, before Android's installer sees it (pure; JVM-tested). */
object ApkCheck {
    const val PACKAGE = "dev.openmob.companion"

    /** Null: hand it to the installer. Else why not: not an APK the phone could read, another app (a different
     *  package would install as a new app named OpenMob), no signer, a signer other than this app's own (exactly the
     *  same set), or a versionCode not strictly above this app's. */
    fun verify(downloaded: ApkFacts?, installed: ApkFacts, expected: String = PACKAGE): ApkRefusal? = when {
        downloaded == null -> ApkRefusal.NOT_AN_APP
        downloaded.pkg != expected || installed.pkg != expected -> ApkRefusal.OTHER_APP
        downloaded.signers.isEmpty() || installed.signers.isEmpty() -> ApkRefusal.UNSIGNED
        downloaded.signers != installed.signers -> ApkRefusal.OTHER_SIGNER
        downloaded.versionCode <= installed.versionCode -> ApkRefusal.NOT_NEWER
        else -> null
    }

    /** SHA-256 of a certificate's DER bytes, lower-case hex. */
    fun fingerprint(der: ByteArray): String =
        java.security.MessageDigest.getInstance("SHA-256").digest(der).joinToString("") { "%02x".format(it) }
}

/**
 * The app's view of updates: what the last welcome said (in memory), what the owner put off and the last download
 * link (in prefs), and the Download button. Updates come only from the paired server's pinned download link. OpenMob
 * downloads the APK into its own cache and checks it before Android's installer sees it ([ApkCheck]: this package,
 * this app's own signer, a higher versionCode); Android checks the signer again when it installs the update.
 */
object AppUpdates {
    private const val TAG = "OpenMobUpdates"
    private const val PREFS = "openmob_updates"
    private const val CHANNEL = "updates"
    private const val NOTIFICATION_ID = 8

    val current: Int get() = BuildConfig.VERSION_CODE
    val hash: String get() = BuildConfig.GIT_HASH

    @Volatile var info: UpdateInfo? = null
        private set
    @Volatile var tooOld: Boolean = false
        private set

    private fun prefs(context: Context) = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun dismissed(context: Context): Int = prefs(context).getInt("dismissed_latest", 0)

    fun state(context: Context): UpdateState = UpdateLogic.state(current, info, dismissed(context), tooOld)

    /** The welcome's app_update (null from an older server). Posts the one "update required" notification. */
    fun onWelcome(context: Context, json: JSONObject?) {
        val parsed = UpdateInfo.parse(json)
        info = parsed
        tooOld = false
        parsed?.url?.let { prefs(context).edit().putString("last_url", it).apply() }
        val state = state(context)
        if (state is UpdateState.Required) notifyRequired(context, state.minimum) else cancelNotification(context)
        AppState.notifyListeners()
    }

    /** The server closed with 4400: this app is too old for its protocol. */
    fun onTooOld(context: Context) {
        tooOld = true
        AppState.notifyListeners()
    }

    /** Later or ✕ on Home's banner: hidden until the server offers something newer than [latest]. */
    fun dismiss(context: Context, latest: Int) {
        if (latest > dismissed(context)) prefs(context).edit().putInt("dismissed_latest", latest).apply()
        AppState.notifyListeners()
    }

    /** The link Download opens, checked against the paired server; null (and logged) when there is none. */
    fun downloadUrl(context: Context, log: Boolean = false): String? {
        val server = Settings(context).server
        // While connected, only this welcome's link (null: the server has no APK to give); after a 4400, the last one.
        val named = if (tooOld) info?.url ?: prefs(context).getString("last_url", null) else info?.url
        if (named != null) {
            UpdateLogic.safeDownloadUrl(named, server)?.let { return it }
            if (log) Log.w(TAG, "Not opening a download link that isn't this phone's server's /download/openmob.apk")
            return null
        }
        return if (tooOld) UpdateLogic.fallbackUrl(server) else null
    }

    /** At most this many bytes are downloaded (the APK is about 20 MB). */
    private const val MAX_BYTES = 200L * 1024 * 1024
    private const val APK_DIR = "updates"
    private const val APK_FILE = "openmob-update.apk"
    @Volatile private var downloading = false

    /** Download: OpenMob downloads the server's APK (the pinned link only, no redirects) into its own cache, checks it
     *  ([ApkCheck]) and only then hands it to Android's installer, which asks the owner. False: the link isn't the
     *  paired server's, so nothing starts. The outcome is told on screen (a short message). */
    fun openDownload(context: Context): Boolean {
        val url = downloadUrl(context, log = true) ?: return false
        val app = context.applicationContext
        if (downloading) { toast(app, R.string.update_downloading); return true }
        downloading = true
        toast(app, R.string.update_downloading)
        downloader(app, url)
        return true
    }

    /** Starts the download and check in the background (tests replace it). */
    internal var downloader: (Context, String) -> Unit = { app, url ->
        Thread({
            val message = try { downloadAndInstall(app, url) } catch (e: Exception) {
                Log.w(TAG, "update download failed: ${e.javaClass.simpleName}")
                R.string.update_download_failed
            } finally { downloading = false }
            message?.let { toast(app, it) }
        }, "openmob-update").apply { isDaemon = true }.start()
    }

    /** The background download ended (tests: their replacement [downloader] calls it). */
    internal fun downloadEnded() { downloading = false }

    /** Blocking: null when the installer was opened, else the message to show. */
    private fun downloadAndInstall(app: Context, url: String): Int? {
        val dir = java.io.File(app.cacheDir, APK_DIR).apply { mkdirs() }
        val file = java.io.File(dir, APK_FILE)
        file.delete()
        val client = okhttp3.OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
            .callTimeout(java.time.Duration.ofMinutes(5)).build()
        client.newCall(okhttp3.Request.Builder().url(url).build()).execute().use { response ->
            if (response.code != 200) return R.string.update_download_failed
            val body = response.body ?: return R.string.update_download_failed
            if (body.contentLength() > MAX_BYTES) return R.string.update_download_failed
            body.byteStream().use { input ->
                file.outputStream().use { out ->
                    val buf = ByteArray(64 * 1024)
                    var total = 0L
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        total += n
                        if (total > MAX_BYTES) { file.delete(); return R.string.update_download_failed }
                        out.write(buf, 0, n)
                    }
                }
            }
        }
        val refusal = ApkCheck.verify(archiveFacts(app, file), installedFacts(app))
        if (refusal != null) {
            Log.w(TAG, "update refused: $refusal")
            file.delete()
            return when (refusal) {
                ApkRefusal.NOT_AN_APP -> R.string.update_refused_not_app
                ApkRefusal.OTHER_APP -> R.string.update_refused_other_app
                ApkRefusal.UNSIGNED, ApkRefusal.OTHER_SIGNER -> R.string.update_refused_signer
                ApkRefusal.NOT_NEWER -> R.string.update_refused_not_newer
            }
        }
        val uri = androidx.core.content.FileProvider.getUriForFile(app, "${app.packageName}.updates", file)
        app.startActivity(installIntent(uri))
        return null
    }

    /** The system package installer's own action (review 5 re-review info): an ACTION_VIEW of an APK could be
     *  answered by any app that claims the type; only the package installer handles ACTION_INSTALL_PACKAGE. */
    @Suppress("DEPRECATION")
    fun installIntent(uri: android.net.Uri): Intent = Intent(Intent.ACTION_INSTALL_PACKAGE)
        .setDataAndType(uri, "application/vnd.android.package-archive")
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)

    private fun signers(info: android.content.pm.PackageInfo?): Set<String> =
        info?.signingInfo?.apkContentsSigners?.map { ApkCheck.fingerprint(it.toByteArray()) }?.toSet().orEmpty()

    private fun facts(info: android.content.pm.PackageInfo?): ApkFacts? =
        info?.let { ApkFacts(it.packageName.orEmpty(), it.longVersionCode, signers(it)) }

    @Suppress("DEPRECATION")
    private fun archiveFacts(app: Context, file: java.io.File): ApkFacts? = runCatching {
        facts(app.packageManager.getPackageArchiveInfo(file.path, android.content.pm.PackageManager.GET_SIGNING_CERTIFICATES))
    }.getOrNull()

    @Suppress("DEPRECATION")
    private fun installedFacts(app: Context): ApkFacts =
        facts(app.packageManager.getPackageInfo(app.packageName, android.content.pm.PackageManager.GET_SIGNING_CERTIFICATES))
            ?: ApkFacts(app.packageName, current.toLong(), emptySet())

    private fun toast(app: Context, message: Int) {
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            android.widget.Toast.makeText(app, message, android.widget.Toast.LENGTH_LONG).show()
        }
    }

    /** One notification per raised minimum: generic text (review 4 M3), private on the lock screen. */
    private fun notifyRequired(context: Context, minimum: Int) {
        val p = prefs(context)
        if (p.getInt("notified_minimum", 0) >= minimum) return
        p.edit().putInt("notified_minimum", minimum).apply()
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(NotificationChannel(CHANNEL, context.getString(R.string.update_channel),
                                                                  NotificationManager.IMPORTANCE_DEFAULT))
        }
        val open = PendingIntent.getActivity(context, 8, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val title = context.getString(R.string.update_notif_title)
        runCatching {
            manager.notify(NOTIFICATION_ID, Notification.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_openmob_tile)
                .setContentTitle(title)
                .setContentText(context.getString(R.string.update_notif_text))
                .setContentIntent(open)
                .setAutoCancel(true)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setPublicVersion(NotificationPrivacy.publicVersion(context, CHANNEL, title))
                .build())
        }
    }

    private fun cancelNotification(context: Context) {
        runCatching { context.getSystemService(NotificationManager::class.java)?.cancel(NOTIFICATION_ID) }
    }
}
