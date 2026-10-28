package dev.openmob.companion.ui.home

import androidx.compose.foundation.Canvas
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.TextButton
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.text
import dev.openmob.companion.ui.theme.PillShape
import dev.openmob.companion.ui.components.largeText
import androidx.activity.compose.BackHandler
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.DrawerState
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.clearAndSetSemantics
import dev.openmob.companion.ui.nav.Route
import kotlinx.coroutines.launch
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedIconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.foundation.BorderStroke
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.ActivityIcon
import dev.openmob.companion.ui.components.AskingBand
import dev.openmob.companion.ui.components.BoltIcon
import dev.openmob.companion.ui.components.ButtonPair
import dev.openmob.companion.ui.components.CheckIcon
import dev.openmob.companion.ui.components.LabeledLine
import dev.openmob.companion.ui.components.LinkButton
import dev.openmob.companion.ui.components.ListRow
import dev.openmob.companion.ui.components.MetaChip
import dev.openmob.companion.ui.components.MicIcon
import dev.openmob.companion.ui.components.MonoValue
import dev.openmob.companion.ui.components.OmCard
import dev.openmob.companion.ui.components.OmTextField
import dev.openmob.companion.ui.components.PhoneIcon
import dev.openmob.companion.ui.components.PowerIcon
import dev.openmob.companion.ui.components.PrimaryButton
import dev.openmob.companion.ui.components.SecondaryButton
import dev.openmob.companion.ui.components.SendIcon
import dev.openmob.companion.ui.components.SettingsIcon
import dev.openmob.companion.ui.components.ShieldIcon
import dev.openmob.companion.ui.components.StatusChip
import dev.openmob.companion.ui.components.StatusKind
import dev.openmob.companion.ui.components.StopButton
import dev.openmob.companion.ui.components.StopSquare
import dev.openmob.companion.ui.theme.OpenMobTheme
import dev.openmob.companion.UpdateState

/** What Home's buttons do. The route wires them to [HomeViewModel] and to the existing screens. */
data class HomeActions(
    val stopTask: () -> Unit = {},
    val disconnect: () -> Unit = {},
    val connect: () -> Unit = {},
    /** True when sent (the field clears). While a task runs the server takes it as a correction; while the agent
     *  asks, as the answer. */
    val send: (String) -> Boolean = { false },
    /** Dictation: Android's speech recognizer; what it heard goes into the composer (never sent by itself). */
    val speak: () -> Unit = {},
    val review: (String) -> Unit = {},
    val deny: (String) -> Unit = {},
    val answer: (Boolean) -> Unit = {},
    val openSettings: () -> Unit = {},
    val openActivity: () -> Unit = {},
    val openSetup: () -> Unit = {},
    val backToApp: (String) -> Unit = {},
    /** A place from the drawer or the status sheet. */
    val openRoute: (Route) -> Unit = {},
    /** The model sheet's pick (§3.5): model id and effort. */
    val setModel: (String, String) -> Unit = { _, _ -> },
    /** The drawer: open a chat on Home, or a new chat (§3.6). */
    val openChat: (String) -> Unit = {},
    val newChat: () -> Unit = {},
    /** The drawer's long-press menu (§3.6): rename with a new title, or delete (after its confirmation). */
    val renameChat: (String, String) -> Unit = { _, _ -> },
    val deleteChat: (String) -> Unit = {},
    /** Paging (§3.6): the drawer reached its end; the thread reached its top. And the title search (debounced). */
    val moreChats: () -> Unit = {},
    val olderTurns: () -> Unit = {},
    val searchChats: (String) -> Unit = {},
    /** A proposal card's Save / Not now (§3.9): the phone's memory_confirm / memory_dismiss, then the chat is re-read. */
    val memoryConfirm: (String) -> Unit = {},
    val memoryDismiss: (String) -> Unit = {},
    /** An issue's fix in the status sheet (Accessibility goes through the consent screen first). */
    val fixIssue: (Issue) -> Unit = {},
    /** The "Disconnected · Reconnect" snackbar went away. */
    val disconnectedBarShown: () -> Unit = {},
    val chatNoticeShown: () -> Unit = {},
    /** App updates (§3.7): open the paired server's download; put the offered version off (Later, ✕). */
    val downloadUpdate: () -> Unit = {},
    val dismissUpdate: (Int) -> Unit = {},
)

