package dev.openmob.companion.ui.nav

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.openmob.companion.R
import dev.openmob.companion.ui.theme.OpenMobTheme

/**
 * The frame every redesign screen shares: an optional back button, the title (a TalkBack heading), the setup
 * progress for setup steps, and a scrolling column inside the system bars.
 */
@Composable
fun ScreenScaffold(
    title: String,
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    largeTitle: Boolean = false,
    setupStep: Int? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val c = OpenMobTheme.colors
    val sp = OpenMobTheme.spacing
    Column(
        modifier = modifier
            .fillMaxSize()
            .background(c.ground)
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = sp.screen, vertical = sp.md),
        verticalArrangement = Arrangement.spacedBy(sp.xl),
    ) {
        if (onBack != null || setupStep != null) {
            Row(
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(sp.sm),
            ) {
                if (onBack != null) {
                    IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.rd_back),
                            tint = c.ink,
                        )
                    }
                }
                if (setupStep != null) SetupProgress(setupStep, Modifier.weight(1f))
            }
        }
        Text(
            text = title,
            style = if (largeTitle) MaterialTheme.typography.displaySmall else MaterialTheme.typography.headlineMedium,
            color = c.ink,
            modifier = Modifier.semantics { heading() },
        )
        content()
        Spacer(Modifier.height(sp.lg))
    }
}

/** "1 of 3" with three segments; read by TalkBack as a progress value. */
@Composable
private fun SetupProgress(step: Int, modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    val label = stringResource(R.string.rd_setup_step, step, Route.SETUP_STEPS)
    Row(
        modifier = modifier.semantics(mergeDescendants = true) {
            progressBarRangeInfo = ProgressBarRangeInfo(step.toFloat(), 0f..Route.SETUP_STEPS.toFloat(), Route.SETUP_STEPS)
        },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        repeat(Route.SETUP_STEPS) { i ->
            Spacer(
                Modifier
                    .weight(1f)
                    .height(4.dp)
                    .background(if (i < step) c.signal else c.outline, RoundedCornerShape(2.dp)),
            )
        }
        Text(label, style = MaterialTheme.typography.bodySmall, color = c.inkTertiary, modifier = Modifier.padding(start = 6.dp))
    }
}
