package dev.openmob.companion.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.openmob.companion.ui.theme.OpenMobTheme
import dev.openmob.companion.ui.theme.PillShape

/**
 * What a status chip reports. Each kind has its own icon, so the state never rests on colour alone:
 * blue is the agent, amber only "the phone is asking you", red a failure; everything else is neutral.
 */
enum class StatusKind { Connected, Working, Asking, Offline, Done, Stopped, Denied, Failed, Info }

private data class ChipStyle(val icon: ImageVector, val fg: Color, val bg: Color, val border: Color?)

@Composable
private fun styleFor(kind: StatusKind): ChipStyle {
    val c = OpenMobTheme.colors
    return when (kind) {
        StatusKind.Connected -> ChipStyle(Icons.Filled.CheckCircle, c.signal, c.signalContainer, null)
        StatusKind.Working -> ChipStyle(Icons.Filled.PlayArrow, c.signal, c.signalContainer, null)
        StatusKind.Done -> ChipStyle(Icons.Filled.CheckCircle, c.signal, c.signalContainer, null)
        StatusKind.Asking -> ChipStyle(Icons.Filled.Lock, c.onAskingContainer, c.askingContainer, null)
        StatusKind.Failed -> ChipStyle(Icons.Filled.Warning, c.onDangerContainer, c.dangerContainer, null)
        StatusKind.Offline -> ChipStyle(Icons.Filled.Close, c.inkSecondary, c.surface, c.outline)
        StatusKind.Stopped -> ChipStyle(StopSquare, c.ink, c.neutralContainer, null)
        StatusKind.Denied -> ChipStyle(Icons.Filled.Close, c.ink, c.neutralContainer, null)
        StatusKind.Info -> ChipStyle(Icons.Filled.Info, c.inkSecondary, c.neutralContainer, null)
    }
}

/** An icon plus a word ("Connected", "Asking you", ...). TalkBack reads the word; the icon is decoration. */
@Composable
fun StatusChip(kind: StatusKind, label: String, modifier: Modifier = Modifier) {
    val s = styleFor(kind)
    val sp = OpenMobTheme.spacing
    val base = modifier
        .semantics(mergeDescendants = true) {}
        .heightIn(min = OpenMobTheme.sizes.chip)
        .background(s.bg, PillShape)
    Row(
        modifier = (if (s.border != null) base.border(1.dp, s.border, PillShape) else base)
            .padding(horizontal = sp.md - sp.xxs, vertical = sp.xs),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(sp.xs + sp.xxs),
    ) {
        Icon(s.icon, contentDescription = null, tint = s.fg, modifier = Modifier.size(OpenMobTheme.sizes.iconSmall))
        Text(label, style = MaterialTheme.typography.labelMedium, color = s.fg)
    }
}
