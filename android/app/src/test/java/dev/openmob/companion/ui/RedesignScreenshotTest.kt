package dev.openmob.companion.ui

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.ui.Modifier
import com.github.takahirom.roborazzi.captureRoboImage
import dev.openmob.companion.ui.components.ComponentGallery
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.settings.IndicatorActions
import dev.openmob.companion.ui.settings.IndicatorSettingsScreen
import dev.openmob.companion.ui.settings.SettingsActions
import dev.openmob.companion.ui.settings.SettingsSamples
import dev.openmob.companion.ui.settings.SettingsScreen
import dev.openmob.companion.ui.nav.PlaceholderFor
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * JVM screenshots (Roborazzi on Robolectric's native graphics) of the design system and every placeholder screen,
 * light and dark. `./gradlew recordRoborazziDebug` writes the reference PNGs to `src/test/screenshots` (gitignored, local);
 * `./gradlew verifyRoborazziDebug` fails on a visual change. A plain `testDebugUnitTest` neither saves nor
 * compares images; the semantics tests cover rendering there.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class RedesignScreenshotTest {
    @get:org.junit.Rule val host = ComponentActivityRegistered()

    private fun shot(name: String, dark: Boolean, content: @androidx.compose.runtime.Composable () -> Unit) =
        captureRoboImage("src/test/screenshots/$name-${if (dark) "dark" else "light"}.png") {
            OpenMobTheme(darkTheme = dark) { content() }
        }

    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h1600dp-xhdpi")
    fun componentGallery() {
        listOf(false, true).forEach { dark -> shot("components", dark) { ComponentGallery(Modifier.fillMaxWidth()) } }
    }

    /** Step 2: every Home state, light and dark. */
    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h844dp-xhdpi")
    fun homeStates() {
        HomeSamples.all.forEach { (name, state) ->
            listOf(false, true).forEach { dark -> shot("home-$name", dark) { HomeScreen(state, HomeActions()) } }
        }
    }

    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h2100dp-xhdpi")
    fun settingsStates() {
        listOf("off" to SettingsSamples.off, "faster-on" to SettingsSamples.fasterOn, "offline" to SettingsSamples.offline)
            .forEach { (name, state) ->
                listOf(false, true).forEach { dark -> shot("settings-$name", dark) { SettingsScreen(state, SettingsActions()) } }
            }
    }

    /** App updates (§3.7; the owner's mockups): Home with an update available, required, and after a 4400. */
    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h844dp-xhdpi")
    fun homeUpdateStates() {
        HomeSamples.updates.forEach { (name, state) ->
            listOf(false, true).forEach { dark -> shot("home-$name", dark) { HomeScreen(state, HomeActions()) } }
        }
    }

    /** Settings › About at the bottom of Settings: an update available, and up to date. */
    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h2600dp-xhdpi")
    fun settingsAboutStates() {
        listOf("about-update" to SettingsSamples.updateAvailable, "about-current" to SettingsSamples.upToDate).forEach { (name, state) ->
            listOf(false, true).forEach { dark -> shot("settings-$name", dark) { SettingsScreen(state, SettingsActions()) } }
        }
    }

    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h1500dp-xhdpi")
    fun indicatorStates() {
        listOf("default" to SettingsSamples.indicator, "custom" to SettingsSamples.indicatorCustom, "invalid-off" to SettingsSamples.indicatorInvalid)
            .forEach { (name, state) ->
                listOf(false, true).forEach { dark ->
                    shot("indicator-$name", dark) { IndicatorSettingsScreen(state, IndicatorActions()) }
                }
            }
    }

    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h844dp-xhdpi")
    fun placeholderScreens() {
        Route.entries.forEach { route ->
            listOf(false, true).forEach { dark ->
                shot("screen-${route.path.replace('/', '-')}", dark) { PlaceholderFor(route, {}, {}, {}) }
            }
        }
    }
}
