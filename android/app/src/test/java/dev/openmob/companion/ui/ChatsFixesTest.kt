package dev.openmob.companion.ui

import android.content.Context
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.rememberDrawerState
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.AppState
import dev.openmob.companion.Chats
import dev.openmob.companion.FasterMode
import dev.openmob.companion.R
import dev.openmob.companion.gate.ModeChange
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeAsk
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.TAG_CHAT_SEARCH
import dev.openmob.companion.ui.home.TAG_DRAWER_LOADING
import dev.openmob.companion.ui.home.TAG_SEARCH_OPEN
import dev.openmob.companion.ui.home.ThreadItem
import dev.openmob.companion.ui.home.ThreadMapper
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.ZoneOffset

/** The 2026-10-18 audit fixes on the phone: paging, search, the thread's content, welcome and task-started, labels,
 *  the mode shown, and Disconnect ending Faster mode. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h1000dp-xhdpi")
class ChatsFixesTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int, vararg a: Any) = ctx.getString(id, *a)

    @After fun clear() = Chats.reset()

    private fun chatsJson(from: Int, n: Int, more: Boolean, q: String = "", current: String? = "c0") = JSONObject().apply {
        put("type", "chats"); put("offset", from); put("more", more); if (q.isNotEmpty()) put("q", q)
        put("current", current ?: JSONObject.NULL)
        put("chats", org.json.JSONArray((from until from + n).map {
            JSONObject().put("id", "c$it").put("title", "Chat $it").put("updated", 1_800_000_000.0 - it).put("origin", "phone").put("this_phone", true)
        }))
    }

    // --- paging -----------------------------------------------------------------------------------------------------

    @Test fun theNextPageIsAskedOnceAtTheEndAndNotWhenThereIsNoMore() {
        Chats.onWelcome(JSONObject("""{"type":"welcome","chats":true,"chat":"c0"}"""))
        Chats.onChats(chatsJson(0, 50, more = true), nowMs = 1_800_000_000_000L)
        val next = Chats.moreChats()!!
        assertEquals(50, next.optInt("offset"))
        assertNull(Chats.moreChats()) // one page on its way at a time
        Chats.onChats(chatsJson(50, 10, more = false), nowMs = 1_800_000_000_000L)
        assertEquals(60, Chats.list.size)
        assertNull(Chats.moreChats())
    }

    @Test fun theDrawersEndAsksForTheNextPage() {
        var more = 0
        val many = (0 until 50).map { Chats.Summary("c$it", "Chat $it", HomeSamples.NOW - it * 60_000L, "phone", true) }
        rule.setContent {
            OpenMobTheme {
                HomeScreen(HomeSamples.connected.copy(chatList = many, chatListMore = true), HomeActions(moreChats = { more++ }),
                           drawerState = rememberDrawerState(DrawerValue.Open))
            }
        }
        rule.waitForIdle()
        val before = more
        rule.onNode(hasTestTag("drawer-list")).performScrollToNode(hasTestTag("chat-c49"))
        rule.waitForIdle()
        assertTrue("the end asked for more", more > before)
    }

    @Test fun olderTurnsAreAskedWithTheFirstShownTurn() {
        Chats.setForTest(true, "c1", HomeSamples.chatList, HomeSamples.chat.copy(first = 30, more = true))
        val req = Chats.olderTurns()!!
        assertEquals("chat_read", req.optString("type")); assertEquals(30, req.optInt("before"))
        assertNull(Chats.olderTurns()) // on its way
        Chats.setForTest(true, "c1", HomeSamples.chatList, HomeSamples.chat.copy(first = 0, more = false))
        assertNull(Chats.olderTurns())
    }

    // --- search -----------------------------------------------------------------------------------------------------

    @Test fun searchGoesToTheServerAndAnOldAnswerIsDropped() {
        Chats.onWelcome(JSONObject("""{"type":"welcome","chats":true,"chat":"c0"}"""))
        assertEquals("pharm", Chats.search("  pharm ")!!.optString("q"))
        assertTrue(Chats.loading)
        Chats.search("pharmacy")
        Chats.onChats(chatsJson(0, 2, more = false, q = "pharm"))
        assertTrue(Chats.searchResults.isEmpty()) // the answer to an older query
        Chats.onChats(chatsJson(0, 1, more = false, q = "pharmacy"))
        assertEquals(listOf("c0"), Chats.searchResults.map { it.id })
        assertNull(Chats.search("")) // empty: the normal list
        assertTrue(Chats.searchResults.isEmpty())
    }

    @Test fun theDrawerSearchIsDebouncedAndShowsTheServersResults() {
        val asked = mutableListOf<String>()
        val results = listOf(Chats.Summary("old", "Find a pharmacy open late", HomeSamples.NOW - 90L * 86_400_000, "phone", true))
        rule.setContent {
            OpenMobTheme {
                HomeScreen(HomeSamples.connected.copy(chatSearchQuery = "pharmacy", chatSearchResults = results),
                           HomeActions(searchChats = { asked += it }), drawerState = rememberDrawerState(DrawerValue.Open))
            }
        }
        rule.onNodeWithTag(TAG_SEARCH_OPEN).performSemanticsAction(SemanticsActions.OnClick)
        rule.waitForIdle()
        asked.clear()
        rule.mainClock.autoAdvance = false
        rule.onNodeWithTag(TAG_CHAT_SEARCH).performTextInput("pharmacy")
        rule.mainClock.advanceTimeBy(100)
        assertFalse(asked.contains("pharmacy")) // not yet: about 300 ms after typing stops
        rule.mainClock.advanceTimeBy(400)
        assertTrue(asked.contains("pharmacy"))
        rule.onNodeWithTag("chat-old").assertExists() // the old chat, found on the server
        rule.onAllNodes(hasTestTag("chat-c1")).assertCountEquals(0)
    }

    @Test fun aLoadingRowShowsWhileAPageIsOnItsWay() {
        rule.setContent {
            OpenMobTheme { HomeScreen(HomeSamples.connected.copy(chatLoading = true), HomeActions(), drawerState = rememberDrawerState(DrawerValue.Open)) }
        }
        rule.onNode(hasTestTag("drawer-list")).performScrollToNode(hasTestTag(TAG_DRAWER_LOADING))
        rule.onNode(hasText(s(R.string.rd_drawer_loading))).assertExists()
    }

    // --- the thread -------------------------------------------------------------------------------------------------

    private fun turn(outcome: String, messages: List<Chats.Message>, question: String = "") = Chats.Thread("c1", "t", 0, true, listOf(
        Chats.Turn("t1", "play jazz", 1_000, if (outcome == "running" || outcome == "interrupted") null else 9_000, outcome,
                   "Playing", 2, listOf("launch_app: Spotify"), messages.count { it.kind == "question" }, false, false, question, messages)),
        0, false)

    @Test fun correctionsAndAnswersAreYourBubblesAndPastQuestionsAreReadOnly() {
        val msgs = listOf(Chats.Message("correction", "the second one", 2_000), Chats.Message("question", "Which?", 3_000),
                          Chats.Message("answer", "the playlist", 4_000))
        val items = ThreadMapper.map(turn("done", msgs), true, emptyList(), null, null, null, ZoneOffset.UTC, 0)
        val reqs = items.filterIsInstance<ThreadItem.Request>()
        assertEquals(listOf(null, R.string.rd_thread_correction, R.string.rd_thread_your_answer), reqs.map { it.caption })
        val q = items.filterIsInstance<ThreadItem.Question>().single()
        assertTrue(q.readOnly)
        // The pending question of the running task shows once, as the live card, not also as a past one.
        val pending = ThreadMapper.map(turn("running", msgs.take(2), "Which?"), true, emptyList(), null, "t1",
                                       HomeAsk.Question("Which?"), ZoneOffset.UTC, 0)
        val cards = pending.filterIsInstance<ThreadItem.Question>()
        assertEquals(1, cards.size); assertFalse(cards.single().readOnly)
    }

    @Test fun aTurnThatNeverEndedSaysDidntFinish() {
        val items = ThreadMapper.map(turn("interrupted", emptyList()), true, emptyList(), null, null, null, ZoneOffset.UTC, 0)
        assertTrue(items.filterIsInstance<ThreadItem.System>().single().interrupted)
        assertTrue(items.none { it is ThreadItem.Live })
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected.copy(thread = items), HomeActions()) } }
        rule.onNode(hasText(s(R.string.rd_thread_failed))).assertExists()
    }

    @Test fun captionsAndReadOnlyQuestionsShowOnScreen() {
        val msgs = listOf(Chats.Message("correction", "the second one", 2_000), Chats.Message("question", "Which one?", 3_000))
        val items = ThreadMapper.map(turn("done", msgs), true, emptyList(), null, null, null, ZoneOffset.UTC, 0)
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected.copy(thread = items), HomeActions()) } }
        rule.onNode(hasText(s(R.string.rd_thread_correction))).assertExists()
        rule.onNode(hasText("Which one?")).assertExists()
        rule.onAllNodes(hasText(s(R.string.rd_thread_answer_below))).assertCountEquals(0)
    }

    // --- welcome, task started, web new chat ----------------------------------------------------------------------

    @Test fun aWelcomeClearsAStaleThreadAndATaskBringsHomeBackToTheCurrentChat() {
        Chats.setForTest(true, "c1", HomeSamples.chatList, HomeSamples.chat)
        val sent = Chats.onWelcome(JSONObject("""{"type":"welcome","chats":true,"chat":"c2"}"""))
        assertNull(Chats.thread)
        assertEquals(listOf("chats_list", "chat_read"), sent.map { it.optString("type") })
        Chats.onWelcome(JSONObject("""{"type":"welcome","chats":true,"chat":null}"""))
        assertNull(Chats.current)
        // Another phone's chat shown read only; a task starts in the current chat: Home goes back to it.
        Chats.setForTest(true, "c1", HomeSamples.chatList, HomeSamples.chat.copy(chatId = "c4", thisPhone = false))
        val back = Chats.onTaskStarted("c1")
        assertEquals(listOf("chat_read"), back.map { it.optString("type") })
        assertNull(Chats.thread)
        Chats.setForTest(true, "c1", HomeSamples.chatList, HomeSamples.chat)
        assertTrue(Chats.onTaskStarted("c1").isEmpty()) // already showing it
    }

    @Test fun aNullCurrentChatFromTheServerIsHonouredAndAWebNewChatSwitchesHome() {
        Chats.setForTest(true, "c1", HomeSamples.chatList, HomeSamples.chat)
        Chats.onChats(chatsJson(0, 2, more = false, current = null), nowMs = 1_800_000_000_000L)
        assertNull(Chats.current)
        Chats.setForTest(true, "c1", HomeSamples.chatList, HomeSamples.chat)
        assertNull(Chats.onOpened(JSONObject("""{"type":"chat_opened","ok":true,"chat_id":null}""")))
        assertNull(Chats.current); assertNull(Chats.thread)
    }

    // --- labels and the mode shown --------------------------------------------------------------------------------

    @Test fun apiAndMcpChatsAreLabelled() {
        val list = listOf(Chats.Summary("a", "By the API", HomeSamples.NOW, "api", true),
                          Chats.Summary("m", "By MCP", HomeSamples.NOW, "mcp", true))
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected.copy(chatList = list), HomeActions(), drawerState = rememberDrawerState(DrawerValue.Open)) } }
        rule.onNode(hasText("From the API", substring = true)).assertExists()
        rule.onNode(hasText("From MCP", substring = true)).assertExists()
    }

    @Test fun theShownModeIsTheSignedCeilingAndTheServersOnlyLabelled() {
        // Review 3 P3-L1: a stricter server mode isn't enforced by the phone, so it is never shown as the phone's.
        assertEquals("auto", AppState.shownMode("auto", "ask"))
        assertEquals("ask", AppState.serverModeShown("auto", "ask"))
        assertEquals("auto", AppState.shownMode("auto", "trusted")) // the phone's ceiling always wins
        assertEquals("trusted", AppState.serverModeShown("auto", "trusted"))
        assertEquals("auto", AppState.shownMode("auto", null))
        assertEquals(null, AppState.serverModeShown("auto", "auto")) // nothing to tell apart
        assertEquals(null, AppState.shownMode(null, "plan")) // not loaded: never the server's as the phone's
        assertEquals("plan", AppState.serverModeShown(null, "plan"))
        assertEquals("auto", AppState.shownMode("auto", "bogus"))
        assertEquals(null, AppState.serverModeShown("auto", "bogus"))
    }

    // --- Disconnect ends Faster mode in every scope (owner, 2026-10-18) -------------------------------------------

    @Test fun disconnectEndsFasterModeEvenAlwaysOnThisPhoneAndReconnectBringsNothingBack() {
        val t0 = System.currentTimeMillis() / 1000
        val phone = FasterMode.grantFrom("Server says\n{\"faster_mode\": \"phone\"}", "a2", "t", "sig", t0)!!
        FasterMode.approve(ctx, phone)
        FasterMode.onServerPush(ctx, "phone")
        assertTrue(FasterMode.isOn)
        FasterMode.ownerDisconnected(ctx)
        assertFalse(FasterMode.isOn)
        FasterMode.load(ctx) // a restart or a reconnect: nothing stored to come back
        FasterMode.onServerPush(ctx, "phone")
        assertFalse(FasterMode.isOn)
        assertNull(FasterMode.resumeMessage())
        @Suppress("UNUSED_VARIABLE") val unused = ModeChange
    }
}