/**
 * Home (canvas rev 6): the current chat's thread, like the web dashboard. The header has ☰ (chats and menu) and the
 * connection pill; the composer is at the bottom, with Stop task above it while working and the phone's own asks
 * (amber) above that, never in the thread. Drawn from [state] alone (tests and previews pass a state).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    state: HomeUiState,
    actions: HomeActions,
    modifier: Modifier = Modifier,
    draft: MutableState<String> = rememberDraft(),
    drawerState: DrawerState = rememberDrawerState(DrawerValue.Closed),
    sheetOpen: MutableState<Boolean> = rememberSaveable { mutableStateOf(false) },
    statusOpen: MutableState<Boolean> = rememberSaveable { mutableStateOf(false) },
    disconnectedBar: Boolean = false,
    listState: LazyListState = rememberLazyListState(),
) {
    val c = OpenMobTheme.colors
    val sp = OpenMobTheme.spacing
    val live = state.task != null
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    BackHandler(enabled = drawerState.isOpen) { scope.launch { drawerState.close() } }
    state.chatNotice?.let { id ->
        LaunchedEffect(id) { Toast.makeText(context, id, Toast.LENGTH_LONG).show(); actions.chatNoticeShown() }
    }
    ModalNavigationDrawer(
        drawerState = drawerState,
        // Closed, the drawer stays composed off screen: keep it out of TalkBack and the tests then.
        gesturesEnabled = drawerState.isOpen,
        drawerContent = {
            val hidden = drawerState.isClosed && !drawerState.isAnimationRunning
            Box(if (hidden) Modifier.clearAndSetSemantics {} else Modifier) {
                HomeDrawerSheet(
                    state,
                    onRename = { id, t -> actions.renameChat(id, t) },
                    onMore = actions.moreChats,
                    onSearch = actions.searchChats,
                    onDelete = { id -> actions.deleteChat(id) },
                    onRoute = { route -> scope.launch { drawerState.close() }; actions.openRoute(route) },
                    onChat = { id -> scope.launch { drawerState.close() }; actions.openChat(id) },
                    onNewChat = { scope.launch { drawerState.close() }; actions.newChat() },
                )
            }
        },
    ) {
        Column(modifier.fillMaxSize().background(c.ground).safeDrawingPadding()) { // safeDrawing includes the keyboard
            Box(Modifier.padding(horizontal = sp.screen).padding(top = sp.md)) {
                HomeHeader(state, onMenu = { scope.launch { drawerState.open() } },
                           onPill = { if (state.pill == PillState.Disconnected) actions.connect() else if (state.pill == PillState.Connected) statusOpen.value = true })
            }
            val connected = state.status in setOf(HomeStatus.Connected, HomeStatus.Working, HomeStatus.Asking)
            when {
                state.status == HomeStatus.NotSetUp -> Column(
                    Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = sp.screen, vertical = sp.md),
                ) { NotSetUpCard(state, actions) }
                !connected && state.update is UpdateState.TooOld -> Column(
                    Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = sp.screen, vertical = sp.md),
                    verticalArrangement = Arrangement.Center,
                ) { TooOldCard(state.updateDownloadable, onDownload = actions.downloadUpdate) }
                !connected -> OfflineBody(state, Modifier.weight(1f))
                // Below the server's minimum (§3.7): the update is the whole body; no thread (no task can run).
                state.updateRequired -> {
                    val required = state.update as UpdateState.Required
                    Column(
                        Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = sp.screen, vertical = sp.md),
                        verticalArrangement = Arrangement.Center,
                    ) {
                        UpdateRequiredCard(required.minimum, required.latest, state.currentVersion, state.updateDownloadable,
                                           onDownload = actions.downloadUpdate)
                    }
                }
                else -> {
                    (state.update as? UpdateState.Available)?.let { available ->
                        UpdateAvailableCard(available.latest, state.currentVersion, state.serverHost, state.updateDownloadable,
                                            onDownload = actions.downloadUpdate, onLater = { actions.dismissUpdate(available.latest) },
                                            modifier = Modifier.padding(horizontal = sp.screen).padding(top = sp.md))
                    }
                    ChatHeader(state)
                    Box(Modifier.weight(1f).padding(horizontal = sp.screen)) {
                        if (state.thread.isEmpty()) EmptyChat() else ThreadList(state.thread, listState, actions,
                            backTo = if (state.backToAppPackage.isNotEmpty()) state.backToAppLabel to state.backToAppPackage else null)
                        // Keep the newest in view while working, unless the owner scrolled up: then offer the jump.
                        val atBottom by remember { derivedStateOf { !listState.canScrollForward } }
                        var following by remember { mutableStateOf(true) }
                        LaunchedEffect(atBottom, listState.isScrollInProgress) { if (listState.isScrollInProgress) following = atBottom }
                        // The owner scrolled to the top, and older turns are on the server: page them in (§3.6).
                        val atTop by remember { derivedStateOf { !listState.canScrollBackward && state.thread.isNotEmpty() } }
                        LaunchedEffect(atTop, following, state.threadMore, state.thread.size) {
                            if (atTop && !following && state.threadMore) actions.olderTurns()
                        }
                        val lastKey = state.thread.lastOrNull()?.let { it.key + ((it as? ThreadItem.Live)?.progress?.step ?: 0) }
                        LaunchedEffect(lastKey) {
                            if (following && state.thread.isNotEmpty()) listState.scrollToItem(state.thread.size - 1)
                        }
                        if (live && !atBottom && !following) {
                            JumpToLatest(onClick = { following = true; scope.launch { listState.animateScrollToItem(state.thread.size - 1) } },
                                         modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 8.dp))
                        }
                    }
                }
            }
            // At large text the bottom stack can outgrow a small screen: it shares the height with the thread and scrolls.
            // reverseScrolling: it opens at its end, so the composer shows first.
            val bottom = if (largeText()) Modifier.weight(2f, fill = false).verticalScroll(rememberScrollState(), reverseScrolling = true)
                         else Modifier
            Column(bottom.padding(horizontal = sp.screen, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (disconnectedBar && !connected) DisconnectedBar(actions)
                // The phone asking (amber): above the composer, never in the thread.
                (state.ask as? HomeAsk.Approval)?.let { AskBlock(it, actions) }
                if (live && connected) {
                    StopButton(stringResource(R.string.rd_home_stop_task), onClick = actions.stopTask)
                }
                // Update required: Disconnect stays in reach (the status sheet has it too).
                if (state.updateRequired) SecondaryButton(stringResource(R.string.ui_disconnect), onClick = actions.disconnect)
                if (state.status != HomeStatus.NotSetUp) {
                    Composer(
                        draft = draft,
                        working = live,
                        answering = state.ask is HomeAsk.Question,
                        enabled = connected && state.canAsk && !state.readOnlyChat,
                        offline = !connected,
                        updateRequired = state.updateRequired,
                        models = state.models,
                        onModel = { sheetOpen.value = true },
                        onMic = actions.speak,
                        onSend = actions.send,
                    )
                }
                Text(stringResource(R.string.rd_home_never_types), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary,
                     textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
            }
        }
    }
    val models = state.models
    if (sheetOpen.value && models != null && !live) {
        ModelSheet(models, onPick = actions.setModel, onDismiss = { sheetOpen.value = false })
    }
    if (statusOpen.value && state.pill == PillState.Connected) StatusSheet(state, actions, onDismiss = { statusOpen.value = false })
}

const val TAG_MENU_BUTTON = "home-menu"
const val TAG_PILL = "home-pill"
const val TAG_MODE_CHIP = "home-mode"
const val TAG_RECONNECT = "home-reconnect"

/** Home's header (owner, 2026-10-17): ☰, the current chat's title, the connection pill. The brand is in the drawer. */
@Composable
private fun HomeHeader(state: HomeUiState, onMenu: () -> Unit, onPill: () -> Unit) {
    val c = OpenMobTheme.colors
    androidx.compose.foundation.layout.BoxWithConstraints(Modifier.fillMaxWidth()) {
        // Large text: the pill drops "· N issues" (kept in its description), and on a narrow screen its word too.
        val large = largeText()
        val pillLevel = when { !large -> 0; maxWidth >= 300.dp -> 1; else -> 2 }
        Row(Modifier.fillMaxWidth().heightIn(min = 48.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onMenu, modifier = Modifier.size(48.dp).testTag(TAG_MENU_BUTTON)) {
                Icon(Icons.Filled.Menu, contentDescription = stringResource(R.string.rd_menu), tint = c.ink)
            }
            val connected = state.status in setOf(HomeStatus.Connected, HomeStatus.Working, HomeStatus.Asking)
            // The title ellipsizes first; the pill keeps its size.
            Text(
                if (connected) state.chatTitle.ifEmpty { stringResource(R.string.rd_drawer_new_chat) } else "",
                style = MaterialTheme.typography.titleMedium, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f).padding(horizontal = 4.dp).testTag(TAG_CHAT_TITLE).semantics { heading() },
            )
            if (state.pill != PillState.NotSetUp) ConnectionPill(state, onPill, pillLevel)
        }
    }
}

