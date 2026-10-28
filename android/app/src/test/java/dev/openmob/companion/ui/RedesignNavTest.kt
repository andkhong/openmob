package dev.openmob.companion.ui

import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isHeading
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.core.app.ApplicationProvider
import android.content.Context
import dev.openmob.companion.R
import dev.openmob.companion.ui.nav.OpenMobNavHost
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The navigation skeleton: every route shows its real title, and the placeholder links move between them. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class RedesignNavTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int) = ctx.getString(id)

    private fun assertTitle(route: Route) =
        // Home's header has no title of its own (owner, 2026-10-17): its ☰ marks it.
        // (the placeholder Home, real = false, still shows its title).
        (if (route == Route.Home) rule.onNode((androidx.compose.ui.test.hasContentDescription(s(R.string.rd_menu)) and hasClickAction()) or
                                              (hasText(s(route.title)) and isHeading()))
         else rule.onNode(hasText(s(route.title)) and isHeading())).also { n -> runCatching { n.performScrollTo() } }.assertIsDisplayed()

    @Test fun everyRouteShowsItsTitle() {
        // setContent runs once per test: switch the start route through state, with a fresh graph each time.
        val current = mutableStateOf(Route.start)
        rule.setContent { OpenMobTheme { key(current.value) { OpenMobNavHost(startRoute = current.value) } } }
        Route.entries.forEach { route ->
            current.value = route
            rule.waitForIdle()
            assertTitle(route)
        }
    }

    @Test fun homeToSettingsToIndicatorAndBack() {
        rule.setContent { OpenMobTheme { OpenMobNavHost() } }
        assertTitle(Route.Home)
        rule.onNode(hasContentDescription(s(R.string.rd_menu)) and hasClickAction()).performClick()
        rule.onNodeWithTag("drawer-Settings").performSemanticsAction(androidx.compose.ui.semantics.SemanticsActions.OnClick)
        assertTitle(Route.Settings)
        rule.onNode(hasText(s(R.string.rd_indicator_title)) and hasClickAction()).performScrollTo().performClick()
        assertTitle(Route.Indicator)
        rule.onNodeWithContentDescription(s(R.string.rd_back)).performScrollTo().performClick()
        assertTitle(Route.Settings)
        rule.onNodeWithContentDescription(s(R.string.rd_back)).performScrollTo().performClick()
        assertTitle(Route.Home)
    }

    @Test fun theRealSetupWalksToTheTypedCode() {
        rule.setContent { OpenMobTheme { OpenMobNavHost(startRoute = Route.SetupWelcome) } }
        assertTitle(Route.SetupWelcome)
        rule.onNode(hasText(s(R.string.rd_setup_get_started)) and hasClickAction()).performScrollTo().performClick()
        assertTitle(Route.SetupPair)
        rule.onNode(hasText(s(R.string.rd_setup_pair_code_instead)) and hasClickAction()).performScrollTo().performClick()
        assertTitle(Route.SetupPairCode)
        rule.onNode(hasText(s(R.string.rd_setup_pair_more_title)) and hasClickAction()).performScrollTo().performClick()
        assertTitle(Route.SetupPairMore)
    }

    @Test fun setupFlowWalksToReadyAndFinishesAtHome() {
        rule.setContent { OpenMobTheme { OpenMobNavHost(startRoute = Route.SetupWelcome, real = false) } }
        rule.onNode(hasText(s(R.string.rd_setup_get_started)) and hasClickAction()).performScrollTo().performClick()
        assertTitle(Route.SetupPair)
        listOf(Route.SetupConfirm, Route.SetupConsent, Route.SetupReady).forEach { next ->
            rule.onNode(hasText(s(R.string.rd_next)) and hasClickAction()).performScrollTo().performClick()
            assertTitle(next)
        }
        rule.onNode(hasText(s(R.string.rd_next)) and hasClickAction()).performScrollTo().performClick()
        assertTitle(Route.Home)
    }
}
