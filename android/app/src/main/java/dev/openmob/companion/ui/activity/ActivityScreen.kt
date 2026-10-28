package dev.openmob.companion.ui.activity

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.BoltIcon
import dev.openmob.companion.ui.components.CheckIcon
import dev.openmob.companion.ui.components.EmptyState
import dev.openmob.companion.ui.components.FilterPill
import dev.openmob.companion.ui.components.ListRow
import dev.openmob.companion.ui.components.OmCard
import dev.openmob.companion.ui.components.SectionHeader
import dev.openmob.companion.ui.components.StopSquare
import dev.openmob.companion.ui.home.elapsed
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.nav.ScreenScaffold
import dev.openmob.companion.ui.theme.OpenMobTheme
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

/** "48 s", "1 min 40 s", "1 h 05 min". */
@Composable
fun duration(ms: Long): String {
    val s = ms / 1000
    return when {
        s < 60 -> stringResource(R.string.rd_activity_seconds, s.toInt())
        s < 3600 -> stringResource(R.string.rd_activity_minutes, (s / 60).toInt(), (s % 60).toInt())
        else -> stringResource(R.string.rd_activity_hours, (s / 3600).toInt(), ((s % 3600) / 60).toInt())
    }
}

/** The row's second line: what happened, how long, how often it asked. */
@Composable
fun statusLine(r: ActivityRow): String {
    val asked = pluralStringResource(R.plurals.rd_asked_you, r.asks, r.asks)
    fun join(vararg parts: String) = parts.filter { it.isNotEmpty() }.joinToString(" · ")
    val took = if (r.durationMs > 0) duration(r.durationMs) else ""
    return when (r.kind) {
        RowKind.Running -> if (r.steps > 0) stringResource(R.string.rd_activity_running, elapsed(r.durationMs / 1000), r.steps)
                           else stringResource(R.string.rd_activity_running_start, elapsed(r.durationMs / 1000))
        RowKind.Done -> join(stringResource(R.string.rd_activity_done), took, asked)
        RowKind.Stopped -> join(stringResource(R.string.rd_activity_stopped), took, asked)
        RowKind.StoppedByYou -> join(stringResource(R.string.rd_activity_stopped_you), took, asked)
        RowKind.Denied -> join(stringResource(R.string.rd_activity_denied), took, asked)
        RowKind.Failed -> join(if (r.reason.isNotEmpty()) stringResource(R.string.rd_activity_failed_why, r.reason)
                               else stringResource(R.string.rd_activity_failed), took)
        RowKind.Interrupted -> stringResource(R.string.rd_activity_interrupted)
        RowKind.FasterApproved, RowKind.FasterDenied -> join(
            stringResource(if (r.kind == RowKind.FasterApproved) R.string.rd_activity_faster_approved else R.string.rd_activity_faster_denied),
            fasterScope(r.title),
        )
    }
}

/** A Faster mode row's scope, as Settings words it ("this session", "always on this phone"). */
@Composable
private fun fasterScope(scope: String): String = when (scope) {
    "session" -> stringResource(R.string.rd_activity_faster_session)
    "phone" -> stringResource(R.string.rd_activity_faster_always)
    else -> ""
}

/** A row's title: the request, "Drive session", or "Faster mode". */
@Composable
fun rowTitle(r: ActivityRow): String = when {
    r.kind == RowKind.FasterApproved || r.kind == RowKind.FasterDenied -> stringResource(R.string.rd_activity_faster_title)
    r.title.isEmpty() -> stringResource(R.string.rd_activity_drive)
    else -> r.title
}

