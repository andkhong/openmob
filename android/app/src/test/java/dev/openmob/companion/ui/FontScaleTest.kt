package dev.openmob.companion.ui

import android.content.Context
import android.widget.Button
import android.widget.CheckBox
import androidx.compose.foundation.background
import androidx.compose.runtime.Composable
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.ComposeContentTestRule
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.semantics.getOrNull
import androidx.test.core.app.ApplicationProvider
import com.github.takahirom.roborazzi.captureRoboImage
import dev.openmob.companion.ApprovalScreenState
import dev.openmob.companion.R
import dev.openmob.companion.ui.activity.ActivityActions
import dev.openmob.companion.ui.activity.ActivitySamples
import dev.openmob.companion.ui.activity.ActivityScreen
import dev.openmob.companion.ui.approval.ApprovalSamples
import dev.openmob.companion.ui.approval.ApprovalScreen
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.settings.IndicatorActions
import dev.openmob.companion.ui.settings.IndicatorSettingsScreen
import dev.openmob.companion.ui.settings.SettingsActions
import dev.openmob.companion.ui.settings.SettingsSamples
import dev.openmob.companion.ui.settings.SettingsScreen
import dev.openmob.companion.ui.setup.SetupActions
import dev.openmob.companion.ui.setup.SetupSamples
import dev.openmob.companion.ui.setup.SetupScreenFor
import dev.openmob.companion.ui.theme.DarkOpenMobColors
import dev.openmob.companion.ui.theme.LightOpenMobColors
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Every redesigned screen and state, as (name, content): shared by the 200% checks and the screenshots. */
internal object FontScaleScreens {
    private val ctx: Context get() = ApplicationProvider.getApplicationContext()

    val approvalStates: List<Pair<String, ApprovalScreenState>> = listOf(
        "purchase" to ApprovalSamples.purchase.copy(expiresAt = 10_000_000, taskText = "Find wireless headphones under \$300 and buy them"),
        "tap" to ApprovalSamples.tap.copy(expiresAt = 10_000_000),
        "permission" to ApprovalSamples.modeChange.copy(expiresAt = 10_000_000),
        "blocked" to ApprovalSamples.blocked.copy(expiresAt = 10_000_000),
        "answered" to ApprovalSamples.gone,
        "expired" to ApprovalSamples.purchase.copy(expiresAt = 10_000_000), // drawn at its expiry: see [approval]
    )

    /** The approval screen with ApprovalActivity's own two Android views, styled as it styles them. */
    @Composable
    fun approval(name: String, state: ApprovalScreenState, dark: Boolean = false) {
        val approve = Button(ctx).apply {
            text = ctx.getString(if (state.gate && state.level == "tap") R.string.rd_approval_allow else R.string.rd_approval_with_lock)
        }
        val always = CheckBox(ctx).apply { text = state.alwaysText }
        ApprovalScreen.styleApprove(approve, if (dark) DarkOpenMobColors else LightOpenMobColors)
        ApprovalScreen.styleAlways(always, if (dark) DarkOpenMobColors else LightOpenMobColors)
        val now = if (name == "expired") state.expiresAt else state.expiresAt - 92_000
        ApprovalScreen.Content(state, if (name == "blocked") ApprovalSamples.MISMATCH else null, "home-server.local",
                               approve, always, {}, now = { now })
    }

