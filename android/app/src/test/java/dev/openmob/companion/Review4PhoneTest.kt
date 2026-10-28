package dev.openmob.companion

import android.app.KeyguardManager
import android.app.Notification
import android.app.NotificationManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Looper
import android.os.PowerManager
import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowToast
import org.xmlpull.v1.XmlPullParser
import java.io.File

/** Security review 4 on the phone (2026-10-18): what notifications say where others read them (M3), other apps'
 *  shortcut actions (L6), backups and device transfer (L7), and the "never type passwords" line (L10). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class Review4PhoneTest {
    private val ctx = ApplicationProvider.getApplicationContext<Context>()
    private val nm get() = ctx.getSystemService(NotificationManager::class.java)
    private val keyguard get() = Shadows.shadowOf(ctx.getSystemService(KeyguardManager::class.java))
    private val power get() = Shadows.shadowOf(ctx.getSystemService(PowerManager::class.java))

    @After fun tearDown() {
        Approvals.clear(ctx)
        keyguard.setKeyguardLocked(false)
        power.setIsInteractive(true)
    }

    private fun allText(n: Notification): String {
        val e = n.extras
        return listOf(Notification.EXTRA_TITLE, Notification.EXTRA_TEXT, Notification.EXTRA_BIG_TEXT, Notification.EXTRA_SUB_TEXT,
                      Notification.EXTRA_TITLE_BIG, Notification.EXTRA_SUMMARY_TEXT, Notification.EXTRA_INFO_TEXT)
            .joinToString("\n") { e.getCharSequence(it)?.toString().orEmpty() } + "\n" + (n.tickerText ?: "")
    }

    // --- M3: locked or dark ----------------------------------------------------------------------------------------

    @Test fun lockedMeansTheKeyguardIsUpOrTheScreenIsOff() {
        assertFalse(NotificationPrivacy.locked(ctx))
        keyguard.setKeyguardLocked(true) // a swipe-only lock counts: it hides nothing
        assertTrue(NotificationPrivacy.locked(ctx))
        keyguard.setKeyguardLocked(false)
        power.setIsInteractive(false) // screen off: a secure lock may come up after its delay
        assertTrue(NotificationPrivacy.locked(ctx))
    }

    @Test fun ongoingLineWhileLockedKeepsOnlyTheAppsOwnLines() {
        val safe = setOf("Connected · ready for your agent", "Waiting for your answer")
        assertEquals("Working on: pay Bob 500", NotificationPrivacy.ongoingLine("Working on: pay Bob 500", false, safe, "OpenMob is working"))
        assertEquals("OpenMob is working", NotificationPrivacy.ongoingLine("Working on: pay Bob 500", true, safe, "OpenMob is working"))
        assertEquals("Waiting for your answer", NotificationPrivacy.ongoingLine("Waiting for your answer", true, safe, "OpenMob is working"))
    }

    // --- M3: the heads-ups never carry the question -----------------------------------------------------------------

    @Test fun approvalNotificationNeverCarriesTheQuestion() {
        Shadows.shadowOf(ctx as android.app.Application).grantPermissions(android.Manifest.permission.POST_NOTIFICATIONS)
        Approvals.requestGate(ctx, "gk-r4", "Send \$500 to Bob Smith on Venmo?", "server says pay rent", null, null)
        val n = Shadows.shadowOf(nm).allNotifications.single()
        val text = allText(n)
        assertFalse(text, text.contains("Bob"))
        assertFalse(text, text.contains("500"))
        assertFalse(text, text.contains("rent"))
        assertEquals(ctx.getString(R.string.approval_notification_public), n.extras.getCharSequence(Notification.EXTRA_TITLE).toString())
        assertEquals(Notification.VISIBILITY_PRIVATE, n.visibility)
        assertEquals(ctx.getString(R.string.approval_notification_public),
                     n.publicVersion!!.extras.getCharSequence(Notification.EXTRA_TITLE).toString())
        // Unchanged: Deny and Review only; approving still goes through ApprovalActivity (FLAG_SECURE, screen lock).
        assertEquals(listOf(ctx.getString(R.string.approval_deny), ctx.getString(R.string.approval_review)),
                     n.actions.map { it.title.toString() })
        assertEquals(ApprovalActivity::class.java.name, Shadows.shadowOf(n.contentIntent).savedIntent.component?.className)
    }

    @Test fun questionNotificationNeverCarriesTheQuestionAndWarnsAboutPasswords() {
        Shadows.shadowOf(ctx as android.app.Application).grantPermissions(android.Manifest.permission.POST_NOTIFICATIONS)
        val alert = QuestionAlert(object : QuestionAlert.Effects {
            override fun post(question: String) = AgentQuestion.post(ctx)
            override fun cancel() = AgentQuestion.cancel(ctx)
            override fun questionOpen(open: Boolean) {}
        })
        alert.sync("Type your bank password to continue")
        val n = Shadows.shadowOf(nm).getNotification(AgentQuestion.NOTIFICATION_ID)
        val text = allText(n)
        assertFalse(text, text.contains("bank"))
        assertTrue(text, text.contains("Never type passwords or codes"))
    }

    // --- M3: the ongoing and owner-dialog notifications follow the lock ---------------------------------------------

    private fun service(): ConnectionService = Robolectric.buildService(ConnectionService::class.java).create().get()

    private fun ongoing(s: ConnectionService, text: String): Notification =
        ConnectionService::class.java.getDeclaredMethod("notification", String::class.java)
            .apply { isAccessible = true }.invoke(s, text) as Notification

    @Test fun ongoingNotificationHidesTheTaskWhileLocked() {
        val s = service()
        val task = "Working on: text Mom the gate code 4417"
        assertTrue(allText(ongoing(s, task)).contains("gate code"))
        keyguard.setKeyguardLocked(true)
        val locked = ongoing(s, task)
        assertFalse(allText(locked).contains("gate code"))
        assertTrue(allText(locked).contains(ctx.getString(R.string.notif_working_locked)))
        // The app's own lines still show, and the public version is generic.
        assertTrue(allText(ongoing(s, ctx.getString(R.string.notif_ready))).contains(ctx.getString(R.string.notif_ready)))
        assertEquals(Notification.VISIBILITY_PRIVATE, locked.visibility)
        assertEquals(ctx.getString(R.string.notif_title), locked.publicVersion!!.extras.getCharSequence(Notification.EXTRA_TITLE).toString())
        // Unlocked again: the full text comes back on the next post.
        keyguard.setKeyguardLocked(false)
        assertTrue(allText(ongoing(s, task)).contains("gate code"))
        s.onDestroy()
    }

    @Test fun ownerDialogNotificationHidesItsWordsWhileLocked() {
        val s = service()
        val post = ConnectionService::class.java.getDeclaredMethod("postOwnerDialog", String::class.java).apply { isAccessible = true }
        val message = "Allow Venmo to access your contacts? Tap Allow or Don't allow yourself."
        fun shown() = allText(Shadows.shadowOf(nm).allNotifications.single { it.extras.getCharSequence(Notification.EXTRA_TITLE)
            ?.toString() == ctx.getString(R.string.owner_dialog_title) })
        keyguard.setKeyguardLocked(true)
        post.invoke(s, message)
        assertFalse(shown().contains("Venmo"))
        assertTrue(shown().contains(ctx.getString(R.string.owner_dialog_locked)))
        keyguard.setKeyguardLocked(false)
        post.invoke(s, message) // what lockChanged does on unlock
        assertTrue(shown().contains("Venmo"))
        s.onDestroy()
    }

    // --- L6: other apps can't run the shortcut actions ---------------------------------------------------------------

    private fun launch(intent: Intent): MainActivity {
        val a = Robolectric.buildActivity(MainActivity::class.java, intent).setup().get()
        Shadows.shadowOf(Looper.getMainLooper()).idle()
        return a
    }

    @Test fun anotherAppsConnectOrAskIsIgnored() {
        ShadowToast.reset()
        // Exported MainActivity, Connect and Ask: the app just opens (unpaired here, so Connect would have toasted).
        launch(Intent(Shortcuts.CONNECT).setClassName(ctx.packageName, MainActivity::class.java.name))
        launch(Intent(Shortcuts.ASK).setClassName(ctx.packageName, MainActivity::class.java.name))
        assertNull(ShadowToast.getTextOfLatestToast())
        assertNull(Shadows.shadowOf(ctx as android.app.Application).nextStartedService)
        // Through OpenMob's own entry, the shortcut runs as before.
        launch(Shortcuts.intent(ctx, Shortcuts.CONNECT))
        assertEquals(ctx.getString(R.string.shortcut_need_pairing), ShadowToast.getTextOfLatestToast())
        launch(Shortcuts.intent(ctx, Shortcuts.ASK))
        assertEquals(ctx.getString(R.string.shortcut_need_connection), ShadowToast.getTextOfLatestToast())
    }

    @Test fun anotherAppsConnectIsIgnoredOnARunningActivityToo() {
        ShadowToast.reset()
        val ctl = Robolectric.buildActivity(MainActivity::class.java, Intent(ctx, MainActivity::class.java)).setup()
        ctl.newIntent(Intent(Shortcuts.CONNECT).setClassName(ctx.packageName, MainActivity::class.java.name))
        Shadows.shadowOf(Looper.getMainLooper()).idle()
        assertNull(ShadowToast.getTextOfLatestToast())
        ctl.newIntent(Shortcuts.intent(ctx, Shortcuts.CONNECT))
        Shadows.shadowOf(Looper.getMainLooper()).idle()
        assertEquals(ctx.getString(R.string.shortcut_need_pairing), ShadowToast.getTextOfLatestToast())
    }

    @Test fun theEntryIsNotExportedAndTheShortcutsUseIt() {
        val info = ctx.packageManager.getActivityInfo(ComponentName(ctx.packageName, Shortcuts.ENTRY), 0)
        assertFalse(info.exported)
        assertEquals(MainActivity::class.java.name, info.targetActivity)
        val targets = mutableListOf<String>()
        val xml = ctx.resources.getXml(R.xml.shortcuts)
        while (xml.next() != XmlPullParser.END_DOCUMENT) {
            if (xml.eventType == XmlPullParser.START_TAG && xml.name == "intent") {
                targets += xml.getAttributeValue("http://schemas.android.com/apk/res/android", "targetClass")
            }
        }
        assertEquals(listOf(Shortcuts.ENTRY, Shortcuts.ENTRY, Shortcuts.ENTRY), targets)
    }

    // --- L7: nothing to back up or transfer ---------------------------------------------------------------------------

    private val domains = listOf("root", "file", "database", "sharedpref", "external",
                                 "device_root", "device_file", "device_database", "device_sharedpref")

    private fun excluded(res: Int): Map<String, List<String>> {
        val out = mutableMapOf<String, MutableList<String>>()
        var section = "full-backup-content"
        val xml = ctx.resources.getXml(res)
        while (xml.next() != XmlPullParser.END_DOCUMENT) {
            if (xml.eventType != XmlPullParser.START_TAG) continue
            when (xml.name) {
                "cloud-backup", "device-transfer" -> section = xml.name
                "include" -> error("nothing is included")
                "exclude" -> out.getOrPut(section) { mutableListOf() } += xml.getAttributeValue(null, "domain")
            }
        }
        return out
    }

    @Test fun backupAndDeviceTransferExcludeEverything() {
        val rules = excluded(R.xml.data_extraction_rules)
        assertEquals(domains, rules["cloud-backup"])
        assertEquals(domains, rules["device-transfer"])
        assertEquals(domains, excluded(R.xml.backup_rules)["full-backup-content"])
        val manifest = File("src/main/AndroidManifest.xml").readText()
        assertTrue(manifest.contains("android:allowBackup=\"false\""))
        assertTrue(manifest.contains("android:dataExtractionRules=\"@xml/data_extraction_rules\""))
        assertTrue(manifest.contains("android:fullBackupContent=\"@xml/backup_rules\""))
    }
}
