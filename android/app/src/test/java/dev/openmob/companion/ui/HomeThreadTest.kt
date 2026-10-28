package dev.openmob.companion.ui

import android.content.ClipboardManager
import android.content.Context
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeDown
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.AppState
import dev.openmob.companion.Chats
import dev.openmob.companion.R
import dev.openmob.companion.TaskLog
import dev.openmob.companion.ui.home.DRAWER_PLACES
import dev.openmob.companion.ui.home.TAG_AVATAR
import dev.openmob.companion.ui.home.TAG_SEARCH_CLOSE
import dev.openmob.companion.ui.home.TAG_SEARCH_OPEN
import dev.openmob.companion.ui.home.ChatGroup
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeAsk
import dev.openmob.companion.ui.home.HomeMapper
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.HomeStatus
import dev.openmob.companion.ui.home.HomeViewModel
import dev.openmob.companion.ui.home.Issue
import dev.openmob.companion.ui.home.PillState
import dev.openmob.companion.ui.home.StatusSheetContent
import dev.openmob.companion.ui.home.TAG_CHAT_SEARCH
import dev.openmob.companion.ui.home.TAG_DISCONNECT
import dev.openmob.companion.ui.home.TAG_DRAWER
import dev.openmob.companion.ui.home.TAG_JUMP
import dev.openmob.companion.ui.home.TAG_LIVE_STEP
import dev.openmob.companion.ui.home.TAG_MENU_BUTTON
import dev.openmob.companion.ui.home.TAG_MODE_CHIP
import dev.openmob.companion.ui.home.TAG_NEW_CHAT
import dev.openmob.companion.ui.home.TAG_PILL
import dev.openmob.companion.ui.home.TAG_RECONNECT
import dev.openmob.companion.ui.home.TAG_THREAD
import dev.openmob.companion.ui.home.TaskProgress
import dev.openmob.companion.ui.home.ThreadItem
import dev.openmob.companion.ui.home.ThreadMapper
import dev.openmob.companion.ui.home.groupChats
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.state.PhoneSnapshot
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.json.JSONObject
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

