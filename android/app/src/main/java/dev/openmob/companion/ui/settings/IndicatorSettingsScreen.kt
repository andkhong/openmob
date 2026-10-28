package dev.openmob.companion.ui.settings

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.openmob.companion.IndicatorColors
import dev.openmob.companion.PillCorner
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.ChoiceTile
import dev.openmob.companion.ui.components.ColorSwatch
import dev.openmob.companion.ui.components.OmCard
import dev.openmob.companion.ui.components.largeText
import dev.openmob.companion.ui.components.OmTextField
import dev.openmob.companion.ui.components.SecondaryButton
import dev.openmob.companion.ui.components.SectionHeader
import dev.openmob.companion.ui.components.ToggleRow
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.nav.ScreenScaffold
import dev.openmob.companion.ui.theme.ApprovalAmber
import dev.openmob.companion.ui.theme.OpenMobTheme

const val TAG_BOTH_OFF = "indicator-both-off"
const val TAG_NEAR_AMBER = "indicator-near-amber"

data class IndicatorActions(
    val back: () -> Unit = {},
    val border: (Boolean) -> Unit = {},
    val preset: (String) -> Unit = {},
    val customText: (String) -> Unit = {},
    val applyCustom: () -> Unit = {},
    val pulse: (Boolean) -> Unit = {},
    val pill: (Boolean) -> Unit = {},
    val corner: (PillCorner) -> Unit = {},
    val preview: () -> Unit = {},
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun IndicatorSettingsScreen(state: IndicatorUiState, actions: IndicatorActions, modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    val argb = Color(IndicatorColors.argb(state.color))
    ScreenScaffold(title = stringResource(Route.Indicator.title), onBack = actions.back, modifier = modifier) {
        OmCard(contentPadding = 16.dp) {
            val description = stringResource(
                R.string.rd_indicator_preview_desc,
                indicatorSummary(state.border, state.color, state.pill, state.corner),
            )
            val legend = @Composable { m: Modifier ->
                Column(m, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(stringResource(R.string.rd_indicator_looks), style = MaterialTheme.typography.labelMedium, color = c.inkSecondary)
                    Look(argb, LookKind.Steady, R.string.rd_indicator_steady, R.string.rd_indicator_steady_body)
                    Look(argb, LookKind.Amber, R.string.rd_indicator_amber, R.string.rd_indicator_amber_body)
                    Look(argb, LookKind.Dashed, R.string.rd_indicator_dashed, R.string.rd_indicator_dashed_body)
                }
            }
            // Side by side; at large text, the drawing above its legend.
            if (largeText()) {
                PhonePreview(state, argb, Modifier.align(Alignment.CenterHorizontally).semantics { contentDescription = description })
                legend(Modifier.fillMaxWidth())
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    PhonePreview(state, argb, Modifier.semantics { contentDescription = description })
                    legend(Modifier.weight(1f))
                }
            }
            SecondaryButton(stringResource(R.string.indicator_preview), onClick = actions.preview)
        }

        OmCard(contentPadding = 0.dp) {
            ToggleRow(stringResource(R.string.indicator_border), checked = state.border, onCheckedChange = actions.border)
            HorizontalDivider(color = c.divider)
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                SectionHeader(stringResource(R.string.indicator_color))
                val perRow = if (largeText()) 3 else 4 // large text: wider swatches, so "Custom" fits
                FlowRow(
                    modifier = Modifier.fillMaxWidth().selectableGroup(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    maxItemsInEachRow = perRow,
                ) {
                    IndicatorColors.PRESETS.forEach { p ->
                        ColorSwatch(
                            label = p.label.substringBefore(" ("),
                            color = Color(p.argb),
                            selected = state.color == p.key,
                            onSelect = { actions.preset(p.key) },
                            description = p.label,
                            modifier = Modifier.weight(1f),
                        )
                    }
                    ColorSwatch(
                        label = stringResource(R.string.rd_custom),
                        color = if (state.customChosen) argb else null,
                        selected = state.customChosen,
                        onSelect = actions.applyCustom,
                        description = stringResource(R.string.rd_indicator_custom_label),
                        modifier = Modifier.weight(1f),
                    )
                    // Keep the last row's swatches the width of the others.
                    repeat((perRow - (IndicatorColors.PRESETS.size + 1) % perRow) % perRow) { Spacer(Modifier.weight(1f)) }
                }
                OmTextField(
                    value = state.customText,
                    onValueChange = actions.customText,
                    placeholder = stringResource(R.string.indicator_custom_hint),
                    label = stringResource(R.string.rd_indicator_custom_label),
                    error = if (state.customInvalid) stringResource(R.string.indicator_custom_invalid) else null,
                    textStyle = OpenMobTheme.mono.medium.copy(fontSize = MaterialTheme.typography.bodyLarge.fontSize),
                    imeAction = ImeAction.Done,
                    onSubmit = actions.applyCustom,
                    modifier = Modifier.fillMaxWidth(),
                )
                if (state.nearAmber) {
                    Text(stringResource(R.string.rd_indicator_near_amber), style = MaterialTheme.typography.bodySmall,
                         color = c.onDangerContainer, modifier = Modifier.testTag(TAG_NEAR_AMBER))
                }
                SecondaryButton(stringResource(R.string.rd_indicator_custom_apply), onClick = actions.applyCustom)
                if (!state.border) {
                    Text(stringResource(R.string.rd_indicator_border_off), style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
                }
            }
            HorizontalDivider(color = c.divider)
            ToggleRow(
                stringResource(R.string.indicator_pulse),
                checked = state.pulse,
                onCheckedChange = actions.pulse,
                subtitle = stringResource(R.string.indicator_pulse_help),
            )
        }

        OmCard(contentPadding = 0.dp) {
            ToggleRow(
                stringResource(R.string.indicator_pill),
                checked = state.pill,
                onCheckedChange = actions.pill,
                subtitle = stringResource(R.string.rd_indicator_pill_body),
            )
            HorizontalDivider(color = c.divider)
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                SectionHeader(stringResource(R.string.rd_indicator_corner))
                val rows = listOf(
                    listOf(PillCorner.TOP_LEFT, PillCorner.TOP_RIGHT),
                    listOf(PillCorner.BOTTOM_LEFT, PillCorner.BOTTOM_RIGHT),
                )
                Column(Modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    rows.forEach { row ->
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            row.forEach { corner ->
                                ChoiceTile(
                                    stringResource(cornerLabel(corner)),
                                    selected = state.corner == corner,
                                    onSelect = { actions.corner(corner) },
                                    modifier = Modifier.weight(1f),
                                )
                            }
                        }
                    }
                }
                Text(stringResource(R.string.rd_indicator_corner_note), style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
            }
        }

        // Both off is the owner's choice (decided); say what it means (UX review 2, M6).
        if (!state.border && !state.pill) {
            Text(stringResource(R.string.rd_indicator_both_off), style = MaterialTheme.typography.bodySmall, color = c.onDangerContainer,
                 modifier = Modifier.fillMaxWidth().background(c.dangerContainer, androidx.compose.foundation.shape.RoundedCornerShape(12.dp))
                     .padding(12.dp).testTag(TAG_BOTH_OFF))
        }
        Text(
            stringResource(R.string.rd_settings_only_you),
            style = MaterialTheme.typography.labelSmall,
            color = c.inkTertiary,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

private enum class LookKind { Steady, Amber, Dashed }

@Composable
private fun Look(argb: Color, kind: LookKind, title: Int, body: Int) {
    val c = OpenMobTheme.colors
    Row(
        Modifier.semantics(mergeDescendants = true) {},
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Canvas(Modifier.size(width = 28.dp, height = 18.dp)) {
            val r = CornerRadius(5.dp.toPx())
            when (kind) {
                LookKind.Steady -> drawRoundRect(argb, cornerRadius = r, style = Stroke(3.dp.toPx()))
                LookKind.Amber -> {
                    drawRoundRect(ApprovalAmber, cornerRadius = r, style = Stroke(5.dp.toPx()))
                    val inset = 4.dp.toPx()
                    drawRoundRect(argb, Offset(inset, inset), Size(size.width - 2 * inset, size.height - 2 * inset),
                                  CornerRadius(2.dp.toPx()), style = Stroke(1.5.dp.toPx()))
                }
                LookKind.Dashed -> drawRoundRect(
                    argb.copy(alpha = 0.6f), cornerRadius = r,
                    style = Stroke(3.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx()))),
                )
            }
        }
        Column {
            Text(stringResource(title), style = MaterialTheme.typography.labelMedium, color = c.ink)
            Text(stringResource(body), style = MaterialTheme.typography.bodySmall, color = c.ink)
        }
    }
}

/** A small phone with the chosen border and the Stop button in its corner (drawn, not the real overlay). */
@Composable
private fun PhonePreview(state: IndicatorUiState, argb: Color, modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    val shape = RoundedCornerShape(20.dp)
    Box(
        modifier = modifier
            .size(width = 124.dp, height = 248.dp)
            .background(if (c.isDark) Color(0xFF242C38) else Color(0xFFEEF0F3), shape)
            .then(if (state.border) Modifier.border(4.dp, argb, shape) else Modifier.border(1.dp, c.border, shape)),
    ) {
        Column(Modifier.padding(start = 12.dp, end = 12.dp, top = 52.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            val bar = if (c.isDark) Color(0xFF3A4556) else Color(0xFFD5D9E0)
            Box(Modifier.fillMaxWidth().height(8.dp).background(bar, RoundedCornerShape(4.dp)))
            Box(Modifier.width(76.dp).height(8.dp).background(bar, RoundedCornerShape(4.dp)))
            Box(Modifier.width(88.dp).height(8.dp).background(bar, RoundedCornerShape(4.dp)))
        }
        if (state.pill) {
            val align = when (state.corner) {
                PillCorner.TOP_RIGHT -> Alignment.TopEnd
                PillCorner.TOP_LEFT -> Alignment.TopStart
                PillCorner.BOTTOM_RIGHT -> Alignment.BottomEnd
                PillCorner.BOTTOM_LEFT -> Alignment.BottomStart
            }
            Row(
                modifier = Modifier
                    .align(align)
                    .padding(horizontal = 6.dp, vertical = 14.dp)
                    .height(22.dp)
                    .background(Color(0xFF0E1621), RoundedCornerShape(11.dp))
                    .border(1.5.dp, if (state.border) argb else Color(0xFF0E1621), RoundedCornerShape(11.dp))
                    .padding(horizontal = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Box(Modifier.size(7.dp).background(Color.White, RoundedCornerShape(1.dp)))
                // A drawing to scale: its label is sized in dp, so large text settings don't burst the 22dp pill.
                val label = with(LocalDensity.current) { 10.dp.toSp() }
                Text(stringResource(R.string.rd_indicator_stop), style = MaterialTheme.typography.labelSmall.copy(fontSize = label, lineHeight = label),
                     color = Color.White, maxLines = 1)
            }
        }
    }
}

@Composable
fun IndicatorRoute(
    back: () -> Unit,
    vm: IndicatorViewModel = viewModel(factory = IndicatorViewModel.factory(LocalContext.current)),
) {
    val state by vm.state.collectAsStateWithLifecycle()
    IndicatorSettingsScreen(
        state,
        IndicatorActions(
            back = back,
            border = vm::setBorder,
            preset = vm::setPreset,
            customText = vm::setCustomText,
            applyCustom = { vm.applyCustom() },
            pulse = vm::setPulse,
            pill = vm::setPill,
            corner = vm::setCorner,
            preview = vm::preview,
        ),
    )
}
