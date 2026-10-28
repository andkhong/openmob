package dev.openmob.companion.ui

import android.content.Context
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso
import dev.openmob.companion.R
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.ModelSheetContent
import dev.openmob.companion.ui.home.TAG_COMPOSER_FIELD
import dev.openmob.companion.ui.home.TAG_COMPOSER_MIC
import dev.openmob.companion.ui.home.TAG_COMPOSER_SEND
import dev.openmob.companion.ui.home.TAG_DRAWER
import dev.openmob.companion.ui.home.TAG_EFFORT_ROW
import dev.openmob.companion.ui.home.TAG_MENU_BUTTON
import dev.openmob.companion.ui.home.TAG_MODEL_CHIP
import dev.openmob.companion.ui.home.TAG_MODEL_SHEET
import dev.openmob.companion.ui.home.TAG_MORE_MODELS
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Home's composer, the model sheet and the menu (owner, 2026-10-17). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h1000dp-xhdpi")
class ComposerTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int, vararg a: Any) = ctx.getString(id, *a)

    @Test fun idleComposerSendsTheTextAndTheMicNeverSends() {
        val sent = mutableListOf<String>()
        var spoke = 0
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected,
            HomeActions(send = { sent += it; true }, speak = { spoke++ })) } }
        rule.onNode(hasText(s(R.string.rd_composer_hint))).assertIsDisplayed()
        rule.onNodeWithTag(TAG_COMPOSER_SEND).assertIsNotEnabled() // nothing to send yet
        rule.onNodeWithTag(TAG_COMPOSER_MIC).performClick()
        assertEquals(1, spoke); assertTrue(sent.isEmpty())        // dictation fills the field; it never sends
        rule.onNodeWithTag(TAG_COMPOSER_FIELD).performTextInput("open settings")
        rule.onNodeWithTag(TAG_COMPOSER_SEND).assertIsEnabled().assertHeightIsAtLeast(48.dp).performClick()
        assertEquals(listOf("open settings"), sent)
        rule.onNode(hasText(s(R.string.rd_composer_hint))).assertIsDisplayed() // cleared
        rule.onNode(hasTestTag(TAG_MODEL_CHIP) and hasContentDescription("Haiku 5.5 · Auto", substring = true)).assertIsEnabled()
    }

    @Test fun whileATaskRunsItSendsToTheAgentAndTheModelIsLocked() {
        val sent = mutableListOf<String>()
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.working, HomeActions(send = { sent += it; true })) } }
        rule.onNode(hasText(s(R.string.rd_composer_hint_working))).assertIsDisplayed()
        rule.onNodeWithTag(TAG_MODEL_CHIP).assertIsNotEnabled()
            .assert(hasContentDescription(s(R.string.rd_composer_model_locked_desc, "Haiku 5.5")))
        rule.onNode(hasText(s(R.string.rd_composer_model_hint))).assertIsDisplayed()
        rule.onNodeWithTag(TAG_COMPOSER_FIELD).performTextInput("use the second playlist")
        rule.onNode(hasText(s(R.string.rd_composer_send_working))).performClick()
        assertEquals(listOf("use the second playlist"), sent) // the server takes it as "User correction: …"
    }

    @Test fun anOlderServerWithNoModelListHasNoChip() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected.copy(models = null), HomeActions()) } }
        rule.onAllNodes(hasTestTag(TAG_MODEL_CHIP)).assertCountEquals(0)
        rule.onNodeWithTag(TAG_COMPOSER_SEND).assertIsDisplayed()
    }

    @Test fun theModelSheetPicksAModelAndAnEffortFromTheServersList() {
        val picks = mutableListOf<Pair<String, String>>()
        rule.setContent { OpenMobTheme { ModelSheetContent(HomeSamples.models, { m, e -> picks += m to e }, {}) } }
        rule.onNode(hasText(s(R.string.rd_model_title))).assertIsDisplayed()
        rule.onNode(hasText(s(R.string.rd_model_offered).uppercase())).assertIsDisplayed()
        rule.onNodeWithTag("model-claude-haiku-5-5")
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.Selected, true)).assertHeightIsAtLeast(48.dp)
        rule.onNode(hasContentDescription(s(R.string.rd_speed_desc, s(R.string.rd_speed_fast)))).assertIsDisplayed() // word, not colour alone
        rule.onNodeWithTag("model-claude-sonnet-5-5").performClick()
        rule.onNodeWithTag(TAG_EFFORT_ROW).performScrollTo().performClick()
        rule.onNode(hasText(s(R.string.rd_effort_high)) and hasClickAction()).performScrollTo().performClick()
        assertEquals(listOf("claude-sonnet-5-5" to "auto", "claude-sonnet-5-5" to "high"), picks)
        // Other providers sit under More models, shown because the server offers one.
        rule.onNodeWithTag(TAG_MORE_MODELS).performScrollTo().performClick()
        rule.onNodeWithTag("model-gpt-6-luna").performScrollTo().performClick()
        assertEquals("gpt-6-luna" to "auto", picks.last())
        rule.onNode(hasText(s(R.string.rd_model_footer))).performScrollTo().assertIsDisplayed()
    }

    @Test fun noOtherProvidersNoMoreModels() {
        val onlyClaude = HomeSamples.models.copy(models = HomeSamples.models.models.filter { it.group == "main" })
        rule.setContent { OpenMobTheme { ModelSheetContent(onlyClaude, { _, _ -> }, {}) } }
        rule.onAllNodes(hasTestTag(TAG_MORE_MODELS)).assertCountEquals(0)
    }

    @Test fun theChipOpensTheSheet() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected, HomeActions()) } }
        rule.onNodeWithTag(TAG_MODEL_CHIP).performClick()
        rule.onNodeWithTag(TAG_MODEL_SHEET).assertIsDisplayed()
    }
}
