package dev.openmob.companion.ui

import android.content.Context
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertWidthIsAtLeast
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isHeading
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.dp
import androidx.compose.runtime.mutableStateOf
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.PillCorner
import dev.openmob.companion.R
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.HomeUiState
import dev.openmob.companion.ui.settings.IndicatorActions
import dev.openmob.companion.ui.settings.IndicatorSettingsScreen
import dev.openmob.companion.ui.settings.SettingsActions
import dev.openmob.companion.ui.settings.SettingsSamples
import dev.openmob.companion.ui.settings.SettingsScreen
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Home, Settings and the indicator settings: 48 dp targets, a reachable Stop, live regions (Robolectric). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h844dp-xhdpi")
class HomeSemanticsTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int, vararg args: Any) = ctx.getString(id, *args)

    /** Every clickable node (buttons, rows, switches, choices) is at least 48 x 48 dp. */
    private fun assertTargets() {
        val nodes = rule.onAllNodes(hasClickAction()).fetchSemanticsNodes()
        assertTrue("no clickable nodes", nodes.isNotEmpty())
        nodes.forEach { n ->
            val w = with(rule.density) { n.size.width.toDp() }
            val h = with(rule.density) { n.size.height.toDp() }
            val name = n.config.getOrNull(SemanticsProperties.Text)?.joinToString() ?: n.config.getOrNull(SemanticsProperties.ContentDescription)?.joinToString()
            assertTrue("target too small ($w x $h): $name", w >= 47.9.dp && h >= 47.9.dp)
        }
    }

    @Test fun everyHomeStateHasItsHeadingAnd48dpTargets() {
        val current = mutableStateOf(HomeSamples.connected)
        rule.setContent { OpenMobTheme { HomeScreen(current.value, HomeActions()) } }
        HomeSamples.all.forEach { (_, state) ->
            current.value = state
            rule.waitForIdle()
            // The header is ☰, the chat's title (a heading, when connected) and the pill; the brand is in the drawer.
            rule.onNode(hasContentDescription(s(R.string.rd_menu)) and hasClickAction()).assertIsDisplayed()
            // Settings moved into the menu (owner, 2026-10-17); the hamburger and Activity stay in the header.
            rule.onNode(hasContentDescription(s(R.string.rd_menu)) and hasClickAction()).assertIsDisplayed()
            // Rev 6: the header is ☰ and the connection pill; Activity is in the drawer's account row.
            assertTargets()
        }
    }

    @Test fun stopTaskIsReachableAndCallsTheTaskOnlyStop() {
        val calls = mutableListOf<String>()
        val actions = HomeActions(stopTask = { calls += "stop" }, disconnect = { calls += "disconnect" })
        val current = mutableStateOf<HomeUiState>(HomeSamples.working)
        rule.setContent { OpenMobTheme { HomeScreen(current.value, actions) } }
        for (state in listOf(HomeSamples.working, HomeSamples.asking, HomeSamples.question)) {
            current.value = state
            rule.waitForIdle()
            rule.onNode(hasText(s(R.string.rd_home_stop_task)) and hasClickAction())
                .also { n -> runCatching { n.performScrollTo() } } // the body scrolls only when it's taller than the window
                .assertIsDisplayed()
                .assertHeightIsAtLeast(48.dp)
                .assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Button))
                .performClick()
        }
        assertEquals(listOf("stop", "stop", "stop"), calls) // Disconnect is the status sheet's (HomeThreadTest)
    }

    @Test fun noStopTaskWhenNothingRuns() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected, HomeActions()) } }
        rule.onAllNodesWithText(s(R.string.rd_home_stop_task)).assertCountEquals(0)
    }

    @Test fun theAskingBandIsAPoliteLiveRegionWithTheQuestion() {
        var reviewed = ""
        rule.setContent { OpenMobTheme(darkTheme = true) { HomeScreen(HomeSamples.asking, HomeActions(review = { reviewed = it })) } }
        rule.onNode(hasText(s(R.string.rd_asking_band), substring = true) and hasText("On my way", substring = true))
            .assertIsDisplayed()
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite))
        rule.onNode(hasText(s(R.string.approval_review)) and hasClickAction()).performClick()
        assertEquals("gk1", reviewed)
    }

    @Test fun theCurrentStepIsAPoliteLiveRegion() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.working, HomeActions()) } }
        rule.onNode(hasText(s(R.string.rd_thread_working_step, 3)) and hasText("Typing “jazz”"))
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite))
        // Only the current step live: no earlier step text anywhere.
        rule.onAllNodesWithText(s(R.string.rd_thread_working_step, 2)).assertCountEquals(0)
    }

    @Test fun settingsTargetsAndFasterButtonsOnlyWhileConnected() {
        val calls = mutableListOf<String>()
        val current = mutableStateOf(SettingsSamples.off)
        rule.setContent {
            OpenMobTheme {
                SettingsScreen(current.value, SettingsActions(fasterSession = { calls += "session" }, fasterOff = { calls += "off" }))
            }
        }
        assertTargets()
        rule.onNode(hasText(s(R.string.faster_on_session)) and hasClickAction()).performScrollTo().performClick()
        current.value = SettingsSamples.offline
        rule.waitForIdle()
        rule.onNode(hasText(s(R.string.faster_on_session)) and hasClickAction()).performScrollTo().performClick() // disabled
        current.value = SettingsSamples.fasterOn
        rule.waitForIdle()
        rule.onNode(hasText(s(R.string.faster_turn_off)) and hasClickAction()).performScrollTo().performClick()
        assertEquals(listOf("session", "off"), calls)
    }

    @Test fun settingsMarksTheCurrentModeReadOnly() {
        val current = mutableStateOf(SettingsSamples.off.copy(mode = "trusted"))
        rule.setContent { OpenMobTheme { SettingsScreen(current.value, SettingsActions()) } }
        rule.onNode(hasText(s(R.string.rd_mode_trusted)) and hasText(s(R.string.rd_mode_current))).assertIsSelected()
            .assert(SemanticsMatcher.keyNotDefined(SemanticsProperties.Role))
        rule.onNode(hasText(s(R.string.rd_mode_risky), substring = true) and hasText(s(R.string.rd_mode_risky_body)))
            .assertIsNotSelected()
        // Read only: no mode row can be tapped.
        listOf(R.string.rd_mode_every, R.string.rd_mode_plan, R.string.rd_mode_risky, R.string.rd_mode_trusted, R.string.rd_mode_never)
            .forEach { rule.onAllNodes(hasText(s(it)) and hasClickAction()).assertCountEquals(0) }
        current.value = SettingsSamples.off.copy(mode = "auto", neverUntil = 4_000_000_000L)
        rule.waitForIdle()
        rule.onNode(hasText(s(R.string.rd_mode_never)) and hasText(s(R.string.rd_mode_current))).assertIsSelected()
    }

    @Test fun indicatorChoicesAreRadioButtonsAndSwitches() {
        var corner: PillCorner? = null
        var preset = ""
        rule.setContent {
            OpenMobTheme {
                IndicatorSettingsScreen(SettingsSamples.indicator, IndicatorActions(corner = { corner = it }, preset = { preset = it }))
            }
        }
        assertTargets()
        rule.onNode(hasContentDescription("Blue")).assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.RadioButton)).assertIsSelected()
        rule.onNode(hasContentDescription("White (high contrast)")).performScrollTo().performClick()
        assertEquals("white", preset)
        rule.onNode(hasText(s(R.string.indicator_corner_bottom_left)) and hasClickAction()).performScrollTo().performClick()
        assertEquals(PillCorner.BOTTOM_LEFT, corner)
        rule.onNode(hasText(s(R.string.indicator_border)) and hasClickAction())
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Switch))
    }
}
