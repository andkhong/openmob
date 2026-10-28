package dev.openmob.companion.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import dev.openmob.companion.ui.theme.OpenMobTheme
import dev.openmob.companion.ui.theme.PillShape

/**
 * The buttons. All are pills at least 56 dp tall (48 dp touch targets at minimum), full width by default, and
 * labelled by their text; an icon is decoration. Deny and Approve, and Stop, use the same sizes, so a risky
 * choice is never the bigger target.
 */
@Composable
private fun ButtonContent(text: String, icon: ImageVector?) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        if (icon != null) Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}

private val ButtonPadding = PaddingValues(horizontal = 20.dp, vertical = 12.dp)

private fun Modifier.buttonSize(fill: Boolean): Modifier =
    (if (fill) fillMaxWidth() else this).heightIn(min = 56.dp)

/** The one main action on a screen, in signal blue ("Get started", "Send"). */
@Composable
fun PrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    enabled: Boolean = true,
    fillWidth: Boolean = true,
) {
    val c = OpenMobTheme.colors
    Button(
        onClick = onClick,
        modifier = modifier.buttonSize(fillWidth),
        enabled = enabled,
        shape = PillShape,
        contentPadding = ButtonPadding,
        colors = ButtonDefaults.buttonColors(
            containerColor = c.signal,
            contentColor = c.onSignal,
            disabledContainerColor = c.neutralContainer,
            disabledContentColor = c.inkSecondary,
        ),
    ) { ButtonContent(text, icon) }
}

/** An outlined alternative ("Type a code instead", "Disconnect this phone"). */
@Composable
fun SecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    enabled: Boolean = true,
    fillWidth: Boolean = true,
) {
    val c = OpenMobTheme.colors
    OutlinedButton(
        onClick = onClick,
        modifier = modifier.buttonSize(fillWidth),
        enabled = enabled,
        shape = PillShape,
        contentPadding = ButtonPadding,
        border = BorderStroke(1.dp, if (enabled) c.outline else c.border),
        colors = ButtonDefaults.outlinedButtonColors(
            containerColor = c.surface,
            contentColor = c.ink,
            disabledContentColor = c.inkSecondary,
        ),
    ) { ButtonContent(text, icon) }
}

/** Something that removes access or can't be undone in one tap ("Unpair", "Stop and disconnect"). */
@Composable
fun DangerButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    enabled: Boolean = true,
    fillWidth: Boolean = true,
) {
    val c = OpenMobTheme.colors
    Button(
        onClick = onClick,
        modifier = modifier.buttonSize(fillWidth),
        enabled = enabled,
        shape = PillShape,
        contentPadding = ButtonPadding,
        colors = ButtonDefaults.buttonColors(
            containerColor = c.danger,
            contentColor = c.onDanger,
            disabledContainerColor = c.neutralContainer,
            disabledContentColor = c.inkSecondary,
        ),
    ) { ButtonContent(text, icon) }
}

/** The Stop control: an ink pill with a square (pale in dark mode). Stops the task; stays connected. */
@Composable
fun StopButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    Button(
        onClick = onClick,
        modifier = modifier.buttonSize(fill = true),
        shape = PillShape,
        contentPadding = ButtonPadding,
        colors = ButtonDefaults.buttonColors(containerColor = c.inverse, contentColor = c.onInverse),
    ) { ButtonContent(text, StopSquare) }
}

/** A text link ("All activity", "More options"), still with a 48 dp target. */
@Composable
fun LinkButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    TextButton(
        onClick = onClick,
        modifier = modifier.heightIn(min = 48.dp),
        colors = ButtonDefaults.textButtonColors(contentColor = OpenMobTheme.colors.signal),
    ) { Text(text, style = MaterialTheme.typography.titleSmall) }
}

/** Two equal buttons side by side (Deny | Approve). */
@Composable
fun ButtonPair(modifier: Modifier = Modifier, content: @Composable RowScope.() -> Unit) {
    Row(modifier = modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp), content = content)
}
