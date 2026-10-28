package dev.openmob.companion.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.openmob.companion.ui.theme.OpenMobTheme

@Composable
private fun RowTexts(title: String, subtitle: String?, modifier: Modifier = Modifier) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(title, style = MaterialTheme.typography.titleSmall, color = OpenMobTheme.colors.ink)
        if (subtitle != null) {
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = OpenMobTheme.colors.inkTertiary)
        }
    }
}

/**
 * A row in a list or a settings group: title, optional subtitle, optional leading content. With [onClick] it is
 * one 56 dp tall button with a chevron, read as a single item by TalkBack.
 */
@Composable
fun ListRow(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    onClick: (() -> Unit)? = null,
    leading: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
) {
    val sp = OpenMobTheme.spacing
    val base = modifier.fillMaxWidth().heightIn(min = OpenMobTheme.sizes.listRow)
    val interactive = if (onClick != null) {
        base.clickable(role = Role.Button, onClick = onClick)
    } else {
        base.semantics(mergeDescendants = true) {}
    }
    Row(
        modifier = interactive.padding(horizontal = sp.lg, vertical = sp.md),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(sp.md),
    ) {
        if (leading != null) leading()
        // At large text the trailing content goes under the texts, so the title keeps the row's width.
        val below = trailing != null && largeText()
        if (below) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(sp.xs)) {
                RowTexts(title, subtitle)
                trailing?.invoke()
            }
        } else {
            RowTexts(title, subtitle, Modifier.weight(1f))
        }
        when {
            below -> {}
            trailing != null -> trailing()
            onClick != null -> Icon(
                Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = null,
                tint = OpenMobTheme.colors.inkSecondary,
                modifier = Modifier.size(20.dp),
            )
        }
    }
}

/**
 * A setting that is on or off. The whole row is the switch (one target, `Role.Switch`), so TalkBack reads the
 * title, subtitle and state together and a tap anywhere on the row flips it.
 */
@Composable
fun ToggleRow(
    title: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    enabled: Boolean = true,
) {
    val c = OpenMobTheme.colors
    val sp = OpenMobTheme.spacing
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = OpenMobTheme.sizes.listRow)
            .toggleable(value = checked, enabled = enabled, role = Role.Switch, onValueChange = onCheckedChange)
            .padding(horizontal = sp.lg, vertical = sp.md),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(sp.md),
    ) {
        RowTexts(title, subtitle, Modifier.weight(1f))
        Switch(
            checked = checked,
            onCheckedChange = null,
            enabled = enabled,
            colors = SwitchDefaults.colors(
                checkedTrackColor = c.signal,
                checkedThumbColor = c.onSignal,
                uncheckedTrackColor = c.neutralContainer,
                uncheckedThumbColor = c.inkSecondary,
                uncheckedBorderColor = c.outline,
            ),
        )
    }
}
