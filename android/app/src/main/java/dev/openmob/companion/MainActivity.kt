package dev.openmob.companion

import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Intent
import android.media.projection.MediaProjectionConfig
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.provider.Settings as AndroidSettings
import android.speech.RecognizerIntent
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import dev.openmob.companion.ui.nav.OpenMobNavHost
import dev.openmob.companion.ui.nav.Route
import java.util.concurrent.Executors

/**
 * The app (redesign step 6): the Compose screens (ui/), plus what only an activity can do. The launcher, shortcuts and
 * tile, pairing links, the screen-sharing consent and voice input all land here.
 *
 * Pairing links (`openmob://connect?server=…&code=…`, from the dashboard's QR code or `openmob phone add`) never pair by
 * themselves: the screen lock must be set up, the code is checked, then Android's screen-lock prompt names the server
 * and account (PairingFlow.confirmPrompt), and only then is the code claimed (PairingFlow.claimAndSave). This is the
 * old MainActivity's flow, unchanged, through PairingFlow (docs/design/redesign-setup.md, S1–S4).
 */
class MainActivity : ComponentActivity() {
    private lateinit var settings: Settings
    private val main = Handler(Looper.getMainLooper())
    private val background = Executors.newSingleThreadExecutor() // account/pairing HTTP calls
    private var approval: CancellationSignal? = null
    private var nav: NavHostController? = null
    private var pendingRoute: Route? = null

