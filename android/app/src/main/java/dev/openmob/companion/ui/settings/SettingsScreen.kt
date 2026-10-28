package dev.openmob.companion.ui.settings

import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.openmob.companion.IndicatorColors
import dev.openmob.companion.PillCorner
import dev.openmob.companion.R
import dev.openmob.companion.Settings
import dev.openmob.companion.ui.components.BlockIcon
import dev.openmob.companion.ui.components.BoltIcon
import dev.openmob.companion.ui.components.CheckIcon
import dev.openmob.companion.ui.components.DangerButton
import dev.openmob.companion.ui.components.LinkButton
import dev.openmob.companion.ui.components.ListRow
import dev.openmob.companion.ui.components.OmCard
import dev.openmob.companion.ui.components.largeText
import dev.openmob.companion.ui.components.SecondaryButton
import dev.openmob.companion.ui.components.SectionHeader
import dev.openmob.companion.ui.components.ShieldIcon
import dev.openmob.companion.ui.components.ToggleRow
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.nav.ScreenScaffold
import dev.openmob.companion.ui.theme.OpenMobTheme
import dev.openmob.companion.ui.theme.PillShape
import java.text.DateFormat
import java.util.Date

data class SettingsActions(
    val back: () -> Unit = {},
    val openIndicator: () -> Unit = {},
    val openConnection: () -> Unit = {},
    val openSetup: () -> Unit = {},
    val fasterSession: () -> Unit = {},
    val fasterAlways: () -> Unit = {},
    val fasterOff: () -> Unit = {},
    val learnMore: () -> Unit = {},
    val downloadUpdate: () -> Unit = {},
    /** Settings › Blocked apps (its own page). */
    val openBlocked: () -> Unit = {},
    /** Settings › What OpenMob remembers (its own page; the row shows only when the server allows it). */
    val openMemory: () -> Unit = {},
)

