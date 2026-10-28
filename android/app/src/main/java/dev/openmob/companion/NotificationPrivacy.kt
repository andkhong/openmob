package dev.openmob.companion

import android.app.KeyguardManager
import android.app.Notification
import android.content.Context
import android.os.PowerManager

/**
 * What OpenMob's notifications may say where others can read them (security review 4, M3, 2026-10-18).
 *
 * Android shows a VISIBILITY_PRIVATE notification's public version only when the owner turned on "hide sensitive
 * content"; by default the lock screen shows everything, and a swipe-only lock never hides anything. Watches and
 * notification listeners get the full text even on an unlocked phone. So:
 * - the question and approval heads-ups never carry the question (AgentQuestion, Approvals): the app shows it, behind
 *   a tap (and, for an approval, behind FLAG_SECURE and the screen lock, as before);
 * - the ongoing notification and the owner-dialog one carry their text only while the phone is unlocked
 *   ([locked]); ConnectionService re-posts them when the screen goes off and when the owner unlocks;
 * - all of them are VISIBILITY_PRIVATE with a generic [publicVersion], for an owner who hides sensitive content.
 */
object NotificationPrivacy {
    /** Locked, or the screen is off (a secure lock may come up a few seconds later, after its delay). Unknown: locked. */
    fun locked(context: Context): Boolean = runCatching {
        val keyguard = context.getSystemService(KeyguardManager::class.java)
        val power = context.getSystemService(PowerManager::class.java)
        keyguard.isKeyguardLocked || !power.isInteractive
    }.getOrDefault(true)

    /** The ongoing notification's line: while [locked], only this app's own fixed lines ([safe]) or [generic]. */
    fun ongoingLine(line: String, locked: Boolean, safe: Set<String>, generic: String): String =
        if (!locked || line in safe) line else generic

    /** The lock screen's version for a VISIBILITY_PRIVATE notification: the [title] alone. */
    fun publicVersion(context: Context, channel: String, title: String, icon: Int = R.drawable.ic_openmob_tile): Notification =
        Notification.Builder(context, channel).setSmallIcon(icon).setContentTitle(title).build()
}