const val TAG_CHAT_TITLE = "home-chat-title"

/** "● Connected", "● Connected · 1 issue", "Connecting…" or "○ Connect" (rev 5). */
@Composable
private fun ConnectionPill(state: HomeUiState, onClick: () -> Unit, level: Int = 0) {
    val c = OpenMobTheme.colors
    val n = state.issues.size
    val update = state.updateRequired // below the server's minimum (§3.7): "● Update needed", the danger dot
    val text = when {
        update -> stringResource(R.string.update_pill)
        state.pill == PillState.Connected -> if (n > 0) stringResource(R.string.rd_pill_connected) + " · " +
            pluralStringResource(R.plurals.rd_pill_issues, n, n) else stringResource(R.string.rd_pill_connected)
        state.pill == PillState.Connecting -> stringResource(R.string.rd_home_status_connecting)
        else -> stringResource(R.string.rd_pill_connect)
    }
    val description = when {
        update -> stringResource(R.string.update_pill_desc)
        else -> when (state.pill) {
        PillState.Connected -> stringResource(R.string.rd_pill_connected_desc, text) // the full text, whatever is shown
        PillState.Disconnected -> stringResource(R.string.rd_pill_connect_desc)
        else -> text
        }
    }
    val disconnected = state.pill == PillState.Disconnected
    OutlinedButton(
        onClick = onClick,
        enabled = state.pill != PillState.Connecting,
        modifier = Modifier.heightIn(min = 48.dp).testTag(TAG_PILL).semantics { contentDescription = description },
        shape = PillShape,
        border = BorderStroke(if (disconnected) 1.5.dp else 1.dp, if (disconnected) c.signal else c.outline),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = c.surface, contentColor = if (update) c.ink else c.signal,
                                                     disabledContainerColor = c.surface, disabledContentColor = c.inkSecondary),
        contentPadding = PaddingValues(horizontal = 12.dp),
    ) {
        Box(Modifier.size(8.dp).then(if (disconnected) Modifier.border(1.5.dp, c.signal, CircleShape)
                                     else Modifier.background(when {
                                         update -> c.danger
                                         state.pill == PillState.Connected -> c.signal
                                         else -> c.inkTertiary
                                     }, CircleShape)))
        val shown = when {
            update -> if (level == 2) "" else text // its word says it all; the dot alone on a narrow large-text screen
            level == 2 && state.pill == PillState.Connected -> ""
            level >= 1 && state.pill == PillState.Connected -> stringResource(R.string.rd_pill_connected)
            else -> text
        }
        if (shown.isNotEmpty()) Text(shown, style = MaterialTheme.typography.labelLarge, maxLines = 1, modifier = Modifier.padding(start = 8.dp))
        if (state.pill == PillState.Connected && level == 0) Icon(Icons.Filled.KeyboardArrowDown, contentDescription = null,
                                                   tint = c.inkSecondary, modifier = Modifier.padding(start = 2.dp).size(16.dp))
    }
}

