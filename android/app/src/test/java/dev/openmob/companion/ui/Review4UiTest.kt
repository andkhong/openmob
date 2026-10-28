package dev.openmob.companion.ui

import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ApplicationInfo
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.compose.material3.Text
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.ConnectionService
import dev.openmob.companion.ConnectionService.Companion.Rejection
import dev.openmob.companion.R
import dev.openmob.companion.ui.home.QuestionCard
import dev.openmob.companion.ui.setup.SecureWhileShown
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Security review 4 and the 2026-10-18 cleanup review, on the phone's screens: the "never type passwords" line (L10),
 *  FLAG_SECURE behind a ContextWrapper, and a late 4401 after pairing again. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class Review4UiTest {
    val rule = createAndroidComposeRule<ComponentActivity>()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private fun s(id: Int) = ctx.getString(id)
    private fun secure() = rule.activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0

    // --- L10 ----------------------------------------------------------------------------------------------------

    @Test fun anOpenQuestionSaysNeverTypePasswordsHere() {
        rule.setContent { OpenMobTheme { QuestionCard("Type your bank password to continue") } }
        rule.onAllNodes(hasText(s(R.string.rd_thread_no_secrets), substring = true)).assertCountEquals(1)
    }

    @Test fun anAnsweredQuestionDoesNot() {
        rule.setContent { OpenMobTheme { QuestionCard("Which one?", readOnly = true) } }
        rule.onAllNodes(hasText(s(R.string.rd_thread_no_secrets), substring = true)).assertCountEquals(0)
    }

    // --- FLAG_SECURE through a ContextWrapper ---------------------------------------------------------------------

    @Test fun secureWindowFindsTheActivityBehindAWrapper() {
        rule.setContent {
            CompositionLocalProvider(LocalContext provides ContextWrapper(ContextWrapper(LocalContext.current))) {
                if (SecureWhileShown()) Text("code 4417")
            }
        }
        rule.waitForIdle()
        assertTrue(secure())
        rule.onAllNodes(hasText("code 4417")).assertCountEquals(1)
    }

    @Test fun noActivityMeansNoProtectedContent() {
        val debuggable = ctx.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
        var failed: Throwable? = null
        runCatching {
            rule.setContent {
                CompositionLocalProvider(LocalContext provides ctx) { if (SecureWhileShown()) Text("code 4417") }
            }
            rule.waitForIdle()
        }.onFailure { failed = it }
        // Debug builds fail loudly; a release build never shows what it protects.
        if (debuggable) assertTrue("debug throws", failed != null)
        else rule.onAllNodes(hasText("code 4417")).assertCountEquals(0)
    }

    // --- a late 4401 after pairing again ---------------------------------------------------------------------------

    @Test fun aLate4401ForTheOldKeyNeverWipesTheNewOne() {
        // The owner paired again while connected: the server's 4401 for the old key arrives on the socket that
        // opened with it, after the new key was saved. It reconnects with the new key; it never unpairs.
        assertEquals(Rejection.RECONNECT, ConnectionService.rejection(true, "dk_old", "", "dk_new", ""))
        // The same key refused: unpaired, as before.
        assertEquals(Rejection.UNPAIR, ConnectionService.rejection(true, "dk_old", "", "dk_old", ""))
        // A socket already replaced: ignored, as before.
        assertEquals(Rejection.IGNORE, ConnectionService.rejection(false, "dk_old", "", "dk_old", ""))
        // Legacy token mode: the token is compared the same way.
        assertEquals(Rejection.RECONNECT, ConnectionService.rejection(true, "", "t_old", "", "t_new"))
        assertEquals(Rejection.UNPAIR, ConnectionService.rejection(true, "", "t_old", "", "t_old"))
    }
}
