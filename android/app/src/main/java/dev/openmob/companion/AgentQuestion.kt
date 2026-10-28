package dev.openmob.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent

/**
 * The agent's question in words (ask_user) while it waits for the owner (owner report 2026-10-18: the question showed
 * only on the dashboard and inside OpenMob's Home, so the owner, on Amazon, never knew the agent was waiting). While
 * one is open the phone posts a heads-up ("Your agent asks" and the question), the ongoing notification reads
 * "Waiting for your answer" and the indicator shows its asking state (IndicatorPolicy.questionOpen).
 *
 * The heads-up never carries the question (security review 4, M3): it can quote the screen, and a notification reaches
 * the lock screen, watches and notification listeners. It says only "Your agent has a question" and that passwords
 * and codes never go in an answer (L10). It has no inline reply: its tap opens OpenMob's Home, which shows the
 * question (the server's words, not checked by this phone) and whose composer answers (the agent's own taps on
 * OpenMob are refused by the gate). Approvals are separate (Approvals): while a phone prompt is open, that is what
 * asks.
 */
object AgentQuestion {
    const val CHANNEL = "agent_question"
    const val NOTIFICATION_ID = 9
    /** MainActivity: open Home (the composer answers there). Only an action, like the shortcuts (cleanIntent). */
    const val ACTION_OPEN_HOME = "dev.openmob.action.OPEN_HOME"

    /** The question open now, or null: Home's own notion (HomeState.askFor), so the phone's states agree. Connected,
     *  no phone prompt open, and the newest event is the question: anything newer (the answer heard, a result, an
     *  error, a Stop) closes it. [events]: newest first, as AppState keeps them. */
    fun open(connected: Boolean, approvalsPending: Boolean, events: List<AppState.Event>): String? {
        if (!connected || approvalsPending) return null
        return events.firstOrNull()?.takeIf { it.kind == "question" }?.message
    }

    /** The ongoing notification's text: [waiting] while a question is open, else the connection's [status]. */
    fun ongoingLine(status: String, question: String?, waiting: String): String = if (question != null) waiting else status

    /** Post (or replace, alerting again) the heads-up for a new question. Notifications off: nothing shows, nothing
     *  fails. The question itself stays in the app (NotificationPrivacy). */
    fun post(context: Context) {
        val app = context.applicationContext
        val manager = app.getSystemService(NotificationManager::class.java) ?: return
        runCatching {
            if (!manager.areNotificationsEnabled()) return
            if (manager.getNotificationChannel(CHANNEL) == null) {
                manager.createNotificationChannel(
                    NotificationChannel(CHANNEL, app.getString(R.string.question_channel), NotificationManager.IMPORTANCE_HIGH)
                        .apply { description = app.getString(R.string.question_channel_description) })
            }
            manager.notify(NOTIFICATION_ID, notification(app))
        }
    }

    fun cancel(context: Context) {
        runCatching { context.applicationContext.getSystemService(NotificationManager::class.java)?.cancel(NOTIFICATION_ID) }
    }

    private fun notification(app: Context): Notification {
        val open = PendingIntent.getActivity(
            app, NOTIFICATION_ID,
            Intent(app, MainActivity::class.java).setAction(ACTION_OPEN_HOME).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val title = app.getString(R.string.question_notification_public)
        val text = app.getString(R.string.question_notification_text)
        return Notification.Builder(app, CHANNEL)
            .setSmallIcon(R.drawable.ic_openmob_tile)
            .setColor(app.getColor(R.color.rd_signal)) // the agent's blue, never the approval amber
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setCategory(Notification.CATEGORY_MESSAGE)
            .setVisibility(Notification.VISIBILITY_PRIVATE)
            .setPublicVersion(NotificationPrivacy.publicVersion(app, CHANNEL, title))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
    }
}

/** Keeps the phone's question alert in step with the open question ([AgentQuestion.open]); [sync] runs on every
 *  change of the phone's state. */
class QuestionAlert(private val effects: Effects) {
    interface Effects {
        /** Post, or replace, the heads-up for this question (which stays out of the notification). */
        fun post(question: String)
        fun cancel()
        /** The question opened or closed: the ongoing notification and the indicator follow. */
        fun questionOpen(open: Boolean)
    }

    /** The question alerted now, or null. */
    var shown: String? = null
        private set

    fun sync(question: String?) {
        if (question == shown) return
        val was = shown
        shown = question
        if (question == null) { effects.cancel(); effects.questionOpen(false); return }
        effects.post(question)
        if (was == null) effects.questionOpen(true)
    }
}
