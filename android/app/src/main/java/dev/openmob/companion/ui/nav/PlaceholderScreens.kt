package dev.openmob.companion.ui.nav

import androidx.compose.foundation.layout.Column
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.EmptyState
import dev.openmob.companion.ui.components.LinkButton
import dev.openmob.companion.ui.components.ListRow
import dev.openmob.companion.ui.components.MonoValue
import dev.openmob.companion.ui.components.OmCard
import dev.openmob.companion.ui.components.PrimaryButton
import dev.openmob.companion.ui.components.SecondaryButton
import dev.openmob.companion.ui.components.SectionHeader
import dev.openmob.companion.ui.components.StatusChip
import dev.openmob.companion.ui.components.StatusKind
import dev.openmob.companion.ui.components.ToggleRow
import dev.openmob.companion.ui.theme.OpenMobTheme

/*
 * Step 1 placeholders: each screen has its real title and is built from the components, but reads and changes
 * nothing. Step 2 replaces them one by one with the real screens.
 */

@Composable
private fun PlaceholderNote() {
    OmCard {
        StatusChip(StatusKind.Info, stringResource(R.string.rd_status_preview))
        Text(
            stringResource(R.string.rd_placeholder_body),
            style = MaterialTheme.typography.bodyMedium,
            color = OpenMobTheme.colors.inkSecondary,
        )
    }
}

@Composable
fun HomePlaceholder(navigate: (Route) -> Unit) {
    ScreenScaffold(title = stringResource(Route.Home.title)) {
        OmCard {
            StatusChip(StatusKind.Info, stringResource(R.string.rd_status_preview))
            Text(stringResource(R.string.rd_home_status), style = MaterialTheme.typography.headlineMedium)
            Text(
                stringResource(R.string.rd_placeholder_body),
                style = MaterialTheme.typography.bodyMedium,
                color = OpenMobTheme.colors.inkSecondary,
            )
            MonoValue(label = stringResource(R.string.rd_home_server), value = "—")
        }
        OmCard {
            Column {
                ListRow(stringResource(R.string.rd_open_activity), onClick = { navigate(Route.Activity) })
                HorizontalDivider(color = OpenMobTheme.colors.divider)
                ListRow(stringResource(R.string.rd_open_settings), onClick = { navigate(Route.Settings) })
                HorizontalDivider(color = OpenMobTheme.colors.divider)
                ListRow(
                    stringResource(R.string.rd_open_setup),
                    subtitle = stringResource(R.string.rd_open_setup_sub),
                    onClick = { navigate(Route.SetupWelcome) },
                )
            }
        }
        Text(
            stringResource(R.string.rd_home_never_types),
            style = MaterialTheme.typography.bodySmall,
            color = OpenMobTheme.colors.inkTertiary,
        )
    }
}

@Composable
fun SettingsPlaceholder(onBack: () -> Unit, navigate: (Route) -> Unit) {
    ScreenScaffold(title = stringResource(Route.Settings.title), onBack = onBack) {
        PlaceholderNote()
        Column {
            SectionHeader(stringResource(R.string.rd_settings_more))
            OmCard {
                ListRow(stringResource(R.string.rd_indicator_title), onClick = { navigate(Route.Indicator) })
            }
        }
        Text(
            stringResource(R.string.rd_settings_only_you),
            style = MaterialTheme.typography.bodySmall,
            color = OpenMobTheme.colors.inkTertiary,
        )
    }
}

@Composable
fun IndicatorPlaceholder(onBack: () -> Unit) {
    // Local, unsaved state: the real indicator settings stay in the current UI until step 2.
    var border by rememberSaveable { mutableStateOf(true) }
    var pill by rememberSaveable { mutableStateOf(true) }
    ScreenScaffold(title = stringResource(Route.Indicator.title), onBack = onBack) {
        PlaceholderNote()
        OmCard {
            Column {
                ToggleRow(
                    stringResource(R.string.rd_indicator_border),
                    checked = border,
                    onCheckedChange = { border = it },
                    subtitle = stringResource(R.string.rd_indicator_example),
                )
                HorizontalDivider(color = OpenMobTheme.colors.divider)
                ToggleRow(
                    stringResource(R.string.rd_indicator_pill),
                    checked = pill,
                    onCheckedChange = { pill = it },
                    subtitle = stringResource(R.string.rd_indicator_example),
                )
            }
        }
    }
}

@Composable
fun ActivityPlaceholder(onBack: () -> Unit) {
    ScreenScaffold(title = stringResource(Route.Activity.title), onBack = onBack) {
        EmptyState(
            icon = Icons.Filled.DateRange,
            title = stringResource(R.string.rd_activity_empty),
            body = stringResource(R.string.rd_activity_empty_body),
        )
    }
}

/** The setup flow's screens: the real title, a placeholder note and the route's onward buttons. */
@Composable
fun SetupPlaceholder(route: Route, onBack: () -> Unit, navigate: (Route) -> Unit, finish: () -> Unit) {
    ScreenScaffold(
        title = stringResource(route.title),
        onBack = onBack,
        largeTitle = route == Route.SetupWelcome,
        setupStep = route.setupStep,
    ) {
        PlaceholderNote()
        when (route) {
            Route.SetupWelcome ->
                PrimaryButton(stringResource(R.string.rd_setup_get_started), onClick = { navigate(Route.SetupPair) })
            Route.SetupPair -> {
                SecondaryButton(
                    stringResource(R.string.rd_setup_pair_code_instead),
                    onClick = { navigate(Route.SetupPairCode) },
                )
                LinkButton(stringResource(R.string.rd_setup_pair_more_title), onClick = { navigate(Route.SetupPairMore) })
                PrimaryButton(stringResource(R.string.rd_next), onClick = { navigate(Route.SetupConfirm) })
            }
            Route.SetupPairCode, Route.SetupPairMore ->
                PrimaryButton(stringResource(R.string.rd_next), onClick = { navigate(Route.SetupConfirm) })
            Route.SetupConfirm ->
                PrimaryButton(stringResource(R.string.rd_next), onClick = { navigate(Route.SetupConsent) })
            Route.SetupConsent ->
                PrimaryButton(stringResource(R.string.rd_next), onClick = { navigate(Route.SetupReady) })
            Route.SetupReady ->
                PrimaryButton(stringResource(R.string.rd_next), onClick = finish)
            else -> Unit
        }
    }
}

/** The placeholder for any route, as the nav host and the screenshot tests use it. */
@Composable
fun PlaceholderFor(route: Route, onBack: () -> Unit, navigate: (Route) -> Unit, finish: () -> Unit) {
    when (route) {
        Route.Home -> HomePlaceholder(navigate)
        Route.Settings -> SettingsPlaceholder(onBack, navigate)
        Route.Indicator -> IndicatorPlaceholder(onBack)
        Route.Activity -> ActivityPlaceholder(onBack)
        else -> SetupPlaceholder(route, onBack, navigate, finish)
    }
}
