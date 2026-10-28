package dev.openmob.companion.ui

import dev.openmob.companion.AccountApi
import dev.openmob.companion.R
import dev.openmob.companion.ui.setup.LockRequest
import dev.openmob.companion.ui.setup.PhoneSetup
import dev.openmob.companion.ui.setup.SetupBackend
import dev.openmob.companion.ui.setup.SetupError
import dev.openmob.companion.ui.setup.SetupNext
import dev.openmob.companion.ui.setup.SetupViewModel
import dev.openmob.companion.ui.setup.TypedCode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The typed-code setup (docs/design/redesign-setup.md): the order of the checks, and nothing pairs without the lock. */
@OptIn(ExperimentalCoroutinesApi::class)
class SetupViewModelTest {
    class FakeBackend : SetupBackend {
        var phone = PhoneSetup()
        var lock = true
        var checkResult: Result<String> = Result.success("owner@example.com")
        var claimResult: Result<Unit> = Result.success(Unit)
        val calls = mutableListOf<String>()
        override fun phone() = phone
        override fun defaultServer() = "https://openmob.fly.dev"
        override fun screenLockReady() = lock
        override fun check(server: String, code: String): String { calls += "check:$server:$code"; return checkResult.getOrThrow() }
        override fun claim(server: String, code: String, email: String) {
            calls += "claim:$server:$code:$email"; claimResult.getOrThrow()
            phone = phone.copy(paired = true, server = server, email = email)
        }
        override fun afterPaired(server: String, email: String, wasRunning: Boolean) { calls += "afterPaired:$email" }
        override fun unpair() { calls += "unpair"; phone = phone.copy(paired = false, email = "", server = "") }
        var signInResult: Result<Pair<String, String>> = Result.success("QRSTYLECODE0123456789abcdefgh" to "owner@example.com")
        override fun signInForCode(server: String, email: String, password: String, create: Boolean, invite: String): Pair<String, String> {
            calls += "signIn:$server:$email:$create"; return signInResult.getOrThrow()
        }
        override fun saveToken(server: String, token: String, wasRunning: Boolean) {
            calls += "token:$server:$token"; phone = phone.copy(paired = true, server = server, tokenMode = true)
        }
        override fun setSmoothLiveView(on: Boolean) { calls += "liveView:$on" }
        override fun connect() { calls += "connect" }
        override fun disconnect() { calls += "disconnect" }
        override fun errorText(error: Throwable) = "shown:${error.message}"
        override fun listen(onChange: () -> Unit): () -> Unit = {}
    }

    private val dispatcher = UnconfinedTestDispatcher()
    private val backend = FakeBackend()
    private fun vm() = SetupViewModel(backend, io = dispatcher)

    @Before fun setUp() { Dispatchers.setMain(dispatcher) }
    @After fun tearDown() { Dispatchers.resetMain() }

    @Test fun typedCodesAreNormalizedAndShapeChecked() {
        assertEquals("K7P2QX", TypedCode.normalize("k7p-2qx"))
        assertEquals("K7P2QX", TypedCode.normalize(" K7P 2QX "))
        assertEquals("K7P2QX", TypedCode.normalize("K7P–2QX"))
        assertNull(TypedCode.normalize("K7P2Q"))       // too short
        assertNull(TypedCode.normalize("K0P2QX"))      // 0 isn't in the alphabet
        assertNull(TypedCode.normalize("KIP2QX"))      // nor I
        assertNull(TypedCode.normalize("K7P2QXA"))
    }

    @Test fun aBadShapeIsNeverSent() {
        val v = vm()
        v.setCode("K0P-2QX")
        v.submitCode()
        assertEquals(SetupError.Local(R.string.rd_setup_code_shape), v.state.value.codeError)
        assertTrue(backend.calls.isEmpty())
    }

    @Test fun noScreenLockNoCheck() {
        backend.lock = false
        val v = vm()
        v.setCode("K7P-2QX")
        v.submitCode()
        assertEquals(SetupError.Local(R.string.ui_need_screen_lock), v.state.value.codeError)
        assertTrue(backend.calls.isEmpty())
    }