@Composable
private fun RowIcon(kind: RowKind) {
    val c = OpenMobTheme.colors
    val (icon: ImageVector, fg: Color, bg: Color) = when (kind) {
        RowKind.Running -> Triple(Icons.Filled.PlayArrow, c.signal, c.signalContainer)
        RowKind.Done -> Triple(CheckIcon, c.signal, c.signalContainer)
        RowKind.Stopped, RowKind.StoppedByYou -> Triple(StopSquare, c.ink, c.neutralContainer)
        RowKind.Denied -> Triple(Icons.Filled.Close, c.ink, c.neutralContainer)
        RowKind.Failed, RowKind.Interrupted -> Triple(Icons.Filled.Warning, c.onDangerContainer, c.dangerContainer)
        RowKind.FasterApproved -> Triple(BoltIcon, c.signal, c.signalContainer)
        RowKind.FasterDenied -> Triple(Icons.Filled.Close, c.ink, c.neutralContainer)
    }
    Box(Modifier.size(32.dp).background(bg, CircleShape), contentAlignment = Alignment.Center) {
        Icon(icon, contentDescription = null, tint = fg, modifier = Modifier.size(16.dp))
    }
}

data class ActivityActions(val back: () -> Unit = {}, val filter: (ActivityFilter) -> Unit = {})

@Composable
@OptIn(ExperimentalLayoutApi::class)
fun ActivityScreen(state: ActivityUiState, actions: ActivityActions, zone: ZoneId = ZoneId.systemDefault()) {
    val c = OpenMobTheme.colors
    val time = DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT)
    ScreenScaffold(title = stringResource(Route.Activity.title), onBack = actions.back) {
        if (state.total == 0) {
            EmptyState(
                icon = Icons.Filled.DateRange,
                title = stringResource(R.string.rd_activity_empty),
                body = stringResource(R.string.rd_activity_empty_body),
            )
        } else {
            // Wraps at large text sizes instead of hiding a filter off the edge.
            FlowRow(
                Modifier.fillMaxWidth().selectableGroup(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                listOf(ActivityFilter.All to R.string.rd_activity_filter_all,
                       ActivityFilter.Asked to R.string.rd_activity_filter_asked,
                       ActivityFilter.StoppedOrDenied to R.string.rd_activity_filter_stopped).forEach { (f, label) ->
                    FilterPill(stringResource(label), selected = state.filter == f, onSelect = { actions.filter(f) })
                }
            }
            if (state.groups.isEmpty()) {
                Text(stringResource(R.string.rd_activity_none_filtered), style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary)
            }
            state.groups.forEach { g ->
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    SectionHeader(dayLabel(g.day, state.today))
                    OmCard(contentPadding = 0.dp) {
                        g.rows.forEachIndexed { i, r ->
                            if (i > 0) HorizontalDivider(color = c.divider)
                            ListRow(
                                title = rowTitle(r),
                                subtitle = statusLine(r),
                                leading = { RowIcon(r.kind) },
                                trailing = {
                                    Text(time.format(Instant.ofEpochMilli(r.startedAt).atZone(zone)), style = OpenMobTheme.mono.small,
                                         color = c.inkTertiary)
                                },
                            )
                        }
                    }
                }
            }
        }
        Text(stringResource(R.string.rd_activity_kept), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary,
             textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun dayLabel(day: LocalDate, today: LocalDate): String = when (day) {
    today -> stringResource(R.string.rd_activity_today)
    today.minusDays(1) -> stringResource(R.string.rd_activity_yesterday)
    else -> day.format(DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM))
}

@Composable
fun ActivityRoute(back: () -> Unit) {
    val context = LocalContext.current
    val vm: ActivityViewModel = viewModel(factory = ActivityViewModel.factory(context))
    val state by vm.state.collectAsStateWithLifecycle()
    ActivityScreen(state, ActivityActions(back = back, filter = vm::setFilter))
}

@Preview(name = "Activity, light", widthDp = 390, heightDp = 1000)
@Preview(name = "Activity, dark", widthDp = 390, heightDp = 1000, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun ActivityPreview() {
    OpenMobTheme { ActivityScreen(ActivitySamples.full(), ActivityActions(), ActivitySamples.ZONE) }
}
