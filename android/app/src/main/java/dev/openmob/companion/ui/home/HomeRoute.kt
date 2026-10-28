package dev.openmob.companion.ui.home

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.speech.RecognizerIntent
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.openmob.companion.ApprovalActivity
import dev.openmob.companion.Approvals
import dev.openmob.companion.R

/** Home wired to the phone: the ViewModel's state, and the same screens and intents MainActivity uses. */
@Composable
fun HomeRoute(
    openSettings: () -> Unit,
    openActivity: () -> Unit,
    openSetup: () -> Unit = {},
    openRoute: (dev.openmob.companion.ui.nav.Route) -> Unit = {},
    vm: HomeViewModel = viewModel(factory = HomeViewModel.factory(LocalContext.current)),
) {
    val context = LocalContext.current
    val state by vm.state.collectAsStateWithLifecycle()
    val notice by vm.notice.collectAsStateWithLifecycle()
    LaunchedEffect(notice) {
        notice?.let { Toast.makeText(context, it, Toast.LENGTH_SHORT).show(); vm.noticeShown() }
    }
    val draft = rememberDraft()
    val speech = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val heard = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
        // Dictation fills the composer; the owner sends it (never sent by itself).
        if (result.resultCode == android.app.Activity.RESULT_OK && !heard.isNullOrBlank()) {
            draft.value = listOf(draft.value.trimEnd(), heard.trim()).filter { it.isNotEmpty() }.joinToString(" ")
        }
    }
    val bar by vm.disconnectedBar.collectAsStateWithLifecycle()
    HomeScreen(
        state = state,
        draft = draft,
        disconnectedBar = bar,
        actions = HomeActions(
            stopTask = vm::stopTask,
            disconnect = vm::disconnect,
            connect = vm::connect,
            send = vm::send,
            speak = {
                // The system recognizer, one result, into the composer.
                val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                    .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    .putExtra(RecognizerIntent.EXTRA_PROMPT, context.getString(R.string.ui_speech_prompt))
                    .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
                try { speech.launch(intent) } catch (e: ActivityNotFoundException) {
                    Toast.makeText(context, R.string.ui_no_speech, Toast.LENGTH_SHORT).show()
                }
            },
            // Approving always goes through the review screen and its screen-lock check (as MainActivity).
            review = { id -> context.startActivity(Intent(context, ApprovalActivity::class.java).putExtra(Approvals.EXTRA_ID, id)) },
            deny = vm::deny,
            answer = vm::answerQuestion,
            openSettings = openSettings,
            openActivity = openActivity,
            openSetup = openSetup,
            openRoute = openRoute,
            setModel = vm::setModel,
            openChat = vm::openChat,
            newChat = vm::newChat,
            renameChat = vm::renameChat,
            deleteChat = vm::deleteChat,
            moreChats = vm::moreChats,
            olderTurns = vm::olderTurns,
            searchChats = vm::searchChats,
            memoryConfirm = vm::memoryConfirm,
            memoryDismiss = vm::memoryDismiss,
            disconnectedBarShown = vm::disconnectedBarShown,
            chatNoticeShown = vm::chatNoticeShown,
            downloadUpdate = vm::downloadUpdate,
            dismissUpdate = vm::dismissUpdate,
            fixIssue = { issue ->
                val activity = context.findActivity()
                when (issue) {
                    // Accessibility only ever through the consent screen (the disclosure first, S10).
                    Issue.Accessibility -> openRoute(dev.openmob.companion.ui.nav.Route.SetupConsent)
                    Issue.Notifications -> activity?.let { dev.openmob.companion.SetupIntents.openNotificationSettings(it) }
                    Issue.Background -> activity?.let { dev.openmob.companion.SetupIntents.requestBatteryExemption(it) }
                }
            },
            backToApp = { pkg ->
                context.packageManager.getLaunchIntentForPackage(pkg)?.let { runCatching { context.startActivity(it) } }
            },
        ),
    )
}

private tailrec fun Context.findActivity(): android.app.Activity? = when (this) {
    is android.app.Activity -> this
    is android.content.ContextWrapper -> baseContext.findActivity()
    else -> null
}
