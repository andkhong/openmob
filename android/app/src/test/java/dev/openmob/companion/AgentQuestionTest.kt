package dev.openmob.companion

import android.app.Notification
import android.app.NotificationManager
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config

/** The agent's question on the phone (owner report 2026-10-18: ask_user showed only on the dashboard and inside
 *  OpenMob's Home, so the owner, on Amazon, never knew the agent waited for them). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class AgentQuestionTest {
    private val ctx = ApplicationProvider.getApplicationContext<Context>()
    private val nm get() = ctx.getSystemService(NotificationManager::class.java)
    private fun ev(kind: String, message: String) = AppState.Event(kind, message, 0)

    // --- when a question is open: Home's notion (HomeState.askFor) -------------------------------------------------

    @Test fun openWhileTheNewestEventIsAQuestionAndConnected() {
        val asked = listOf(ev("question", "Which mouthwash is your favorite?"), ev("action", "launch_app: Amazon"))
        assertEquals("Which mouthwash is your favorite?", AgentQuestion.open(connected = true, approvalsPending = false, asked))
        assertNull(AgentQuestion.open(connected = false, approvalsPending = false, asked))
        // A phone prompt is open: that is what Home shows, and its own notification asks.
        assertNull(AgentQuestion.open(connected = true, approvalsPending = true, asked))
        // Answered ("heard"), ended (result, error), or stopped: any newer event closes it.
        for (k in listOf("heard", "result", "error", "status")) {
            assertNull(k, AgentQuestion.open(true, false, listOf(ev(k, "x")) + asked))
        }
        assertNull(AgentQuestion.open(true, false, emptyList()))
    }

    // --- the heads-up: posted, replaced, cancelled ------------------------------------------------------------------

    private class Recorder : QuestionAlert.Effects {
        val log = mutableListOf<String>()
        override fun post(question: String) { log += "post:$question" }
        override fun cancel() { log += "cancel" }
        override fun questionOpen(open: Boolean) { log += "asking:$open" }
    }

    @Test fun alertPostsOnceReplacesAndCancels() {
        val r = Recorder()
        val a = QuestionAlert(r)
        a.sync(null)
        assertTrue(r.log.isEmpty())
        a.sync("Which one?")
        a.sync("Which one?") // the same question again (any other listener update): no second alert
        assertEquals(listOf("post:Which one?", "asking:true"), r.log)
        r.log.clear()
        a.sync("And the size?") // a new question replaces it
        assertEquals(listOf("post:And the size?"), r.log)
        r.log.clear()
        a.sync(null) // answered, or the task ended
        assertEquals(listOf("cancel", "asking:false"), r.log)
        assertNull(a.shown)
    }

    @Test fun ongoingLineSaysWaitingWhileTheQuestionIsOpen() {
        assertEquals("Waiting for your answer", AgentQuestion.ongoingLine("Working on: mouthwash", "Which one?", "Waiting for your answer"))
        assertEquals("Working on: mouthwash", AgentQuestion.ongoingLine("Working on: mouthwash", null, "Waiting for your answer"))
        assertEquals(ctx.getString(R.string.question_waiting), "Waiting for your answer")
    }

    /** Review 4 M3: the heads-up says only that there is a question (the lock screen, watches and listeners read
     *  notifications); Home shows the question. */
    @Test fun notificationIsHeadsUpAndGeneric() {
        Shadows.shadowOf(ctx as android.app.Application).grantPermissions(android.Manifest.permission.POST_NOTIFICATIONS)
        AgentQuestion.post(ctx)
        val channel = nm.getNotificationChannel(AgentQuestion.CHANNEL)
        assertEquals(NotificationManager.IMPORTANCE_HIGH, channel.importance)
        val n = Shadows.shadowOf(nm).getNotification(AgentQuestion.NOTIFICATION_ID)
        assertEquals(AgentQuestion.CHANNEL, n.channelId)
        assertEquals(ctx.getString(R.string.question_notification_public), n.extras.getCharSequence(Notification.EXTRA_TITLE).toString())
        assertEquals(ctx.getString(R.string.question_notification_text), n.extras.getCharSequence(Notification.EXTRA_TEXT).toString())
        // Private too, with a generic public version, for an owner who hides sensitive content.
        assertEquals(Notification.VISIBILITY_PRIVATE, n.visibility)
        assertEquals(ctx.getString(R.string.question_notification_public),
                     n.publicVersion!!.extras.getCharSequence(Notification.EXTRA_TITLE).toString())
        // No inline reply: tapping opens OpenMob's Home, where the composer answers.
        assertTrue(n.actions.isNullOrEmpty())
        val open = Shadows.shadowOf(n.contentIntent)
        assertTrue(open.isActivityIntent)
        assertTrue(n.contentIntent.isImmutable)
        assertEquals(MainActivity::class.java.name, open.savedIntent.component?.className)
        assertEquals(AgentQuestion.ACTION_OPEN_HOME, open.savedIntent.action)
        // A new question replaces it (one notification), and cancel removes it.
        AgentQuestion.post(ctx)
        assertEquals(1, Shadows.shadowOf(nm).allNotifications.size)
        AgentQuestion.cancel(ctx)
        assertTrue(Shadows.shadowOf(nm).allNotifications.isEmpty())
    }

    @Test fun notificationsOffDoesNotCrash() {
        Shadows.shadowOf(ctx as android.app.Application).denyPermissions(android.Manifest.permission.POST_NOTIFICATIONS)
        Shadows.shadowOf(nm).setNotificationsEnabled(false)
        AgentQuestion.post(ctx) // nothing to see, nothing thrown
        AgentQuestion.cancel(ctx)
    }
}