/** The chat's title and its read-only mode chip (tap: "Change it on the dashboard"). */
@Composable
private fun ChatHeader(state: HomeUiState) {
    val c = OpenMobTheme.colors
    var hint by rememberSaveable { mutableStateOf(false) }
    Column(Modifier.padding(horizontal = OpenMobTheme.spacing.screen)) {
        modeChipLabel(state.mode)?.let { label ->
            val chip = stringResource(label)
            val desc = stringResource(R.string.rd_mode_chip_desc, chip)
            Row(
                Modifier.heightIn(min = 48.dp).clickable(role = Role.Button) { hint = !hint }.testTag(TAG_MODE_CHIP)
                    .semantics(mergeDescendants = true) { contentDescription = desc },
                verticalAlignment = Alignment.CenterVertically,
            ) { MetaChip(chip, icon = ShieldIcon) }
            if (hint) {
                val server = modeChipLabel(state.serverMode)?.let { "\n" + stringResource(R.string.rd_mode_server_says, stringResource(it)) } ?: ""
                Text(stringResource(R.string.rd_mode_chip_hint) + server, style = MaterialTheme.typography.bodySmall, color = c.onInverse,
                     modifier = Modifier.background(c.inverse, RoundedCornerShape(12.dp)).padding(horizontal = 12.dp, vertical = 8.dp)
                         .semantics { liveRegion = LiveRegionMode.Polite })
            }
        }
        if (state.readOnlyChat) {
            Text(stringResource(R.string.rd_chat_read_only), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        }
    }
}

/** Disconnected or connecting: no thread (the chats live on the server and load again when connected). */
@Composable
private fun OfflineBody(state: HomeUiState, modifier: Modifier) {
    val c = OpenMobTheme.colors
    Column(modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 32.dp),
           horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically)) {
        val connecting = state.status == HomeStatus.Connecting
        Text(stringResource(if (connecting) R.string.rd_home_connecting_title else R.string.rd_offline_title),
             style = MaterialTheme.typography.headlineMedium, color = c.ink, textAlign = TextAlign.Center,
             modifier = Modifier.semantics { heading() })
        Text(if (connecting) state.connectionText else stringResource(R.string.rd_offline_body), style = MaterialTheme.typography.bodyMedium,
             color = c.inkSecondary, textAlign = TextAlign.Center, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        if (!connecting && state.serverHost.isNotEmpty()) {
            Text(stringResource(R.string.rd_offline_chats, state.serverHost), style = MaterialTheme.typography.bodySmall,
                 color = c.inkSecondary, textAlign = TextAlign.Center)
        }
        A11yWarning(state)
    }
}