@Composable
fun SettingsScreen(
    state: SettingsUiState,
    actions: SettingsActions,
    modifier: Modifier = Modifier,
    /** Debug builds only: developer switches (the new approval screen). */
    developer: (@Composable () -> Unit)? = null,
    /** The Blocked apps row (BlockedAppsRowRoute on the phone, with the owner's count; previews and tests show 0). */
    blocked: @Composable () -> Unit = { BlockedAppsRow(0, onClick = actions.openBlocked) },
    /** The memory row (MemoryRowRoute on the phone: only when the welcome said `memory`); none in previews and tests. */
    memory: @Composable () -> Unit = {},
) {
    val c = OpenMobTheme.colors
    ScreenScaffold(title = stringResource(Route.Settings.title), onBack = actions.back, modifier = modifier) {
        ModesSection(state)
        blocked()
        memory()
        FasterCard(state, actions)
        Column {
            SectionHeader(stringResource(R.string.rd_settings_more))
            OmCard(contentPadding = 0.dp) {
                ListRow(
                    stringResource(R.string.rd_indicator_title),
                    subtitle = indicatorSummary(state.border, state.color, state.pill, state.corner),
                    onClick = actions.openIndicator,
                )
                HorizontalDivider(color = c.divider)
                ListRow(
                    stringResource(R.string.rd_settings_connection),
                    subtitle = if (state.serverHost.isEmpty()) stringResource(R.string.rd_settings_connection_none)
                    else stringResource(R.string.rd_settings_connection_sub, state.serverHost),
                    onClick = actions.openConnection,
                )
                HorizontalDivider(color = c.divider)
                ListRow(
                    stringResource(R.string.rd_settings_setup),
                    subtitle = if (state.checksDone >= state.checksTotal) stringResource(R.string.rd_settings_setup_all, state.checksTotal)
                    else stringResource(R.string.rd_settings_setup_some, state.checksDone, state.checksTotal),
                    onClick = actions.openSetup,
                )
            }
        }
        AboutSection(state, actions)
        developer?.invoke()
        Text(
            stringResource(R.string.rd_settings_only_you),
            style = MaterialTheme.typography.labelSmall,
            color = c.inkTertiary,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

const val TAG_ABOUT = "settings-about"
const val TAG_ABOUT_DOWNLOAD = "settings-about-download"

/**
 * About (mockup About, §3.7): this app's version and commit, the server's latest, and either "Update available" with
 * Download update (the agent's blue container) or "Up to date" with a check. Then where updates come from.
 */
@Composable
private fun AboutSection(state: SettingsUiState, actions: SettingsActions) {
    val c = OpenMobTheme.colors
    Column(Modifier.testTag(TAG_ABOUT), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionHeader(stringResource(R.string.about_title))
        OmCard(contentPadding = 0.dp) {
            AboutRow(stringResource(R.string.about_app_version),
                     stringResource(R.string.about_app_version_value, state.appVersionCode, state.appHash))
            HorizontalDivider(color = c.divider)
            AboutRow(stringResource(R.string.about_latest),
                     state.latestVersion?.toString() ?: stringResource(R.string.update_unknown))
            if (state.latestVersion != null) {
                HorizontalDivider(color = c.divider)
                if (state.updateAvailable) {
                    Column(Modifier.fillMaxWidth().background(c.signalContainer).padding(16.dp),
                           verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                            androidx.compose.foundation.layout.Box(Modifier.size(8.dp).background(c.signal, androidx.compose.foundation.shape.CircleShape))
                            Text(stringResource(R.string.about_update_available), style = MaterialTheme.typography.titleSmall, color = c.ink)
                        }
                        if (state.updateDownloadable) {
                            dev.openmob.companion.ui.components.PrimaryButton(
                                stringResource(R.string.update_download), onClick = actions.downloadUpdate,
                                icon = dev.openmob.companion.ui.components.DownloadIcon,
                                modifier = Modifier.testTag(TAG_ABOUT_DOWNLOAD))
                        } else {
                            Text(stringResource(R.string.update_no_download), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
                        }
                    }
                } else {
                    Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(horizontal = 16.dp, vertical = 12.dp)
                            .semantics(mergeDescendants = true) {},
                        horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(CheckIcon, contentDescription = null, tint = c.signal, modifier = Modifier.size(18.dp))
                        Text(stringResource(R.string.about_up_to_date), style = MaterialTheme.typography.titleSmall, color = c.ink)
                    }
                }
            }
        }
        Text(stringResource(R.string.about_updates_note), style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
    }
}

/** "App version   47 · 7d7c887": the label, and the value in mono (read together). At large text, stacked. */
@Composable
private fun AboutRow(label: String, value: String) {
    val c = OpenMobTheme.colors
    val content = @Composable {
        Text(label, style = MaterialTheme.typography.titleSmall, color = c.ink)
        Text(value, style = OpenMobTheme.mono.medium, color = c.inkSecondary)
    }
    val m = Modifier.fillMaxWidth().heightIn(min = 56.dp).semantics(mergeDescendants = true) {}
        .padding(horizontal = 16.dp, vertical = 12.dp)
    if (largeText()) {
        Column(m, verticalArrangement = Arrangement.spacedBy(2.dp)) { content() }
    } else {
        Row(m, horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) { content() }
    }
}

/** The tag on the server's own mode in the list (review 3 P3-L1). */
const val TAG_MODE_SERVER = "mode-server"

/** The modes, for reading only (owner, 2026-10-17: changed on the dashboard; loosening is signed here, in
 *  ApprovalActivity). The current one is the phone's own signed ceiling (GateHost.ceilingOrNull). */
@Composable
private fun ModesSection(state: SettingsUiState) {
    val c = OpenMobTheme.colors
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionHeader(stringResource(R.string.rd_settings_how_ask))
        Text(stringResource(R.string.rd_settings_how_ask_body), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        if (state.neverUntil > 0) {
            Text(
                stringResource(R.string.rd_settings_never_on, DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(state.neverUntil * 1000))),
                style = MaterialTheme.typography.titleSmall,
                color = c.ink,
            )
        }
        Text(stringResource(R.string.rd_mode_change_here), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        if (state.mode == null && state.neverUntil == 0L) {
            Text(stringResource(R.string.rd_mode_unknown), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        }
        OmCard(contentPadding = 0.dp) {
            val modes = listOf(
                Triple("ask", R.string.rd_mode_every, R.string.rd_mode_every_body),
                Triple("plan", R.string.rd_mode_plan, R.string.rd_mode_plan_body),
                Triple("auto", R.string.rd_mode_risky, R.string.rd_mode_risky_body),
                Triple("trusted", R.string.rd_mode_trusted, R.string.rd_mode_trusted_body),
                Triple("never", R.string.rd_mode_never, R.string.rd_mode_never_body),
            )
            // Don't ask, while its signed window runs, is the mode in force; otherwise the signed standing ceiling.
            val current = if (state.neverUntil > 0) "never" else state.mode
            modes.forEachIndexed { i, (key, title, body) ->
                val lock = key == "never"
                val isCurrent = key == current
                // The server's own mode, labelled as the server's: the phone enforces only the ceiling (review 3 P3-L1).
                val isServer = state.neverUntil == 0L && key == state.serverMode
                if (i > 0) HorizontalDivider(color = c.divider)
                // Information only (UX review 2, M4): no highlight, chevron or ripple; the current mode is named above.
                Column(
                    Modifier.fillMaxWidth().heightIn(min = 56.dp)
                        // Read only: marked selected for TalkBack, with no click action (changed on the dashboard).
                        .semantics(mergeDescendants = true) { selected = isCurrent }
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    val tags = @Composable {
                        if (key == "auto") {
                            Text(stringResource(R.string.rd_mode_default), style = MaterialTheme.typography.labelSmall, color = c.signal)
                        }
                        if (isCurrent) {
                            Text(stringResource(R.string.rd_mode_current), style = MaterialTheme.typography.labelSmall, color = c.signal)
                        }
                        if (isServer) {
                            Text(stringResource(R.string.rd_mode_server_tag), style = MaterialTheme.typography.labelSmall,
                                 color = c.inkTertiary, modifier = Modifier.testTag(TAG_MODE_SERVER))
                        }
                    }
                    // At large text the "Default" and "Current" tags go on their own line under the mode's name.
                    if (largeText()) {
                        Text(stringResource(title), style = MaterialTheme.typography.titleSmall, color = c.ink)
                        if (key == "auto" || isCurrent || isServer) Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) { tags() }
                    } else {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(stringResource(title), style = MaterialTheme.typography.titleSmall, color = c.ink)
                            tags()
                        }
                    }
                    Text(stringResource(body), style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
                    if (lock) {
                        Text(
                            stringResource(R.string.rd_mode_needs_lock),
                            style = MaterialTheme.typography.labelSmall,
                            color = c.ink,
                            modifier = Modifier.padding(top = 4.dp).background(c.neutralContainer, PillShape).padding(horizontal = 8.dp, vertical = 3.dp),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun FasterCard(state: SettingsUiState, actions: SettingsActions) {
    val c = OpenMobTheme.colors
    OmCard {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(BoltIcon, contentDescription = null, tint = c.ink, modifier = Modifier.size(20.dp))
                Text(stringResource(R.string.rd_settings_faster), style = MaterialTheme.typography.titleMedium, color = c.ink)
            }
            val on = state.fasterOn
            Text(
                stringResource(if (on) R.string.rd_faster_on else R.string.rd_faster_off),
                style = MaterialTheme.typography.labelSmall,
                // Not amber: amber only ever means "the phone is asking you".
                color = if (on) c.signal else c.ink,
                modifier = Modifier
                    .background(if (on) c.signalContainer else c.surface, PillShape)
                    .border(1.dp, if (on) c.signal else c.outline, PillShape)
                    .padding(horizontal = 10.dp, vertical = 4.dp),
            )
        }
        Text(
            stringResource(when {
                state.fasterOn && state.fasterScope == "session" -> R.string.faster_status_session
                state.fasterOn -> R.string.faster_status_phone
                else -> R.string.faster_status_off
            }),
            style = MaterialTheme.typography.bodyMedium,
            color = c.ink,
        )
        Text(
            stringResource(R.string.faster_warning),
            style = MaterialTheme.typography.bodySmall,
            color = c.inkSecondary,
            modifier = Modifier.background(c.surfaceSunken, androidx.compose.foundation.shape.RoundedCornerShape(12.dp)).padding(12.dp),
        )
        LinkButton(stringResource(R.string.faster_learn_more), onClick = actions.learnMore)
        if (state.fasterOn) {
            DangerButton(stringResource(R.string.faster_turn_off), onClick = actions.fasterOff)
        } else {
            // Turn-on goes server → approval → ApprovalActivity behind the screen lock; only while connected.
            SecondaryButton(stringResource(R.string.faster_on_session), onClick = actions.fasterSession, enabled = state.connected, icon = ShieldIcon)
            SecondaryButton(stringResource(R.string.faster_on_always), onClick = actions.fasterAlways, enabled = state.connected, icon = ShieldIcon)
            if (!state.connected) Text(stringResource(R.string.faster_offline), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        }
        Text(stringResource(R.string.rd_faster_footer), style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
    }
}

/** "Blue border · Stop button top right". */
@Composable
fun indicatorSummary(border: Boolean, color: String, pill: Boolean, corner: PillCorner): String {
    val colour = IndicatorColors.PRESETS.firstOrNull { it.key == color }?.label?.substringBefore(" (") ?: stringResource(R.string.rd_custom)
    val where = stringResource(cornerLabel(corner)).lowercase()
    return when {
        border && pill -> stringResource(R.string.rd_indicator_summary_both, colour, where)
        border -> stringResource(R.string.rd_indicator_summary_border, colour)
        pill -> stringResource(R.string.rd_indicator_summary_pill, where)
        else -> stringResource(R.string.rd_indicator_summary_off)
    }
}

fun cornerLabel(corner: PillCorner): Int = when (corner) {
    PillCorner.TOP_RIGHT -> R.string.indicator_corner_top_right
    PillCorner.TOP_LEFT -> R.string.indicator_corner_top_left
    PillCorner.BOTTOM_RIGHT -> R.string.indicator_corner_bottom_right
    PillCorner.BOTTOM_LEFT -> R.string.indicator_corner_bottom_left
}

@Composable
fun SettingsRoute(
    back: () -> Unit,
    openIndicator: () -> Unit,
    openSetup: () -> Unit = {},
    openConnection: () -> Unit = {},
    openBlocked: () -> Unit = {},
    openMemory: () -> Unit = {},
    vm: SettingsViewModel = viewModel(factory = SettingsViewModel.factory(LocalContext.current)),
) {
    val context = LocalContext.current
    val state by vm.state.collectAsStateWithLifecycle()
    val notice by vm.notice.collectAsStateWithLifecycle()
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { vm.refresh() }
    LaunchedEffect(notice) { notice?.let { Toast.makeText(context, it, Toast.LENGTH_LONG).show(); vm.noticeShown() } }
    val limited by vm.limitedMinutes.collectAsStateWithLifecycle()
    LaunchedEffect(limited) {
        limited?.let {
            Toast.makeText(context, context.resources.getQuantityString(R.plurals.rd_faster_limited, it, it), Toast.LENGTH_LONG).show()
            vm.limitedShown()
        }
    }
    SettingsScreen(
        state,
        actions = SettingsActions(
            back = back,
            openIndicator = openIndicator,
            openConnection = openConnection,
            openSetup = openSetup,
            fasterSession = { vm.requestFaster("session") },
            fasterAlways = { vm.requestFaster("phone") },
            fasterOff = vm::turnOffFaster,
            downloadUpdate = vm::downloadUpdate,
            openBlocked = openBlocked,
            openMemory = openMemory,
            learnMore = {
                // As MainActivity: the page is served by this phone's own OpenMob server (public, no sign-in).
                val server = Settings(context).server
                if (server.isEmpty()) Toast.makeText(context, R.string.faster_offline, Toast.LENGTH_SHORT).show()
                else runCatching {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(server).buildUpon().path("/safety")
                        .clearQuery().fragment("faster-mode").build()))
                }
            },
        ),
        blocked = { BlockedAppsRowRoute(open = openBlocked) },
        memory = { MemoryRowRoute(open = openMemory) },
    )
}
