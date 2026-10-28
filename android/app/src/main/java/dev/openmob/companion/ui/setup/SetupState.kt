package dev.openmob.companion.ui.setup

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.PowerManager
import dev.openmob.companion.AccountApi
import dev.openmob.companion.AppState
import dev.openmob.companion.ConnectionService
import dev.openmob.companion.OpenMobAccessibilityService
import dev.openmob.companion.PairingFlow
import dev.openmob.companion.Settings

/** The typed code's shape (docs/design/pairing-code.md §2): 6 characters from 31, any case, spaces and dashes ignored. */
object TypedCode {
    const val ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
    const val LENGTH = 6
    private val IGNORED = Regex("[\\s\\-‐‑‒–—−]")

    /** The code as the server reads it, or null if it can't be one (it then isn't sent: no try is used). */
    fun normalize(typed: String): String? {
        val s = typed.replace(IGNORED, "").uppercase()
        return s.takeIf { it.length == LENGTH && it.all { ch -> ch in ALPHABET } }
    }
}

/** The phone's setup as the screens show it (MainActivity's checklist reads the same). */
data class PhoneSetup(
    val paired: Boolean = false,
    val server: String = "",
    val email: String = "",
    val accessibilityOn: Boolean = false,
    val notificationsOn: Boolean = false,
    val batteryUnrestricted: Boolean = false,
    val running: Boolean = false,
    val connected: Boolean = false,
    /** Settings.smoothLiveView: offer screen sharing for the dashboard's live view. */
    val smoothLiveView: Boolean = true,
    val screenSharing: Boolean = false,
    /** Someone opened the live view on the dashboard while this phone shared no screen. */
    val liveViewRequested: Boolean = false,
    val deviceId: String = "",
    /** Paired by developer token (legacy token mode), not by account. */
    val tokenMode: Boolean = false,
    val samsung: Boolean = false,
    /** Android 13+ may block Accessibility for this sideloaded app until "Allow restricted settings". */
    val restricted: Boolean = false,
    /** This phone's Build.MODEL (what the dashboard shows while a typed code waits). */
    val model: String = "",
) {
    val host: String get() = if (server.isBlank()) "" else PairingFlow.hostOf(server)
}

/** A checked code: the account it would pair with (from /api/pair/check) and the server the phone asked. */
data class Checked(val server: String, val code: String, val email: String) {
    val host: String get() = PairingFlow.hostOf(server)
}

/** An error to show: one of the phone's own strings, or a text that PairingFlow.errorText let through. */
sealed interface SetupError {
    data class Local(val res: Int) : SetupError
    data class Shown(val text: String) : SetupError
}

enum class LockRequest { Pair, Unpair, Token }
enum class SetupNext { Code, Confirm, Replace, Consent, Ready }

data class SetupUiState(
    val phone: PhoneSetup = PhoneSetup(),
    /** Where a typed code goes: the hosted server, or the owner's own (More options). */
    val server: String = PairingFlow.HOSTED_SERVER,
    val serverInput: String = "",
    val serverError: Int? = null,
    val code: String = "",
    val codeError: SetupError? = null,
    val confirmError: SetupError? = null,
    val busy: Boolean = false,
    val checked: Checked? = null,
    /** The screen should show the screen-lock prompt for this (then call lockShown). */
    val lock: LockRequest? = null,
    /** Just paired with this account (for Paired / Ready). */
    val paired: String? = null,
    /** Where the flow goes next (the screen navigates, then calls navigated). */
    val next: SetupNext? = null,
    /** The sign-in fallback's or developer token's error (phone words, or a server sentence errorText let through). */
    val formError: SetupError? = null,
    /** A developer token waiting for "Connect to <host>?" (server, token). */
    val tokenPending: Pair<String, String>? = null,
    /** A one-off message (a string resource) for a toast. */
    val notice: Int? = null,
    /** Android's notification permission was asked once before pairing (UX review 2, item 5). */
    val notificationsAsked: Boolean = false,
)