/** Home as the chat thread (rev 6): the thread, the pill and status sheet, the drawer, and the chats state. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h1000dp-xhdpi")
class HomeThreadTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int, vararg a: Any) = ctx.getString(id, *a)
    private val utc = ZoneOffset.UTC

    // --- the thread (pure) ----------------------------------------------------------------------------------------

    @Test fun theThreadIsRequestsRepliesAndSystemLinesWithTheLiveStepLast() {
        val task = TaskProgress("Play some relaxed jazz", null, 3, "Typing “jazz”", "", 14)
        val items = ThreadMapper.map(HomeSamples.chat, true, emptyList(), task, "t4", null, utc, HomeSamples.NOW)
        val kinds = items.map { it::class.simpleName }
        assertEquals(listOf("Day", "Request", "Reply", "Request", "Reply", "System", "Request", "Reply", "Request", "Live"), kinds)
        val stopped = items.filterIsInstance<ThreadItem.System>().single()
        assertFalse(stopped.denied)                                           // "Stopped by you"
        assertEquals("", (items[4] as ThreadItem.Reply).text)                // no reply text under a system line
        assertEquals(6, (items[7] as ThreadItem.Reply).steps)
        assertTrue(items.last() is ThreadItem.Live)
        // The agent's question goes into the thread (blue); the phone's own approval never does.
        val q = ThreadMapper.map(HomeSamples.chat, true, emptyList(), task, "t4", HomeAsk.Question("Which one?"), utc, HomeSamples.NOW)
        assertTrue(q.last() is ThreadItem.Question)
        val a = ThreadMapper.map(HomeSamples.chat, true, emptyList(), task, "t4",
            HomeAsk.Approval(dev.openmob.companion.ui.state.PendingApproval("gk", "Buy?", "This phone"), 0), utc, HomeSamples.NOW)
        assertTrue(a.none { it is ThreadItem.Question } && a.last() is ThreadItem.Live)
    }

    @Test fun anOlderServerGetsOneThreadFromThePhonesOwnTaskLog() {
        val history = listOf(
            TaskLog.Record("b", "Turn on Wi-Fi", 2_000, 3_000, "done", steps = 2),
            TaskLog.Record("a", "Buy it", 1_000, 1_500, "stopped", stoppedByOwner = true),
        )
        val items = ThreadMapper.map(null, false, history, null, null, null, utc, 0)
        assertEquals(listOf("Day", "Request", "Reply", "System", "Request", "Reply"), items.map { it::class.simpleName })
        assertEquals("Turn on Wi-Fi", (items[4] as ThreadItem.Request).text)
    }

    @Test fun chatTitleSearchAndGroups() {
        val g = groupChats(HomeSamples.chatList, "", HomeSamples.NOW, utc)
        assertEquals(listOf(ChatGroup.Today, ChatGroup.Yesterday, ChatGroup.Week, ChatGroup.Older), g.map { it.first })
        assertEquals(listOf("c1", "c2"), g[0].second.map { it.id })
        // Titles only (owner): "settings" matches a title; a device name or text inside a chat never would.
        assertEquals(listOf("c2"), groupChats(HomeSamples.chatList, "SETTINGS", HomeSamples.NOW, utc).flatMap { it.second }.map { it.id })
        assertTrue(groupChats(HomeSamples.chatList, "Pixel", HomeSamples.NOW, utc).isEmpty())
    }

    // --- the 30-minute reopen and the chats state (pure) ----------------------------------------------------------

    @Test fun theLastChatReopensOnlyIfUsedInTheLast30Minutes() {
        assertFalse(Chats.shouldStartNew(1_000_000L, 1_000_000L + 29 * 60_000))
        assertTrue(Chats.shouldStartNew(1_000_000L, 1_000_000L + 31 * 60_000))
        assertTrue(Chats.shouldStartNew(null, 5))
        val now = 2_000_000_000_000L
        Chats.setForTest(true, "c1", emptyList(), null)
        val fresh = JSONObject("""{"type":"chats","offset":0,"current":"c1","chats":[{"id":"c1","title":"t","updated":${(now - 60_000) / 1000.0},"origin":"phone","this_phone":true}]}""")
        assertNull(Chats.onChats(fresh, now))                        // used a minute ago: reopened
        Chats.setForTest(true, "c1", emptyList(), null)
        val old = JSONObject("""{"type":"chats","offset":0,"current":"c1","chats":[{"id":"c1","title":"t","updated":${(now - 3_600_000) / 1000.0},"origin":"phone","this_phone":true}]}""")
        assertEquals("chat_new", Chats.onChats(old, now)?.optString("type")) // an hour ago: a new chat
        assertNull(Chats.onChats(old, now))                           // only once, at start
        Chats.reset()
    }

    @Test fun anOlderServerWithoutChatsAsksForNothing() {
        assertTrue(Chats.onWelcome(JSONObject("""{"type":"welcome","task_state":true}""")).isEmpty())
        assertFalse(Chats.supported)
        val sent = Chats.onWelcome(JSONObject("""{"type":"welcome","chats":true,"chat":"c9"}"""))
        assertEquals(listOf("chats_list", "chat_read"), sent.map { it.optString("type") })
        assertEquals("c9", Chats.current)
        Chats.reset()
    }

    // --- the pill, the status sheet and Reconnect -----------------------------------------------------------------

    @Test fun thePillReadsConnectedIssuesOrConnect() {
        assertEquals(PillState.Connected, HomeSamples.connected.pill)
        assertEquals(listOf(Issue.Notifications), HomeSamples.empty.issues)
        assertEquals(PillState.Disconnected, HomeSamples.disconnected.pill)
        rule.setContent { OpenMobTheme { HomeScreen(current.value, actions) } }
        current.value = HomeSamples.empty
        rule.onNodeWithTag(TAG_PILL).assert(hasText(s(R.string.rd_pill_connected) + " · 1 issue")).assertHeightIsAtLeast(48.dp)
        rule.onNodeWithTag(TAG_PILL).performClick()
        rule.onNode(hasText(s(R.string.rd_issue_notif))).assertIsDisplayed() // the sheet, issues first
        current.value = HomeSamples.disconnected
        rule.waitForIdle()
        rule.onNodeWithTag(TAG_PILL).assert(hasText(s(R.string.rd_pill_connect))).performClick()
        assertEquals(listOf("connect"), calls) // one tap, no screen lock
    }

    private val calls = mutableListOf<String>()
    private val current = mutableStateOf(HomeSamples.connected)
    private val actions = HomeActions(connect = { calls += "connect" }, disconnect = { calls += "disconnect" },
                                      fixIssue = { calls += "fix:$it" }, openRoute = { calls += "route:$it" })

    @Test fun theStatusSheetFixesIssuesAndDisconnectsWithTheSecondTap() {
        rule.setContent { OpenMobTheme { StatusSheetContent(HomeSamples.empty.copy(accessibilityOn = false), actions, {}) } }
        rule.onNode(hasText(s(R.string.rd_issue_a11y_fix))).performScrollTo().performClick()
        rule.onNode(hasText(s(R.string.rd_issue_notif_fix))).performScrollTo().performClick()
        assertEquals(listOf("fix:Accessibility", "fix:Notifications"), calls)
        rule.onNode(hasText("home-server.local")).performScrollTo().assertIsDisplayed() // the server, in mono
        rule.onNode(hasText(s(R.string.rd_status_disconnect_note))).performScrollTo().assertIsDisplayed()
        rule.onNodeWithTag(TAG_DISCONNECT).performScrollTo().assertHeightIsAtLeast(48.dp).performClick()
        assertEquals("disconnect", calls.last())
        rule.onNode(hasText(s(R.string.rd_home_never_types))).performScrollTo().assertIsDisplayed()
    }

    @Test fun reconnectOnlyReconnectsNoPermitComesBack() {
        val controls = FakeControls()
        val source = FakeSource(PhoneSnapshot(paired = true, accessibilityOn = true, running = true, connected = true))
        val vm = HomeViewModel(source, controls)
        vm.disconnect()
        assertTrue(vm.disconnectedBar.value)
        source.change(PhoneSnapshot(paired = true, accessibilityOn = true, running = false, connected = false))
        vm.connect()
        assertFalse(vm.disconnectedBar.value)
        // Reconnect is the saved pairing's connect, nothing else: no Faster mode, Don't ask or task grant call.
        assertEquals(listOf("disconnect", "connect"), controls.calls)
    }

    @Test fun theDisconnectedHomeDisablesTheComposerAndOffersReconnect() {
        val reconnects = mutableListOf<String>()
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.disconnected, HomeActions(connect = { reconnects += "c" }), disconnectedBar = true) } }
        rule.onNode(hasText(s(R.string.rd_offline_title))).assertIsDisplayed()
        rule.onNode(hasText(s(R.string.rd_composer_hint_offline))).assertIsDisplayed()
        rule.onNodeWithTag(dev.openmob.companion.ui.home.TAG_COMPOSER_SEND).assertIsNotEnabled()
        rule.onNodeWithTag(TAG_RECONNECT).assertHeightIsAtLeast(48.dp).performClick()
        assertEquals(listOf("c"), reconnects)
    }

    // --- the thread on screen -------------------------------------------------------------------------------------

    @Test fun theThreadShowsTheChatAndTheLiveStepIsALiveRegion() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.working, HomeActions()) } }
        rule.onNode(hasContentDescription(s(R.string.rd_thread_you, "Play some relaxed jazz"))).assertExists() // the newest in view
        val live = rule.onNodeWithTag(TAG_LIVE_STEP, useUnmergedTree = true).fetchSemanticsNode()
        assertEquals(androidx.compose.ui.semantics.LiveRegionMode.Polite, live.config.getOrNull(SemanticsProperties.LiveRegion))
        rule.onNode(hasText(s(R.string.rd_home_stop_task))).assertIsDisplayed().assertHeightIsAtLeast(48.dp) // by the composer
        rule.onNode(hasText(s(R.string.rd_composer_hint_working))).assertIsDisplayed()
    }

    @Test fun anEmptyChatIsCalm() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.empty, HomeActions()) } }
        rule.onNode(hasText(s(R.string.rd_empty_title))).assertIsDisplayed()
    }

    @Test fun theAgentsQuestionSwitchesTheComposerToAnAnswer() {
        val sent = mutableListOf<String>()
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.question, HomeActions(send = { sent += it; true })) } }
        rule.onNode(hasText(s(R.string.rd_thread_question_source))).assertExists()
        rule.onNode(hasText(s(R.string.rd_composer_hint_answer))).assertIsDisplayed()
        rule.onNodeWithTag(dev.openmob.companion.ui.home.TAG_COMPOSER_FIELD).performTextInput("the playlist")
        rule.onNode(hasText(s(R.string.rd_composer_send_answer))).performClick()
        assertEquals(listOf("the playlist"), sent)
    }

    @Test fun thePhonesOwnAskIsAboveTheComposerNotInTheThread() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.asking, HomeActions()) } }
        rule.onNode(hasText(s(R.string.rd_asking_band), substring = true)).assertIsDisplayed()
        rule.onNode(hasTestTag(TAG_THREAD)).assertExists()
        rule.onAllNodes(hasText(s(R.string.rd_asking_band), substring = true) and hasTestTag(TAG_THREAD)).assertCountEquals(0)
    }

    @Test fun longPressCopiesAReplyAndTalkBackOffersIt() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected, HomeActions()) } }
        val reply = HomeSamples.chat.turns[2].summary
        val node = rule.onNode(hasContentDescription(s(R.string.rd_thread_agent, reply)))
        val actionsList = node.fetchSemanticsNode().config.getOrNull(SemanticsActions.CustomActions).orEmpty()
        assertEquals(listOf(s(R.string.rd_thread_copy)), actionsList.map { it.label })
        node.performSemanticsAction(SemanticsActions.OnLongClick)
        assertEquals(reply, ctx.getSystemService(ClipboardManager::class.java).primaryClip?.getItemAt(0)?.text.toString())
    }

    @Test fun theModeChipIsReadOnlyAndSaysWhereToChangeIt() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected, HomeActions()) } }
        rule.onNodeWithTag(TAG_MODE_CHIP).assertHeightIsAtLeast(48.dp).performClick()
        rule.onNode(hasText(s(R.string.rd_mode_chip_hint))).assertIsDisplayed()
    }

    @Test fun jumpToLatestShowsWhenTheOwnerScrolledUpWhileWorking() {
        val long = HomeSamples.working.copy(thread = (1..30).map { ThreadItem.Request("r$it", "Request $it", 0) } +
            ThreadItem.Live("live", HomeSamples.working.task!!))
        rule.setContent { OpenMobTheme { HomeScreen(long, HomeActions()) } }
        rule.waitForIdle()
        rule.onAllNodes(hasTestTag(TAG_JUMP)).assertCountEquals(0) // following the newest
        rule.onNodeWithTag(TAG_THREAD).performTouchInput { swipeDown() }
        rule.waitForIdle()
        rule.onNodeWithTag(TAG_JUMP).assertIsDisplayed().assertHeightIsAtLeast(48.dp).performClick()
        rule.waitForIdle()
        rule.onAllNodes(hasTestTag(TAG_JUMP)).assertCountEquals(0)
    }

    // --- the drawer -----------------------------------------------------------------------------------------------

    @Test fun theDrawerListsChatsGroupedWithTheCurrentMarkedAndOpensThem() {
        val opened = mutableListOf<String>()
        val routes = mutableListOf<Route>()
        var newChats = 0
        rule.setContent {
            OpenMobTheme {
                HomeScreen(HomeSamples.connected, HomeActions(openChat = { opened += it }, newChat = { newChats++ }, openRoute = { routes += it }),
                           drawerState = rememberDrawerState(DrawerValue.Open))
            }
        }
        val drawer = rule.onNodeWithTag(TAG_DRAWER).fetchSemanticsNode()
        assertEquals(s(R.string.rd_menu), drawer.config.getOrNull(SemanticsProperties.PaneTitle)) // the nav landmark
        rule.onNode(hasText("From the dashboard", substring = true)).assertExists() // "From the dashboard"
        rule.onNodeWithTag("chat-c1").assert(SemanticsMatcher.expectValue(SemanticsProperties.Selected, true))
            .assertHeightIsAtLeast(48.dp)
        rule.onNodeWithTag("chat-c3").performSemanticsAction(SemanticsActions.OnClick)
        assertEquals(listOf("c3"), opened)
        rule.onNodeWithTag(TAG_MENU_BUTTON).performClick()
        rule.waitForIdle()
        rule.onNodeWithTag(TAG_NEW_CHAT).performSemanticsAction(SemanticsActions.OnClick)
        assertEquals(1, newChats)
        rule.onNodeWithTag(TAG_MENU_BUTTON).performClick()
        rule.waitForIdle()
        // Places first (Settings is the first row), then the chats.
        val places = DRAWER_PLACES.map { rule.onNodeWithTag("drawer-${it.name}").assertHeightIsAtLeast(48.dp).fetchSemanticsNode().boundsInRoot.top }
        assertEquals(places.sorted(), places)
        assertTrue(places.last() < rule.onNodeWithTag("chat-c1").fetchSemanticsNode().boundsInRoot.top)
        rule.onNodeWithTag("drawer-${Route.Settings.name}").performSemanticsAction(SemanticsActions.OnClick)
        assertEquals(listOf(Route.Settings), routes)
        rule.onNodeWithTag(TAG_MENU_BUTTON).performClick()
        rule.waitForIdle()
        // Search is an icon that opens the field; titles only; closing shows everything again.
        rule.onAllNodes(hasTestTag(TAG_CHAT_SEARCH)).assertCountEquals(0)
        rule.onNodeWithTag(TAG_SEARCH_OPEN).assert(hasContentDescription(s(R.string.rd_drawer_search))).assertHeightIsAtLeast(48.dp)
            .performSemanticsAction(SemanticsActions.OnClick)
        rule.onNodeWithTag(TAG_CHAT_SEARCH).performTextInput("chess")
        rule.onAllNodes(hasTestTag("chat-c1")).assertCountEquals(0)
        rule.onNodeWithTag("chat-c3").assertExists()
        rule.onNodeWithTag(TAG_SEARCH_CLOSE).performSemanticsAction(SemanticsActions.OnClick)
        rule.onNodeWithTag("chat-c1").assertExists()
        // The avatar shows the account and server, read only; New chat and the avatar are 48 dp.
        rule.onNodeWithTag(TAG_NEW_CHAT).assertHeightIsAtLeast(48.dp)
        rule.onNodeWithTag(TAG_AVATAR).assertHeightIsAtLeast(48.dp).performSemanticsAction(SemanticsActions.OnClick)
        rule.onNode(hasText("home-server.local")).assertIsDisplayed()
        rule.onAllNodes(hasText(s(R.string.rd_home_disconnect))).assertCountEquals(0) // no Disconnect in the drawer
    }

    @Test fun theMapperBuildsTheThreadFromTheChatAndTheMenuHidesOnBack() {
        val snap = PhoneSnapshot(paired = true, accessibilityOn = true, running = true, connected = true, chatsSupported = true,
                                 currentChat = "c1", chatThread = HomeSamples.chat, chatList = HomeSamples.chatList)
        val home = HomeMapper.map(snap, HomeSamples.NOW)
        assertEquals(HomeStatus.Connected, home.status)
        assertEquals("Coffee, shopping, Chrome", home.chatTitle)
        assertTrue(home.thread.any { it is ThreadItem.Reply })
        rule.setContent { OpenMobTheme { HomeScreen(home, HomeActions()) } }
        rule.onNodeWithTag(TAG_MENU_BUTTON).performClick()
        rule.waitForIdle()
        rule.onNodeWithTag(TAG_DRAWER).assertIsDisplayed()
        androidx.test.espresso.Espresso.pressBack()
        rule.waitForIdle()
        rule.onAllNodes(hasTestTag(TAG_DRAWER)).assertCountEquals(0)
    }

    @Test fun theDisconnectedHomeShowsNoThread() {
        val snap = PhoneSnapshot(paired = true, accessibilityOn = true, running = false, connected = false, chatsSupported = true,
                                 chatThread = HomeSamples.chat)
        assertTrue(HomeMapper.map(snap, HomeSamples.NOW).thread.isEmpty())
        @Suppress("UNUSED_VARIABLE") val unused = AppState
    }
}
