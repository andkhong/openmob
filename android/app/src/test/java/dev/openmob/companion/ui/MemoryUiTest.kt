package dev.openmob.companion.ui

import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isHeading
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.MemoryNotes
import dev.openmob.companion.MemoryNotes.Note
import dev.openmob.companion.R
import dev.openmob.companion.ui.nav.OpenMobNavHost
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.settings.EditNoteContent
import dev.openmob.companion.ui.settings.MemoryActions
import dev.openmob.companion.ui.settings.MemoryContent
import dev.openmob.companion.ui.settings.MemorySource
import dev.openmob.companion.ui.settings.MemoryUiState
import dev.openmob.companion.ui.settings.MemoryViewModel
import dev.openmob.companion.ui.settings.TAG_BLOCKED_ROW
import dev.openmob.companion.ui.settings.TAG_MEMORY_ABOUT
import dev.openmob.companion.ui.settings.TAG_MEMORY_APPS
import dev.openmob.companion.ui.settings.TAG_MEMORY_EDIT_CONTACT
import dev.openmob.companion.ui.settings.TAG_MEMORY_EDIT_FIELD
import dev.openmob.companion.ui.settings.TAG_MEMORY_EDIT_SAVE
import dev.openmob.companion.ui.settings.TAG_MEMORY_EMPTY
import dev.openmob.companion.ui.settings.TAG_MEMORY_PEOPLE
import dev.openmob.companion.ui.settings.TAG_MEMORY_ROW
import dev.openmob.companion.ui.settings.TAG_MEMORY_WAITING
import dev.openmob.companion.ui.settings.memoryDeleteTag
import dev.openmob.companion.ui.settings.memoryDismissTag
import dev.openmob.companion.ui.settings.memoryMenuTag
import dev.openmob.companion.ui.settings.memorySaveTag
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The "What OpenMob remembers" page (spec §5.5, docs/phone-protocol.md §3.9): a Settings row only when the server
 *  allows it, its own page with Waiting for you, About you, People and Apps in that order, Save / Dismiss, edit, delete. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class MemoryUiTest {
    val rule = createAndroidComposeRule<ComponentActivity>()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()

    @After fun clear() = MemoryNotes.reset()

    private val soda = Note("n1", "about_you", "My favorite soda is Diet Coke", "active")
    private val wife = Note("n2", "person", "texts after nine", "active", relation = "wife", contactName = "Sam")
    private val amazon = Note("n3", "app", "Use the second account", "active", pkg = "com.amazon.mShop.android.shopping")
    private val idea = Note("p1", "about_you", "Prefers the app over the browser", "proposed")
    private val sis = Note("p2", "person", "birthday is May 3", "proposed", relation = "sis", contactName = "Maya")

    private fun full() = MemoryUiState(proposed = listOf(idea, sis), aboutYou = listOf(soda), people = listOf(wife),
                                       apps = mapOf(amazon.pkg!! to listOf(amazon)), available = true, loaded = true)

    private fun welcome(memory: Boolean) = MemoryNotes.onWelcome(JSONObject().put("type", "welcome").put("memory", memory))

    private class Fake(var notes: List<Note>, var proposed: List<Note>) : MemorySource {
        val confirmed = mutableListOf<String>()
        val dismissed = mutableListOf<String>()
        val deleted = mutableListOf<String>()
        val edits = mutableListOf<Triple<String, String?, String?>>()
        var refreshes = 0
        private var listener: () -> Unit = {}
        override fun available() = true
        override fun loaded() = true
        override fun notes() = notes
        override fun proposed() = proposed
        override fun error(): String? = null
        override fun refresh(): Boolean { refreshes++; return true }
        override fun edit(id: String, text: String?, contactName: String?): Boolean { edits += Triple(id, text, contactName); return true }
        override fun delete(id: String): Boolean { deleted += id; notes = notes.filter { it.id != id }; listener(); return true }
        override fun confirm(id: String): Boolean {
            confirmed += id
            notes = notes + proposed.filter { it.id == id }.map { it.copy(status = "active") }
            proposed = proposed.filter { it.id != id }; listener(); return true
        }
        override fun dismiss(id: String): Boolean { dismissed += id; proposed = proposed.filter { it.id != id }; listener(); return true }
        override fun listen(listener: () -> Unit): () -> Unit { this.listener = listener; return { this.listener = {} } }
    }

    private fun show(vm: MemoryViewModel) {
        rule.setContent {
            OpenMobTheme {
                val state by vm.state.collectAsState()
                MemoryContent(state, MemoryActions(save = { vm.save(it) }, dismiss = { vm.dismiss(it) },
                                                   delete = { vm.delete(it) }, edit = { n, t, c -> vm.edit(n, t, c) }))
            }
        }
    }

    @Test fun settingsRowOpensThePageAndBackReturns() {
        welcome(true)
        MemoryNotes.onMemory(JSONObject("""{"type":"memory","notes":[{"id":"n1","kind":"about_you","text":"My favorite soda is Diet Coke","status":"active"}],"proposed":[]}"""))
        rule.setContent { OpenMobTheme { OpenMobNavHost(startRoute = Route.Settings) } }
        rule.onNode(hasText(ctx.getString(R.string.rd_settings_title)) and isHeading()).assertExists()
        rule.onAllNodes(hasText("My favorite soda is Diet Coke")).assertCountEquals(0) // Settings holds only the row
        rule.onNodeWithTag(TAG_MEMORY_ROW).performScrollTo().performClick()
        rule.onNode(hasText("What OpenMob remembers") and isHeading()).assertExists()
        rule.onAllNodes(hasText("My favorite soda is Diet Coke")).assertCountEquals(1)
        rule.onNodeWithContentDescription(ctx.getString(R.string.rd_back)).performClick()
        rule.onNode(hasText(ctx.getString(R.string.rd_settings_title)) and isHeading()).assertExists()
    }

    @Test fun theRowIsHiddenUnlessTheWelcomeSaysMemory() {
        welcome(false)
        rule.setContent { OpenMobTheme { OpenMobNavHost(startRoute = Route.Settings) } }
        rule.onNodeWithTag(TAG_BLOCKED_ROW).assertExists()
        rule.onAllNodes(hasText("What OpenMob remembers")).assertCountEquals(0)
        rule.runOnIdle { welcome(true) }
        rule.onNodeWithTag(TAG_MEMORY_ROW).assertExists()
        // The server says this phone isn't trusted any more (or memory is off): the row goes.
        rule.runOnIdle { MemoryNotes.onMemory(JSONObject("""{"type":"memory","denied":true}""")) }
        rule.onAllNodes(hasText("What OpenMob remembers")).assertCountEquals(0)
    }

    @Test fun sectionsComeInOrderWithPersonCards() {
        rule.setContent { OpenMobTheme { MemoryContent(full(), MemoryActions()) } }
        val y = listOf(TAG_MEMORY_WAITING, TAG_MEMORY_ABOUT, TAG_MEMORY_PEOPLE, TAG_MEMORY_APPS)
            .map { rule.onNodeWithTag(it).fetchSemanticsNode().positionInRoot.y }
        assertEquals(y.sorted(), y)
        for (title in listOf("Waiting for you", "About you", "People", "Apps")) rule.onNode(hasText(title) and isHeading()).assertExists()
        rule.onAllNodes(hasText("Save this? Prefers the app over the browser")).assertCountEquals(1)
        rule.onAllNodes(hasText("Save this? your sis = Maya — birthday is May 3")).assertCountEquals(1)
        rule.onAllNodes(hasText("your wife = Sam")).assertCountEquals(1) // a person card shows relation and contact
        rule.onAllNodes(hasText("texts after nine")).assertCountEquals(1)
        rule.onAllNodes(hasText(amazon.pkg!!)).assertCountEquals(1) // the app's name (here: not installed, its package)
        rule.onAllNodes(hasText("Use the second account")).assertCountEquals(1)
        rule.onAllNodes(hasText("Save")).assertCountEquals(2)
        rule.onAllNodes(hasText("Dismiss")).assertCountEquals(2)
    }

    @Test fun saveAndDismissGoToTheServerAndTheCardsLeave() {
        val fake = Fake(listOf(soda), listOf(idea, sis))
        show(MemoryViewModel(fake))
        rule.onNodeWithTag(memorySaveTag(idea.id)).performClick()
        rule.waitForIdle()
        assertEquals(listOf(idea.id), fake.confirmed)
        rule.onAllNodes(hasText("Save this? Prefers the app over the browser")).assertCountEquals(0)
        rule.onAllNodes(hasText("Prefers the app over the browser")).assertCountEquals(1) // now under About you
        rule.onNodeWithTag(memoryDismissTag(sis.id)).performClick()
        rule.waitForIdle()
        assertEquals(listOf(sis.id), fake.dismissed)
        rule.onAllNodes(hasText("Waiting for you")).assertCountEquals(0)
    }

    @Test fun theMenuDeletesANote() {
        val fake = Fake(listOf(soda, wife), emptyList())
        show(MemoryViewModel(fake))
        rule.onNodeWithTag(memoryMenuTag(soda.id)).performClick()
        rule.onNodeWithTag(memoryDeleteTag(soda.id)).performClick()
        rule.waitForIdle()
        assertEquals(listOf(soda.id), fake.deleted)
        rule.onAllNodes(hasText(soda.text)).assertCountEquals(0)
    }

    @Test fun editingSendsOnlyWhatChanged() {
        val fake = Fake(listOf(soda, wife), emptyList())
        val vm = MemoryViewModel(fake)
        var saved: Pair<String, String?>? = null
        rule.setContent { OpenMobTheme { EditNoteContent(wife, onSave = { t, c -> saved = t to c }, onCancel = {}) } }
        rule.onNodeWithTag(TAG_MEMORY_EDIT_CONTACT).performTextReplacement("Sam K")
        rule.onNodeWithTag(TAG_MEMORY_EDIT_SAVE).performClick()
        assertEquals("texts after nine" to "Sam K", saved)
        vm.edit(wife, saved!!.first, saved!!.second)
        vm.edit(soda, "My favorite soda is Coke Zero", null)
        assertEquals(listOf(Triple(wife.id, null, "Sam K"), Triple(soda.id, "My favorite soda is Coke Zero", null)), fake.edits)
        // Nothing changed: nothing is sent (no write, no audit row on the server).
        assertEquals(false, vm.edit(soda, soda.text, null))
        assertEquals(false, vm.edit(wife, wife.text, wife.contactName))
        assertEquals(2, fake.edits.size)
    }

    @Test fun anEmptyTextCannotBeSaved() {
        var saved = false
        rule.setContent { OpenMobTheme { EditNoteContent(soda, onSave = { _, _ -> saved = true }, onCancel = {}) } }
        rule.onNodeWithTag(TAG_MEMORY_EDIT_FIELD).performTextReplacement("  ")
        rule.onNodeWithTag(TAG_MEMORY_EDIT_SAVE).performClick()
        assertTrue(!saved)
    }

    @Test fun nothingSavedExplainsHowToAddOne() {
        rule.setContent { OpenMobTheme { MemoryContent(MemoryUiState(available = true, loaded = true), MemoryActions()) } }
        rule.onNodeWithTag(TAG_MEMORY_EMPTY).assertExists()
        rule.onAllNodes(hasText("Say 'remember …' in a chat", substring = true)).assertCountEquals(1)
        rule.onAllNodes(hasText("Waiting for you")).assertCountEquals(0)
    }

    @Test fun thePageAsksForTheNotesWhenItShows() {
        val fake = Fake(emptyList(), emptyList())
        MemoryViewModel(fake).load()
        assertEquals(1, fake.refreshes)
    }
}
