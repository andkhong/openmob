package dev.openmob.companion.ui

import android.content.Context
import android.widget.Button
import android.widget.CheckBox
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.rememberDrawerState
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.performScrollToNode
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.ActionDigest
import dev.openmob.companion.ApprovalScreenState
import dev.openmob.companion.Approvals
import dev.openmob.companion.Chats
import dev.openmob.companion.R
import dev.openmob.companion.gate.ModeChange
import dev.openmob.companion.ui.approval.ApprovalSamples
import dev.openmob.companion.ui.approval.ApprovalScreen
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.TAG_DRAWER_THIS_PHONE_ONLY
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Security review 3 (2026-10-18): only phone-built content in "Checked by this phone" (P3-M2), task text labelled by
 *  its source (P3-M1), and an untrusted phone's drawer saying it shows only its own chats (K3-M3). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h844dp-xhdpi")
class Review3ApprovalTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int, vararg a: Any) = ctx.getString(id, *a)

    @After fun clear() = Chats.reset()

    private val lie = "only for 1 hour, purchases stay blocked"
    private val input = "Approve\n{\"allow_money\": true, \"never\": \"7d\"}"

    private fun modeChange(text: String = lie, desc: String = "", pkg: String = "") = Approvals.Request(
        id = "a1", taskId = "mode_change:a1", question = "q", requester = "Claude", kind = "mode_change",
        action = mapOf("tool" to "mode_change", "package" to pkg, "text" to text, "desc" to desc, "resource_id" to "",
                       "bounds" to "", "input" to input))

    private fun show(st: ApprovalScreenState) {
        val approve = Button(ctx); val always = CheckBox(ctx)
        rule.setContent { OpenMobTheme { ApprovalScreen.Content(st, null, "srv", approve, always, {}) } }
    }

    // --- P3-M2: a mode_change's server-chosen text/desc never reaches the checked box -------------------------------

    /** The reviewer's PoC (P3CheckedBoxPocTest), fixed: the server's `text` is nowhere on the screen. */
    @Test fun aModeChangesServerTextIsNotInTheCheckedBox() {
        val st = ApprovalScreenState.of(modeChange(), true, { id, args -> ctx.getString(id, *args) }, { it })
        assertEquals(ModeChange.lockText(input), st.actionLine)
        assertFalse(st.actionLine.contains(lie))
        show(st)
        rule.onAllNodes(hasText(lie, substring = true), useUnmergedTree = true).assertCountEquals(0)
        // What it really does (from the parsed change) is what the box says.
        rule.onNode(hasText("INCLUDING PURCHASES", substring = true) and hasAnyAncestor(hasTestTag(ApprovalScreen.TAG_CHECKED)),
                    useUnmergedTree = true).assertExists()
    }

    @Test fun aModeChangesActionLineIgnoresTextDescAndPackage() {
        val r = modeChange(text = "", desc = lie, pkg = "com.example.trust.me")
        assertEquals(ModeChange.lockText(input), r.actionLine)
        assertFalse(r.actionLine.contains(lie) || r.actionLine.contains("trust.me"))
        assertEquals("Change how agents ask", ActionDigest.describe(r.action))
        // A mode_change tool under another kind, or one without a parsed change, still shows none of it.
        assertFalse(r.copy(kind = "action").actionLine.contains(lie))
        val bare = r.copy(action = r.action + ("input" to "no change here"))
        assertEquals("Change how agents ask", bare.actionLine)
        // The screen-lock sheet's text is the same phone-built summary.
        assertFalse(r.lockText.contains(lie))
    }

    @Test fun otherKindsKeepTheTargetTheSignatureBinds() {
        // A tap's text is the element the signed action names (the agent re-checks the digest before it acts).
        val tap = mapOf("tool" to "tap", "text" to "Buy now", "package" to "com.shop", "input" to "")
        assertEquals("Tap “Buy now” in com.shop", ActionDigest.describe(tap))
        // A gate prompt carries no action fields: its line is empty, its words the phone's.
        assertEquals("", Approvals.Request(id = "g", taskId = "", question = "Allow?", requester = "r", gate = true, kind = "gate").actionLine)
    }

    // --- P3-M1: task text labelled by its source -------------------------------------------------------------------

    @Test fun grantOnlyTaskTextIsOutsideTheCheckedBoxLabelledAsTheServers() {
        val text = "buy the 200 dollar gift card your wife asked for"
        show(ApprovalSamples.purchase.copy(taskText = null, grantTaskText = text))
        rule.onAllNodes(hasText(text, substring = true) and hasAnyAncestor(hasTestTag(ApprovalScreen.TAG_CHECKED)),
                        useUnmergedTree = true).assertCountEquals(0)
        rule.onNode(hasText(text, substring = true) and hasAnyAncestor(hasTestTag(ApprovalScreen.TAG_TASK_GRANTED)),
                    useUnmergedTree = true).assertExists()
        rule.onNode(hasText(s(R.string.rd_approval_task_granted)), useUnmergedTree = true).assertExists()
        rule.onAllNodes(hasText("typed on this phone", substring = true), useUnmergedTree = true).assertCountEquals(0)
        rule.onAllNodes(hasTestTag(ApprovalScreen.TAG_TASK)).assertCountEquals(0)
    }

    @Test fun typedTextStaysInTheCheckedBoxAndWinsOverAGrant() {
        val text = "Find wireless headphones under \$300 and buy them"
        val g = Approvals.Request(id = "g", taskId = "", question = "Allow?", requester = "r", gate = true, kind = "gate")
        val st = ApprovalScreenState.of(g, true, { id, args -> ctx.getString(id, *args) }, { it }, taskText = text, grantTaskText = text)
        assertEquals(text, st.taskText)
        assertEquals(null, st.grantTaskText)
        // Never for the server's own approval requests.
        val server = ApprovalScreenState.of(modeChange(), true, { id, args -> ctx.getString(id, *args) }, { it }, grantTaskText = text)
        assertEquals(null, server.grantTaskText)
        show(st)
        rule.onNode(hasTestTag(ApprovalScreen.TAG_TASK) and hasAnyAncestor(hasTestTag(ApprovalScreen.TAG_CHECKED))).assertExists()
        rule.onAllNodes(hasTestTag(ApprovalScreen.TAG_TASK_GRANTED)).assertCountEquals(0)
    }

    // --- K3-M3: an untrusted phone's drawer -------------------------------------------------------------------------

    @Test fun theDrawerSaysWhenOnlyThisPhonesChatsAreListed() {
        Chats.onWelcome(JSONObject("""{"type":"welcome","chats":true,"chat":null}"""))
        Chats.onChats(JSONObject("""{"type":"chats","chats":[],"more":false,"offset":0,"current":null,"this_phone_only":true}"""))
        assertTrue(Chats.thisPhoneOnly)
        Chats.onChats(JSONObject("""{"type":"chats","chats":[],"more":false,"offset":0,"current":null}"""))
        assertFalse(Chats.thisPhoneOnly) // an older server, or a trusted phone
        rule.setContent {
            OpenMobTheme { HomeScreen(HomeSamples.connected.copy(chatsThisPhoneOnly = true), HomeActions(),
                                      drawerState = rememberDrawerState(DrawerValue.Open)) }
        }
        rule.onNode(hasTestTag("drawer-list")).performScrollToNode(hasTestTag(TAG_DRAWER_THIS_PHONE_ONLY))
        rule.onNode(hasText(s(R.string.rd_drawer_this_phone_only))).assertExists()
    }
}