/** What setup needs from the phone: PairingFlow, AccountApi and Settings, behind an interface for the tests. */
interface SetupBackend {
    fun phone(): PhoneSetup
    fun defaultServer(): String
    fun screenLockReady(): Boolean
    /** /api/pair/check with this phone's device_id and model; returns the account's email. Throws on failure. */
    fun check(server: String, code: String): String
    /** /api/pair/claim, then save (PairingFlow.claimAndSave). Throws on failure; nothing saved then. */
    fun claim(server: String, code: String, email: String)
    /** The "Paired with … · Undo" notification, and connect as MainActivity does after pairing. */
    fun afterPaired(server: String, email: String, wasRunning: Boolean)
    fun unpair()
    /** The sign-in fallback (PairingFlow.signInForCode): the minted code and the account's email. Throws on failure. */
    fun signInForCode(server: String, email: String, password: String, create: Boolean, invite: String): Pair<String, String>
    /** Developer token (PairingFlow.saveToken), then connect as the old screen did. */
    fun saveToken(server: String, token: String, wasRunning: Boolean)
    fun setSmoothLiveView(on: Boolean)
    fun connect()
    fun disconnect()
    fun errorText(error: Throwable): String
    fun listen(onChange: () -> Unit): () -> Unit
}

class AppSetupBackend(context: Context) : SetupBackend {
    private val app = context.applicationContext
    private val settings = Settings(app)

    override fun phone(): PhoneSetup {
        val permission = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            app.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        return PhoneSetup(
            paired = PairingFlow.isPaired(settings),
            server = settings.server,
            email = settings.email,
            accessibilityOn = OpenMobAccessibilityService.instance != null,
            notificationsOn = permission && app.getSystemService(NotificationManager::class.java)?.areNotificationsEnabled() == true,
            batteryUnrestricted = app.getSystemService(PowerManager::class.java)?.isIgnoringBatteryOptimizations(app.packageName) == true,
            running = ConnectionService.isRunning,
            connected = AppState.connected,
            smoothLiveView = settings.smoothLiveView,
            screenSharing = AppState.screenSharing,
            liveViewRequested = AppState.liveViewRequested,
            deviceId = settings.deviceId,
            tokenMode = settings.deviceKey.isEmpty() && settings.token.isNotEmpty(),
            model = Build.MODEL,
            restricted = dev.openmob.companion.SetupIntents.accessibilityRestriction(app) !=
                dev.openmob.companion.AccessibilitySetup.Restriction.NONE,
            samsung = dev.openmob.companion.Pairing.batteryGuide(Build.MANUFACTURER) == dev.openmob.companion.Pairing.BatteryGuide.SAMSUNG,
        )
    }

    override fun defaultServer(): String = PairingFlow.HOSTED_SERVER
    override fun screenLockReady(): Boolean = PairingFlow.screenLockReady(app)
    override fun check(server: String, code: String): String = AccountApi(server).check(code, settings.deviceId, Build.MODEL).email
    override fun claim(server: String, code: String, email: String) = PairingFlow.claimAndSave(app, settings, server, code, email)

    override fun afterPaired(server: String, email: String, wasRunning: Boolean) {
        PairingFlow.notifyPaired(app, server, settings.email.ifBlank { email })
        if (OpenMobAccessibilityService.instance != null || wasRunning) PairingFlow.reconnect(app)
    }

    override fun unpair() = PairingFlow.unpair(app, settings)
    override fun signInForCode(server: String, email: String, password: String, create: Boolean, invite: String) =
        PairingFlow.signInForCode(server, email, password, create, invite)
    override fun saveToken(server: String, token: String, wasRunning: Boolean) {
        PairingFlow.saveToken(app, settings, server, token)
        if (wasRunning || OpenMobAccessibilityService.instance != null) PairingFlow.reconnect(app)
    }
    override fun setSmoothLiveView(on: Boolean) { settings.smoothLiveView = on }
    override fun connect() { if (PairingFlow.isPaired(settings)) ConnectionService.start(app) }
    override fun disconnect() { ConnectionService.stop(app) }
    override fun errorText(error: Throwable): String = PairingFlow.errorText(app, error)
    override fun listen(onChange: () -> Unit): () -> Unit = AppState.listen(onChange)
}
