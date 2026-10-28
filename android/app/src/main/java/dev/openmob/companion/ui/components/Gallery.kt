package dev.openmob.companion.ui.components

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import dev.openmob.companion.R
import dev.openmob.companion.ui.theme.OpenMobTheme

/** Every status kind with its word, for the gallery and the tests. */
@Composable
fun statusLabel(kind: StatusKind): String = stringResource(
    when (kind) {
        StatusKind.Connected -> R.string.rd_status_connected
        StatusKind.Working -> R.string.rd_status_working
        StatusKind.Asking -> R.string.rd_status_asking
        StatusKind.Offline -> R.string.rd_status_offline
        StatusKind.Done -> R.string.rd_status_done
        StatusKind.Stopped -> R.string.rd_status_stopped
        StatusKind.Denied -> R.string.rd_status_denied
        StatusKind.Failed -> R.string.rd_status_failed
        StatusKind.Info -> R.string.rd_status_preview
    },
)

/** The design system on one page: the previews and screenshot tests render this. No real data. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ComponentGallery(modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    val sp = OpenMobTheme.spacing
    Column(
        modifier = modifier.background(c.ground).padding(sp.screen),
        verticalArrangement = Arrangement.spacedBy(sp.lg),
    ) {
        Text(stringResource(R.string.rd_home_status), style = MaterialTheme.typography.headlineMedium, color = c.ink)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(sp.sm), verticalArrangement = Arrangement.spacedBy(sp.sm)) {
            StatusKind.entries.forEach { StatusChip(it, statusLabel(it)) }
        }
        AskingBand(stringResource(R.string.rd_asking_band), detail = stringResource(R.string.rd_asking_band_detail))
        OmCard {
            StatusChip(StatusKind.Connected, statusLabel(StatusKind.Connected))
            Text(stringResource(R.string.rd_home_status_body), style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary)
            MonoValue(label = stringResource(R.string.rd_home_server), value = "server.example")
            MonoValue(value = "$249.99", style = OpenMobTheme.mono.display)
        }
        Column {
            SectionHeader(stringResource(R.string.rd_settings_more))
            OmCard {
                Column {
                    ListRow(stringResource(R.string.rd_indicator_title), subtitle = stringResource(R.string.rd_indicator_example), onClick = {})
                    HorizontalDivider(color = c.divider)
                    ToggleRow(stringResource(R.string.rd_indicator_border), checked = true, onCheckedChange = {})
                    HorizontalDivider(color = c.divider)
                    ToggleRow(stringResource(R.string.rd_indicator_pill), checked = false, onCheckedChange = {})
                }
            }
        }
        PrimaryButton(stringResource(R.string.rd_setup_get_started), onClick = {})
        SecondaryButton(stringResource(R.string.rd_setup_pair_code_instead), onClick = {})
        DangerButton(stringResource(R.string.rd_home_disconnect), onClick = {})
        StopButton(stringResource(R.string.rd_home_stop_task), onClick = {})
        ButtonPair {
            SecondaryButton(stringResource(R.string.rd_back), onClick = {}, modifier = Modifier.weight(1f))
            PrimaryButton(stringResource(R.string.rd_next), onClick = {}, icon = Icons.Filled.Lock, modifier = Modifier.weight(1f))
        }
        LinkButton(stringResource(R.string.rd_home_all_activity), onClick = {})
        EmptyState(
            icon = Icons.Filled.DateRange,
            title = stringResource(R.string.rd_activity_empty),
            body = stringResource(R.string.rd_activity_empty_body),
        )
    }
}

@Preview(name = "Components, light", widthDp = 390, heightDp = 1600, showBackground = true)
@Preview(name = "Components, dark", widthDp = 390, heightDp = 1600, showBackground = true, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun ComponentGalleryPreview() {
    OpenMobTheme { ComponentGallery(Modifier.fillMaxWidth()) }
}
