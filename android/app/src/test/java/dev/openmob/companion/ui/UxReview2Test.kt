package dev.openmob.companion.ui

import android.content.Context
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performScrollTo
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.IndicatorPrefs
import dev.openmob.companion.PairingFlow
import dev.openmob.companion.R
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.settings.IndicatorActions
import dev.openmob.companion.ui.settings.IndicatorSettingsScreen
import dev.openmob.companion.ui.settings.IndicatorViewModel
import dev.openmob.companion.ui.settings.SettingsSamples
import dev.openmob.companion.ui.settings.TAG_BOTH_OFF
import dev.openmob.companion.ui.settings.TAG_NEAR_AMBER
import dev.openmob.companion.ui.setup.SetupActions
import dev.openmob.companion.ui.setup.SetupSamples
import dev.openmob.companion.ui.setup.SetupScreenFor
import dev.openmob.companion.ui.setup.TAG_NO_UNDO
import dev.openmob.companion.ui.setup.TAG_RESTRICTED
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The second UX review's view and copy fixes, and the owner's four held items (2026-10-17). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h1400dp-xhdpi")
class UxReview2Test {
    val rule = createComposeRule()
    @get:org.junit.Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int, vararg a: Any) = ctx.getString(id, *a)

    @Test fun theAgentsQuestionIsBlueAndSaysWhoAsks() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.question, HomeActions()) } }
        rule.onNode(hasText(s(R.string.rd_home_question), substring = true)).assertExists()          // blue, in the thread
        rule.onAllNodes(hasText(s(R.string.rd_asking_band), substring = true)).assertCountEquals(0) // not the amber band
    }

    @Test fun confirmNamesThePhoneAndWarnsWithoutNotifications() {
        val state = SetupSamples.confirm.copy(phone = SetupSamples.confirm.phone.copy(model = "SM-S948U1", notificationsOn = false))
        rule.setContent { OpenMobTheme { SetupScreenFor(Route.SetupConfirm, state, SetupActions()) } }
        rule.onNode(hasText(s(R.string.rd_setup_dashboard_shows, "SM-S948U1"))).assertIsDisplayed()
        rule.onNodeWithTag(TAG_NO_UNDO).performScrollTo().assertIsDisplayed()
        // Owner condition 1a (docs/decisions.md) sets this sentence word for word (review 3).
        rule.onNode(hasText("Only pair with your own account. OpenMob will never ask you for a code.")).assertIsDisplayed()
    }

    @Test fun consentSaysWhereScreenContentsGoAndShowsRestrictedHelpInline() {
        val state = SetupSamples.consent.copy(phone = SetupSamples.consent.phone.copy(restricted = true))
        rule.setContent { OpenMobTheme { SetupScreenFor(Route.SetupConsent, state, SetupActions()) } }
        rule.onNode(hasText("home-server.local) and the AI model it uses", substring = true)).assertIsDisplayed()
        rule.onAllNodes(hasText("only to your own server", substring = true)).assertCountEquals(0)
        rule.onNodeWithTag(TAG_RESTRICTED).performScrollTo().assertIsDisplayed()
    }

    @Test fun indicatorWarnsWhenBothAreOff() {
        rule.setContent { OpenMobTheme { IndicatorSettingsScreen(SettingsSamples.indicatorInvalid, IndicatorActions()) } }
        rule.onNodeWithTag(TAG_BOTH_OFF).performScrollTo().assertIsDisplayed()
    }

    @Test fun aCustomColourNearTheAmberIsWarned() {
        val vm = IndicatorViewModel(IndicatorPrefs(MapStore()), onChanged = {}, onPreview = {})
        vm.setCustomText("#FFC107")
        vm.applyCustom()
        assertTrue(vm.state.value.nearAmber)
        vm.setCustomText("#00B8D4")
        vm.applyCustom()
        assertFalse(vm.state.value.nearAmber)
        rule.setContent { OpenMobTheme { IndicatorSettingsScreen(SettingsSamples.indicatorCustom.copy(nearAmber = true), IndicatorActions()) } }
        rule.onNodeWithTag(TAG_NEAR_AMBER).performScrollTo().assertIsDisplayed()
    }

    @Test fun noDeveloperTextLeaks() {
        listOf(R.string.rd_setup_more_signin_body, R.string.rd_setup_more_token_body, R.string.rd_settings_connection_sub)
            .forEach { assertFalse(s(it, "x").contains("current screen")) }
        rule.setContent { OpenMobTheme { SetupScreenFor(Route.SetupPairMore, SetupSamples.more, SetupActions()) } }
        rule.onAllNodes(hasText("current screen", substring = true)).assertCountEquals(0)
    }

    @Test fun welcomeDoesntPromiseTheIndicatorAlwaysShows() {
        rule.setContent { OpenMobTheme { SetupScreenFor(Route.SetupWelcome, SetupSamples.fresh, SetupActions()) } }
        rule.onNode(hasText("By default", substring = true)).assertIsDisplayed()
        rule.onAllNodes(hasText("always see it", substring = true)).assertCountEquals(0)
        rule.onNode(hasText(PairingFlow.hostOf(PairingFlow.HOSTED_SERVER), substring = true)).assertIsDisplayed()
    }

    @Test fun disconnectedHomeSaysNotConnectedOnce() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.disconnected, HomeActions()) } }
        rule.onAllNodes(hasText(s(R.string.rd_offline_title))).assertCountEquals(1) // rev 6: said once, in the body
        rule.onAllNodes(hasTestTag("never")).assertCountEquals(0)
    }
}
