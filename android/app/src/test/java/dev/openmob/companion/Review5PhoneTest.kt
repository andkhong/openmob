package dev.openmob.companion

import android.content.Context
import android.content.pm.PackageManager
import androidx.core.content.FileProvider
import androidx.test.core.app.ApplicationProvider
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

/** Security review 5 on the phone (2026-10-21): what Home keeps after unpair and Disconnect (P5-L2), and the in-app
 *  check of a downloaded update (P5-L3, owner 2026-10-21). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class Review5PhoneTest {
    private val ctx = ApplicationProvider.getApplicationContext<Context>()

    @After fun tearDown() { AppState.endSession() }

    // --- P5-L2: unpair and Disconnect clear what the account showed -------------------------------------------------

    private fun fill() {
        Chats.onWelcome(JSONObject().put("chats", true).put("chat", "c1"))
        Chats.onChat(JSONObject("""{"type":"chat","chat_id":"c1","title":"t","turns":[{"id":"t1","request":"remember soda",
            "started":1.0,"finished":2.0,"outcome":"done","summary":"ok","steps":1,"step_lines":[],"asks":0,"denied":false,
            "stopped_by_owner":false,"question":"","messages":[],"memory":["Used your preferences: Diet Coke"]}]}"""))
        MemoryNotes.onWelcome(JSONObject().put("memory", true))
        MemoryNotes.onMemory(JSONObject("""{"notes":[{"id":"n1","kind":"about_you","text":"Likes Diet Coke","status":"active"}]}"""))
        AppState.addEvent("memory", "Used your preferences: Diet Coke")
        AppState.onTaskState("started", "t2", "order my usual soda", "Opening Amazon", 1)
        assertTrue(Chats.supported)
        assertTrue(MemoryNotes.notes.isNotEmpty())
        assertTrue(AppState.events().isNotEmpty())
        assertTrue(AppState.task != null)
    }

    private fun assertCleared() {
        assertFalse(Chats.supported)
        assertNull(Chats.current)
        assertNull(Chats.thread)
        assertTrue(Chats.list.isEmpty())
        assertFalse(MemoryNotes.supported)
        assertTrue(MemoryNotes.notes.isEmpty())
        assertTrue(AppState.events().isEmpty())
        assertNull(AppState.task)
    }

    @Test fun theSessionEndClearsChatsNotesTheFeedAndTheTask() {
        fill()
        AppState.endSession() // ConnectionService.shutDown: Disconnect, unpair, a refused key
        assertCleared()
    }

    @Test fun unpairClearsAtOnceEvenWithTheServiceStopped() {
        fill()
        PairingFlow.unpair(ctx, Settings(ctx))
        assertCleared()
    }

    // --- P5-L3: the downloaded update is checked before the installer sees it ---------------------------------------

    private val me = ApkFacts(ApkCheck.PACKAGE, 400, setOf("8b6dcac4d3b8"))

    @Test fun onlyANewerBuildOfThisAppSignedLikeItGoesToTheInstaller() {
        assertNull(ApkCheck.verify(ApkFacts(ApkCheck.PACKAGE, 401, setOf("8b6dcac4d3b8")), me))
        assertEquals(ApkRefusal.NOT_AN_APP, ApkCheck.verify(null, me))
        // Another package would install beside OpenMob as a new app (it could be named OpenMob).
        assertEquals(ApkRefusal.OTHER_APP, ApkCheck.verify(ApkFacts("dev.openmob.companion2", 401, setOf("8b6dcac4d3b8")), me))
        assertEquals(ApkRefusal.OTHER_APP, ApkCheck.verify(ApkFacts("dev.openmob.companion", 401, setOf("x")),
                                                           me.copy(pkg = "dev.openmob.other")))
        assertEquals(ApkRefusal.UNSIGNED, ApkCheck.verify(ApkFacts(ApkCheck.PACKAGE, 401, emptySet()), me))
        assertEquals(ApkRefusal.UNSIGNED, ApkCheck.verify(ApkFacts(ApkCheck.PACKAGE, 401, setOf("a")), me.copy(signers = emptySet())))
        // A debug key, another key, or an extra signer: exactly this app's signers or nothing.
        assertEquals(ApkRefusal.OTHER_SIGNER, ApkCheck.verify(ApkFacts(ApkCheck.PACKAGE, 401, setOf("debugkey")), me))
        assertEquals(ApkRefusal.OTHER_SIGNER, ApkCheck.verify(ApkFacts(ApkCheck.PACKAGE, 401, setOf("8b6dcac4d3b8", "x")), me))
        // Not strictly newer: the same build or a downgrade.
        assertEquals(ApkRefusal.NOT_NEWER, ApkCheck.verify(ApkFacts(ApkCheck.PACKAGE, 400, setOf("8b6dcac4d3b8")), me))
        assertEquals(ApkRefusal.NOT_NEWER, ApkCheck.verify(ApkFacts(ApkCheck.PACKAGE, 12, setOf("8b6dcac4d3b8")), me))
    }

    @Test fun fingerprintsAreSha256OfTheCertificate() {
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", ApkCheck.fingerprint(ByteArray(0)))
    }

    @Test fun theManifestCanHandAnUpdateToTheInstallerAndShareOnlyTheUpdatesFolder() {
        val info = ctx.packageManager.getPackageInfo(ctx.packageName, PackageManager.GET_PERMISSIONS)
        assertTrue(info.requestedPermissions!!.contains("android.permission.REQUEST_INSTALL_PACKAGES"))
        val dir = File(ctx.cacheDir, "updates").apply { mkdirs() }
        val apk = File(dir, "openmob-update.apk").apply { writeBytes(ByteArray(1)) }
        val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.updates", apk)
        assertEquals("content", uri.scheme)
        try {
            FileProvider.getUriForFile(ctx, "${ctx.packageName}.updates", File(ctx.filesDir, "gatekeeper_policy.json"))
            fail("only the updates folder is shared")
        } catch (_: IllegalArgumentException) {
        }
        val provider = ctx.packageManager.resolveContentProvider("${ctx.packageName}.updates", 0)!!
        assertFalse(provider.exported)
    }

    // --- re-review 1 (info): the update goes to the package installer only ----------------------------------------

    @Suppress("DEPRECATION")
    @Test fun theUpdateIsHandedToThePackageInstallerAction() {
        val uri = android.net.Uri.parse("content://dev.openmob.companion.updates/updates/OpenMob.apk")
        val i = AppUpdates.installIntent(uri)
        assertEquals(android.content.Intent.ACTION_INSTALL_PACKAGE, i.action)
        assertEquals("application/vnd.android.package-archive", i.type)
        assertEquals(uri, i.data)
        assertTrue(i.flags and android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
    }
}
