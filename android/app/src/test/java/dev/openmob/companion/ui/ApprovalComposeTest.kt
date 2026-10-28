package dev.openmob.companion.ui

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.widget.Button
import android.widget.CheckBox
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isFocused
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import com.github.takahirom.roborazzi.captureRoboImage
import dev.openmob.companion.ApprovalScreenState
import dev.openmob.companion.R
import dev.openmob.companion.ui.approval.ApprovalSamples
import dev.openmob.companion.ui.approval.ApprovalScreen
import dev.openmob.companion.ui.theme.DarkOpenMobColors
import dev.openmob.companion.ui.theme.LightOpenMobColors
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.ByteArrayOutputStream

/** The redesigned approval screen's layout and semantics (Robolectric), and its screenshots. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h844dp-xhdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ApprovalComposeTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int) = ctx.getString(id)

    private fun views(dark: Boolean = false): Pair<Button, CheckBox> {
        val approve = Button(ctx).apply { text = s(R.string.approval_approve); filterTouchesWhenObscured = true }
        val always = CheckBox(ctx).apply { filterTouchesWhenObscured = true }
        val colors = if (dark) DarkOpenMobColors else LightOpenMobColors
        ApprovalScreen.styleApprove(approve, colors)
        ApprovalScreen.styleAlways(always, colors)
        return approve to always
    }

    private fun show(state: ApprovalScreenState, status: String? = null, onDeny: () -> Unit = {}) {
        val (approve, always) = views()
        always.text = state.alwaysText
        rule.setContent { OpenMobTheme { ApprovalScreen.Content(state, status, "home-server.local", approve, always, onDeny) } }
    }

    @Test fun p15_denyAndApproveAreTheSameSize() {
        show(ApprovalSamples.purchase)
        val deny = rule.onNodeWithTag(ApprovalScreen.TAG_DENY).fetchSemanticsNode().size
        val approve = rule.onNodeWithTag(ApprovalScreen.TAG_APPROVE).fetchSemanticsNode().size
        assertEquals(deny, approve)
        with(rule.density) { assertTrue(deny.height.toDp() >= 56.dp - 0.5.dp && deny.width.toDp() >= 48.dp) }
    }

    @Test fun theAskIsAPoliteLiveRegion() {
        show(ApprovalSamples.purchase)
        rule.onNode(hasText(ApprovalSamples.purchase.question, substring = true) and hasText(ApprovalSamples.purchase.label, substring = true))
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite))
    }

    @Test fun p12_serverTextOnlyUnderServerSays() {
        show(ApprovalSamples.purchase)
        val said = ApprovalSamples.purchase.serverSays
        rule.onAllNodes(hasText(said, substring = true) and hasAnyAncestor(hasTestTag(ApprovalScreen.TAG_SERVER))).assertCountEquals(1)
        rule.onAllNodes(hasText(said, substring = true) and hasAnyAncestor(hasTestTag(ApprovalScreen.TAG_CHECKED))).assertCountEquals(0)
        // The phone-built action line is in the checked box.
        rule.onAllNodes(hasText(ApprovalSamples.purchase.actionLine) and hasAnyAncestor(hasTestTag(ApprovalScreen.TAG_CHECKED))).assertCountEquals(1)
    }

    @Test fun p12_aServerRequesterIsLabelledAsTheServers() {
        show(ApprovalSamples.modeChange)
        rule.onAllNodes(hasText("Claude", substring = true) and hasAnyAncestor(hasTestTag(ApprovalScreen.TAG_SERVER))).assertCountEquals(1)
        rule.onAllNodes(hasText("Claude", substring = true) and hasAnyAncestor(hasTestTag(ApprovalScreen.TAG_CHECKED))).assertCountEquals(0)
    }

    @Test fun p11_aBlockerLeavesOnlyDeny() {
        var denied = 0
        show(ApprovalSamples.blocked, status = ApprovalSamples.MISMATCH, onDeny = { denied++ })
        rule.onAllNodes(hasTestTag(ApprovalScreen.TAG_APPROVE)).assertCountEquals(0)
        rule.onNodeWithTag(ApprovalScreen.TAG_DENY).performClick()
        assertEquals(1, denied)
    }

    /** UX review 2, B1: an answered or expired request shows no Approve, no Deny, no "Always allow", no amber band:
     *  one Close. */
    @Test fun p13_anAnsweredRequestShowsOnlyClose() {
        var closed = 0
        val (approve, always) = views()
        rule.setContent {
            OpenMobTheme { ApprovalScreen.Content(ApprovalSamples.gone, null, "h", approve, always, {}, onClose = { closed++ }) }
        }
        rule.onAllNodes(hasTestTag(ApprovalScreen.TAG_APPROVE)).assertCountEquals(0)
        rule.onAllNodes(hasTestTag(ApprovalScreen.TAG_DENY)).assertCountEquals(0)
        rule.onAllNodes(hasTestTag(ApprovalScreen.TAG_CHECKED)).assertCountEquals(0)
        rule.onNodeWithTag(ApprovalScreen.TAG_CLOSED).assertExists()
        rule.onNodeWithTag(ApprovalScreen.TAG_CLOSE).performClick()
        assertEquals(1, closed)
    }

    /** Owner, 2026-10-17: a screen-lock prompt has the lock heading; a one-tap prompt doesn't. */
    @Test fun lockAndOneTapPromptsLookDifferent() {
        val current = androidx.compose.runtime.mutableStateOf(ApprovalSamples.purchase)
        val (approve, always) = views()
        rule.setContent { OpenMobTheme { ApprovalScreen.Content(current.value, null, "h", approve, always, {}) } }
        rule.onNodeWithTag(ApprovalScreen.TAG_LOCK_HEADING, useUnmergedTree = true).assertExists()
        current.value = ApprovalSamples.tap
        rule.waitForIdle()
        rule.onAllNodes(hasTestTag(ApprovalScreen.TAG_LOCK_HEADING), useUnmergedTree = true).assertCountEquals(0)
    }

    /** UX review 2, item 12: a money prompt with no amount in its words says the amount wasn't checked. */
    @Test fun amountNotCheckedOnlyForAMoneyPromptWithoutAnAmount() {
        val base = dev.openmob.companion.Approvals.Request(id = "gk1", taskId = "", question = "Allow tapping “Buy now” in Shop?",
            requester = "This phone", kind = "gate", gate = true, level = "fingerprint")
        assertTrue(ApprovalScreenState.amountUnchecked(base))
        assertTrue(!ApprovalScreenState.amountUnchecked(base.copy(question = "Allow tapping “Buy now · \$249.99” in Shop?")))
        assertTrue(!ApprovalScreenState.amountUnchecked(base.copy(question = "Allow tapping “Send” in Messages?")))
        assertTrue(!ApprovalScreenState.amountUnchecked(base.copy(level = "tap")))
        show(ApprovalSamples.purchase.copy(amountUnchecked = true))
        rule.onNodeWithTag(ApprovalScreen.TAG_AMOUNT, useUnmergedTree = true).assertExists()
    }

    /** UX review 2, H6: a Faster mode prompt shows the Faster mode warning, not "agents would ask you less". */
    @Test fun fasterModePromptShowsItsWarning() {
        val input = "Turn on Faster mode for this session?\n{\"faster_mode\": \"session\", \"faster_until\": 1, \"faster_idle_s\": 3600, \"faster_resume_s\": 300}"
        val r = dev.openmob.companion.Approvals.Request(id = "a", taskId = "t", question = "q", requester = "Claude", kind = "mode_change",
            action = mapOf("tool" to "mode_change", "input" to input))
        val st = ApprovalScreenState.of(r, true, { id, args -> ctx.getString(id, *args) }, { it })
        if (dev.openmob.companion.gate.ModeChange.fasterScope(input) != null) {
            assertEquals(ctx.getString(R.string.faster_warning), st.explain)
            assertTrue(!st.actionLine.startsWith("mode_change"))
        }
    }

    @Test fun p16_nothingIsFocusedAtFirst() {
        show(ApprovalSamples.tap)
        rule.onAllNodes(isFocused()).assertCountEquals(0)
    }

    @Test fun theLockNoteOnlyWhereTheLockIsUsed() {
        show(ApprovalSamples.tap)
        rule.onAllNodes(hasText(s(R.string.rd_approval_lock_note))).assertCountEquals(0)
        rule.onAllNodes(hasText(s(R.string.rd_approval_tap_note))).assertCountEquals(1)
    }

    @Test fun theStatusIsAPoliteLiveRegion() {
        show(ApprovalSamples.purchase, status = ApprovalSamples.INTERRUPTED)
        rule.onNode(hasText(ApprovalSamples.INTERRUPTED))
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite))
    }

    @Test fun thePhoneHeldTaskTextIsInTheCheckedBox() {
        show(ApprovalSamples.purchase.copy(taskText = "Find wireless headphones under \$300 and buy them"))
        rule.onNode(hasTestTag(ApprovalScreen.TAG_TASK) and hasAnyAncestor(hasTestTag(ApprovalScreen.TAG_CHECKED)))
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.Text,
                listOf(androidx.compose.ui.text.AnnotatedString(ctx.getString(R.string.rd_approval_task, "Find wireless headphones under \$300 and buy them")))))
    }

    @Test fun noPhoneHeldTextShowsNothingNotTheServers() {
        show(ApprovalSamples.purchase.copy(taskText = null))
        rule.onAllNodes(hasTestTag(ApprovalScreen.TAG_TASK)).assertCountEquals(0)
        rule.onAllNodes(hasText("Your task", substring = true)).assertCountEquals(0)
    }

    @Test fun theCountdownRunsOnThePhonesClockAndEndsInExpired() {
        var t = 1_000_000L
        val state = ApprovalSamples.purchase.copy(expiresAt = t + 120_000)
        val (approve, always) = views()
        var denied = 0
        rule.setContent {
            OpenMobTheme { ApprovalScreen.Content(state, null, "home-server.local", approve, always, { denied++ }, now = { t }) }
        }
        rule.onNodeWithTag(ApprovalScreen.TAG_COUNTDOWN).assert(hasText("2:00", substring = true))
        t += 61_500
        rule.mainClock.advanceTimeBy(500)
        rule.onNodeWithTag(ApprovalScreen.TAG_COUNTDOWN).assert(hasText("0:59", substring = true))
        rule.onAllNodes(hasTestTag(ApprovalScreen.TAG_APPROVE)).assertCountEquals(1)
        t += 60_000
        rule.mainClock.advanceTimeBy(500)
        // Expired (UX review 2, B1): Approve and Deny are gone; the screen says it's over, with one Close.
        rule.onAllNodes(hasTestTag(ApprovalScreen.TAG_APPROVE)).assertCountEquals(0)
        rule.onAllNodes(hasTestTag(ApprovalScreen.TAG_DENY)).assertCountEquals(0)
        rule.onNodeWithTag(ApprovalScreen.TAG_CLOSED).assertExists()
        rule.onNodeWithTag(ApprovalScreen.TAG_CLOSE).assertExists()
        assertEquals(0, denied)
    }

    @Test fun clockFormat() {
        assertEquals("2:00", ApprovalScreen.clock(120_000))
        assertEquals("0:01", ApprovalScreen.clock(1))
        assertEquals("0:00", ApprovalScreen.clock(0))
        assertEquals(-1L, ApprovalScreen.remainingMs(ApprovalSamples.purchase, 5))
        assertEquals(0L, ApprovalScreen.remainingMs(ApprovalSamples.purchase.copy(expiresAt = 10), 50))
    }

    @Test fun taskTextIsIgnoredForServerApprovals() {
        val r = dev.openmob.companion.Approvals.Request(id = "a", taskId = "t", question = "q", requester = "r", kind = "mode_change")
        val st = ApprovalScreenState.of(r, true, { id, args -> ctx.getString(id, *args) }, { it }, taskText = "typed")
        assertEquals(null, st.taskText)
        val g = r.copy(gate = true, kind = "gate", receivedAt = 500)
        val gs = ApprovalScreenState.of(g, true, { id, args -> ctx.getString(id, *args) }, { it }, taskText = "typed")
        assertEquals("typed", gs.taskText)
        assertEquals(500 + dev.openmob.companion.Approvals.EXPIRY_MS, gs.expiresAt)
    }
}