/** "Disconnected · Reconnect": Reconnect only reconnects; permits need approving again. */
@Composable
private fun DisconnectedBar(actions: HomeActions) {
    val c = OpenMobTheme.colors
    Row(
        Modifier.fillMaxWidth().background(c.inverse, RoundedCornerShape(14.dp)).semantics { liveRegion = LiveRegionMode.Polite }
            .padding(start = 16.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(stringResource(R.string.rd_bar_disconnected), style = MaterialTheme.typography.bodyMedium, color = c.onInverse,
             modifier = Modifier.weight(1f))
        TextButton(onClick = actions.connect, modifier = Modifier.heightIn(min = 48.dp).testTag(TAG_RECONNECT)) {
            Text(stringResource(R.string.rd_bar_reconnect), style = MaterialTheme.typography.labelLarge, color = c.onInverse)
        }
    }
}

/** The mockups' mark: a phone with the agent's blue frame around it. Decoration (the title says "OpenMob"). */
@Composable
internal fun AppMark() {
    val c = OpenMobTheme.colors
    Canvas(Modifier.size(28.dp)) {
        val u = size.width / 28f
        drawRoundRect(c.signal.copy(alpha = if (c.isDark) 0.7f else 0.55f), Offset(3 * u, 5 * u), Size(22 * u, 18 * u),
                      CornerRadius(6 * u), style = Stroke(2 * u))
        drawRoundRect(c.ink, Offset(6 * u, 2 * u), Size(16 * u, 24 * u), CornerRadius(4 * u), style = Stroke(2 * u))
        drawCircle(c.ink, 1.5f * u, Offset(14 * u, 21 * u))
    }
}

@Composable
private fun Headline(text: String, large: Boolean = true) {
    Text(
        text,
        style = if (large) MaterialTheme.typography.headlineMedium else MaterialTheme.typography.headlineSmall,
        color = OpenMobTheme.colors.ink,
        modifier = Modifier.semantics { heading() },
    )
}

@Composable
private fun Body(text: String) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = OpenMobTheme.colors.inkSecondary)
}

