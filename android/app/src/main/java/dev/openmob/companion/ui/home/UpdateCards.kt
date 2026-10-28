package dev.openmob.companion.ui.home

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.DownloadIcon
import dev.openmob.companion.ui.components.OmCard
import dev.openmob.companion.ui.components.PrimaryButton
import dev.openmob.companion.ui.components.SecondaryButton
import dev.openmob.companion.ui.components.StatusChip
import dev.openmob.companion.ui.components.StatusKind
import dev.openmob.companion.ui.components.largeText
import dev.openmob.companion.ui.theme.OpenMobTheme

const val TAG_UPDATE_AVAILABLE = "update-available"
const val TAG_UPDATE_REQUIRED = "update-required"
const val TAG_UPDATE_TOO_OLD = "update-too-old"
const val TAG_UPDATE_DOWNLOAD = "update-download"
const val TAG_UPDATE_LATER = "update-later"
const val TAG_UPDATE_DISMISS = "update-dismiss"

/**
 * "An update is available" (mockup Main): at the top of Home, in the agent's blue container (never the approval
 * amber: nothing is asking the owner). Download update, Later, and ✕ ("Not now"); Later and ✕ hide it until a higher
 * version is offered.
 */
@Composable
fun UpdateAvailableCard(latest: Int, current: Int, host: String, downloadable: Boolean,
                        onDownload: () -> Unit, onLater: () -> Unit, modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    Surface(
        modifier = modifier.fillMaxWidth().testTag(TAG_UPDATE_AVAILABLE),
        shape = RoundedCornerShape(OpenMobTheme.radii.cardLarge),
        color = c.signalContainer,
        contentColor = c.ink,
        border = BorderStroke(1.dp, c.signal.copy(alpha = 0.25f)),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.Top) {
                Icon(DownloadIcon, contentDescription = null, tint = c.signal, modifier = Modifier.padding(top = 2.dp).size(20.dp))
                Column(Modifier.weight(1f).semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
                       verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(stringResource(R.string.update_available_title), style = MaterialTheme.typography.titleSmall,
                         color = c.ink, modifier = Modifier.semantics { heading() })
                    Text(stringResource(R.string.update_available_body, latest, host, current),
                         style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
                }
                IconButton(onClick = onLater, modifier = Modifier.size(48.dp).testTag(TAG_UPDATE_DISMISS)) {
                    Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.update_not_now),
                         tint = c.inkSecondary, modifier = Modifier.size(18.dp))
                }
            }
            val download = @Composable { m: Modifier ->
                if (downloadable) PrimaryButton(stringResource(R.string.update_download), onClick = onDownload,
                                                modifier = m.testTag(TAG_UPDATE_DOWNLOAD), icon = DownloadIcon)
            }
            val later = @Composable { m: Modifier, fill: Boolean ->
                SecondaryButton(stringResource(R.string.update_later), onClick = onLater, fillWidth = fill,
                                modifier = m.testTag(TAG_UPDATE_LATER))
            }
            // At large text the two buttons stack (no cut words); otherwise Download takes the width.
            if (largeText() || !downloadable) {
                download(Modifier)
                later(Modifier, true)
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    download(Modifier.weight(1f))
                    later(Modifier, false)
                }
            }
        }
    }
}

/**
 * "Update required" (mockup Required): Home's body while this app is below the server's minimum. The chip, the
 * title, why, a mono table of versions, Download update and three small steps. Disconnect and the (disabled)
 * composer stay below it.
 */
@Composable
fun UpdateRequiredCard(minimum: Int, latest: Int?, current: Int, downloadable: Boolean, onDownload: () -> Unit,
                       modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    OmCard(modifier.testTag(TAG_UPDATE_REQUIRED)) {
        StatusChip(StatusKind.Failed, stringResource(R.string.update_required_chip))
        Text(stringResource(R.string.update_required_title), style = MaterialTheme.typography.headlineSmall, color = c.ink,
             modifier = Modifier.semantics { heading(); liveRegion = LiveRegionMode.Polite })
        Text(stringResource(R.string.update_required_body), style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary)
        VersionTable(listOf(
            stringResource(R.string.update_this_phone) to current.toString(),
            stringResource(R.string.update_required_row) to stringResource(R.string.update_required_value, minimum),
            stringResource(R.string.update_latest_row) to (latest?.toString() ?: stringResource(R.string.update_unknown)),
        ))
        if (downloadable) {
            PrimaryButton(stringResource(R.string.update_download), onClick = onDownload, icon = DownloadIcon,
                          modifier = Modifier.testTag(TAG_UPDATE_DOWNLOAD))
            UpdateSteps()
        } else {
            Text(stringResource(R.string.update_no_download), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        }
    }
}

/** After a 4400: the server speaks a protocol this app doesn't. The last known download, else the server's own. */
@Composable
fun TooOldCard(downloadable: Boolean, onDownload: () -> Unit, modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    OmCard(modifier.testTag(TAG_UPDATE_TOO_OLD)) {
        StatusChip(StatusKind.Failed, stringResource(R.string.update_required_chip))
        Text(stringResource(R.string.update_too_old), style = MaterialTheme.typography.headlineSmall, color = c.ink,
             modifier = Modifier.semantics { heading(); liveRegion = LiveRegionMode.Polite })
        Text(stringResource(R.string.update_too_old_body), style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary)
        if (downloadable) {
            PrimaryButton(stringResource(R.string.update_download), onClick = onDownload, icon = DownloadIcon,
                          modifier = Modifier.testTag(TAG_UPDATE_DOWNLOAD))
            UpdateSteps()
        }
    }
}

/** "This phone 47 / Required 50 or newer / Latest 52", in mono on the sunken surface. Each row reads as one. */
@Composable
fun VersionTable(rows: List<Pair<String, String>>) {
    val c = OpenMobTheme.colors
    Column(
        Modifier.fillMaxWidth().background(c.surfaceSunken, RoundedCornerShape(12.dp)).padding(horizontal = 14.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        rows.forEach { (label, value) ->
            Row(Modifier.fillMaxWidth().semantics(mergeDescendants = true) {}, verticalAlignment = Alignment.CenterVertically) {
                Text(label, style = OpenMobTheme.mono.medium, color = c.inkSecondary, modifier = Modifier.weight(1f))
                Text(value, style = OpenMobTheme.mono.medium, color = c.ink, textAlign = TextAlign.End)
            }
        }
    }
}

/** The three small steps after Download (an ordered list: TalkBack reads "Step 1 of 3: …"). */
@Composable
private fun UpdateSteps() {
    val c = OpenMobTheme.colors
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        listOf(R.string.update_step_1, R.string.update_step_2, R.string.update_step_3).forEachIndexed { i, id ->
            val text = stringResource(id)
            val desc = stringResource(R.string.update_steps_desc, i + 1, text)
            Row(Modifier.semantics(mergeDescendants = true) { contentDescription = desc },
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("${i + 1}.", style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
                Text(text, style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
            }
        }
    }
}
