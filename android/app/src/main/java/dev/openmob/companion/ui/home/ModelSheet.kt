package dev.openmob.companion.ui.home

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SheetState
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import dev.openmob.companion.AppState
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.CheckIcon
import dev.openmob.companion.ui.components.FilterPill
import dev.openmob.companion.ui.components.ShieldIcon
import dev.openmob.companion.ui.theme.OpenMobTheme

const val TAG_MODEL_SHEET = "model-sheet"
const val TAG_EFFORT_ROW = "model-effort"
const val TAG_MORE_MODELS = "model-more"

/** The model sheet (canvas ModelSheet / ModelSheetDark), as a modal bottom sheet. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ModelSheet(
    models: AppState.ModelState,
    onPick: (model: String, effort: String) -> Unit,
    onDismiss: () -> Unit,
    sheetState: SheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
) {
    val c = OpenMobTheme.colors
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState, containerColor = c.surface) {
        ModelSheetContent(models, onPick, onDismiss)
    }
}

/** The sheet's content, also drawn on its own (tests and screenshots). A pick is sent at once; the chip follows
 *  the server's `model_state`. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ModelSheetContent(models: AppState.ModelState, onPick: (String, String) -> Unit, onDismiss: () -> Unit,
                      modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    var picked by remember(models.model) { mutableStateOf(models.model) }
    var effort by remember(models.effort) { mutableStateOf(models.effort) }
    var effortOpen by rememberSaveable { mutableStateOf(false) }
    val more = models.models.filter { it.group == "more" }
    var moreOpen by rememberSaveable { mutableStateOf(more.any { it.id == models.model }) }
    val pickedModel = models.models.firstOrNull { it.id == picked }
    fun pick(id: String, e: String) { picked = id; effort = e; onPick(id, e) }
    Column(
        modifier.fillMaxWidth().testTag(TAG_MODEL_SHEET).verticalScroll(rememberScrollState())
            .padding(start = 20.dp, end = 20.dp, bottom = 24.dp).navigationBarsPadding(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.rd_model_title), style = MaterialTheme.typography.titleLarge, color = c.ink,
                 modifier = Modifier.weight(1f).semantics { heading() })
            IconButton(onClick = onDismiss, modifier = Modifier.size(48.dp)) {
                Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.rd_model_close), tint = c.ink)
            }
        }
        Text(stringResource(R.string.rd_model_offered).uppercase(), style = MaterialTheme.typography.labelMedium,
             color = c.inkSecondary, modifier = Modifier.semantics { heading() })
        Column(Modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            models.models.filter { it.group != "more" }.forEach { m -> ModelRow(m, m.id == picked) { pick(m.id, effort) } }
        }
        Column {
            HorizontalDivider(color = c.divider)
            if (pickedModel?.effort == true) {
                ExpandRow(stringResource(R.string.rd_model_effort), effortLabel(effort), effortOpen, Modifier.testTag(TAG_EFFORT_ROW)) {
                    effortOpen = !effortOpen
                }
                if (effortOpen) {
                    FlowRow(Modifier.padding(start = 4.dp, bottom = 8.dp).selectableGroup(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf("auto", "low", "medium", "high").forEach { e ->
                            FilterPill(effortLabel(e), selected = effort == e, onSelect = { pick(picked, e) })
                        }
                    }
                }
                Text(stringResource(R.string.rd_model_effort_auto), style = MaterialTheme.typography.bodySmall,
                     color = c.inkTertiary, modifier = Modifier.padding(start = 4.dp, bottom = 8.dp))
            }
            // Other providers: only when this server has their keys.
            if (more.isNotEmpty()) {
                HorizontalDivider(color = c.divider)
                ExpandRow(stringResource(R.string.rd_model_more), null, moreOpen, Modifier.testTag(TAG_MORE_MODELS)) { moreOpen = !moreOpen }
                if (moreOpen) {
                    Column(Modifier.selectableGroup().padding(bottom = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        more.forEach { m -> ModelRow(m, m.id == picked) { pick(m.id, "auto") } }
                    }
                } else {
                    Text(more.joinToString(", ") { it.label }, style = MaterialTheme.typography.bodySmall, color = c.inkTertiary,
                         modifier = Modifier.padding(start = 4.dp, bottom = 8.dp))
                }
            }
        }
        Row(
            Modifier.fillMaxWidth().background(c.ground, RoundedCornerShape(14.dp)).padding(horizontal = 14.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(ShieldIcon, contentDescription = null, tint = c.ink, modifier = Modifier.size(16.dp))
            Text(stringResource(R.string.rd_model_footer), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        }
    }
}

@Composable
private fun ExpandRow(title: String, value: String?, open: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val c = OpenMobTheme.colors
    val state = stringResource(if (open) R.string.rd_expanded else R.string.rd_collapsed)
    Row(
        modifier.fillMaxWidth().heightIn(min = 52.dp).clickable(role = Role.Button, onClick = onClick)
            .semantics { stateDescription = state }.padding(horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(title, style = MaterialTheme.typography.titleSmall, color = c.ink, modifier = Modifier.weight(1f))
        if (value != null) Text(value, style = OpenMobTheme.mono.medium, color = c.inkSecondary)
        Icon(if (open) Icons.Filled.KeyboardArrowUp else Icons.Filled.KeyboardArrowDown, contentDescription = null, tint = c.inkSecondary)
    }
}

/** One model: name, the speed tag (a word and bars, never colour alone), the description, a check when chosen. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ModelRow(m: AppState.PhoneModel, selected: Boolean, onSelect: () -> Unit) {
    val c = OpenMobTheme.colors
    val shape = RoundedCornerShape(16.dp)
    Row(
        Modifier.fillMaxWidth().heightIn(min = 72.dp)
            .background(if (selected) c.signalContainer else c.surface, shape)
            .border(2.dp, if (selected) c.signal else c.border, shape)
            .selectable(selected = selected, role = Role.RadioButton, onClick = onSelect)
            .padding(start = 14.dp, end = 12.dp, top = 10.dp, bottom = 10.dp)
            .testTag("model-${m.id}"),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(m.label, style = MaterialTheme.typography.titleMedium, color = c.ink)
                SpeedTag(m.speed)
            }
            if (m.description.isNotEmpty()) Text(m.description, style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary)
        }
        Box(Modifier.size(28.dp), contentAlignment = Alignment.Center) {
            if (selected) {
                Box(Modifier.size(28.dp).background(c.signal, CircleShape), contentAlignment = Alignment.Center) {
                    Icon(CheckIcon, contentDescription = null, tint = c.onSignal, modifier = Modifier.size(16.dp))
                }
            }
        }
    }
}

@Composable
private fun SpeedTag(speed: String) {
    val c = OpenMobTheme.colors
    val bars = when (speed) { "fast" -> 3; "slow" -> 1; else -> 2 }
    val word = stringResource(when (speed) { "fast" -> R.string.rd_speed_fast; "slow" -> R.string.rd_speed_slow; else -> R.string.rd_speed_medium })
    val spoken = stringResource(R.string.rd_speed_desc, word)
    Row(
        Modifier.heightIn(min = 22.dp).background(c.ground, RoundedCornerShape(11.dp)).border(1.dp, c.border, RoundedCornerShape(11.dp))
            .padding(horizontal = 8.dp).semantics(mergeDescendants = true) { contentDescription = spoken },
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Canvas(Modifier.size(12.dp)) {
            val u = size.width / 12f
            val on = c.signal
            val off = c.outline
            drawRoundRect(on, Offset(0f, 8 * u), Size(3 * u, 4 * u), CornerRadius(0.5f * u))
            drawRoundRect(if (bars >= 2) on else off, Offset(4.5f * u, 4.5f * u), Size(3 * u, 7.5f * u), CornerRadius(0.5f * u))
            drawRoundRect(if (bars >= 3) on else off, Offset(9 * u, 1 * u), Size(3 * u, 11 * u), CornerRadius(0.5f * u))
        }
        Text(word, style = OpenMobTheme.mono.small, color = c.inkSecondary)
    }
}
