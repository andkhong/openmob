package dev.openmob.companion.ui

import android.app.NotificationManager
import android.content.Context
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.PairUndoReceiver
import dev.openmob.companion.PairingFlow
import dev.openmob.companion.R
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.setup.SetupActions
import dev.openmob.companion.ui.setup.SetupSamples
import dev.openmob.companion.ui.setup.SetupScreenFor
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config

/** Owner, 2026-10-17: FLAG_SECURE on the setup screens that show or hold a pairing code; "Paired · Undo" after every
 *  account pairing. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class SetupSecureTest {
    val rule = createAndroidComposeRule<ComponentActivity>()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()

    private fun secure() = rule.activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0

    @Test fun flagSecureOnlyWhileACodeIsShownOrHeld() {
        val route = mutableStateOf(Route.SetupWelcome)
        rule.setContent {
            OpenMobTheme {
                val state = when (route.value) {
                    Route.SetupConfirm -> SetupSamples.confirm
                    Route.SetupReplace -> SetupSamples.replace
                    else -> SetupSamples.codeTyped
                }
                SetupScreenFor(route.value, state, SetupActions())
            }
        }
        val expected = mapOf(
            Route.SetupWelcome to false, Route.SetupPair to false, Route.SetupPairCode to true, Route.SetupPairMore to true,
            Route.SetupConfirm to true, Route.SetupReplace to true, Route.SetupConsent to false, Route.SetupReady to false,
            // Step 6: a password or a developer token is typed on these.
            Route.SetupSignIn to true, Route.SetupToken to true, Route.Connection to false,
        )
        for ((r, want) in expected) {
            route.value = r
            rule.waitForIdle()
            assertEquals("FLAG_SECURE on ${r.name}", want, secure())
        }
        // From the code straight to the confirm screen: never insecure in between (counted holds).
        route.value = Route.SetupPairCode; rule.waitForIdle()
        route.value = Route.SetupConfirm; rule.waitForIdle()
        assertTrue(secure())
        route.value = Route.SetupReady; rule.waitForIdle()
        assertFalse(secure())
    }

    @Test fun pairedNotificationOffersUndoWithoutALock() {
        rule.setContent { }
        Shadows.shadowOf(ctx as android.app.Application).grantPermissions(android.Manifest.permission.POST_NOTIFICATIONS)
        PairingFlow.notifyPaired(ctx, "https://home.example", "owner@example.com")
        val nm = ctx.getSystemService(NotificationManager::class.java)
        val n = Shadows.shadowOf(nm).allNotifications.single()
        assertEquals(ctx.getString(R.string.pair_notification_title, "owner@example.com"),
                     n.extras.getCharSequence(android.app.Notification.EXTRA_TITLE).toString())
        val undo = n.actions.single()
        assertEquals(ctx.getString(R.string.pair_undo), undo.title.toString())
        val intent = Shadows.shadowOf(undo.actionIntent).savedIntent
        assertEquals(PairUndoReceiver::class.java.name, intent.component?.className)
        assertEquals(PairingFlow.ACTION_UNDO, intent.action)
        assertTrue(Shadows.shadowOf(undo.actionIntent).isBroadcast)
        assertNotNull(PairingFlow.undoExtras(intent).first)
        // The receiver isn't exported (manifest) and the PendingIntent is immutable.
        assertTrue(undo.actionIntent.isImmutable)
    }
}