    val all: List<Pair<String, @Composable () -> Unit>> =
        HomeSamples.all.map { (n, s) -> "home-$n" to @Composable { HomeScreen(s, HomeActions()) } } +
            listOf("off" to SettingsSamples.off, "faster-on" to SettingsSamples.fasterOn, "offline" to SettingsSamples.offline)
                .map { (n, s) -> "settings-$n" to @Composable { SettingsScreen(s, SettingsActions()) } } +
            listOf("default" to SettingsSamples.indicator, "custom" to SettingsSamples.indicatorCustom.copy(nearAmber = true),
                   "invalid-off" to SettingsSamples.indicatorInvalid)
                .map { (n, s) -> "indicator-$n" to @Composable { IndicatorSettingsScreen(s, IndicatorActions()) } } +
            listOf("activity-full" to @Composable { ActivityScreen(ActivitySamples.full(), ActivityActions(), ActivitySamples.ZONE) },
                   "activity-empty" to @Composable { ActivityScreen(ActivitySamples.empty(), ActivityActions(), ActivitySamples.ZONE) }) +
            SetupSamples.all.map { (n, r, s) -> "setup-$n" to @Composable { SetupScreenFor(r, s, SetupActions()) } } +
            approvalStates.map { (n, s) -> "approval-$n" to @Composable { approval(n, s) } } +
            listOf(
                "model-sheet" to @Composable {
                    androidx.compose.foundation.layout.Box(androidx.compose.ui.Modifier.background(OpenMobTheme.colors.surface)) {
                        dev.openmob.companion.ui.home.ModelSheetContent(HomeSamples.models, { _, _ -> }, {})
                    }
                },
                "home-drawer" to @Composable {
                    HomeScreen(HomeSamples.connected, HomeActions(),
                               drawerState = androidx.compose.material3.rememberDrawerState(androidx.compose.material3.DrawerValue.Open))
                },
            )
}

/** Texts whose layout overflowed (clipped by a fixed height, a width, or cut by maxLines). */
internal fun ComposeContentTestRule.overflowingTexts(): List<String> =
    onAllNodes(SemanticsMatcher.keyIsDefined(SemanticsActions.GetTextLayoutResult), useUnmergedTree = true)
        .fetchSemanticsNodes()
        // Home's chat title ellipsizes on purpose (it gives way to the pill).
        .filter { it.config.getOrNull(androidx.compose.ui.semantics.SemanticsProperties.TestTag) != dev.openmob.companion.ui.home.TAG_CHAT_TITLE }
        .mapNotNull { node ->
            val out = mutableListOf<TextLayoutResult>()
            node.config[SemanticsActions.GetTextLayoutResult].action?.invoke(out)
            out.firstOrNull()?.takeIf { r -> r.didOverflowHeight || (0 until r.lineCount).any { r.isLineEllipsized(it) } }?.let { "${it.layoutInput.text.text} [w=${it.didOverflowWidth} h=${it.didOverflowHeight} size=${it.size} mp=${it.multiParagraph.width}x${it.multiParagraph.height} c=${it.layoutInput.constraints} lines=${it.lineCount}]" }
        }

