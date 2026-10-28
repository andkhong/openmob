package dev.openmob.companion

import android.app.Notification
import android.app.NotificationManager
import android.content.Context
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.lang.reflect.Proxy

/** Preferences memory never reaches a notification (global constraint; spec §6): the server's memory messages go
 *  through the real socket handler, and no notification the app posts carries a note's text, relation or contact. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class MemoryNotificationsTest {
    private val ctx = ApplicationProvider.getApplicationContext<Context>()
    private val nm get() = ctx.getSystemService(NotificationManager::class.java)

    @After fun clear() {
        // The fed welcome changed process-wide state: put it back for the tests that run after this one.
        MemoryNotes.reset()
        Chats.reset()
        AppState.setTaskProtocol(false)
        AppState.setModels(null)
        AppState.setConnection("Disconnected", false)
        Shadows.shadowOf(Looper.getMainLooper()).idle()
    }

    private fun allText(n: Notification): String {
        val e = n.extras
        return listOf(Notification.EXTRA_TITLE, Notification.EXTRA_TEXT, Notification.EXTRA_BIG_TEXT, Notification.EXTRA_SUB_TEXT,
                      Notification.EXTRA_TITLE_BIG, Notification.EXTRA_SUMMARY_TEXT, Notification.EXTRA_INFO_TEXT)
            .joinToString("\n") { e.getCharSequence(it)?.toString().orEmpty() } + "\n" + (n.tickerText ?: "") +
            (n.publicVersion?.let { "\n" + allText(it) } ?: "")
    }

    private val socket = Proxy.newProxyInstance(WebSocket::class.java.classLoader, arrayOf(WebSocket::class.java)) { _, m, _ ->
        when (m.returnType) { java.lang.Boolean.TYPE -> false; java.lang.Long.TYPE -> 0L; else -> null }
    } as WebSocket

    /** The service's own socket listener (opened with no device key or token). */
    private fun listener(s: ConnectionService): WebSocketListener =
        Class.forName("dev.openmob.companion.ConnectionService\$Listener")
            .getDeclaredConstructor(ConnectionService::class.java, String::class.java, String::class.java)
            .apply { isAccessible = true }.newInstance(s, "", "") as WebSocketListener

    /** The service's own socket listener, fed [messages] as the server would send them. */
    private fun feed(s: ConnectionService, vararg messages: String) {
        val l = listener(s)
        messages.forEach { l.onMessage(socket, it) }
        idle()
    }

    private fun idle() = Shadows.shadowOf(Looper.getMainLooper()).idle()

    /** This socket is the service's current one (as after connect()). */
    private fun current(s: ConnectionService) =
        ConnectionService::class.java.getDeclaredField("socket").apply { isAccessible = true }.set(s, socket)

    private val notesJson = """{"type":"memory","notes":[{"id":"n1","kind":"person","package":null,"relation":"wife",
        "contact_name":"Samantha","text":"texts after nine","status":"active"}],"proposed":[]}"""

    private fun showing() {
        MemoryNotes.onWelcome(org.json.JSONObject("""{"type":"welcome","memory":true}"""))
        MemoryNotes.onMemory(org.json.JSONObject(notesJson))
        assertTrue(MemoryNotes.supported && MemoryNotes.notes.size == 1 && MemoryNotes.loaded)
    }

    private fun assertCleared() {
        assertFalse(MemoryNotes.supported)
        assertTrue(MemoryNotes.notes.isEmpty() && MemoryNotes.proposed.isEmpty())
        assertFalse(MemoryNotes.loaded)
    }

    @Test fun noNotificationCarriesANotesText() {
        val s = Robolectric.buildService(ConnectionService::class.java).create().get()
        running(s) // as after ACTION_START: the service posts its ongoing notification
        feed(s,
             """{"type":"welcome","session":"app-x","task_state":true,"memory":true}""",
             """{"type":"memory","notes":[{"id":"n1","kind":"person","package":null,"relation":"wife","contact_name":"Samantha",
                 "text":"texts after nine","status":"active"}],
                 "proposed":[{"id":"n2","kind":"about_you","package":null,"relation":null,"contact_name":null,
                 "text":"favorite soda is Diet Coke","status":"proposed"}]}""",
             """{"type":"memory","ok":false,"error":"bad_note","notes":[],"proposed":[]}""",
             """{"type":"event","kind":"memory","message":""}""")
        // The page got them...
        assertTrue(MemoryNotes.supported)
        val posted = Shadows.shadowOf(nm).allNotifications
        assertTrue("the ongoing notification is up", posted.isNotEmpty())
        // ...and no notification says any of it.
        for (n in posted) {
            val shown = allText(n)
            for (secret in listOf("Samantha", "wife", "nine", "Diet Coke", "soda")) assertFalse(shown, shown.contains(secret, ignoreCase = true))
        }
        running(null)
        s.onDestroy()
    }

    private fun running(s: ConnectionService?) =
        ConnectionService::class.java.getDeclaredField("running").apply { isAccessible = true }.set(null, s)

    @Test fun deniedClearsEverythingShown() {
        MemoryNotes.onWelcome(org.json.JSONObject("""{"type":"welcome","memory":true}"""))
        MemoryNotes.onMemory(org.json.JSONObject("""{"type":"memory","notes":[{"id":"n1","kind":"about_you","text":"x","status":"active"}],"proposed":[]}"""))
        assertEquals(1, MemoryNotes.notes.size)
        MemoryNotes.onMemory(org.json.JSONObject("""{"type":"memory","denied":true}"""))
        assertFalse(MemoryNotes.supported)
        assertTrue(MemoryNotes.notes.isEmpty() && MemoryNotes.proposed.isEmpty())
    }

    // --- the cache ends with the pairing (review fix round 1) -----------------------------------------------------

    @Test fun aRefusedKeyClearsTheNotes() {
        val s = Robolectric.buildService(ConnectionService::class.java).create().get()
        running(s)
        // Unpaired credentials ("" key and token, as saved now): the socket opened with what is saved, so a 4401 unpairs.
        current(s)
        showing()
        listener(s).onClosing(socket, 4401, "Bad or missing token")
        idle()
        assertCleared()
        running(null)
        s.onDestroy()
    }

    @Test fun theOwnersUnpairClearsTheNotes() {
        showing()
        runCatching { PairingFlow.unpair(ctx, Settings(ctx)) } // (Robolectric has no keystore for the key's wipe)
        assertCleared()
    }

    @Test fun theOwnersDisconnectClearsTheNotes() {
        val s = Robolectric.buildService(ConnectionService::class.java).create().get()
        running(s)
        showing()
        s.onStartCommand(android.content.Intent("dev.openmob.STOP"), 0, 1)
        idle()
        assertCleared()
        s.onDestroy()
    }

    @Test fun aNetworkDropKeepsTheNotesUntilTheNextWelcome() {
        val s = Robolectric.buildService(ConnectionService::class.java).create().get()
        running(s)
        current(s)
        showing()
        listener(s).onClosing(socket, 1006, "gone") // a blip: the service reconnects by itself
        idle()
        assertEquals(1, MemoryNotes.notes.size)
        running(null)
        s.onDestroy()
    }

    @Test fun aWelcomeAfterARePairClearsTheNotesUntilAFreshList() {
        showing()
        // Re-paired (maybe to another account): nothing old shows; the list is asked again since the page had one.
        val ask = MemoryNotes.onWelcome(org.json.JSONObject("""{"type":"welcome","memory":true}"""))
        assertEquals("memory_list", ask?.getString("type"))
        assertTrue(MemoryNotes.supported)
        assertTrue(MemoryNotes.notes.isEmpty() && !MemoryNotes.loaded)
        MemoryNotes.onMemory(org.json.JSONObject("""{"type":"memory","notes":[{"id":"b1","kind":"about_you","text":"B's note","status":"active"}],"proposed":[]}"""))
        assertEquals(listOf("b1"), MemoryNotes.notes.map { it.id })
        // A welcome saying no memory clears it and asks nothing.
        assertEquals(null, MemoryNotes.onWelcome(org.json.JSONObject("""{"type":"welcome","memory":false}""")))
        assertCleared()
    }
}
