package dev.openmob.companion.ui.components

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import dev.openmob.companion.ui.theme.OpenMobTheme
import dev.openmob.companion.ui.theme.PillShape

/*
 * Step 2 components: choices (a tile with a radio, a colour swatch), a small neutral chip, and the text field.
 * Each choice is one 48 dp target with Role.RadioButton, so TalkBack reads "<label>, selected/not selected".
 */

/** One option of a small grid ("Top right"): a bordered tile with a radio; the chosen one is outlined in blue. */
@Composable
fun ChoiceTile(label: String, selected: Boolean, onSelect: () -> Unit, modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    val shape = RoundedCornerShape(12.dp)
    Row(
        modifier = modifier
            .heightIn(min = OpenMobTheme.sizes.touchTarget)
            .background(if (selected) c.signalContainer else c.surface, shape)
            .border(if (selected) 2.dp else 1.dp, if (selected) c.signal else c.outline, shape)
            .selectable(selected = selected, role = Role.RadioButton, onClick = onSelect)
            .padding(horizontal = 12.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        RadioButton(
            selected = selected,
            onClick = null,
            colors = RadioButtonDefaults.colors(selectedColor = c.signal, unselectedColor = c.inkSecondary),
        )
        Text(label, style = MaterialTheme.typography.titleSmall, color = c.ink)
    }
}

/**
 * A colour choice: a 44 dp dot with its name under it (one target, at least 48 dp). The chosen dot gets a ring and a
 * check, so the choice doesn't rest on colour; a faint dot (white, light custom) gets a hairline. [color] null draws
 * the custom (rainbow) dot.
 */
@Composable
fun ColorSwatch(
    label: String,
    color: Color?,
    selected: Boolean,
    onSelect: () -> Unit,
    modifier: Modifier = Modifier,
    description: String = label,
) {
    val c = OpenMobTheme.colors
    Column(
        modifier = modifier
            .widthIn(min = OpenMobTheme.sizes.touchTarget)
            .selectable(selected = selected, role = Role.RadioButton, onClick = onSelect)
            .semantics(mergeDescendants = true) { contentDescription = description }
            .padding(vertical = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        val ring = if (selected) Modifier.border(2.dp, c.ink, CircleShape).padding(4.dp) else Modifier.padding(4.dp)
        Box(ring) {
            val fill = if (color == null) {
                Modifier.background(
                    Brush.sweepGradient(listOf(Color(0xFF2F7BFF), Color(0xFFA855F7), Color(0xFFFF4F9A), Color(0xFFFF5722), Color(0xFF00C853), Color(0xFF2F7BFF))),
                    CircleShape,
                )
            } else {
                Modifier.background(color, CircleShape)
            }
            val faint = color != null && color.luminance() > 0.6f
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .then(fill)
                    .then(if (faint) Modifier.border(1.5.dp, c.ink, CircleShape) else Modifier),
                contentAlignment = Alignment.Center,
            ) {
                if (selected) {
                    val tick = if (color == null || color.luminance() > 0.5f) Color(0xFF0E1621) else Color.White
                    Icon(Icons.Filled.Check, contentDescription = null, tint = tick, modifier = Modifier.size(20.dp))
                }
            }
        }
        Text(label, style = MaterialTheme.typography.labelSmall, color = c.ink, modifier = Modifier.clearAndSetSemantics {})
    }
}

/** A filter in a row of filters ("All", "Asked you"): a 48 dp pill, filled when chosen; one choice at a time. */
@Composable
fun FilterPill(label: String, selected: Boolean, onSelect: () -> Unit, modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    Row(
        modifier = modifier
            .heightIn(min = OpenMobTheme.sizes.touchTarget)
            .widthIn(min = 64.dp)
            .background(if (selected) c.inverse else c.surface, PillShape)
            .border(1.dp, if (selected) c.inverse else c.outline, PillShape)
            .selectable(selected = selected, role = Role.RadioButton, onClick = onSelect)
            .padding(horizontal = 16.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        Text(label, style = MaterialTheme.typography.labelLarge.copy(fontSize = MaterialTheme.typography.labelMedium.fontSize),
             color = if (selected) c.onInverse else c.ink)
    }
}

/** A small neutral chip with an optional icon ("Faster mode off", "Asked you 0 times"): information, not a status. */
@Composable
fun MetaChip(label: String, modifier: Modifier = Modifier, icon: ImageVector? = null) {
    val c = OpenMobTheme.colors
    Row(
        modifier = modifier
            .semantics(mergeDescendants = true) {}
            .heightIn(min = OpenMobTheme.sizes.chip)
            .background(c.surfaceSunken, PillShape)
            .border(1.dp, c.border, PillShape)
            .padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (icon != null) Icon(icon, contentDescription = null, tint = c.inkSecondary, modifier = Modifier.size(14.dp))
        Text(label, style = MaterialTheme.typography.labelSmall, color = c.inkSecondary)
    }
}

/** The one-line text field ("Tell your phone what to do…", "#RRGGBB"). [pill]: the ask field's round ends. */
@Composable
fun OmTextField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    label: String? = null,
    enabled: Boolean = true,
    pill: Boolean = false,
    error: String? = null,
    textStyle: TextStyle = MaterialTheme.typography.bodyLarge,
    keyboardType: KeyboardType = KeyboardType.Text,
    imeAction: ImeAction = ImeAction.Done,
    capitalization: KeyboardCapitalization = KeyboardCapitalization.None,
    autoCorrect: Boolean = true,
    visualTransformation: VisualTransformation = VisualTransformation.None,
    onSubmit: () -> Unit = {},
) {
    val c = OpenMobTheme.colors
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.heightIn(min = 52.dp),
        enabled = enabled,
        singleLine = true,
        textStyle = textStyle,
        label = label?.let { { Text(it) } },
        // The hint wraps rather than being cut off at large text sizes.
        placeholder = { Text(placeholder, style = textStyle, color = c.inkTertiary) },
        isError = error != null,
        visualTransformation = visualTransformation,
        supportingText = error?.let { { Text(it) } },
        shape = if (pill) PillShape else RoundedCornerShape(12.dp),
        keyboardOptions = KeyboardOptions(capitalization = capitalization, autoCorrectEnabled = autoCorrect,
                                          keyboardType = keyboardType, imeAction = imeAction),
        keyboardActions = KeyboardActions(onAny = { onSubmit() }),
        colors = OutlinedTextFieldDefaults.colors(
            focusedContainerColor = c.surface,
            unfocusedContainerColor = c.surface,
            disabledContainerColor = c.neutralContainer,
            focusedBorderColor = c.signal,
            unfocusedBorderColor = c.outline,
            disabledBorderColor = c.border,
            focusedTextColor = c.ink,
            unfocusedTextColor = c.ink,
            disabledTextColor = c.inkSecondary,
            cursorColor = c.signal,
        ),
    )
}

@Preview(name = "Choices, light", widthDp = 390, showBackground = true)
@Preview(name = "Choices, dark", widthDp = 390, showBackground = true, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun ChoicesPreview() {
    OpenMobTheme {
        Column(
            Modifier.background(OpenMobTheme.colors.ground).padding(20.dp).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ChoiceTile("Top left", selected = false, onSelect = {}, modifier = Modifier.weight(1f))
                ChoiceTile("Top right", selected = true, onSelect = {}, modifier = Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ColorSwatch("Blue", Color(0xFF2F7BFF), selected = true, onSelect = {})
                ColorSwatch("White", Color.White, selected = false, onSelect = {})
                ColorSwatch("Custom", null, selected = false, onSelect = {})
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetaChip("Faster mode off", icon = Icons.Filled.Info)
                MetaChip("Asks for risky actions")
            }
            OmTextField("", {}, placeholder = "Tell your phone what to do…", pill = true, modifier = Modifier.fillMaxWidth())
            OmTextField("#12", {}, placeholder = "#RRGGBB", label = "Custom colour", error = "Use six hex digits", modifier = Modifier.fillMaxWidth())
        }
    }
}
