package dev.openmob.companion.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.CheckIcon
import dev.openmob.companion.ui.components.LabeledLine
import dev.openmob.companion.ui.components.ListRow
import dev.openmob.companion.ui.components.MonoValue
import dev.openmob.companion.ui.components.PowerIcon
import dev.openmob.companion.ui.components.SecondaryButton
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.theme.OpenMobTheme

const val TAG_STATUS_SHEET = "status-sheet"
const val TAG_DISCONNECT = "status-disconnect"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatusSheet(state: HomeUiState, actions: HomeActions, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
                     containerColor = OpenMobTheme.colors.surface) {
        StatusSheetContent(state, actions, onDismiss)
    }
}

/** The connection sheet (canvas HomeStatus): issues first with a fix, then the details, then Disconnect. */
@Composable
fun StatusSheetContent(state: HomeUiState, actions: HomeActions, onDismiss: () -> Unit, modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    Column(
        modifier.fillMaxWidth().testTag(TAG_STATUS_SHEET).verticalScroll(rememberScrollState())
            .padding(start = 20.dp, end = 20.dp, bottom = 24.dp).navigationBarsPadding(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.rd_status_title), style = MaterialTheme.typography.titleLarge, color = c.ink,
                 modifier = Modifier.weight(1f).semantics { heading() })
            IconButton(onClick = onDismiss, modifier = Modifier.size(48.dp)) {
                Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.rd_status_close), tint = c.ink)
            }
        }
        state.issues.forEach { issue -> IssueCard(issue) { actions.fixIssue(issue) } }
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            LabeledLine(stringResource(R.string.rd_home_server)) {
                Text(stringResource(R.string.rd_status_connected_to), style = MaterialTheme.typography.bodySmall, color = c.signal)
                Text(" · ", color = c.inkTertiary)
                Text(state.serverHost, style = OpenMobTheme.mono.medium, color = c.ink)
            }
            if (state.email.isNotEmpty()) MonoValue(label = stringResource(R.string.rd_home_account), value = state.email)
            LabeledLine(stringResource(R.string.rd_status_mode)) {
                // The phone's signed ceiling; the server's own mode only labelled as the server's (review 3 P3-L1).
                Text((modeChipLabel(state.mode)?.let { stringResource(R.string.rd_mode_at_most, stringResource(it)) }
                          ?: stringResource(R.string.rd_status_mode_unknown)) +
                         (modeChipLabel(state.serverMode)?.let { " · " + stringResource(R.string.rd_mode_server_says, stringResource(it)) } ?: "") +
                         " · " + stringResource(R.string.rd_mode_change_dashboard),
                     style = MaterialTheme.typography.bodySmall, color = c.ink)
            }
        }
        HorizontalDivider(color = c.divider)
        ListRow(stringResource(R.string.rd_settings_faster),
                subtitle = stringResource(if (state.fasterOn) R.string.rd_status_on else R.string.rd_status_off),
                onClick = { onDismiss(); actions.openRoute(Route.Settings) })
        Text(stringResource(R.string.rd_status_this_phone), style = MaterialTheme.typography.labelMedium, color = c.inkSecondary,
             modifier = Modifier.semantics { heading() })
        Check(state.accessibilityOn, R.string.rd_status_a11y_on, R.string.rd_status_a11y_off)
        Check(state.notificationsOn, R.string.rd_status_notif_on, R.string.rd_status_notif_off)
        Check(state.backgroundOk, R.string.rd_status_bg_on, R.string.rd_status_bg_off)
        HorizontalDivider(color = c.divider)
        ListRow(stringResource(R.string.rd_settings_connection), onClick = { onDismiss(); actions.openRoute(Route.Connection) })
        // Disconnect: the second tap (the pill was the first). Outline, not red.
        SecondaryButton(stringResource(R.string.rd_home_disconnect), onClick = { onDismiss(); actions.disconnect() }, icon = PowerIcon,
                        modifier = Modifier.testTag(TAG_DISCONNECT))
        Text(stringResource(R.string.rd_status_disconnect_note), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary,
             textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        Text(stringResource(R.string.rd_home_never_types), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary,
             textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun IssueCard(issue: Issue, onFix: () -> Unit) {
    val c = OpenMobTheme.colors
    val (title, why, fix) = when (issue) {
        Issue.Accessibility -> Triple(R.string.rd_issue_a11y, R.string.rd_issue_a11y_why, R.string.rd_issue_a11y_fix)
        Issue.Notifications -> Triple(R.string.rd_issue_notif, R.string.rd_issue_notif_why, R.string.rd_issue_notif_fix)
        Issue.Background -> Triple(R.string.rd_issue_bg, R.string.rd_issue_bg_why, R.string.rd_issue_bg_fix)
    }
    Column(
        Modifier.fillMaxWidth().background(c.surface, RoundedCornerShape(16.dp)).border(1.dp, c.border, RoundedCornerShape(16.dp))
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Icon(Icons.Filled.Warning, contentDescription = null, tint = c.ink, modifier = Modifier.size(18.dp))
            Text(stringResource(title), style = MaterialTheme.typography.titleSmall, color = c.ink)
        }
        Text(stringResource(why), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        SecondaryButton(stringResource(fix), onClick = onFix, fillWidth = false)
    }
}

@Composable
private fun Check(on: Boolean, onText: Int, offText: Int) {
    val c = OpenMobTheme.colors
    Row(Modifier.heightIn(min = 32.dp).semantics(mergeDescendants = true) {}, verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Icon(if (on) CheckIcon else Icons.Filled.Warning, contentDescription = null, tint = if (on) c.signal else c.ink,
             modifier = Modifier.size(16.dp))
        Text(stringResource(if (on) onText else offText), style = MaterialTheme.typography.bodyMedium, color = c.ink)
    }
}