/**
 * The owner's 200% text check (2026-10-17): Android's largest Font size with the largest Display size give a font
 * scale of about 2.0 on Android 14 and later. Run on a small phone window (360 x 740 dp).
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "w360dp-h740dp-xhdpi", fontScale = 2.0f)
class FontScaleTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)

    private val content = androidx.compose.runtime.mutableStateOf<(@Composable () -> Unit)?>(null)

    @Test fun noTextOverflowsOnAnyScreenAtTwiceTheTextSize() {
        rule.setContent { OpenMobTheme { content.value?.invoke() } }
        val bad = FontScaleScreens.all.flatMap { (name, screen) ->
            content.value = screen
            rule.waitForIdle()
            rule.overflowingTexts().map { "$name: $it" }
        }
        assertTrue("Text overflowed at font scale 2.0:\n" + bad.joinToString("\n"), bad.isEmpty())
    }

    @Test fun theComposerStillWorksAtTwiceTheTextSize() {
        rule.setContent { OpenMobTheme { content.value?.invoke() } }
        listOf(HomeSamples.connected, HomeSamples.working).forEach { state ->
            content.value = @Composable { HomeScreen(state, HomeActions()) }
            rule.waitForIdle()
            val root = rule.onRoot().fetchSemanticsNode().size
            listOf(dev.openmob.companion.ui.home.TAG_COMPOSER_FIELD, dev.openmob.companion.ui.home.TAG_COMPOSER_MIC,
                   dev.openmob.companion.ui.home.TAG_COMPOSER_SEND, dev.openmob.companion.ui.home.TAG_MODEL_CHIP).forEach { tag ->
                val n = rule.onNodeWithTag(tag, useUnmergedTree = true)
                assertTrue("$tag not displayed (${state.status})", runCatching { n.assertIsDisplayed() }.isSuccess)
                val b = n.fetchSemanticsNode().boundsInRoot
                assertTrue("$tag off screen: $b in $root", b.top >= 0f && b.left >= 0f && b.bottom <= root.height && b.right <= root.width)
            }
        }
    }

    @Test fun bothApprovalButtonsAreFullyOnScreenAndEqualAtTwiceTheTextSize() {
        rule.setContent { OpenMobTheme { content.value?.invoke() } }
        listOf("purchase", "tap", "permission").forEach { name ->
            val state = FontScaleScreens.approvalStates.first { it.first == name }.second
            content.value = @Composable { FontScaleScreens.approval(name, state) }
            rule.waitForIdle()
            val root = rule.onRoot().fetchSemanticsNode().size
            val deny = rule.onNodeWithTag(ApprovalScreen.TAG_DENY, useUnmergedTree = true).assertIsDisplayed().fetchSemanticsNode()
            val approve = rule.onNodeWithTag(ApprovalScreen.TAG_APPROVE, useUnmergedTree = true).assertIsDisplayed().fetchSemanticsNode()
            listOf(deny, approve).forEach { n ->
                val b = n.boundsInRoot
                assertTrue("$name: ${n.config} off screen: $b in $root", b.top >= 0f && b.left >= 0f && b.bottom <= root.height && b.right <= root.width)
            }
            assertEquals("$name: Deny and Approve differ in size", deny.size, approve.size)
            // Stacked at this scale, Deny first: Approve is never above (or without) Deny.
            assertTrue("$name: Deny is not first", deny.boundsInRoot.top < approve.boundsInRoot.top)
            rule.onNodeWithTag(ApprovalScreen.TAG_COUNTDOWN, useUnmergedTree = true).assertIsDisplayed()
        }
    }
}

/**
 * Screenshots of every screen at font scale 1.0, 1.5 and 2.0 (light; the approval screen in dark too), for review.
 * `./gradlew recordRoborazziDebug` writes them to src/test/screenshots/fontscale (gitignored).
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class FontScaleScreenshotTest {
    @get:Rule val host = ComponentActivityRegistered()

    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h844dp-xhdpi")
    fun everyScreenAtThreeTextSizes() {
        listOf(1.0f, 1.5f, 2.0f).forEach { scale ->
            RuntimeEnvironment.setFontScale(scale)
            val tag = "x" + scale.toString().replace('.', '_')
            FontScaleScreens.all.forEach { (name, screen) ->
                captureRoboImage("src/test/screenshots/fontscale/$tag/$name-light.png") { OpenMobTheme(darkTheme = false) { screen() } }
            }
            FontScaleScreens.approvalStates.forEach { (name, state) ->
                captureRoboImage("src/test/screenshots/fontscale/$tag/approval-$name-dark.png") {
                    OpenMobTheme(darkTheme = true) { FontScaleScreens.approval(name, state, dark = true) }
                }
            }
        }
        RuntimeEnvironment.setFontScale(1.0f)
    }

    /** The same screens at 2.0 in a very tall window, to see each one whole (what scrolls below the fold). */
    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h3200dp-xhdpi")
    fun everyScreenWholeAtTwiceTheTextSize() {
        RuntimeEnvironment.setFontScale(2.0f)
        FontScaleScreens.all.forEach { (name, screen) ->
            captureRoboImage("src/test/screenshots/fontscale/x2_0-whole/$name-light.png") { OpenMobTheme(darkTheme = false) { screen() } }
        }
        RuntimeEnvironment.setFontScale(1.0f)
    }
}