    /** Android's "Start recording or casting?" result: connect either way (declining means screenshots, not video). */
    private val screenShare = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode != RESULT_OK) {
            settings.smoothLiveView = false // remembered: Connect won't ask again
            toast(getString(R.string.ui_live_view_declined))
        }
        ConnectionService.start(this, result.data.takeIf { result.resultCode == RESULT_OK }, result.resultCode)
    }

    /** A pairing link waiting for the notification-permission answer (asked first so "Paired · Undo" can show). */
    private var linkAfterPermission: Pair<String, String>? = null
    private val notificationsFirst = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        linkAfterPermission?.let { (server, code) -> linkAfterPermission = null; checkAndConfirm(server, code) }
    }

    /** The Ask shortcut: the system recognizer, one result, sent as a request. */
    private val speech = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val heard = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
        if (result.resultCode == RESULT_OK && !heard.isNullOrBlank() && !ConnectionService.sendCommand(heard)) {
            toast(getString(R.string.ui_not_connected))
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        settings = Settings(this)
        TaskHistory.init(this)
        // An older version kept a full dashboard session after pairing: sign it out and forget it.
        val legacySession = settings.takeLegacySession()
        val legacyServer = settings.server
        if (legacySession.isNotEmpty() && legacyServer.isNotBlank()) {
            background.execute { AccountApi(legacyServer).logout(legacySession) }
        }
        val own = ownEntry(intent) // before cleanIntent, which rebuilds the component
        // Before the NavHost reads it: only the action and the link survive (review 3 P3-L3, see [cleanIntent]).
        intent = cleanIntent(intent)
        setContent {
            val controller = rememberNavController()
            nav = controller
            dev.openmob.companion.ui.theme.OpenMobTheme { OpenMobNavHost(navController = controller) }
            pendingRoute?.let { r -> pendingRoute = null; main.post { go(r) } }
        }
        // On recreation (rotation, dark-mode switch) the link or shortcut was already handled.
        if (savedInstanceState == null) handleIntent(intent, own)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val own = ownEntry(intent)
        val clean = cleanIntent(intent)
        setIntent(clean) // a recreation's NavHost reads this one again
        handleIntent(clean, own)
    }

    /** Came through [Shortcuts.ENTRY], which isn't exported: OpenMob's own shortcut, tile or notification (review 4
     *  L6). Another app can start this activity with any action, but not that component. */
    internal fun ownEntry(intent: Intent?): Boolean = intent?.component?.className == Shortcuts.ENTRY

    /** This activity is exported (the launcher, shortcuts and pairing links start it), and Navigation's NavHost follows
     *  any intent's deep-link extras (NavController.KEY_DEEP_LINK_IDS and the like) to any screen of the graph, with no
     *  deep link declared. OpenMob's own intents carry only an action (shortcuts, the tile) or a link (pairing), so
     *  every intent is rebuilt from those two alone: no extras reach the NavHost (review 3 P3-L3, 2026-10-18). */
    internal fun cleanIntent(intent: Intent?): Intent =
        Intent(this, MainActivity::class.java).setAction(intent?.action).setData(intent?.data)

    override fun onDestroy() {
        approval?.cancel()
        approval = null
        background.shutdown() // lets an in-flight call finish; its UI callback is skipped
        main.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun go(route: Route) {
        val n = nav
        if (n == null) { pendingRoute = route; return }
        runCatching { n.navigate(route.path) { launchSingleTop = true } }
    }

    /** Home (the start screen), with the screens opened over it closed. A cold start needs nothing: it opens there. */
    private fun goHome() {
        val n = nav ?: return
        runCatching {
            n.navigate(Route.Home.path) { popUpTo(Route.Home.path) { inclusive = false }; launchSingleTop = true }
        }
    }

    // ---------------------------------------------------------------- intents

    private fun handleIntent(intent: Intent?, own: Boolean) {
        when (val action = intent?.action) {
            in Shortcuts.all -> {
                setIntent(Intent(this, MainActivity::class.java)) // handle once, not again on recreate
                // From another app (this activity is exported): just open the app. Connect after the owner's
                // Disconnect, voice input or the screen-sharing prompt only from OpenMob's own entry (review 4 L6).
                if (own && action != null) runShortcut(action)
                return
            }
            AgentQuestion.ACTION_OPEN_HOME -> { // the agent's question notification: the composer answers on Home
                setIntent(Intent(this, MainActivity::class.java))
                goHome()
                return
            }
        }
        val data = intent?.data ?: return
        // Don't re-handle the same link if the activity is recreated from this intent later.
        setIntent(Intent(this, MainActivity::class.java))
        // A link never changes anything by itself: developer-token links aren't accepted at all, and account links
        // only after the owner confirms the server and account with the screen lock.
        when (val link = Pairing.parse(data.toString())) {
            null -> return
            Pairing.Link.TokenRefused -> toast(getString(R.string.ui_token_link_refused))
            Pairing.Link.Invalid -> toast(getString(R.string.ui_bad_link))
            is Pairing.Link.Account -> startAccountPairing(link.server, link.code)
        }
    }

    private fun runShortcut(action: String) {
        when (action) {
            // The consent screen: its disclosure comes before anything is granted.
            Shortcuts.OPEN_ACCESSIBILITY -> if (OpenMobAccessibilityService.instance != null) {
                toast(getString(R.string.ui_step_a11y_done))
            } else go(Route.SetupConsent)
            Shortcuts.CONNECT -> when {
                !PairingFlow.isPaired(settings) -> toast(getString(R.string.shortcut_need_pairing))
                ConnectionService.isRunning -> toast(AppState.connection)
                else -> ConnectionService.start(this)
            }
            Shortcuts.ASK -> if (AppState.connected) startVoiceInput() else toast(getString(R.string.shortcut_need_connection))
            Shortcuts.SHARE_SCREEN -> if (ConnectionService.isRunning) askForScreenSharing()
                else toast(getString(R.string.shortcut_need_connection))
        }
    }

    /** Android's "Start recording or casting?" prompt (the live view's smooth video). */
    fun askForScreenSharing() {
        val projections = getSystemService(MediaProjectionManager::class.java)
        val consent = if (Build.VERSION.SDK_INT >= 34) {
            projections.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay()) // whole screen
        } else {
            projections.createScreenCaptureIntent()
        }
        try { screenShare.launch(consent) } catch (e: ActivityNotFoundException) { ConnectionService.start(this) }
    }

    private fun startVoiceInput() {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_PROMPT, getString(R.string.ui_speech_prompt))
            .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        try { speech.launch(intent) } catch (e: ActivityNotFoundException) { toast(getString(R.string.ui_no_speech)) }
    }

    // ---------------------------------------------------------------- account pairing from a link

    /** A pairing in progress. Nothing is saved (the current pairing stays as it is) until it succeeds. */
    private class Pending(val target: String, val code: String, val email: String)

    private var pending: Pending? = null

    /** A one-time code from the dashboard's QR code (or `openmob phone add`): ask the server which account it's for,
     *  then ONE confirmation, then redeem it for this phone's own device key. */
    private fun startAccountPairing(server: String, code: String) {
        // Checked first so nobody gets as far as the prompt only to be refused afterwards.
        if (!PairingFlow.screenLockReady(this)) {
            showScreenLockRequired()
            return
        }
        // Notifications first, so this pairing's "Paired · Undo" can show (UX review 2, item 5). Denied: pairing goes on.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            linkAfterPermission = server to code
            try { notificationsFirst.launch(android.Manifest.permission.POST_NOTIFICATIONS); return } catch (e: RuntimeException) { linkAfterPermission = null }
        }
        checkAndConfirm(server, code)
    }

    private fun checkAndConfirm(server: String, code: String) {
        if (isDestroyed) return
        val target = server.trim().trimEnd('/')
        toast(getString(R.string.ui_checking_code, PairingFlow.hostOf(target)))
        inBackground({ AccountApi(target).check(code) }) { result ->
            result.onSuccess { info -> confirmAndPair(Pending(target, code, info.email)) }
                .onFailure { showPairError(it) }
        }
    }

    private fun showScreenLockRequired() {
        AlertDialog.Builder(this)
            .setTitle(R.string.ui_need_screen_lock_title)
            .setMessage(R.string.ui_need_screen_lock)
            .setPositiveButton(R.string.ui_open_security_settings) { _, _ ->
                try {
                    startActivity(Intent(AndroidSettings.ACTION_SECURITY_SETTINGS))
                } catch (e: ActivityNotFoundException) {
                    startActivity(Intent(AndroidSettings.ACTION_SETTINGS))
                }
            }
            .setNegativeButton(R.string.ui_ok, null)
            .show()
    }

    /** The one confirmation: Android's own screen-lock prompt, naming the server and the account (PairingFlow). */
    private fun confirmAndPair(p: Pending) {
        if (!PairingFlow.screenLockReady(this)) {
            showScreenLockRequired()
            return
        }
        pending = p
        approval?.cancel()
        val cancel = CancellationSignal().also { approval = it }
        PairingFlow.confirmPrompt(this, settings, p.target, p.email, cancel, onOk = {
            if (approval === cancel) approval = null
            if (pending === p) claim(p)
        }, onError = { errorCode, errString ->
            if (approval === cancel) approval = null
            if (pending === p) pending = null
            if (!isDestroyed) {
                toast(if (PairingFlow.cancelled(errorCode) || errString.isNullOrBlank()) getString(R.string.ui_pair_cancelled)
                      else errString.toString())
            }
        })
    }

    /** Redeem the code (it's the credential: no session) for this phone's own device key. */
    private fun claim(p: Pending) {
        val wasRunning = ConnectionService.isRunning
        inBackground({ PairingFlow.claimAndSave(this, settings, p.target, p.code, p.email) }) { result ->
            if (pending === p) pending = null
            result.onSuccess {
                toast(getString(R.string.ui_paired_as_toast, PairingFlow.hostOf(p.target), settings.email))
                // "Paired with … · Undo" (owner, 2026-10-17): Undo needs no screen lock and removes only this pairing.
                PairingFlow.notifyPaired(this, p.target, settings.email)
                if (OpenMobAccessibilityService.instance != null || wasRunning) PairingFlow.reconnect(this)
                go(Route.Home)
            }.onFailure { showPairError(it) } // the existing pairing is untouched
        }
    }

    private fun showPairError(error: Throwable) {
        // Never a link or a code on this screen (PairingFlow.errorText; abuse series 2026-10-10).
        val detail = PairingFlow.errorText(this, error)
        // 400 = the code itself: expired, already used, or voided.
        val codeProblem = error is AccountApi.ApiError && error.status == 400
        AlertDialog.Builder(this)
            .setTitle(R.string.ui_pair_failed_title)
            .setMessage(if (codeProblem) "$detail\n\n${getString(R.string.ui_pair_new_code)}" else detail)
            .setPositiveButton(R.string.ui_ok, null)
            .show()
    }

    /** Runs [work] off the main thread, then [done] on it (skipped if this screen is gone). */
    private fun <T> inBackground(work: () -> T, done: (Result<T>) -> Unit) {
        if (background.isShutdown) return
        background.execute {
            val result = runCatching(work)
            main.post { if (!isDestroyed) done(result) }
        }
    }

    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
}
