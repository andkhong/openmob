package dev.openmob.companion.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.assertWidthIsAtLeast
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isHeading
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import dev.openmob.companion.ui.components.AskingBand
import dev.openmob.companion.ui.components.DangerButton
import dev.openmob.companion.ui.components.ListRow
import dev.openmob.companion.ui.components.PrimaryButton
import dev.openmob.companion.ui.components.SecondaryButton
import dev.openmob.companion.ui.components.SectionHeader
import dev.openmob.companion.ui.components.StatusChip
import dev.openmob.companion.ui.components.StatusKind
import dev.openmob.companion.ui.components.StopButton
import dev.openmob.companion.ui.components.ToggleRow
import dev.openmob.companion.ui.components.LinkButton
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The components render, are labelled for TalkBack, and keep 48 dp touch targets (Robolectric, no device). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ComponentSemanticsTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)

    @Test fun statusChipShowsItsWordForEveryKind() {
        rule.setContent {
            OpenMobTheme { Column { StatusKind.entries.forEach { StatusChip(it, "word-${it.name}") } } }
        }
        StatusKind.entries.forEach { rule.onNodeWithText("word-${it.name}").assertIsDisplayed() }
    }

    @Test fun buttonsAreAtLeast48dpAndClickable() {
        var clicks = 0
        rule.setContent {
            OpenMobTheme {
                Column {
                    PrimaryButton("Primary", onClick = { clicks++ })
                    SecondaryButton("Secondary", onClick = { clicks++ })
                    DangerButton("Danger", onClick = { clicks++ })
                    StopButton("Stop task", onClick = { clicks++ })
                    LinkButton("Link", onClick = { clicks++ })
                }
            }
        }
        listOf("Primary", "Secondary", "Danger", "Stop task", "Link").forEach {
            rule.onNode(hasText(it) and hasClickAction(), useUnmergedTree = false)
                .assertHeightIsAtLeast(48.dp)
                .assertWidthIsAtLeast(48.dp)
                .assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Button))
                .performClick()
        }
        assertEquals(5, clicks)
    }

    @Test fun toggleRowIsOneSwitchTarget() {
        rule.setContent {
            var on by androidx.compose.runtime.remember { mutableStateOf(false) }
            OpenMobTheme { ToggleRow("Border while an agent acts", checked = on, onCheckedChange = { on = it }, subtitle = "sub") }
        }
        val row = rule.onNode(hasText("Border while an agent acts") and hasText("sub"))
        row.assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Switch))
            .assertHeightIsAtLeast(48.dp)
            .assertIsOff()
            .performClick()
        row.assertIsOn()
    }

    @Test fun listRowIsOneButton() {
        var clicked = false
        rule.setContent { OpenMobTheme { ListRow("Agent indicator", subtitle = "Blue border", onClick = { clicked = true }) } }
        rule.onNode(hasText("Agent indicator") and hasText("Blue border") and hasClickAction())
            .assertHeightIsAtLeast(48.dp)
            .performClick()
        assertEquals(true, clicked)
    }

    @Test fun sectionHeaderIsAHeading() {
        rule.setContent { OpenMobTheme { SectionHeader("Always blocked") } }
        rule.onNode(hasText("Always blocked") and isHeading()).assertIsDisplayed()
    }

    @Test fun askingBandIsAPoliteLiveRegion() {
        rule.setContent { OpenMobTheme(darkTheme = true) { AskingBand("The phone is asking you", detail = "detail") } }
        rule.onNode(hasText("The phone is asking you") and hasText("detail"))
            .assertHeightIsAtLeast(48.dp)
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite))
    }

    @Test fun darkThemeRendersTheSameComponents() {
        rule.setContent { OpenMobTheme(darkTheme = true) { StatusChip(StatusKind.Asking, "Asking you") } }
        rule.onNodeWithText("Asking you").assertIsDisplayed()
        // The icon is decoration: no separate description to read twice.
        rule.onNodeWithContentDescription("Asking you").assertDoesNotExist()
    }
}
