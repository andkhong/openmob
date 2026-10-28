package dev.openmob.companion.ui

import android.content.Intent
import androidx.navigation.NavController
import androidx.navigation.NavHostController
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.MainActivity
import dev.openmob.companion.ui.nav.Route
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config

/** Review 3 P3-L3 (the reviewer's P3NavDeepLinkPocTest, fixed): another app's intent with Navigation's deep-link
 *  extras no longer opens an arbitrary OpenMob screen; only the action and the link reach the activity. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class MainActivityIntentTest {
    private val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()

    private fun launch(intent: Intent): MainActivity {
        val ctl = Robolectric.buildActivity(MainActivity::class.java, intent).setup().visible()
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
        return ctl.get()
    }

    private fun nav(a: MainActivity): NavHostController? =
        MainActivity::class.java.getDeclaredField("nav").apply { isAccessible = true }.get(a) as NavHostController?

    @Test fun deepLinkExtrasDontOpenAnyScreen() {
        val target = "android-app://androidx.navigation/${Route.Indicator.path}".hashCode()
        val intent = Intent().setClassName(ctx.packageName, MainActivity::class.java.name)
            .putExtra(NavController.KEY_DEEP_LINK_IDS, intArrayOf(0, target))
            .putExtra(NavController.KEY_DEEP_LINK_EXTRAS, android.os.Bundle())
        val a = launch(intent)
        val n = nav(a)!!
        assertNotEquals(Route.Indicator.path, n.currentDestination?.route)
        assertFalse(n.currentBackStack.value.any { it.destination.route == Route.Indicator.path })
        assertNull(a.intent.extras) // nothing of the caller's extras is left for a recreation to follow
    }

    @Test fun shortcutsAndLinksKeepTheirActionAndData() {
        val a = launch(Intent(ctx, MainActivity::class.java))
        val dirty = Intent("dev.openmob.SOME_ACTION").setData(android.net.Uri.parse("openmob://connect?x=1"))
            .putExtra(NavController.KEY_DEEP_LINK_IDS, intArrayOf(1, 2)).putExtra("other", "x")
        val clean = a.cleanIntent(dirty)
        assertEquals("dev.openmob.SOME_ACTION", clean.action)
        assertEquals("openmob://connect?x=1", clean.data.toString())
        assertNull(clean.extras)
        assertEquals(MainActivity::class.java.name, clean.component?.className)
    }

    /** The agent's question notification (AgentQuestion): its tap opens Home, where the composer answers, from any
     *  screen of the app, with nothing but the action. */
    @Test fun openHomeActionShowsHomeFromAnotherScreen() {
        val ctl = Robolectric.buildActivity(MainActivity::class.java, Intent(ctx, MainActivity::class.java)).setup().visible()
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
        val n = nav(ctl.get())!!
        n.navigate(Route.Settings.path)
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
        assertEquals(Route.Settings.path, n.currentDestination?.route)
        ctl.newIntent(Intent(ctx, MainActivity::class.java).setAction(dev.openmob.companion.AgentQuestion.ACTION_OPEN_HOME))
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
        assertEquals(Route.Home.path, n.currentDestination?.route)
        assertFalse(n.currentBackStack.value.any { it.destination.route == Route.Settings.path })
    }
}
