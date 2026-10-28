package dev.openmob.companion.ui

import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import dev.openmob.companion.Chats
import dev.openmob.companion.MemoryNotes.Note
import dev.openmob.companion.ui.home.HomeActions
import dev.openmob.companion.ui.home.HomeSamples
import dev.openmob.companion.ui.home.HomeScreen
import dev.openmob.companion.ui.home.ThreadMapper
import dev.openmob.companion.ui.settings.MemoryActions
import dev.openmob.companion.ui.settings.MemoryPage
import dev.openmob.companion.ui.settings.MemoryUiState
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.json.JSONObject
import java.time.ZoneOffset
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Security review 5 P5-L4: "What OpenMob remembers" is kept out of screenshots, the live view and Faster mode's
 *  frames (FLAG_SECURE) while it shows, and only then. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w390dp-h1000dp-xhdpi")
class Review5UiTest {
    val rule = createAndroidComposeRule<ComponentActivity>()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)

    private fun secure() = rule.activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0

    @Test fun theMemoryPageIsSecureWhileShown() {
        val shown = mutableStateOf(true)
        val state = MemoryUiState(aboutYou = listOf(Note("n1", "about_you", "My favorite soda is Diet Coke", "active")),
                                  available = true, loaded = true)
        rule.setContent { OpenMobTheme { if (shown.value) MemoryPage(state, MemoryActions()) } }
        rule.waitForIdle()
        assertTrue(secure())
        shown.value = false
        rule.waitForIdle()
        assertFalse(secure())
    }

    private fun chat(extra: String) = Chats.parseThread(JSONObject("""{"chat_id":"c1","title":"t","turns":[
        {"id":"t1","request":"remember","started":1.0,"finished":9.0,"outcome":"done","summary":"ok","steps":1,
         "step_lines":[],"asks":0,"denied":false,"stopped_by_owner":false,"question":"","messages":[]$extra}]}"""))!!

    private fun showHome(extra: String) = rule.setContent {
        OpenMobTheme {
            HomeScreen(HomeSamples.connected.copy(thread = ThreadMapper.map(chat(extra), true, emptyList(), null, null, null,
                ZoneOffset.UTC, 0)), HomeActions())
        }
    }

    @Test fun homeIsSecureWhileAProposalCardShows() {
        showHome(""","memory_cards":[{"note_id":"n1","text":"Save this? Likes tea","status":"proposed"}]""")
        rule.onNode(androidx.compose.ui.test.hasText("Save this? Likes tea")).assertExists()
        assertTrue(secure())
    }

    @Test fun homeIsSecureWhileAUsedPreferencesLineShows() {
        showHome(""","memory":["Used your preferences: Diet Coke"]""")
        rule.onNode(androidx.compose.ui.test.hasText("Used your preferences: Diet Coke")).assertExists()
        assertTrue(secure())
    }

    @Test fun homeWithoutMemoryIsNotSecure() {
        showHome("")
        rule.waitForIdle()
        assertFalse(secure())
    }
}
