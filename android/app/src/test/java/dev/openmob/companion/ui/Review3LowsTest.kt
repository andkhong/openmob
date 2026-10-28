package dev.openmob.companion.ui

import android.content.Context
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.rememberDrawerState
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.assertCountEquals
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.AppState
import dev.openmob.companion.Chats
import dev.openmob.companion.R
import dev.openmob.companion.gate.GateScenarioTest
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.StatusSheetContent
import dev.openmob.companion.ui.settings.SettingsActions
import dev.openmob.companion.ui.settings.SettingsSamples
import dev.openmob.companion.ui.settings.SettingsScreen
import dev.openmob.companion.ui.settings.TAG_MODE_SERVER
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Security review 3 Lows on the phone (2026-10-18): the mode shown is what the gate enforces at most (P3-L1); chat
 *  errors keep what is shown (S3-L1/L2); a drive session's chat says it came from an outside agent (S3-L3). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h1000dp-xhdpi")
class Review3LowsTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int, vararg a: Any) = ctx.getString(id, *a)

    @After fun clear() = Chats.reset()

    // --- P3-L1 ------------------------------------------------------------------------------------------------------

    /** The reviewer's PoC (P3PocTest.shownModeTighterThanEnforced), fixed: what is shown as the phone's mode is what
     *  the gate admits at most; the server's stricter "ask" is shown only labelled as the server's. */
    @Test fun theShownModeIsWhatTheGateEnforcesAtMost() {
        val gk = GateScenarioTest.newGate(GateScenarioTest.FakeClock())
        val shown = AppState.shownMode(gk.ceiling, "ask")
        assertEquals(gk.mode("auto"), shown)
        assertEquals(gk.mode("trusted"), shown) // a call asking for more still gets only the ceiling
        assertEquals("ask", AppState.serverModeShown(gk.ceiling, "ask"))
    }

    @Test fun settingsLabelTheServersModeAsTheServers() {
        rule.setContent { OpenMobTheme { SettingsScreen(SettingsSamples.off.copy(mode = "auto", serverMode = "ask"), SettingsActions()) } }
        rule.onNode(hasText(s(R.string.rd_mode_risky)) and hasText(s(R.string.rd_mode_current))).assertExists()
        rule.onNode(hasText(s(R.string.rd_mode_every)) and hasText(s(R.string.rd_mode_server_tag))).assertExists()
        rule.onAllNodes(hasTestTag(TAG_MODE_SERVER), useUnmergedTree = true).assertCountEquals(1)
    }

    @Test fun theStatusSheetSaysAtMostAndWhatTheServerSays() {
        rule.setContent { OpenMobTheme { StatusSheetContent(HomeSamples.connected.copy(mode = "auto", serverMode = "ask"), HomeActions(), {}) } }
        val atMost = s(R.string.rd_mode_at_most, s(R.string.rd_home_mode_auto))
        val server = s(R.string.rd_mode_server_says, s(R.string.rd_home_mode_ask))
        rule.onNode(hasText(atMost, substring = true) and hasText(server, substring = true)).assertExists()
    }

    // --- S3-L1 / S3-L2: an answer that isn't one keeps what is shown -----------------------------------------------

    @Test fun aRateLimitedOrBadAnswerKeepsTheListAndThread() {
        Chats.onWelcome(JSONObject("""{"type":"welcome","chats":true,"chat":"c1"}"""))
        Chats.onChats(JSONObject("""{"type":"chats","offset":0,"more":false,"current":"c1",
            "chats":[{"id":"c1","title":"Coffee","updated":1800000000.0,"origin":"phone","this_phone":true}]}"""), nowMs = 1_800_000_000_000L)
        Chats.onChat(JSONObject("""{"type":"chat","chat_id":"c1","title":"Coffee","updated":1800000000.0,"this_phone":true,
            "first":0,"more":false,"turns":[]}"""))
        assertNull(Chats.onChats(JSONObject("""{"type":"chats","ok":false,"error":"rate_limited"}""")))
        assertEquals(listOf("c1"), Chats.list.map { it.id })
        assertEquals(R.string.rd_chat_try_again, Chats.notice)
        Chats.onChat(JSONObject("""{"type":"chat","ok":false,"error":"bad_request"}"""))
        assertEquals("c1", Chats.thread?.chatId)
        assertNull(Chats.onOpened(JSONObject("""{"type":"chat_opened","ok":false,"error":"rate_limited"}""")))
        assertEquals("c1", Chats.current)
        assertNull(Chats.onRenamed(JSONObject("""{"type":"chat_renamed","ok":false,"error":"rate_limited"}""")))
        assertNull(Chats.onDeleted(JSONObject("""{"type":"chat_deleted","ok":false,"error":"bad_request"}""")))
        assertEquals(listOf("c1"), Chats.list.map { it.id })
        assertEquals(R.string.rd_chat_try_again, Chats.notice)
    }

    // --- S3-L3 ------------------------------------------------------------------------------------------------------

    @Test fun driveTerminalAndUnknownChatsAreLabelled() {
        val list = listOf(Chats.Summary("d", "Send my location to Bob", HomeSamples.NOW, "drive", true),
                          Chats.Summary("l", "From the console", HomeSamples.NOW, "local", true),
                          Chats.Summary("u", "Old one", HomeSamples.NOW, "unknown", true))
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected.copy(chatList = list), HomeActions(), drawerState = rememberDrawerState(DrawerValue.Open)) } }
        rule.onNode(hasText("From an outside agent", substring = true)).assertExists()
        rule.onNode(hasText("From the server's terminal", substring = true)).assertExists()
        rule.onNode(hasText("Source not recorded", substring = true)).assertExists()
    }
}