@Composable
private fun A11yWarning(state: HomeUiState) {
    if (state.accessibilityOn) return
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
        Icon(Icons.Filled.Warning, contentDescription = null, tint = OpenMobTheme.colors.ink, modifier = Modifier.size(18.dp))
        Text(stringResource(R.string.ui_a11y_warning), style = MaterialTheme.typography.bodySmall, color = OpenMobTheme.colors.ink)
    }
}

@Composable
private fun NotSetUpCard(state: HomeUiState, actions: HomeActions) {
    OmCard {
        StatusChip(StatusKind.Info, stringResource(R.string.rd_home_status_not_set_up))
        Headline(stringResource(R.string.rd_home_setup_title))
        Body(stringResource(R.string.rd_home_setup_body, state.checksDone, state.checksTotal))
        PrimaryButton(stringResource(R.string.rd_home_setup_button), onClick = actions.openSetup)
        Text(stringResource(R.string.rd_home_setup_note), style = MaterialTheme.typography.bodySmall, color = OpenMobTheme.colors.inkTertiary)
    }
}

@Composable
private fun AskBlock(ask: HomeAsk, actions: HomeActions) {
    when (ask) {
        is HomeAsk.Approval -> {
            val more = if (ask.more > 0) "\n" + stringResource(R.string.rd_home_ask_more, ask.more) else ""
            AskingBand(stringResource(R.string.rd_asking_band), detail = ask.approval.question + more)
            ButtonPair {
                SecondaryButton(stringResource(R.string.approval_deny), onClick = { actions.deny(ask.approval.id) }, modifier = Modifier.weight(1f))
                PrimaryButton(stringResource(R.string.approval_review), onClick = { actions.review(ask.approval.id) }, modifier = Modifier.weight(1f))
            }
        }
        is HomeAsk.Question -> {
            // The agent's own (server-written) question: never amber or a lock (UX review 2, H1).
            AgentQuestion(ask.text)
            ButtonPair {
                SecondaryButton(stringResource(R.string.ui_no), onClick = { actions.answer(false) }, modifier = Modifier.weight(1f))
                PrimaryButton(stringResource(R.string.ui_yes), onClick = { actions.answer(true) }, modifier = Modifier.weight(1f))
            }
        }
    }
}

/** "Your agent asks": the agent's own question, in the agent's blue (a polite live region). */
@Composable
private fun AgentQuestion(text: String) {
    val c = OpenMobTheme.colors
    Column(
        Modifier.fillMaxWidth().background(c.signalContainer, RoundedCornerShape(OpenMobTheme.radii.md))
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite }
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(stringResource(R.string.rd_home_question), style = MaterialTheme.typography.labelMedium, color = c.signal)
        Text(text, style = MaterialTheme.typography.titleSmall, color = c.ink)
    }
}

/** Home's chip for the signed standing mode (GateHost.ceilingOrNull); null: unknown, no chip. */
fun modeChipLabel(mode: String?): Int? = when (mode) {
    "ask" -> R.string.rd_home_mode_ask
    "plan" -> R.string.rd_home_mode_plan
    "auto" -> R.string.rd_home_mode_auto
    "trusted" -> R.string.rd_home_mode_trusted
    else -> null
}

/** 0:14, 12:05, 1:02:03. */
fun elapsed(seconds: Long): String {
    val h = seconds / 3600
    val m = (seconds % 3600) / 60
    val s = seconds % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}
