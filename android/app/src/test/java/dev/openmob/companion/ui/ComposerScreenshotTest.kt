package dev.openmob.companion.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.rememberDrawerState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.ModelSheetContent
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Screenshots of the composer, the model sheet and the menu (`recordRoborazziDebug`; src/test/screenshots/composer). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ComposerScreenshotTest {
    @get:Rule val host = ComponentActivityRegistered()

    private fun shot(name: String, dark: Boolean, content: @androidx.compose.runtime.Composable () -> Unit) =
        captureRoboImage("src/test/screenshots/composer/$name-${if (dark) "dark" else "light"}.png") {
            OpenMobTheme(darkTheme = dark) { content() }
        }

    /** The sheet over a dimmed Home, as the bottom sheet shows it. */
    @androidx.compose.runtime.Composable
    private fun sheetOverHome() {
        Box(Modifier.fillMaxSize()) {
            HomeScreen(HomeSamples.connected, HomeActions())
            Box(Modifier.fillMaxSize().background(androidx.compose.ui.graphics.Color(0x8C0E1621)))
            Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                .background(OpenMobTheme.colors.surface, RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp))) {
                ModelSheetContent(HomeSamples.models.copy(model = "claude-sonnet-5-5", effort = "high"), { _, _ -> }, {})
            }
        }
    }

    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h844dp-xhdpi")
    fun composerSheetAndMenu() {
        listOf(1.0f, 2.0f).forEach { scale ->
            RuntimeEnvironment.setFontScale(scale)
            val tag = if (scale == 1.0f) "" else "-x2"
            listOf(false, true).forEach { dark ->
                shot("home-idle$tag", dark) { HomeScreen(HomeSamples.connected, HomeActions()) }
                shot("home-empty$tag", dark) { HomeScreen(HomeSamples.empty, HomeActions()) }
                shot("home-working$tag", dark) { HomeScreen(HomeSamples.working, HomeActions()) }
                shot("home-asking$tag", dark) { HomeScreen(HomeSamples.asking, HomeActions()) }
                shot("home-question$tag", dark) { HomeScreen(HomeSamples.question, HomeActions()) }
                shot("home-disconnected$tag", dark) { HomeScreen(HomeSamples.disconnected, HomeActions(), disconnectedBar = true) }
                shot("home-no-models$tag", dark) { HomeScreen(HomeSamples.connected.copy(models = null), HomeActions()) }
                shot("status-sheet$tag", dark) {
                    Box(Modifier.fillMaxSize().background(OpenMobTheme.colors.surface)) {
                        dev.openmob.companion.ui.home.StatusSheetContent(HomeSamples.empty, HomeActions(), {})
                    }
                }
                shot("model-sheet$tag", dark) { sheetOverHome() }
                shot("drawer$tag", dark) {
                    HomeScreen(HomeSamples.connected, HomeActions(), drawerState = rememberDrawerState(DrawerValue.Open))
                }
            }
        }
        RuntimeEnvironment.setFontScale(1.0f)
    }
}
