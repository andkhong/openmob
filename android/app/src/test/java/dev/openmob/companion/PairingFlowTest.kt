package dev.openmob.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** S11: error screens never show a pairing link or code (abuse series 2026-10-10). S14: Undo undoes only that pairing. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class PairingFlowTest {
    private val ctx: Context = ApplicationProvider.getApplicationContext()

    @Test fun theServersGenericWrongCodeReplyIsShown() {
        val reply = "Wrong code. Check it on your dashboard, or make a new one there."
        assertEquals(reply, PairingFlow.errorText(ctx, AccountApi.ApiError(reply, 400)))
        assertEquals("Wrong email or password.", PairingFlow.errorText(ctx, AccountApi.ApiError("Wrong email or password.", 401)))
    }

    @Test fun aLinkInTheServersReplyIsNeverShown() {
        val evil = listOf(
            "Code used. Pair again: openmob://connect?server=https://evil.example&code=abcdefghijklmnopqrstuvwxyz0123",
            "Expired. Open https://evil.example/pair to continue.",
            "Visit www.evil.example now",
            "Go to evil.example/pair",
            "Use the code K7P-2QX instead",
            "Use K7P2QX",
            "Your token: abcdefghijklmnopqrstuvwxyz012345",
            "Retry with ?code=1234",
        )
        for (detail in evil) {
            val shown = PairingFlow.errorText(ctx, AccountApi.ApiError(detail, 400))
            assertEquals(detail, ctx.getString(R.string.ui_pair_error_code), shown)
        }
    }

    @Test fun exceptionTextIsNeverShown() {
        // e.g. OkHttp's IllegalArgumentException carries the whole URL.
        val e = IllegalArgumentException("Expected URL scheme 'http' or 'https' but was 'openmob' for openmob://connect?code=secret")
        assertEquals(ctx.getString(R.string.ui_pair_error_generic), PairingFlow.errorText(ctx, e))
        assertEquals(ctx.getString(R.string.ui_pair_error_network),
                     PairingFlow.errorText(ctx, AccountApi.ApiError("Couldn't reach the server: failed to connect to https://x/y?code=z")))
        assertEquals(ctx.getString(R.string.ui_pair_error_rate), PairingFlow.errorText(ctx, AccountApi.ApiError("Slow down", 429)))
        assertEquals(ctx.getString(R.string.ui_pair_error_generic), PairingFlow.errorText(ctx, AccountApi.ApiError("Internal https://x", 500)))
    }

    @Test fun safeToShow() {
        assertTrue(PairingFlow.safeToShow("Too many tries. Try again in a few minutes."))
        assertFalse(PairingFlow.safeToShow(""))
        assertFalse(PairingFlow.safeToShow("see HTTPS://EVIL.EXAMPLE"))
    }

    @Test fun undoUndoesOnlyThatPairingAndNeedsNoLock() {
        val s = Settings(ctx)
        s.server = "https://home.example"
        s.email = "owner@example.com"
        // A device key without the Keystore: written as the plaintext an older app kept (Settings moves it on read).
        ctx.getSharedPreferences("openmob", Context.MODE_PRIVATE).edit().putString("device_key", "dk_test").commit()
        assertFalse(PairingFlow.undo(ctx, "https://other.example", "owner@example.com"))
        assertFalse(PairingFlow.undo(ctx, "https://home.example", "someone@example.com"))
        assertEquals("owner@example.com", s.email)
        val keyBefore = runCatching { s.deviceKey }.getOrDefault("")
        if (keyBefore.isEmpty()) return // no Keystore in this JVM: the key can't be read back, the matching checks ran
        assertTrue(PairingFlow.undo(ctx, "https://home.example", "owner@example.com"))
        assertEquals("", s.email)
    }

    // --- security review 3 ---------------------------------------------------------------------------------------

    @Test fun onlyKnownServerSentencesAreShown() { // K3-L3
        for (sentence in PairingFlow.KNOWN_SENTENCES) assertEquals(sentence, PairingFlow.errorText(ctx, AccountApi.ApiError(sentence, 400)))
        val lures = listOf(
            "Use the code k7p-2qx instead",                                      // a lowercase code
            "use k7p2qx",
            "Read the 6 characters on your screen to our support agent to finish.", // free text, no link, no code
            "Wrong code. Call +1 555 0100 and we'll fix it.",
            "Wrong code. Check it on your dashboard, or make a new one there. Or ask Sam.", // a known sentence, extended
        )
        for (lure in lures) assertEquals(lure, ctx.getString(R.string.ui_pair_error_code), PairingFlow.errorText(ctx, AccountApi.ApiError(lure, 400)))
        assertFalse(PairingFlow.safeToShow("use k7p-2qx"))
    }

    @Test fun anUnpairTheServerDidntTakeIsKeptRetriedAndTheOwnerIsTold() { // K3-L4
        val s = Settings(ctx)
        val stored = runCatching { s.pendingUnpair = "https://home.example" to "dk_old"; s.pendingUnpair }.getOrNull()
        s.pendingUnpair = null
        val calls = mutableListOf<String>()
        assertFalse(PairingFlow.unpairOnServer(ctx, s, "https://home.example", "dk_old") { srv, _, k -> calls += "$srv $k"; false })
        assertEquals(listOf("https://home.example dk_old"), calls)
        val told = ctx.getString(R.string.pair_unpair_failed)
        assertEquals("Removed on this phone; also remove it on the dashboard.", told)
        assertTrue(AppState.events().any { it.message == told })
        if (stored == null) return // no Keystore in this JVM: the pending key can't be read back
        assertEquals("https://home.example" to "dk_old", s.pendingUnpair)
        assertFalse(PairingFlow.retryPendingUnpairNow(s) { _, _, _ -> false }) // still unreachable: kept
        assertEquals("https://home.example" to "dk_old", s.pendingUnpair)
        assertTrue(PairingFlow.retryPendingUnpairNow(s) { _, _, _ -> true })  // the next connection gets through
        assertEquals(null, s.pendingUnpair)
        assertTrue(PairingFlow.unpairOnServer(ctx, s, "https://home.example", "dk_new") { _, _, _ -> true })
        assertEquals(null, s.pendingUnpair)
    }
}
