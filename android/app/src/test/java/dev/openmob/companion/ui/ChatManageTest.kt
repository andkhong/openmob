package dev.openmob.companion.ui

import android.content.Context
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.rememberDrawerState
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.Chats
import dev.openmob.companion.R
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.TAG_CHAT_MENU_DELETE
import dev.openmob.companion.ui.home.TAG_CHAT_MENU_RENAME
import dev.openmob.companion.ui.home.TAG_CHAT_TITLE
import dev.openmob.companion.ui.home.TAG_DELETE_CONFIRM
import dev.openmob.companion.ui.home.TAG_PILL
import dev.openmob.companion.ui.home.TAG_RENAME_FIELD
import dev.openmob.companion.ui.home.TAG_RENAME_SAVE
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Home's decluttered header, and renaming or deleting a chat from the drawer (owner, 2026-10-17). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h1000dp-xhdpi")
class ChatManageTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int, vararg a: Any) = ctx.getString(id, *a)

    @Test fun theHeaderIsMenuTitleAndPillWithNoBrand() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.connected, HomeActions()) } }
        rule.onNodeWithTag(TAG_CHAT_TITLE).assert(hasText("Coffee, shopping, Chrome")).assertIsDisplayed()
        rule.onAllNodes(hasText(s(R.string.rd_home_title))).assertCountEquals(0) // no "OpenMob" on Home
        rule.onNodeWithTag(TAG_PILL).assertIsDisplayed()
    }

    @Test fun aNewChatIsTitledNewChat() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.empty, HomeActions()) } }
        rule.onNodeWithTag(TAG_CHAT_TITLE).assert(hasText(s(R.string.rd_drawer_new_chat)))
    }

    @Test fun longPressOffersRenameAndDeleteAndTalkBackToo() {
        val renamed = mutableListOf<Pair<String, String>>()
        val deleted = mutableListOf<String>()
        rule.setContent {
            OpenMobTheme {
                // The rename dialog's content drawn inline: Robolectric never idles a text field in a dialog window.
                androidx.compose.runtime.CompositionLocalProvider(dev.openmob.companion.ui.home.LocalRenameInDialog provides false) {
                    HomeScreen(HomeSamples.connected, HomeActions(renameChat = { id, t -> renamed += id to t }, deleteChat = { deleted += it }),
                               drawerState = rememberDrawerState(DrawerValue.Open))
                }
            }
        }
        val row = rule.onNodeWithTag("chat-c3")
        val labels = row.fetchSemanticsNode().config.getOrNull(SemanticsActions.CustomActions).orEmpty().map { it.label }
        assertEquals(listOf(s(R.string.rd_chat_rename), s(R.string.rd_chat_delete)), labels)
        row.performSemanticsAction(SemanticsActions.OnLongClick)
        rule.onNodeWithTag(TAG_CHAT_MENU_RENAME).assertHeightIsAtLeast(48.dp).performClick()
        // Rename: prefilled, single line; Save off while empty.
        rule.onNodeWithTag(TAG_RENAME_FIELD).assert(hasText("Install a chess app and play 5 moves")).performTextClearance()
        rule.onNodeWithTag(TAG_RENAME_SAVE).assertIsNotEnabled()
        rule.onNodeWithTag(TAG_RENAME_FIELD).performTextInput("Chess")
        rule.onNodeWithTag(TAG_RENAME_SAVE).assertIsEnabled().performClick()
        assertEquals(listOf("c3" to "Chess"), renamed)
        // Delete: through its confirmation, then a second action sends it.
        rule.onNodeWithTag("chat-c3").performSemanticsAction(SemanticsActions.OnLongClick)
        rule.onNodeWithTag(TAG_CHAT_MENU_DELETE).performClick()
        rule.onNode(hasText(s(R.string.rd_chat_delete_title))).assertIsDisplayed()
        rule.onNode(hasText(s(R.string.rd_chat_delete_body))).assertIsDisplayed()
        assertTrue(deleted.isEmpty())
        rule.onNodeWithTag(TAG_DELETE_CONFIRM).assertHeightIsAtLeast(48.dp).performClick()
        assertEquals(listOf("c3"), deleted)
        // TalkBack's action opens the same confirmation.
        val del = rule.onNodeWithTag("chat-c1").fetchSemanticsNode().config.getOrNull(SemanticsActions.CustomActions)!!
            .first { it.label == s(R.string.rd_chat_delete) }
        rule.runOnUiThread { del.action() }
        rule.onNode(hasText(s(R.string.rd_chat_delete_title))).assertIsDisplayed()
    }

    @Test fun deletingTheShownChatMakesHomeANewChatAndRenamesFollow() {
        Chats.setForTest(true, "c1", HomeSamples.chatList, HomeSamples.chat)
        Chats.onRenamed(JSONObject("""{"type":"chat_renamed","ok":true,"chat_id":"c1","title":"Renamed"}"""))
        assertEquals("Renamed", Chats.list.first { it.id == "c1" }.title)
        assertEquals("Renamed", Chats.thread?.title)
        Chats.onDeleted(JSONObject("""{"type":"chat_deleted","ok":true,"chat_id":"c1"}"""))
        assertNull(Chats.current); assertNull(Chats.thread)
        assertTrue(Chats.list.none { it.id == "c1" })
        Chats.onDeleted(JSONObject("""{"type":"chat_deleted","ok":false,"chat_id":"c2","error":"busy"}"""))
        assertEquals(R.string.rd_chat_busy, Chats.notice)
        assertEquals("chat_rename", Chats.renameRequest("c2", "  x ").optString("type"))
        assertEquals("x", Chats.renameRequest("c2", "  x ").optString("title"))
        Chats.reset()
    }

    @Test fun aChatAlreadyGoneOnTheServerLeavesTheListAndTheListReloads() {
        // Deleted on the web while this phone still listed it: deleting it here answers "unknown".
        Chats.setForTest(true, "c1", HomeSamples.chatList, HomeSamples.chat)
        Chats.clearNotice()
        val reload = Chats.onDeleted(JSONObject("""{"type":"chat_deleted","ok":false,"chat_id":"c1","error":"unknown"}"""))
        assertEquals("chats_list", reload?.optString("type"))
        assertTrue(Chats.list.none { it.id == "c1" })
        assertNull(Chats.current); assertNull(Chats.thread)
        assertNull(Chats.notice) // what was asked happened: no error
        // Renaming or opening one that is gone also drops it, says so, and reloads.
        val other = HomeSamples.chatList.first { it.id != "c1" }.id
        assertEquals("chats_list", Chats.onRenamed(JSONObject("""{"type":"chat_renamed","ok":false,"chat_id":"$other","error":"unknown"}"""))?.optString("type"))
        assertTrue(Chats.list.none { it.id == other })
        assertEquals(R.string.rd_chat_unknown, Chats.notice)
        Chats.reset()
    }
}

/** The header at twice the text size on a small phone: the title gives way first, the pill stays. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w360dp-h740dp-xhdpi", fontScale = 2.0f)
class ChatHeaderFontScaleTest {
    val rule = createComposeRule()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()

    @Test fun thePillStaysReadableAndKeepsItsFullDescription() {
        rule.setContent { OpenMobTheme { HomeScreen(HomeSamples.empty, HomeActions()) } }
        val pill = rule.onNodeWithTag(TAG_PILL).assertIsDisplayed().assertHeightIsAtLeast(48.dp)
        pill.assert(hasContentDescription(ctx.getString(R.string.rd_pill_connected) + " · 1 issue", substring = true))
        val b = pill.fetchSemanticsNode().boundsInRoot
        val root = rule.onNodeWithTag(TAG_CHAT_TITLE).fetchSemanticsNode().layoutInfo.coordinates.parentLayoutCoordinates
        assertTrue(b.right <= with(rule.density) { 360.dp.toPx() } + 1)
        assertTrue(root != null)
        @Suppress("UNUSED_VARIABLE") val unused = SemanticsProperties.Text
    }
}
