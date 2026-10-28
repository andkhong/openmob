package dev.openmob.companion.ui.setup

import android.Manifest
import android.app.Activity
import android.os.Build
import android.os.CancellationSignal
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.openmob.companion.ConnectionService
import dev.openmob.companion.PairingFlow
import dev.openmob.companion.SetupIntents
import dev.openmob.companion.Settings
import android.widget.Toast
import dev.openmob.companion.R
import dev.openmob.companion.ui.nav.Route

/**
 * One setup screen wired to the shared [SetupViewModel] (scoped to the activity, so the steps share one flow) and to
 * the existing prompts and system screens (PairingFlow, SetupIntents). The screen lock is shown here, from the
 * ViewModel's request, and its result goes back to it.
 */
@Composable
fun SetupRoute(route: Route, navigate: (Route) -> Unit, back: () -> Unit, finish: () -> Unit) {
    val context = LocalContext.current
    val activity = context as? ComponentActivity
    val vm: SetupViewModel = if (activity != null) viewModel(viewModelStoreOwner = activity, factory = SetupViewModel.factory(context))
        else viewModel(factory = SetupViewModel.factory(context))
    val state by vm.state.collectAsStateWithLifecycle()
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { vm.refresh() } // back from Android's Settings

    LaunchedEffect(state.next) {
        val next = state.next ?: return@LaunchedEffect
        vm.navigated()
        navigate(when (next) {
            SetupNext.Code -> Route.SetupPairCode
            SetupNext.Confirm -> Route.SetupConfirm
            SetupNext.Replace -> Route.SetupReplace
            SetupNext.Consent -> Route.SetupConsent
            SetupNext.Ready -> Route.SetupReady
        })
    }

    // The screen lock, as the ViewModel asks for it (PairingFlow's prompts, shared with MainActivity).
    val cancel = remember { arrayOfNulls<CancellationSignal>(1) }
    DisposableEffect(Unit) { onDispose { cancel[0]?.cancel() } }
    LaunchedEffect(state.lock) {
        val request = state.lock ?: return@LaunchedEffect
        val host = activity as? Activity ?: return@LaunchedEffect
        if (request == LockRequest.Token) {
            val pending = state.tokenPending ?: return@LaunchedEffect
            vm.lockShown()
            cancel[0]?.cancel()
            val signal = CancellationSignal().also { cancel[0] = it }
            // Replacing a pairing with a developer token needs the screen lock (the old screen's requireScreenLockToReplace).
            PairingFlow.unpairPrompt(host, Settings(host), pending.first, signal, onOk = { vm.lockPassed(LockRequest.Token) },
                                     onError = { code, text -> vm.lockFailed(PairingFlow.cancelled(code), text?.toString()) })
            return@LaunchedEffect
        }
        val checked = state.checked ?: return@LaunchedEffect
        vm.lockShown()
        cancel[0]?.cancel()
        val signal = CancellationSignal().also { cancel[0] = it }
        val settings = Settings(host)
        val onError: (Int, CharSequence?) -> Unit = { code, text -> vm.lockFailed(PairingFlow.cancelled(code), text?.toString()) }
        when (request) {
            LockRequest.Token -> Unit
            LockRequest.Pair -> PairingFlow.confirmPrompt(host, settings, checked.server, checked.email, signal,
                                                          onOk = { vm.lockPassed(LockRequest.Pair) }, onError = onError)
            LockRequest.Unpair -> PairingFlow.unpairPrompt(host, settings, checked.server, signal,
                                                           onOk = { vm.lockPassed(LockRequest.Unpair) }, onError = onError)
        }
    }

    val notifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { vm.refresh() }
    // Before pairing, so the first pairing's "Paired · Undo" can show (UX review 2, item 5). Asked once; if it's
    // denied, the confirm screen says no Undo notice will appear and how to undo.
    LaunchedEffect(route) {
        val pairing = route == Route.SetupPairCode || route == Route.SetupPairMore || route == Route.SetupSignIn
        if (pairing && !state.notificationsAsked && !state.phone.notificationsOn && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            vm.notificationsAsked()
            notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
    val actions = SetupActions(
        back = back,
        getStarted = { navigate(Route.SetupPair) },
        typeCode = { navigate(Route.SetupPairCode) },
        moreOptions = { navigate(Route.SetupPairMore) },
        scanInstead = { navigate(Route.SetupPair) },
        setCode = vm::setCode,
        setServer = vm::setServer,
        submitCode = { vm.submitCode() },
        submitOwnServer = { vm.submitCode(fromMore = true) },
        signIn = { navigate(Route.SetupSignIn) },
        developerToken = { navigate(Route.SetupToken) },
        confirm = vm::confirm,
        notMe = vm::notMe,
        unpair = vm::unpairForReplace,
        keep = finish,
        // The consent screen is the disclosure: only its Agree opens Android's Accessibility settings.
        agree = {
            if (state.phone.accessibilityOn) navigate(Route.SetupReady)
            else activity?.let {
                // App info only offers approval after Android has shown its first denial (the old screen's rule).
                if (SetupIntents.accessibilityRestriction(it) == dev.openmob.companion.AccessibilitySetup.Restriction.NEEDS_APPROVAL)
                    SetupIntents.openAppInfo(it) else SetupIntents.openAccessibilitySettings(it)
            }
        },
        notNow = { navigate(Route.SetupReady) },
        cantTurnOn = { activity?.let { SetupIntents.openAppInfo(it) } },
        samsungSleep = {
            activity?.let { if (SetupIntents.openSamsungSleepingApps(it)) Toast.makeText(it, R.string.ui_samsung_sleep_hint, Toast.LENGTH_LONG).show() }
        },
        notifications = {
            val granted = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == android.content.pm.PackageManager.PERMISSION_GRANTED
            if (granted || Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) activity?.let { SetupIntents.openNotificationSettings(it) }
            else notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        },
        battery = { activity?.let { SetupIntents.requestBatteryExemption(it) } },
        connect = { if (state.phone.paired) ConnectionService.start(context) },
        home = finish,
    )
    LaunchedEffect(state.notice) {
        state.notice?.let { Toast.makeText(context, it, Toast.LENGTH_SHORT).show(); vm.noticeShown() }
    }
    when (route) {
        Route.SetupSignIn -> SetupSignInScreen(state, onSubmit = vm::signIn, back = back)
        Route.SetupToken -> SetupTokenScreen(state, onSubmit = vm::submitToken, onConfirm = vm::confirmToken,
                                             onCancel = vm::cancelToken, back = back)
        Route.Connection -> ConnectionScreen(state, ConnectionActions(
            back = back,
            connect = vm::connect,
            disconnect = vm::disconnect,
            liveView = { on ->
                vm.setSmoothLiveView(on)
                // Turned on while connected: ask now rather than at the next Connect (as before).
                if (on && state.phone.running) (activity as? dev.openmob.companion.MainActivity)?.askForScreenSharing()
            },
            shareScreen = { (activity as? dev.openmob.companion.MainActivity)?.askForScreenSharing() },
            unpair = vm::unpairNow,
            pairAgain = { navigate(Route.SetupPair) },
        ))
        else -> SetupScreenFor(route, state, actions)
    }
}

/** The screen for a setup route, drawn from state alone (the previews and screenshot tests use this). */
@Composable
fun SetupScreenFor(route: Route, state: SetupUiState, actions: SetupActions) {
    when (route) {
        Route.SetupWelcome -> SetupWelcomeScreen(actions)
        Route.SetupPair -> SetupPairScreen(actions)
        Route.SetupPairCode -> SetupCodeScreen(state, actions)
        Route.SetupPairMore -> SetupMoreScreen(state, actions)
        Route.SetupConfirm -> SetupConfirmScreen(state, actions)
        Route.SetupReplace -> SetupReplaceScreen(state, actions)
        Route.SetupConsent -> SetupConsentScreen(state, actions)
        Route.SetupReady -> SetupReadyScreen(state, actions)
        // Drawn from state only (previews, tests); SetupRoute wires these three itself.
        Route.SetupSignIn -> SetupSignInScreen(state, onSubmit = { _, _, _, _, _ -> }, back = actions.back)
        Route.SetupToken -> SetupTokenScreen(state, onSubmit = { _, _ -> }, onConfirm = {}, onCancel = {}, back = actions.back)
        Route.Connection -> ConnectionScreen(state, ConnectionActions(back = actions.back))
        else -> Unit
    }
}
