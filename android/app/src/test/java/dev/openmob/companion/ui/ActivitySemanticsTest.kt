package dev.openmob.companion.ui

import android.content.Context
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isHeading
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import com.github.takahirom.roborazzi.captureRoboImage
import dev.openmob.companion.R
import dev.openmob.companion.ui.activity.ActivityActions
import dev.openmob.companion.ui.activity.ActivityFilter
import dev.openmob.companion.ui.activity.ActivitySamples
import dev.openmob.companion.ui.activity.ActivityScreen
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** The Activity screen: day headings, filters as one choice, 48 dp targets, the rows' words, the empty state. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h1400dp-xhdpi")
class ActivitySemanticsTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int) = ctx.getString(id)

    @Test fun headingsRowsAndFilters() {
        var chosen: ActivityFilter? = null
        rule.setContent {
            OpenMobTheme { ActivityScreen(ActivitySamples.full(), ActivityActions(filter = { chosen = it }), ActivitySamples.ZONE) }
        }
        rule.onNode(hasText(s(R.string.rd_activity_today)) and isHeading()).assertIsDisplayed()
        rule.onNode(hasText(s(R.string.rd_activity_yesterday)) and isHeading()).assertIsDisplayed()
        rule.onNode(hasText("Running · 0:14 · step 3", substring = true)).assertIsDisplayed()
        rule.onNode(hasText("Stopped by you · 1 min 40 s · asked you once", substring = true)).assertIsDisplayed()
        rule.onNode(hasText("Denied by you · 22 s · asked you once", substring = true)).assertIsDisplayed()
        rule.onNode(hasText("Done · 48 s · asked you 0 times", substring = true)).assertIsDisplayed()
        rule.onNode(hasText("Failed: couldn't find the setting", substring = true)).performScrollTo().assertIsDisplayed()
        rule.onNode(hasText(s(R.string.rd_activity_drive))).performScrollTo().assertIsDisplayed()
        rule.onNode(hasText(s(R.string.rd_activity_filter_all)))
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.RadioButton)).assertIsSelected()
        rule.onNode(hasText(s(R.string.rd_activity_filter_asked)) and hasClickAction()).performClick()
        assertEquals(ActivityFilter.Asked, chosen)
        rule.onAllNodes(hasClickAction()).fetchSemanticsNodes().forEach { n ->
            val h = with(rule.density) { n.size.height.toDp() }
            val w = with(rule.density) { n.size.width.toDp() }
            assertTrue("target ${n.config.getOrNull(SemanticsProperties.Text)} is $w x $h", h >= 47.9.dp && w >= 47.9.dp)
        }
        rule.onNode(hasText(s(R.string.rd_activity_kept))).performScrollTo().assertIsDisplayed()
    }

    @Test fun emptyState() {
        rule.setContent { OpenMobTheme { ActivityScreen(ActivitySamples.empty(), ActivityActions(), ActivitySamples.ZONE) } }
        rule.onNode(hasText(s(R.string.rd_activity_empty)) and isHeading()).assertIsDisplayed()
        rule.onAllNodes(hasText(s(R.string.rd_activity_filter_all))).fetchSemanticsNodes().let { assertTrue(it.isEmpty()) }
    }
}

/** Screenshots of the Activity screen (copied to scratchpad/redesign5). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ActivityScreenshotTest {
    @get:Rule val host = ComponentActivityRegistered()

    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h1300dp-xhdpi")
    fun activityStates() {
        listOf("all" to ActivitySamples.full(), "asked" to ActivitySamples.full(ActivityFilter.Asked),
               "stopped" to ActivitySamples.full(ActivityFilter.StoppedOrDenied), "empty" to ActivitySamples.empty())
            .forEach { (name, state) ->
                listOf(false, true).forEach { dark ->
                    captureRoboImage("src/test/screenshots/activity-$name-${if (dark) "dark" else "light"}.png") {
                        OpenMobTheme(darkTheme = dark) { ActivityScreen(state, ActivityActions(), ActivitySamples.ZONE) }
                    }
                }
            }
    }
}
