package dev.openmob.companion.ui

import android.content.Context
import android.content.Intent
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.ApprovalActivity
import dev.openmob.companion.Approvals
import dev.openmob.companion.R
import dev.openmob.companion.ui.approval.ApprovalScreen
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config

/** The screen's Deny (Compose, step 6) answers no without a lock, through the same send(false). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ApprovalDenyTest {
    @get:Rule val rule = createEmptyComposeRule()
    private val ctx: Context = ApplicationProvider.getApplicationContext()

    @After fun tearDown() = Approvals.clear(ctx)

    @Test fun denyIsTriedWithoutALockAndNeverAYes() {
        Shadows.shadowOf(ctx as android.app.Application).grantPermissions(android.Manifest.permission.HIDE_OVERLAY_WINDOWS)
        val r = Approvals.Request(id = "a1", taskId = "t1", question = "Q", requester = "Claude", kind = "mode_change")
        @Suppress("UNCHECKED_CAST")
        (Approvals::class.java.getDeclaredField("pending").apply { isAccessible = true }.get(Approvals)
            as LinkedHashMap<String, Approvals.Request>)["a1"] = r
        val scenario = ActivityScenario.launch<ApprovalActivity>(Intent(ctx, ApprovalActivity::class.java).putExtra(Approvals.EXTRA_ID, "a1"))
        rule.onNodeWithTag(ApprovalScreen.TAG_DENY).performClick()
        rule.waitForIdle()
        scenario.onActivity { a ->
            val f = ApprovalActivity::class.java.getDeclaredField("status").apply { isAccessible = true }
            @Suppress("UNCHECKED_CAST")
            val status = (f.get(a) as androidx.compose.runtime.MutableState<String?>).value
            // Not connected in tests: the no can't go, so it stays pending and says so (never a yes).
            assertEquals(ctx.getString(R.string.approval_offline), status)
        }
        assertNotNull(Approvals.get("a1"))
        scenario.close()
    }
}
