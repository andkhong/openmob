package dev.openmob.companion.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import dev.openmob.companion.ui.theme.OpenMobTheme

/** A white (dark: blue-black) card with a hairline border. [highlighted] gives it the agent's blue ring. */
@Composable
fun OmCard(
    modifier: Modifier = Modifier,
    highlighted: Boolean = false,
    /** Inside padding; 0 for a card that holds full-width rows (each row pads itself). */
    contentPadding: Dp = OpenMobTheme.spacing.xl,
    content: @Composable ColumnScope.() -> Unit,
) {
    val c = OpenMobTheme.colors
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(OpenMobTheme.radii.cardLarge),
        color = c.surface,
        contentColor = c.ink,
        border = if (highlighted) BorderStroke(2.dp, c.signal) else BorderStroke(1.dp, c.border),
    ) {
        Column(
            modifier = Modifier.padding(contentPadding),
            verticalArrangement = Arrangement.spacedBy(if (contentPadding == 0.dp) 0.dp else OpenMobTheme.spacing.lg),
            content = content,
        )
    }
}

/** A group's title above a card or list ("Always blocked"). Marked as a heading for TalkBack navigation. */
@Composable
fun SectionHeader(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        style = MaterialTheme.typography.titleSmall.copy(fontWeight = MaterialTheme.typography.labelMedium.fontWeight),
        color = OpenMobTheme.colors.inkSecondary,
        modifier = modifier
            .fillMaxWidth()
            .padding(top = OpenMobTheme.spacing.sm, bottom = OpenMobTheme.spacing.xs)
            .semantics { heading() },
    )
}

/**
 * An exact value in IBM Plex Mono: a server, an account, a code, an amount, the action being approved.
 * [label], when given, is read with the value ("Server, home-server.local").
 */
@Composable
fun MonoValue(
    value: String,
    modifier: Modifier = Modifier,
    label: String? = null,
    style: TextStyle = OpenMobTheme.mono.medium,
) {
    if (label == null) {
        Text(value, style = style, color = OpenMobTheme.colors.ink, modifier = modifier)
        return
    }
    LabeledLine(label, modifier) { Text(value, style = style, color = OpenMobTheme.colors.ink) }
}

/** True at large text sizes (font scale 1.3 and up), where side-by-side labels stack instead. */
@Composable
fun largeText(): Boolean = androidx.compose.ui.platform.LocalDensity.current.fontScale >= 1.3f

/** A label in an 88dp column with its value beside it; at large text, the label above the value (no cut words). */
@Composable
fun LabeledLine(label: String, modifier: Modifier = Modifier, value: @Composable () -> Unit) {
    val labelText = @Composable { w: Modifier ->
        Text(label, style = MaterialTheme.typography.bodySmall, color = OpenMobTheme.colors.inkTertiary, modifier = w)
    }
    if (largeText()) {
        Column(modifier.fillMaxWidth().semantics(mergeDescendants = true) {}) {
            labelText(Modifier)
            Row(verticalAlignment = Alignment.CenterVertically) { value() }
        }
    } else {
        Row(
            modifier = modifier.fillMaxWidth().semantics(mergeDescendants = true) {},
            verticalAlignment = Alignment.CenterVertically,
        ) {
            labelText(Modifier.width(88.dp))
            value()
        }
    }
}

/**
 * The amber "the phone is asking you" band. Amber means only this, in both themes. The text is ink on amber
 * (far above 4.5:1), and the band is a polite live region so TalkBack announces it when it appears.
 */
@Composable
fun AskingBand(text: String, modifier: Modifier = Modifier, detail: String? = null) {
    val c = OpenMobTheme.colors
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = OpenMobTheme.sizes.touchTarget)
            .background(c.asking, RoundedCornerShape(OpenMobTheme.radii.md))
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite }
            .padding(horizontal = OpenMobTheme.spacing.lg, vertical = OpenMobTheme.spacing.md),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(OpenMobTheme.spacing.md),
    ) {
        Icon(Icons.Filled.Lock, contentDescription = null, tint = c.onAsking, modifier = Modifier.size(20.dp))
        Column(verticalArrangement = Arrangement.spacedBy(OpenMobTheme.spacing.xxs)) {
            Text(text, style = MaterialTheme.typography.titleSmall.copy(fontWeight = MaterialTheme.typography.labelLarge.fontWeight), color = c.onAsking)
            if (detail != null) Text(detail, style = MaterialTheme.typography.bodySmall, color = c.onAsking)
        }
    }
}

/** Nothing to show yet ("No activity yet"), with an optional action below. */
@Composable
fun EmptyState(
    icon: ImageVector,
    title: String,
    body: String,
    modifier: Modifier = Modifier,
    action: (@Composable () -> Unit)? = null,
) {
    val c = OpenMobTheme.colors
    Column(
        modifier = modifier.fillMaxWidth().padding(vertical = OpenMobTheme.spacing.xxl),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(OpenMobTheme.spacing.sm),
    ) {
        Icon(
            icon,
            contentDescription = null,
            tint = c.inkSecondary,
            modifier = Modifier.size(56.dp).background(c.neutralContainer, CircleShape).padding(16.dp),
        )
        Spacer(Modifier.size(OpenMobTheme.spacing.xs))
        Text(
            title,
            style = MaterialTheme.typography.titleMedium,
            color = c.ink,
            textAlign = TextAlign.Center,
            modifier = Modifier.semantics { heading() },
        )
        Text(body, style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary, textAlign = TextAlign.Center)
        if (action != null) {
            Spacer(Modifier.size(OpenMobTheme.spacing.sm))
            action()
        }
    }
}