    @Test fun claimOnlyAfterTheLock() {
        val v = vm()
        v.setCode("k7p-2qx")
        v.submitCode()
        assertEquals(listOf("check:https://openmob.fly.dev:K7P2QX"), backend.calls)
        assertEquals("owner@example.com", v.state.value.checked?.email)
        assertEquals(SetupNext.Confirm, v.state.value.next)
        v.navigated()
        v.confirm()
        assertEquals(LockRequest.Pair, v.state.value.lock)
        assertEquals(1, backend.calls.size) // nothing claimed yet
        v.lockShown()
        v.lockPassed(LockRequest.Pair)
        assertEquals("claim:https://openmob.fly.dev:K7P2QX:owner@example.com", backend.calls[1])
        assertEquals("afterPaired:owner@example.com", backend.calls[2])
        assertEquals("", v.state.value.code) // the code isn't kept
        assertNull(v.state.value.checked)
        assertEquals(SetupNext.Consent, v.state.value.next)
    }

    @Test fun aCancelledLockPairsNothing() {
        val v = vm()
        v.setCode("K7P2QX"); v.submitCode(); v.confirm(); v.lockShown()
        v.lockFailed(cancelled = true, message = null)
        assertEquals(SetupError.Local(R.string.ui_pair_cancelled), v.state.value.confirmError)
        assertEquals(1, backend.calls.size)
    }

    @Test fun failedClaimSavesNothing() {
        backend.claimResult = Result.failure(AccountApi.ApiError("Wrong code.", 400))
        val v = vm()
        v.setCode("K7P2QX"); v.submitCode(); v.confirm(); v.lockPassed(LockRequest.Pair)
        assertEquals(SetupError.Shown("shown:Wrong code."), v.state.value.confirmError)
        assertTrue(backend.calls.none { it.startsWith("afterPaired") })
        assertEquals(false, backend.phone.paired)
    }

    @Test fun wrongCodeShowsTheServersReply() {
        backend.checkResult = Result.failure(AccountApi.ApiError("Wrong code. Check it on your dashboard, or make a new one there.", 400))
        val v = vm()
        v.setCode("K7P2QB"); v.submitCode()
        assertEquals(SetupError.Shown("shown:Wrong code. Check it on your dashboard, or make a new one there."), v.state.value.codeError)
        assertNull(v.state.value.checked)
        assertNull(v.state.value.next)
    }

    @Test fun alreadyPairedGoesThroughReplace() {
        backend.phone = PhoneSetup(paired = true, server = "https://other.example", email = "current@example.com")
        val v = vm()
        v.setCode("K7P2QX"); v.submitCode()
        assertEquals(SetupNext.Replace, v.state.value.next)
        v.unpairForReplace()
        assertEquals(LockRequest.Unpair, v.state.value.lock)
        assertTrue("unpair" !in backend.calls) // only after its prompt
        v.lockPassed(LockRequest.Unpair)
        assertTrue("unpair" in backend.calls)
        assertEquals(SetupNext.Confirm, v.state.value.next)
    }

    @Test fun samePairingAgainNeedsNoReplace() {
        backend.phone = PhoneSetup(paired = true, server = "https://openmob.fly.dev", email = "owner@example.com")
        val v = vm()
        v.setCode("K7P2QX"); v.submitCode()
        assertEquals(SetupNext.Confirm, v.state.value.next)
    }

    @Test fun notMePairsNothing() {
        val v = vm()
        v.setCode("K7P2QX"); v.submitCode()
        v.notMe()
        assertNull(v.state.value.checked)
        assertEquals(SetupNext.Code, v.state.value.next)
        v.lockPassed(LockRequest.Pair) // a late prompt result does nothing without a checked code
        assertEquals(1, backend.calls.size)
    }

