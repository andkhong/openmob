package dev.openmob.companion.ui

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.R
import dev.openmob.companion.UpdateInfo
import dev.openmob.companion.UpdateState
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeMapper
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.HomeViewModel
import dev.openmob.companion.ui.home.TAG_COMPOSER_FIELD
import dev.openmob.companion.ui.home.TAG_PILL
import dev.openmob.companion.ui.home.TAG_UPDATE_AVAILABLE
import dev.openmob.companion.ui.home.TAG_UPDATE_DISMISS
import dev.openmob.companion.ui.home.TAG_UPDATE_DOWNLOAD
import dev.openmob.companion.ui.home.TAG_UPDATE_LATER
import dev.openmob.companion.ui.home.TAG_UPDATE_REQUIRED
import dev.openmob.companion.ui.home.TAG_UPDATE_TOO_OLD
import dev.openmob.companion.ui.settings.SettingsActions
import dev.openmob.companion.ui.settings.SettingsSamples
import dev.openmob.companion.ui.settings.SettingsScreen
import dev.openmob.companion.ui.settings.TAG_ABOUT_DOWNLOAD
import dev.openmob.companion.ui.state.PhoneSnapshot
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** App updates on Home and in Settings › About (§3.7; the owner's mockups), and Home's mapping of them. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h844dp-xhdpi")
class AppUpdatesUiTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int, vararg args: Any) = ctx.getString(id, *args)

    private val now = 1_800_000_000_000L
    private val ready = PhoneSnapshot(
        paired = true, accessibilityOn = true, notificationsOn = true, batteryUnrestricted = true,
        running = true, connected = true, connectionText = "Connected to openmob.fly.dev", serverHost = "openmob.fly.dev",
        appVersionCode = 47, updateDownloadable = true,
    )

    // --- the mapping --------------------------------------------------------------------------------------------

    @Test fun availableDismissedAndReshownOnAHigherVersion() {
        val available = HomeMapper.map(ready.copy(update = UpdateInfo(52, 0, "u")), now)
        assertEquals(UpdateState.Available(52), available.update)
        assertTrue(available.canAsk)
        assertFalse(available.updateRequired)
        assertEquals(UpdateState.None, HomeMapper.map(ready.copy(update = UpdateInfo(52, 0, "u"), updateDismissed = 52), now).update)
        assertEquals(UpdateState.Available(53),
                     HomeMapper.map(ready.copy(update = UpdateInfo(53, 0, "u"), updateDismissed = 52), now).update)
    }

    @Test fun requiredTurnsTheComposerOff() {
        val required = HomeMapper.map(ready.copy(update = UpdateInfo(52, 50, "u")), now)
        assertEquals(UpdateState.Required(50, 52), required.update)
        assertTrue(required.updateRequired)
        assertFalse("nothing would run: no asking", required.canAsk)
        // Offline, the pill doesn't claim it (nothing is known to be refused until the next welcome).
        assertFalse(HomeMapper.map(ready.copy(connected = false, update = UpdateInfo(52, 50, "u")), now).updateRequired)
    }

    @Test fun laterAndDownloadReachTheControls() {
        val source = FakeSource(ready.copy(update = UpdateInfo(52, 0, "u")))
        val controls = object : dev.openmob.companion.ui.state.OwnerControls by FakeControls() {
            val calls = mutableListOf<String>()
            override fun downloadUpdate(): Boolean { calls += "download"; return false }
            override fun dismissUpdate(latest: Int) { calls += "dismiss:$latest" }
        }
        val vm = HomeViewModel(source, controls, clock = { now })
        vm.dismissUpdate(52)
        vm.downloadUpdate()
        assertEquals(listOf("dismiss:52", "download"), controls.calls)
        assertEquals("a refused link says so", R.string.update_link_refused, vm.notice.value)
    }

    // --- Home ---------------------------------------------------------------------------------------------------

    @Test fun theAvailableCardOffersDownloadLaterAndNotNow() {
        val calls = mutableListOf<String>()
        rule.setContent {
            OpenMobTheme {
                HomeScreen(HomeSamples.updateAvailable, HomeActions(downloadUpdate = { calls += "download" },
                                                                    dismissUpdate = { calls += "dismiss:$it" }))
            }
        }
        rule.onNodeWithTag(TAG_UPDATE_AVAILABLE).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.update_available_title)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.update_available_body, 52, "openmob.fly.dev", 47)).assertIsDisplayed()
        rule.onNode(hasContentDescription(s(R.string.update_not_now)) and hasClickAction()).performClick()
        rule.onNodeWithTag(TAG_UPDATE_LATER).performClick()
        rule.onNodeWithTag(TAG_UPDATE_DOWNLOAD).performClick()
        assertEquals(listOf("dismiss:52", "dismiss:52", "download"), calls)
        rule.onNodeWithTag(TAG_COMPOSER_FIELD).assertIsEnabled() // the agent still works
        assertTargets()
    }

    @Test fun requiredShowsTheCardThePillAndADisabledComposer() {
        val calls = mutableListOf<String>()
        rule.setContent {
            OpenMobTheme {
                HomeScreen(HomeSamples.updateRequired, HomeActions(downloadUpdate = { calls += "download" },
                                                                   disconnect = { calls += "disconnect" }))
            }
        }
        rule.onNodeWithTag(TAG_UPDATE_REQUIRED).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.update_required_chip)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.update_required_title)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.update_required_value, 50)).assertIsDisplayed()
        rule.onNodeWithText(s(R.string.update_step_3)).performScrollTo().assertIsDisplayed()
        // The pill: "Update needed", with its description for TalkBack.
        rule.onNodeWithTag(TAG_PILL).assertIsDisplayed()
        rule.onNode(hasContentDescription(s(R.string.update_pill_desc))).assertIsDisplayed()
        // The composer is off, with the mockup's placeholder.
        rule.onNodeWithTag(TAG_COMPOSER_FIELD).assertIsNotEnabled()
        rule.onNodeWithText(s(R.string.update_composer_hint)).assertIsDisplayed()
        // Disconnect stays.
        rule.onNode(hasText(s(R.string.ui_disconnect)) and hasClickAction()).performClick()
        rule.onNodeWithTag(TAG_UPDATE_DOWNLOAD).performScrollTo().performClick()
        assertEquals(listOf("disconnect", "download"), calls)
        assertTargets()
    }

    @Test fun requiredWithoutADownloadSaysWhoToAsk() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.updateRequired.copy(updateDownloadable = false), HomeActions()) } }
        rule.onNodeWithText(s(R.string.update_no_download)).performScrollTo().assertIsDisplayed()
        assertEquals(0, rule.onAllNodes(hasText(s(R.string.update_download))).fetchSemanticsNodes().size)
    }

    @Test fun a4400SaysTheAppIsTooOldWithDownload() {
        var downloads = 0
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.tooOld, HomeActions(downloadUpdate = { downloads++ })) } }
        rule.onNodeWithTag(TAG_UPDATE_TOO_OLD).assertIsDisplayed()
        rule.onNodeWithText("This app is too old for the server. Update it.").assertIsDisplayed()
        rule.onNodeWithTag(TAG_UPDATE_DOWNLOAD).performScrollTo().performClick()
        assertEquals(1, downloads)
    }

    @Test fun nothingNewShowsNoCard() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected, HomeActions()) } }
        assertEquals(0, rule.onAllNodes(hasText(s(R.string.update_available_title))).fetchSemanticsNodes().size)
        assertEquals(0, rule.onAllNodes(hasText(s(R.string.update_pill))).fetchSemanticsNodes().size)
    }

    @Test fun updateStatesAtLargeTextKeepTheirButtons() {
        val state = mutableStateOf(HomeSamples.updateAvailable)
        rule.setContent {
            androidx.compose.runtime.CompositionLocalProvider(
                androidx.compose.ui.platform.LocalDensity provides androidx.compose.ui.unit.Density(2f, fontScale = 2f),
            ) { OpenMobTheme { HomeScreen(state.value, HomeActions()) } }
        }
        rule.onNodeWithTag(TAG_UPDATE_DOWNLOAD).assertExists()
        rule.onNodeWithTag(TAG_UPDATE_LATER).assertExists()
        state.value = HomeSamples.updateRequired
        rule.waitForIdle()
        rule.onNodeWithTag(TAG_UPDATE_DOWNLOAD).performScrollTo().assertIsDisplayed()
    }

    // --- Settings › About ---------------------------------------------------------------------------------------

    @Test fun aboutSaysUpdateAvailableWithDownload() {
        var downloads = 0
        rule.setContent { OpenMobTheme { SettingsScreen(SettingsSamples.updateAvailable, SettingsActions(downloadUpdate = { downloads++ })) } }
        rule.onNodeWithText(s(R.string.about_app_version_value, 47, "7d7c887")).performScrollTo().assertIsDisplayed()
        rule.onNodeWithText(s(R.string.about_update_available)).performScrollTo().assertIsDisplayed()
        rule.onNodeWithTag(TAG_ABOUT_DOWNLOAD).performScrollTo().performClick()
        assertEquals(1, downloads)
        rule.onNodeWithText(s(R.string.about_updates_note)).performScrollTo().assertIsDisplayed()
    }

    @Test fun aboutSaysUpToDate() {
        rule.setContent { OpenMobTheme { SettingsScreen(SettingsSamples.upToDate, SettingsActions()) } }
        rule.onNodeWithText(s(R.string.about_up_to_date)).performScrollTo().assertIsDisplayed()
        assertEquals(0, rule.onAllNodes(hasText(s(R.string.update_download))).fetchSemanticsNodes().size)
    }

    /** Every clickable node is at least 48 x 48 dp. */
    private fun assertTargets() {
        rule.onAllNodes(hasClickAction()).fetchSemanticsNodes().forEach { n ->
            val w = with(rule.density) { n.size.width.toDp() }
            val h = with(rule.density) { n.size.height.toDp() }
            val name = n.config.getOrNull(SemanticsProperties.Text)?.joinToString()
                ?: n.config.getOrNull(SemanticsProperties.ContentDescription)?.joinToString()
            assertTrue("target too small ($w x $h): $name", w >= 47.9.dp && h >= 47.9.dp)
        }
    }
}
