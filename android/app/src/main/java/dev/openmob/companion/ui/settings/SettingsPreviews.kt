package dev.openmob.companion.ui.settings

import android.content.res.Configuration
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import dev.openmob.companion.PillCorner
import dev.openmob.companion.ui.theme.OpenMobTheme

/** Example states for the previews and screenshot tests. */
object SettingsSamples {
    val off = SettingsUiState(connected = true, paired = true, serverHost = "home-server.local", checksDone = 4, mode = "auto")
    val fasterOn = off.copy(mode = "trusted", fasterOn = true, fasterScope = "session", color = "green", corner = PillCorner.BOTTOM_LEFT)
    val offline = off.copy(connected = false, checksDone = 3, border = false)
    /** About (§3.7): a newer build on the server, and up to date. */
    val updateAvailable = off.copy(appVersionCode = 47, appHash = "7d7c887", latestVersion = 52, updateAvailable = true,
                                   updateDownloadable = true)
    val upToDate = off.copy(appVersionCode = 52, appHash = "7d7c887", latestVersion = 52)
    val indicator = IndicatorUiState()
    val indicatorCustom = IndicatorUiState(color = "#00B8D4", customText = "#00B8D4", corner = PillCorner.BOTTOM_RIGHT, pulse = false)
    val indicatorInvalid = IndicatorUiState(border = false, customText = "#12", customInvalid = true, pill = false)
}

@Preview(name = "Settings, light", widthDp = 390, heightDp = 1900)
@Preview(name = "Settings, dark", widthDp = 390, heightDp = 1900, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun SettingsPreview() {
    OpenMobTheme { SettingsScreen(SettingsSamples.off, SettingsActions()) }
}

@Preview(name = "Indicator, light", widthDp = 390, heightDp = 1300)
@Preview(name = "Indicator, dark", widthDp = 390, heightDp = 1300, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun IndicatorPreview() {
    OpenMobTheme { IndicatorSettingsScreen(SettingsSamples.indicator, IndicatorActions()) }
}
