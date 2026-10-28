package dev.openmob.companion.ui

import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.os.Looper
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.TextView
import androidx.compose.ui.platform.ComposeView
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.ActionDigest
import dev.openmob.companion.ApprovalActivity
import dev.openmob.companion.Approvals
import dev.openmob.companion.R
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Robolectric
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.time.Duration

/**
 * The approval screen's protections (docs/design/redesign-approval.md), checked on the real ApprovalActivity: the
 * Compose screen (step 6: the only approval UI) with its two embedded original controls. What only a device can show
 * (a real overlay, a
 * real accessibility service, the system screen lock) is listed in that doc.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ApprovalProtectionTest {

    private val ctx: Context = ApplicationProvider.getApplicationContext()

    @Before fun setUp() {
        // Declared in the manifest (P2); Robolectric grants it only when told.
        Shadows.shadowOf(ctx as android.app.Application).grantPermissions(android.Manifest.permission.HIDE_OVERLAY_WINDOWS)
        // Robolectric's phone has no screen lock (BiometricManager can't authenticate): Approve stops at "needs a lock".
    }

    @After fun tearDown() {
        Approvals.clear(ctx)
    }

    /** A pending server approval (a permission change), put straight into Approvals' table. */
    private fun pending(id: String, digestOk: Boolean = true, canApprove: Boolean = true, withAlways: Boolean = false): Approvals.Request {
        val action = mapOf("tool" to "mode_change", "input" to "Let agents ask less on this phone?")
        val r = Approvals.Request(
            id = id, taskId = "t1", question = "SERVER QUESTION", requester = "Claude", kind = "mode_change",
            action = action, digest = if (digestOk) ActionDigest.of(action) else "0000", signatureRequired = true,
            canApprove = canApprove,
            always = if (withAlways) Approvals.Always("com.example", "send", 30.0, "Agents could send as you", false) else null,
        )
        @Suppress("UNCHECKED_CAST")
        val table = Approvals::class.java.getDeclaredField("pending").apply { isAccessible = true }.get(Approvals)
            as LinkedHashMap<String, Approvals.Request>
        table[id] = r
        return r
    }

    private fun launch(id: String): ApprovalActivity {
        val intent = Intent(ctx, ApprovalActivity::class.java).putExtra(Approvals.EXTRA_ID, id)
        val activity = Robolectric.buildActivity(ApprovalActivity::class.java, intent).setup().visible().get()
        Shadows.shadowOf(Looper.getMainLooper()).idle()
        return activity
    }

    private fun all(v: View): List<View> = listOf(v) + ((v as? ViewGroup)?.let { g -> (0 until g.childCount).flatMap { all(g.getChildAt(it)) } } ?: emptyList())
    private fun views(a: ApprovalActivity) = all(a.window.decorView)
    /** The original Approve Button, as laid out on the screen (its label is "Approve with screen lock" or "Allow"). */
    private fun approve(a: ApprovalActivity) = views(a).filterIsInstance<Button>().first { it === approveField(a) }
    private fun approveOrNull(a: ApprovalActivity) = views(a).filterIsInstance<Button>().firstOrNull { it === approveField(a) }
    private fun always(a: ApprovalActivity) = views(a).filterIsInstance<CheckBox>().single()
    private fun shownText(a: ApprovalActivity) = views(a).filterIsInstance<TextView>().filter { it.isShown }.joinToString("\n") { it.text.toString() }

    private fun tap(v: View, obscured: Boolean): Boolean {
        val props = arrayOf(MotionEvent.PointerProperties().apply { id = 0; toolType = MotionEvent.TOOL_TYPE_FINGER })
        val coords = arrayOf(MotionEvent.PointerCoords().apply { x = 5f; y = 5f; pressure = 1f; size = 1f })
        val flags = if (obscured) MotionEvent.FLAG_WINDOW_IS_OBSCURED else 0
        val now = SystemClock.uptimeMillis()
        fun ev(action: Int) = MotionEvent.obtain(now, now, action, 1, props, coords, 0, 0, 1f, 1f, 0, 0,
                                                  android.view.InputDevice.SOURCE_TOUCHSCREEN, flags)
        val down = v.dispatchTouchEvent(ev(MotionEvent.ACTION_DOWN))
        v.dispatchTouchEvent(ev(MotionEvent.ACTION_UP))
        Shadows.shadowOf(Looper.getMainLooper()).idle()
        return down
    }

    @Test fun theComposeScreenIsTheOnlyUi() {
        pending("a1")
        val a = launch("a1")
        assertTrue(views(a).any { it is ComposeView })
        // The old view rendering is gone: the only Android Button and CheckBox are the two original controls.
        assertEquals(1, views(a).filterIsInstance<Button>().size)
    }

    @Test fun p1_flagSecure() {
        pending("a1")
        val a = launch("a1")
        assertTrue(a.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0)
    }

    /** P2: onCreate hides other apps' overlays, which needs the declared HIDE_OVERLAY_WINDOWS: without it, it throws. */
    @Test fun p2_hidingOverlaysIsDeclaredAndCalled() {
        val pkg = ctx.packageManager.getPackageInfo(ctx.packageName, android.content.pm.PackageManager.GET_PERMISSIONS)
        assertTrue(android.Manifest.permission.HIDE_OVERLAY_WINDOWS in pkg.requestedPermissions.orEmpty())
        Shadows.shadowOf(ctx as android.app.Application).denyPermissions(android.Manifest.permission.HIDE_OVERLAY_WINDOWS)
        pending("a1")
        val thrown = runCatching { launch("a1") }.exceptionOrNull()
        assertTrue("setHideOverlayWindows is called in onCreate", thrown is SecurityException)
    }

    @Test fun p3_p4_approveAndAlwaysKeepTheirFlags() {
        pending("a1", withAlways = true)
        val a = launch("a1")
        val approve = approve(a)
        val box = always(a)
        assertTrue(approve.filterTouchesWhenObscured)
        assertTrue(box.filterTouchesWhenObscured)
        assertTrue(approve.isAccessibilityDataSensitive)
        assertTrue(box.isAccessibilityDataSensitive)
        assertTrue(approve.isShown)
        assertTrue(box.isShown)
    }

    @Test fun p3_anObscuredTouchOnApproveDoesNothing() {
        pending("a1")
        val a = launch("a1")
        // On this test phone onApprove stops before any prompt (no screen lock or no Keystore key), with a status.
        val stops = setOf(ctx.getString(R.string.approval_need_lock), ctx.getString(R.string.approval_no_key))
        tap(approve(a), obscured = true)
        assertEquals(null, statusOf(a)) // dropped: onApprove never ran
        tap(approve(a), obscured = false)
        assertTrue(statusOf(a) in stops) // a plain touch reaches onApprove
        assertNotNull(Approvals.get("a1"))
    }

    /** The same, delivered the way a real touch is: to the window, at Approve's place (through Compose's interop). */
    @Test fun p3_anObscuredTouchThroughTheWindowDoesNothing() {
        pending("a1")
        val a = launch("a1")
        val b = approve(a)
        val at = IntArray(2).also { b.getLocationInWindow(it) }
        assertTrue("Approve is laid out", b.width > 0 && b.height > 0)
        fun touch(obscured: Boolean) {
            val x = at[0] + b.width / 2f
            val y = at[1] + b.height / 2f
            val now = SystemClock.uptimeMillis()
            val flags = if (obscured) MotionEvent.FLAG_WINDOW_IS_OBSCURED else 0
            val props = arrayOf(MotionEvent.PointerProperties().apply { id = 0; toolType = MotionEvent.TOOL_TYPE_FINGER })
            fun ev(action: Int) = MotionEvent.obtain(now, now, action, 1, props,
                arrayOf(MotionEvent.PointerCoords().apply { this.x = x; this.y = y; pressure = 1f; size = 1f }),
                0, 0, 1f, 1f, 0, 0, android.view.InputDevice.SOURCE_TOUCHSCREEN, flags)
            a.window.decorView.dispatchTouchEvent(ev(MotionEvent.ACTION_DOWN))
            a.window.decorView.dispatchTouchEvent(ev(MotionEvent.ACTION_UP))
            Shadows.shadowOf(Looper.getMainLooper()).idle()
        }
        touch(obscured = true)
        assertEquals(null, statusOf(a))
        touch(obscured = false)
        assertNotNull(statusOf(a))
    }

    /** The status line the screen shows. */
    private fun statusOf(a: ApprovalActivity): String? {
        val f = ApprovalActivity::class.java.getDeclaredField("status").apply { isAccessible = true }
        @Suppress("UNCHECKED_CAST")
        return (f.get(a) as androidx.compose.runtime.MutableState<String?>).value
    }

    /** The original Approve Button object, whether or not the screen shows it now. */
    private fun approveField(a: ApprovalActivity): Button =
        ApprovalActivity::class.java.getDeclaredField("approveButton").apply { isAccessible = true }.get(a) as Button

    /** P13 (the countdown, 2026-10-17): once its 2 minutes are up by the phone's clock, Approve does nothing, even
     *  before the expiry timer has removed it. */
    @Test fun p13_approveAfterTheTwoMinutesIsRefused() {
        val r = pending("a1")
        @Suppress("UNCHECKED_CAST")
        val table = Approvals::class.java.getDeclaredField("pending").apply { isAccessible = true }.get(Approvals)
            as LinkedHashMap<String, Approvals.Request>
        org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofMinutes(5))
        table["a1"] = r.copy(receivedAt = SystemClock.uptimeMillis() - Approvals.EXPIRY_MS - 1)
        val a = launch("a1")
        assertTrue("the screen took Approve away at 0", approveOrNull(a)?.isShown != true)
        // Even a click that reached the original Button (it's still the same object) is refused by onApprove.
        approveField(a).performClick()
        Shadows.shadowOf(Looper.getMainLooper()).idle()
        assertEquals(ctx.getString(R.string.approval_gone), statusOf(a))
        assertNotNull(Approvals.get("a1")) // nothing was sent
    }

    @Test fun approveIsHiddenAtZero() {
        val r = pending("a1")
        @Suppress("UNCHECKED_CAST")
        val table = Approvals::class.java.getDeclaredField("pending").apply { isAccessible = true }.get(Approvals)
            as LinkedHashMap<String, Approvals.Request>
        org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofMinutes(5))
        table["a1"] = r.copy(receivedAt = SystemClock.uptimeMillis() - Approvals.EXPIRY_MS - 1)
        val a = launch("a1")
        assertTrue(approveOrNull(a)?.isShown != true)
    }

    @Test fun p6_approveWithoutAScreenLockNeverAnswers() {
        pending("a1")
        val a = launch("a1")
        tap(approve(a), obscured = false)
        assertNotNull(Approvals.get("a1")) // still pending: nothing was sent
    }

    @Test fun p11_aMismatchedDigestLeavesOnlyDeny() {
        pending("a1", digestOk = false)
        val a = launch("a1")
        assertTrue(views(a).filterIsInstance<Button>().none { it === approveField(a) && it.isShown })
        assertEquals(ctx.getString(R.string.approval_mismatch), statusOf(a))
    }

    @Test fun p11_aPhoneThatCantSignCanOnlyDeny() {
        pending("a1", canApprove = false)
        val a = launch("a1")
        assertTrue(views(a).filterIsInstance<Button>().none { it === approveField(a) && it.isShown })
    }

    @Test fun p13_anAnsweredOrExpiredRequestCantBeApproved() {
        val a = launch("gone")
        assertTrue(views(a).filterIsInstance<Button>().none { it === approveField(a) && it.isShown && it.isEnabled })
    }

    @Test fun p16_p17_noDefaultFocusAndAlwaysStartsOff() {
        pending("a1", withAlways = true)
        val a = launch("a1")
        assertFalse(approve(a).isFocused)
        assertFalse(always(a).isChecked)
        val focused = a.currentFocus
        assertTrue(focused == null || focused is ComposeView || focused !is Button)
    }

    @Test fun theRedesignEmbedsTheOriginalApproveButton() {
        pending("a1")
        val a = launch("a1")
        val field = ApprovalActivity::class.java.getDeclaredField("approveButton").apply { isAccessible = true }
        assertSame(field.get(a), approve(a))
    }

}