/** Screenshots of the redesigned approval screen (light, dark, tap level, permission change, blocked, the lock
 *  interrupted, answered). The heads-up notification and the lock sheet are Android's own UI: not drawn here. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ApprovalScreenshotTest {
    @get:Rule val host = ComponentActivityRegistered()
    private val ctx: Context = ApplicationProvider.getApplicationContext()

    private fun shot(name: String, state: ApprovalScreenState, status: String? = null, dark: Boolean) =
        captureRoboImage("src/test/screenshots/approval-$name-${if (dark) "dark" else "light"}.png") {
            val approve = Button(ctx).apply { text = ctx.getString(R.string.approval_approve) }
            val always = CheckBox(ctx).apply { text = state.alwaysText }
            ApprovalScreen.styleApprove(approve, if (dark) DarkOpenMobColors else LightOpenMobColors)
            ApprovalScreen.styleAlways(always, if (dark) DarkOpenMobColors else LightOpenMobColors)
            OpenMobTheme(darkTheme = dark) {
                ApprovalScreen.Content(state, status, "home-server.local", approve, always, {}, now = { state.expiresAt - 92_000 })
            }
        }

    private fun crop(): ByteArray {
        val bmp = Bitmap.createBitmap(360, 160, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        canvas.drawColor(Color.rgb(244, 244, 244))
        val p = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(242, 169, 0) }
        canvas.drawRoundRect(70f, 50f, 290f, 110f, 30f, 30f, p)
        p.color = Color.rgb(14, 22, 33); p.style = Paint.Style.STROKE; p.strokeWidth = 5f
        canvas.drawRoundRect(62f, 42f, 298f, 118f, 36f, 36f, p)
        return ByteArrayOutputStream().also { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
    }

    @Test
    @Config(sdk = [35], qualifiers = "w390dp-h844dp-xhdpi")
    fun approvalStates() {
        val purchase = ApprovalSamples.purchase.copy(crop = crop(), expiresAt = 10_000_000,
            taskText = "Find wireless headphones under \$300 and buy them")
        listOf(false, true).forEach { dark ->
            shot("purchase", purchase, dark = dark)
            shot("tap", ApprovalSamples.tap, dark = dark)
            shot("permission", ApprovalSamples.modeChange, dark = dark)
            shot("blocked", ApprovalSamples.blocked, ApprovalSamples.MISMATCH, dark = dark)
            shot("lock-interrupted", purchase, ApprovalSamples.INTERRUPTED, dark = dark)
            shot("answered", ApprovalSamples.gone, "This request was already answered or has expired.", dark = dark)
        }
    }
}
