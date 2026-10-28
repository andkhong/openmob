package dev.openmob.companion.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import dev.openmob.companion.ui.home.DeleteChatDialog
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.LocalRenameInDialog
import dev.openmob.companion.ui.home.RenameChatContent
import dev.openmob.companion.ui.home.TAG_SEARCH_OPEN
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Screenshots: the decluttered header, the drawer (and its search), the chat menu and the two dialogs. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ChatManageScreenshotTest {
    @get:Rule val host = ComponentActivityRegistered()

    private fun shot(name: String, dark: Boolean, content: @androidx.compose.runtime.Composable () -> Unit) =
        captureRoboImage("src/test/screenshots/chatmanage/$name-${if (dark) "dark" else "light"}.png") {
            OpenMobTheme(darkTheme = dark) { content() }
        }

    @Test
    @Config(sdk = [35], qualifiers = "w360dp-h780dp-xhdpi")
    fun headerDrawerAndDialogs() {
        listOf(1.0f, 2.0f).forEach { scale ->
            RuntimeEnvironment.setFontScale(scale)
            val tag = if (scale == 1.0f) "" else "-x2"
            listOf(false, true).forEach { dark ->
                shot("home$tag", dark) { HomeScreen(HomeSamples.connected, HomeActions()) }
                shot("home-issue$tag", dark) { HomeScreen(HomeSamples.empty, HomeActions()) }
                shot("drawer$tag", dark) { HomeScreen(HomeSamples.connected, HomeActions(), drawerState = rememberDrawerState(DrawerValue.Open)) }
                shot("rename$tag", dark) {
                    Box(Modifier.fillMaxSize().background(androidx.compose.ui.graphics.Color(0x990E1621)), contentAlignment = Alignment.Center) {
                        Box(Modifier.padding(24.dp)) { RenameChatContent("Install a chess app and play 5 moves", {}, {}) }
                    }
                }
                shot("delete$tag", dark) { DeleteChatDialog({}, {}) }
            }
        }
        RuntimeEnvironment.setFontScale(1.0f)
    }
}

/** States that need an action first: the drawer's search open, and a chat's long-press menu. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "w360dp-h780dp-xhdpi")
class ChatManageStateScreenshotTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)

    private fun drawer(dark: Boolean) = rule.setContent {
        OpenMobTheme(darkTheme = dark) {
            CompositionLocalProvider(LocalRenameInDialog provides false) {
                HomeScreen(HomeSamples.connected, HomeActions(), drawerState = rememberDrawerState(DrawerValue.Open))
            }
        }
    }

    @Test fun searchOpenLight() { drawer(false); open(TAG_SEARCH_OPEN); rule.onRoot().captureRoboImage("src/test/screenshots/chatmanage/drawer-search-light.png") }
    @Test fun searchOpenDark() { drawer(true); open(TAG_SEARCH_OPEN); rule.onRoot().captureRoboImage("src/test/screenshots/chatmanage/drawer-search-dark.png") }
    @Test fun menuLight() { drawer(false); longPress(); rule.onRoot().captureRoboImage("src/test/screenshots/chatmanage/chat-menu-light.png") }
    @Test fun menuDark() { drawer(true); longPress(); rule.onRoot().captureRoboImage("src/test/screenshots/chatmanage/chat-menu-dark.png") }

    private fun open(tag: String) { rule.onNodeWithTag(tag).performSemanticsAction(SemanticsActions.OnClick); rule.waitForIdle() }
    private fun longPress() { rule.onNodeWithTag("chat-c3").performSemanticsAction(SemanticsActions.OnLongClick); rule.waitForIdle() }
    private fun androidx.compose.ui.test.junit4.ComposeContentTestRule.onRoot() = onNode(androidx.compose.ui.test.isRoot())
}
