package dev.openmob.companion

import androidx.test.core.app.ApplicationProvider
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config

/** App updates (docs/phone-protocol.md §3.7): which state Home shows, and which download links may be opened. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class AppUpdatesTest {
    private val ctx: android.app.Application = ApplicationProvider.getApplicationContext()
    private val server = "https://openmob.example"
    private val url = "https://openmob.example/download/openmob.apk?v=3f9a0c1e2b4d"

    @After fun tearDown() {
        ctx.getSharedPreferences("openmob_updates", 0).edit().clear().commit()
        AppUpdates.onWelcome(ctx, null)
    }

    // --- the banner state -------------------------------------------------------------------------------------

    @Test fun nothingKnownOrNothingNewerShowsNothing() {
        assertEquals(UpdateState.None, UpdateLogic.state(47, null, 0, false))
        assertEquals(UpdateState.None, UpdateLogic.state(47, UpdateInfo(47, 0, url), 0, false))
        assertEquals(UpdateState.None, UpdateLogic.state(52, UpdateInfo(47, 0, url), 0, false)) // a newer app than the server's
        assertEquals(UpdateState.None, UpdateLogic.state(47, UpdateInfo(null, 0, null), 0, false)) // the server serves none
    }

    @Test fun aNewerBuildIsAvailable() {
        assertEquals(UpdateState.Available(52), UpdateLogic.state(47, UpdateInfo(52, 0, url), 0, false))
        assertTrue(UpdateLogic.newer(47, UpdateInfo(52, 0, url)))
        assertFalse(UpdateLogic.newer(52, UpdateInfo(52, 0, url)))
    }

    @Test fun laterHidesItUntilAHigherVersionComes() {
        assertEquals(UpdateState.None, UpdateLogic.state(47, UpdateInfo(52, 0, url), dismissed = 52, tooOld = false))
        assertEquals(UpdateState.Available(53), UpdateLogic.state(47, UpdateInfo(53, 0, url), dismissed = 52, tooOld = false))
        assertTrue("About still says so", UpdateLogic.newer(47, UpdateInfo(52, 0, url)))
    }

    @Test fun dismissingIsRememberedAndNeverGoesDown() {
        AppUpdates.dismiss(ctx, 52)
        AppUpdates.dismiss(ctx, 50)
        assertEquals(52, AppUpdates.dismissed(ctx))
    }

    @Test fun belowTheMinimumIsRequiredEvenIfDismissed() {
        assertEquals(UpdateState.Required(50, 52), UpdateLogic.state(47, UpdateInfo(52, 50, url), dismissed = 52, tooOld = false))
        assertEquals(UpdateState.Required(50, null), UpdateLogic.state(47, UpdateInfo(null, 50, null), 0, false))
        assertEquals(UpdateState.Available(52), UpdateLogic.state(50, UpdateInfo(52, 50, url), 0, false)) // at the minimum: fine
    }

    @Test fun a4400IsTooOld() {
        assertEquals(UpdateState.TooOld, UpdateLogic.state(47, null, 0, true))
        assertEquals(UpdateState.TooOld, UpdateLogic.state(47, UpdateInfo(52, 0, url), 0, true))
    }

    @Test fun theWelcomeIsParsedStrictly() {
        assertEquals(UpdateInfo(52, 50, url),
                     UpdateInfo.parse(JSONObject("""{"latest": 52, "minimum": 50, "url": "$url"}""")))
        assertEquals(UpdateInfo(null, 0, null), UpdateInfo.parse(JSONObject("""{"latest": null, "minimum": 0, "url": null}""")))
        assertEquals(UpdateInfo(null, 0, null),
                     UpdateInfo.parse(JSONObject("""{"latest": "52", "minimum": 5.5, "url": 7}""")))
        assertEquals(UpdateInfo(null, 0, null), UpdateInfo.parse(JSONObject("""{"latest": -1, "minimum": true}""")))
        assertNull(UpdateInfo.parse(null)) // an older server
    }

    @Test fun theWelcomeSetsTheStateAndClearsTooOld() {
        AppUpdates.onTooOld(ctx)
        assertEquals(UpdateState.TooOld, AppUpdates.state(ctx))
        AppUpdates.onWelcome(ctx, JSONObject("""{"latest": ${AppUpdates.current + 5}, "minimum": 0, "url": "$url"}"""))
        assertFalse(AppUpdates.tooOld)
        assertEquals(UpdateState.Available(AppUpdates.current + 5), AppUpdates.state(ctx))
    }

    @Test fun requiredPostsOnePrivateNotificationAndAvailableNone() {
        val nm = ctx.getSystemService(android.app.NotificationManager::class.java)
        val shadow = Shadows.shadowOf(nm)
        AppUpdates.onWelcome(ctx, JSONObject("""{"latest": ${AppUpdates.current + 5}, "minimum": 0, "url": "$url"}"""))
        assertEquals("available: no notification", 0, shadow.allNotifications.size)
        val required = JSONObject("""{"latest": ${AppUpdates.current + 5}, "minimum": ${AppUpdates.current + 1}, "url": "$url"}""")
        AppUpdates.onWelcome(ctx, required)
        AppUpdates.onWelcome(ctx, required) // a reconnect: not again
        assertEquals(1, shadow.allNotifications.size)
        val n = shadow.allNotifications.single()
        assertEquals(android.app.Notification.VISIBILITY_PRIVATE, n.visibility)
        assertEquals(ctx.getString(R.string.update_notif_title), n.extras.getCharSequence(android.app.Notification.EXTRA_TITLE).toString())
        assertEquals(ctx.getString(R.string.update_notif_text), n.extras.getCharSequence(android.app.Notification.EXTRA_TEXT).toString())
        assertTrue(n.publicVersion != null)
    }

    // --- the download link ------------------------------------------------------------------------------------

    @Test fun theServersOwnDownloadIsAllowed() {
        assertEquals(url, UpdateLogic.safeDownloadUrl(url, server))
        assertEquals("https://openmob.example/download/openmob.apk", UpdateLogic.safeDownloadUrl(
            "https://openmob.example/download/openmob.apk", server))
        assertEquals(url, UpdateLogic.safeDownloadUrl("https://OPENMOB.example:443/download/openmob.apk?v=3f9a0c1e2b4d", "openmob.example"))
        assertEquals("http://home.local:8765/download/openmob.apk?v=ab12",
                     UpdateLogic.safeDownloadUrl("http://home.local:8765/download/openmob.apk?v=ab12", "http://home.local:8765/"))
        // A server behind a path keeps its prefix.
        assertEquals("https://h.example/om/download/openmob.apk",
                     UpdateLogic.safeDownloadUrl("https://h.example/om/download/openmob.apk", "https://h.example/om"))
    }

    @Test fun otherHostsSchemesPortsAndPathsAreRefused() {
        listOf(
            "https://evil.example/download/openmob.apk", // another host
            "https://openmob.example.evil.example/download/openmob.apk",
            "https://evil.example/download/openmob.apk#openmob.example",
            "https://openmob.example@evil.example/download/openmob.apk", // user info: the host is evil.example
            "https://user@openmob.example/download/openmob.apk",
            "http://openmob.example/download/openmob.apk", // https paired: no downgrade
            "intent://openmob.example/download/openmob.apk#Intent;scheme=https;end",
            "file:///sdcard/Download/openmob.apk",
            "javascript:alert(1)",
            "https://openmob.example:8443/download/openmob.apk", // another port
            "https://openmob.example/download/other.apk", // another path
            "https://openmob.example/download/openmob.apk/../evil.apk",
            "https://openmob.example/download/openmob.apk/",
            "https://openmob.example/download/%6Fpenmob.apk",
            "https://openmob.example//download/openmob.apk",
            "https://openmob.example/download/openmob.apk?v=../../x", // only v=<hex>
            "https://openmob.example/download/openmob.apk?v=ab&next=https://evil.example",
            "https://openmob.example/download/openmob.apk#x",
            "https://openmob.example\\@evil.example/download/openmob.apk",
            "",
        ).forEach { assertNull(it, UpdateLogic.safeDownloadUrl(it, server)) }
        assertNull(UpdateLogic.safeDownloadUrl(null, server))
        assertNull("no paired server", UpdateLogic.safeDownloadUrl(url, ""))
        assertNull("http paired, https link", UpdateLogic.safeDownloadUrl(
            "https://home.local:8765/download/openmob.apk", "http://home.local:8765"))
    }

    @Test fun theFallbackIsTheServersOwnPath() {
        assertEquals("https://openmob.example/download/openmob.apk", UpdateLogic.fallbackUrl("https://openmob.example/"))
        assertEquals("http://home.local:8765/download/openmob.apk", UpdateLogic.fallbackUrl("ws://home.local:8765"))
        assertNull(UpdateLogic.fallbackUrl(""))
    }

    @Test fun downloadFetchesOnlyACheckedLink() {
        // Review 5 P5-L3 (owner, 2026-10-21): the app downloads the checked link itself and checks the APK
        // (Review5PhoneTest); nothing is opened before that check.
        val fetched = mutableListOf<String>()
        val real = AppUpdates.downloader
        AppUpdates.downloader = { _, u -> fetched += u; AppUpdates.downloadEnded() }
        Settings(ctx).server = server
        AppUpdates.onWelcome(ctx, JSONObject("""{"latest": 99999, "minimum": 0, "url": "https://evil.example/download/openmob.apk"}"""))
        assertFalse(AppUpdates.openDownload(ctx))
        assertTrue(fetched.isEmpty())
        AppUpdates.onWelcome(ctx, JSONObject("""{"latest": 99999, "minimum": 0, "url": "$url"}"""))
        assertTrue(AppUpdates.openDownload(ctx))
        assertEquals(listOf(url), fetched)
        assertNull("nothing opened before the APK is checked", Shadows.shadowOf(ctx).nextStartedActivity)
        AppUpdates.downloader = real
        // While connected, no link from the server means no button (an older link isn't reused).
        AppUpdates.onWelcome(ctx, JSONObject("""{"latest": null, "minimum": 0, "url": null}"""))
        assertNull(AppUpdates.downloadUrl(ctx))
        // After a 4400: the last link a welcome gave, else the server's own path.
        AppUpdates.onTooOld(ctx)
        assertEquals(url, AppUpdates.downloadUrl(ctx))
        ctx.getSharedPreferences("openmob_updates", 0).edit().remove("last_url").commit()
        assertEquals("https://openmob.example/download/openmob.apk", AppUpdates.downloadUrl(ctx))
        Settings(ctx).server = ""
    }

    @Test fun theAppAsksToInstallPackagesOnlyForItsCheckedUpdate() {
        // Owner, 2026-10-21 (review 5 P5-L3): declared for the in-app update hand-off, which ApkCheck gates
        // (Review5PhoneTest covers the check and the FileProvider).
        val info = ctx.packageManager.getPackageInfo(ctx.packageName, android.content.pm.PackageManager.GET_PERMISSIONS)
        assertTrue(info.requestedPermissions.orEmpty().contains("android.permission.REQUEST_INSTALL_PACKAGES"))
    }

    @Test fun theBuildHasAVersionAndAHash() {
        assertTrue(BuildConfig.VERSION_CODE >= 1)
        assertTrue(BuildConfig.GIT_HASH == "unknown" || BuildConfig.GIT_HASH.matches(Regex("[0-9a-f]{7,40}")))
        assertEquals("${BuildConfig.VERSION_CODE} (${BuildConfig.GIT_HASH})", BuildConfig.VERSION_NAME)
    }
}
