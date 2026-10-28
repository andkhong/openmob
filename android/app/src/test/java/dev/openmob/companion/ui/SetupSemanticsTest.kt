package dev.openmob.companion.ui

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import com.github.takahirom.roborazzi.captureRoboImage
import dev.openmob.companion.R
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.setup.Checked
import dev.openmob.companion.ui.setup.SetupActions
import dev.openmob.companion.ui.setup.SetupSamples
import dev.openmob.companion.ui.setup.SetupScreenFor
import dev.openmob.companion.ui.setup.SetupUiState
import dev.openmob.companion.ui.setup.TAG_CODE_ERROR
import dev.openmob.companion.ui.setup.TAG_CONFIRM_ACCOUNT
import dev.openmob.companion.ui.setup.TAG_CONFIRM_SERVER
import dev.openmob.companion.ui.setup.TAG_UNUSUAL_CHARS
import dev.openmob.companion.ui.setup.plainAscii
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** The setup screens (docs/design/redesign-setup.md): 48 dp targets, the confirm screen, the consent, no tries-left. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h844dp-xhdpi")
class SetupSemanticsTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int, vararg a: Any) = ctx.getString(id, *a)

    private fun assertTargets() {
        rule.onAllNodes(hasClickAction()).fetchSemanticsNodes().forEach { n ->
            val w = with(rule.density) { n.size.width.toDp() }
            val h = with(rule.density) { n.size.height.toDp() }
            val name = n.config.getOrNull(SemanticsProperties.Text)?.joinToString()
            assertTrue("target too small ($w x $h): $name", w >= 47.9.dp && h >= 47.9.dp)
        }
    }

    @Test fun everySetupScreenHasItsTitleAnd48dpTargets() {
        val current = mutableStateOf(SetupSamples.all.first())
        rule.setContent { OpenMobTheme { current.value.let { (_, route, state) -> SetupScreenFor(route, state, SetupActions()) } } }
        SetupSamples.all.forEach { item ->
            current.value = item
            rule.waitForIdle()
            rule.onNode(hasText(s(item.second.title))).performScrollTo().assertIsDisplayed()
            assertTargets()
        }
    }

    @Test fun s5_confirmNamesAccountAndServer() {
        rule.setContent { OpenMobTheme { SetupScreenFor(Route.SetupConfirm, SetupSamples.confirm, SetupActions()) } }
        rule.onNodeWithTag(TAG_CONFIRM_ACCOUNT).assert(hasText("owner@example.com"))
        rule.onNodeWithTag(TAG_CONFIRM_SERVER).assert(hasText("home-server.local"))
        rule.onNode(hasText(s(R.string.rd_setup_only_yours))).assertIsDisplayed()
        rule.onAllNodes(hasTestTag(TAG_UNUSUAL_CHARS)).assertCountEquals(0) // a plain address: no flag
    }

    @Test fun s5_confirmFlagsAnAddressWithUnusualCharacters() {
        // A Cyrillic "о" in the email (review 3, K3-M2): it reads as the owner's own address, so the screen says so.
        val lookAlike = SetupUiState(checked = Checked("https://home-server.local", "K7P2QX", "j\u043erdan@mail.example.com"))
        rule.setContent { OpenMobTheme { SetupScreenFor(Route.SetupConfirm, lookAlike, SetupActions()) } }
        rule.onNodeWithTag(TAG_UNUSUAL_CHARS).assertIsDisplayed()
        rule.onNode(hasText(s(R.string.rd_setup_unusual_chars))).assertIsDisplayed()
        assertTrue(plainAscii("owner@example.com") && plainAscii("home-server.local:8443"))
        for (odd in listOf("jordan@mail.example.com\u200b", "jordan@ma\u0456l.example.com", "\uff41@example.com", "a b@example.com")) {
            assertTrue(odd, !plainAscii(odd))
        }
    }

    @Test fun s5_confirmCallsOnlyConfirmAndNotMeGoesBack() {
        val calls = mutableListOf<String>()
        rule.setContent {
            OpenMobTheme {
                SetupScreenFor(Route.SetupConfirm, SetupSamples.confirm,
                               SetupActions(confirm = { calls += "confirm" }, notMe = { calls += "notMe" }))
            }
        }
        rule.onNode(hasText(s(R.string.rd_setup_confirm_button)) and hasClickAction()).performScrollTo().performClick()
        rule.onNode(hasText(s(R.string.rd_setup_not_me)) and hasClickAction()).performScrollTo().performClick()
        assertEquals(listOf("confirm", "notMe"), calls)
    }

    @Test fun s10_consentIsTheOnlyRouteToAccessibility() {
        val calls = mutableListOf<String>()
        rule.setContent {
            OpenMobTheme {
                SetupScreenFor(Route.SetupConsent, SetupSamples.consent, SetupActions(
                    agree = { calls += "agree" }, notNow = { calls += "notNow" }, cantTurnOn = { calls += "cant" }))
            }
        }
        // The disclosure is on the screen before its Agree.
        rule.onNode(hasText(s(R.string.rd_setup_consent_see))).assertIsDisplayed()
        rule.onNode(hasText(s(R.string.rd_setup_consent_not_now)) and hasClickAction()).performScrollTo().performClick()
        assertEquals(listOf("notNow"), calls) // Not now opens nothing
        rule.onNode(hasText(s(R.string.rd_setup_consent_agree)) and hasClickAction()).performScrollTo().performClick()
        assertEquals(listOf("notNow", "agree"), calls)
    }

    @Test fun s12_aWrongCodeShowsTheReplyAndNoTriesLeft() {
        rule.setContent { OpenMobTheme { SetupScreenFor(Route.SetupPairCode, SetupSamples.codeWrong, SetupActions()) } }
        rule.onNodeWithTag(TAG_CODE_ERROR)
            .assert(hasText("Wrong code. Check it on your dashboard, or make a new one there."))
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite))
        rule.onAllNodes(hasText("tries left", substring = true, ignoreCase = true)).assertCountEquals(0)
    }

    @Test fun replaceShowsBothPairingsAndUnpairsOnlyByItsButton() {
        val calls = mutableListOf<String>()
        rule.setContent {
            OpenMobTheme {
                SetupScreenFor(Route.SetupReplace, SetupSamples.replace,
                               SetupActions(unpair = { calls += "unpair" }, keep = { calls += "keep" }))
            }
        }
        rule.onNode(hasText("current@example.com")).assertIsDisplayed()
        rule.onNode(hasText("owner@example.com")).assertIsDisplayed()
        rule.onNode(hasText(s(R.string.rd_setup_replace_keep)) and hasClickAction()).performScrollTo().performClick()
        assertEquals(listOf("keep"), calls)
    }
}

/** Screenshots of every setup screen, light and dark (copied to scratchpad/redesign4). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class SetupScreenshotTest {
    @get:Rule val host = ComponentActivityRegistered()

    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h1100dp-xhdpi")
    fun setupScreens() {
        SetupSamples.all.forEach { (name, route, state: SetupUiState) ->
            listOf(false, true).forEach { dark ->
                captureRoboImage("src/test/screenshots/setup-$name-${if (dark) "dark" else "light"}.png") {
                    OpenMobTheme(darkTheme = dark) { SetupScreenFor(route, state, SetupActions()) }
                }
            }
        }
    }
}
