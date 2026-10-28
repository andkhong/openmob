package dev.openmob.companion.ui

import android.content.Context
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.AppState
import dev.openmob.companion.Chats
import dev.openmob.companion.MemoryNotes
import dev.openmob.companion.R
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeMapper
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.ThreadItem
import dev.openmob.companion.ui.home.ThreadMapper
import dev.openmob.companion.ui.home.threadMemoryDismissTag
import dev.openmob.companion.ui.home.threadMemorySaveTag
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.ZoneOffset

/** Task 8: the proposal card and the "Used your preferences" line in the phone's chat (docs/phone-protocol.md §3.6). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h1000dp-xhdpi")
class MemoryThreadTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()

    private fun chat(vararg extra: String): Chats.Thread = Chats.parseThread(JSONObject("""{"chat_id":"c1","title":"t","turns":[
        {"id":"t1","request":"remember","started":1.0,"finished":9.0,"outcome":"done","summary":"ok","steps":1,
         "step_lines":[],"asks":0,"denied":false,"stopped_by_owner":false,"question":"","messages":[]
         ${extra.joinToString("") { ",$it" }}}]}"""))!!

    private fun items(t: Chats.Thread) = ThreadMapper.map(t, true, emptyList(), null, null, null, ZoneOffset.UTC, 0)

    private fun show(t: Chats.Thread, actions: HomeActions = HomeActions()) =
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected.copy(thread = items(t)), actions) } }

    @Test fun theThreadParsesCardsAndUsedLines() {
        val t = chat(""""memory":["Used your preferences: Likes tea"]""",
                     """"memory_cards":[{"note_id":"n1","text":"Save this? Likes tea","status":"proposed"}]""")
        val turn = t.turns.single()
        assertEquals(listOf("Used your preferences: Likes tea"), turn.memoryLines)
        assertEquals(Chats.MemoryCard("n1", "Save this? Likes tea", "proposed"), turn.memoryCards.single())
        val it = items(t)
        assertTrue(it.any { x -> x is ThreadItem.MemoryLine && x.text.startsWith("Used your preferences") })
        assertTrue(it.any { x -> x is ThreadItem.MemoryCard && x.noteId == "n1" })
        assertTrue(Chats.parseThread(JSONObject("""{"chat_id":"c","turns":[{"id":"t"}]}"""))!!.turns.single().memoryCards.isEmpty())
    }

    @Test fun aProposedCardShowsTheTextAndSaveSendsConfirmNotNowSendsDismiss() {
        val sent = ArrayList<String>()
        show(chat(""""memory_cards":[{"note_id":"n1","text":"Save this? your sis = Maya Lee — likes voice notes","status":"proposed"}]"""),
             HomeActions(memoryConfirm = { sent += "c:$it" }, memoryDismiss = { sent += "d:$it" }))
        rule.onAllNodes(hasText("Save this? your sis = Maya Lee — likes voice notes")).assertCountEquals(1)
        rule.onNodeWithTag(threadMemorySaveTag("n1")).performClick()
        rule.onNodeWithTag(threadMemoryDismissTag("n1")).performClick()
        assertEquals(listOf("c:n1", "d:n1"), sent)
        assertEquals("memory_confirm", MemoryNotes.confirmRequest("n1").optString("type"))
        assertEquals("memory_dismiss", MemoryNotes.dismissRequest("n1").optString("type"))
    }

    @Test fun aCardShowsWhereTheSuggestionCameFrom() {  // review 5 M5-L3
        val t = chat(""""memory_cards":[{"note_id":"n1","text":"Save this? Likes tea","status":"proposed","origin":"Suggested from what the agent saw on screen"}]""")
        assertEquals("Suggested from what the agent saw on screen", t.turns.single().memoryCards.single().origin)
        show(t)
        rule.onAllNodes(hasText("Suggested from what the agent saw on screen")).assertCountEquals(1)
    }

    @Test fun savedDeletedAndUntrustedCardsHaveNoButtons() {
        show(chat(""""memory_cards":[
            {"note_id":"a","text":"Save this? Likes tea","status":"active"},
            {"note_id":"b","text":"a deleted preference","status":"gone"},
            {"note_id":"c","text":"a saved preference","status":"gone"},
            {"note_id":"d","text":"Saved: Likes coffee","status":"active"}]"""))
        rule.onAllNodes(hasTestTag(threadMemorySaveTag("a"))).assertCountEquals(0)
        rule.onAllNodes(hasTestTag(threadMemorySaveTag("b"))).assertCountEquals(0)
        rule.onAllNodes(hasTestTag(threadMemoryDismissTag("c"))).assertCountEquals(0)
        rule.onAllNodes(hasText("a deleted preference")).assertCountEquals(1)
        rule.onAllNodes(hasText("a saved preference")).assertCountEquals(1)
        rule.onAllNodes(hasText(ctx.getString(R.string.rd_memory_saved))).assertCountEquals(1) // the older wording only
        rule.onAllNodes(hasText("Saved: Likes coffee")).assertCountEquals(1)
        rule.onAllNodes(hasTestTag(threadMemorySaveTag("d"))).assertCountEquals(0)
    }

    @Test fun theUsedLineShowsSmall() {
        show(chat(""""memory":["Used your preferences: Likes tea","Sending to Maya Lee — your sis, from your saved preferences"]"""))
        rule.onAllNodes(hasText("Used your preferences: Likes tea")).assertCountEquals(1)
        rule.onAllNodes(hasText("Sending to Maya Lee — your sis, from your saved preferences")).assertCountEquals(1)
    }

    // --- the live line (final fix wave I1): pushed rendered by the server, shown before the chat is read ---------

    @Test fun aLiveMemoryEventShowsTheLineInTheRunningTask() {
        val now = 1_000_000L
        val events = listOf( // newest first, as AppState keeps them
            AppState.Event("action", "tap: Tapped “Send”", now + 30),
            AppState.Event("memory", "Sending to Maya Lee — your sis, from your saved preferences", now + 20),
            AppState.Event("memory", "Used your preferences: Likes tea", now + 10),
            AppState.Event("status", "Working on: text my sis", now),
        )
        val progress = HomeMapper.map(dev.openmob.companion.ui.state.PhoneSnapshot(paired = true, accessibilityOn = true, running = true,
            connected = true, events = events), now + 40).task!!
        assertEquals(listOf("Used your preferences: Likes tea", "Sending to Maya Lee — your sis, from your saved preferences"),
                     progress.memoryLines)
        val thread = ThreadMapper.map(null, true, emptyList(), progress, "t9", null, ZoneOffset.UTC, now)
        val lines = thread.filterIsInstance<ThreadItem.MemoryLine>().map { it.text }
        assertEquals(progress.memoryLines, lines)
        assertTrue(thread.indexOfFirst { it is ThreadItem.MemoryLine } < thread.indexOfFirst { it is ThreadItem.Live })
        // The chat (read mid-task) already has a line: it isn't shown twice.
        val chat = chat(""""memory":["Used your preferences: Likes tea"]""").let { t ->
            t.copy(turns = t.turns.map { it.copy(id = "t9", outcome = "running") })
        }
        val both = ThreadMapper.map(chat, true, emptyList(), progress, "t9", null, ZoneOffset.UTC, now)
        assertEquals(1, both.count { it is ThreadItem.MemoryLine && it.text == "Used your preferences: Likes tea" })
    }

    @Test fun anEmptyMessageEventAddsNothingToTheFeedOrActivity() {
        val before = AppState.events().size
        AppState.addEvent("memory", "")
        AppState.addEvent("status", "   ")
        assertEquals(before, AppState.events().size)
        AppState.addEvent("memory", "Used your preferences: a saved preference")
        assertEquals(before + 1, AppState.events().size)
        assertEquals("Used your preferences: a saved preference", AppState.events().first().message)
    }
}