    @Test fun ownServerMustPassServerPolicy() {
        val v = vm()
        v.setCode("K7P2QX")
        v.setServer("http://example.com")
        v.submitCode(fromMore = true)
        assertEquals(R.string.ui_invalid_server, v.state.value.serverError)
        assertTrue(backend.calls.isEmpty())
        v.setServer("https://home.example.com/")
        v.submitCode(fromMore = true)
        assertEquals("check:https://home.example.com:K7P2QX", backend.calls.single())
    }

    // --- step 6: the sign-in fallback and the developer token, now in the new UI ---

    @Test fun signInChecksFirstThenTheSameConfirmAndClaim() {
        val v = vm()
        v.signIn("http://example.com", "a@b.c", "pw", "", false)
        assertEquals(SetupError.Local(R.string.ui_invalid_server), v.state.value.formError)
        v.signIn("https://home.example", "", "pw", "", false)
        assertEquals(SetupError.Local(R.string.ui_signin_missing), v.state.value.formError)
        v.signIn("https://home.example", "a@b.c", "pw", "", true)
        assertEquals(SetupError.Local(R.string.ui_invite_missing), v.state.value.formError)
        backend.lock = false
        v.signIn("https://home.example", "a@b.c", "pw", "", false)
        assertEquals(SetupError.Local(R.string.ui_need_screen_lock), v.state.value.formError)
        assertTrue(backend.calls.isEmpty())
        backend.lock = true
        v.signIn("https://home.example/", "a@b.c", "pw", "", false)
        assertEquals("signIn:https://home.example:a@b.c:false", backend.calls.single())
        assertEquals(SetupNext.Confirm, v.state.value.next)
        v.confirm(); v.lockPassed(LockRequest.Pair) // the same screen lock and claim as a typed code
        assertEquals("claim:https://home.example:QRSTYLECODE0123456789abcdefgh:owner@example.com", backend.calls[1])
    }

    @Test fun aFailedSignInShowsOnlyTheSafeText() {
        backend.signInResult = Result.failure(AccountApi.ApiError("Wrong email or password.", 401))
        val v = vm()
        v.signIn("https://home.example", "a@b.c", "pw", "", false)
        assertEquals(SetupError.Shown("shown:Wrong email or password."), v.state.value.formError)
        assertNull(v.state.value.checked)
    }

    @Test fun developerTokenAsksConnectAndTheLockOnlyToReplace() {
        val v = vm()
        v.submitToken("http://example.com", "tok")
        assertEquals(SetupError.Local(R.string.ui_invalid_server), v.state.value.formError)
        v.submitToken("http://192.168.1.5:8765", "")
        assertEquals(SetupError.Local(R.string.ui_missing_token), v.state.value.formError)
        v.submitToken("http://192.168.1.5:8765", " tok ")
        assertEquals("http://192.168.1.5:8765" to "tok", v.state.value.tokenPending) // "Connect to …?" shows
        assertTrue(backend.calls.isEmpty())
        v.confirmToken() // not paired: no lock needed
        assertEquals("token:http://192.168.1.5:8765:tok", backend.calls.single())
        // Now paired: replacing needs the screen lock first.
        v.submitToken("http://192.168.1.6:8765", "tok2")
        v.confirmToken()
        assertEquals(LockRequest.Token, v.state.value.lock)
        assertEquals(1, backend.calls.size)
        v.lockPassed(LockRequest.Token)
        assertEquals("token:http://192.168.1.6:8765:tok2", backend.calls[1])
    }

    @Test fun cancellingTheTokenSavesNothing() {
        val v = vm()
        v.submitToken("http://192.168.1.5:8765", "tok")
        v.cancelToken()
        assertNull(v.state.value.tokenPending)
        assertTrue(backend.calls.isEmpty())
    }

    @Test fun accessibilityAlreadyOnSkipsTheConsentScreen() {
        backend.phone = PhoneSetup(accessibilityOn = true)
        val v = vm()
        v.setCode("K7P2QX"); v.submitCode(); v.confirm(); v.lockPassed(LockRequest.Pair)
        assertEquals(SetupNext.Ready, v.state.value.next)
    }
}
