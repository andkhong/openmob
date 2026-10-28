package dev.openmob.companion.ui

import android.content.ComponentName
import androidx.activity.ComponentActivity
import androidx.test.core.app.ApplicationProvider
import org.junit.rules.ExternalResource
import org.junit.rules.RuleChain
import org.junit.rules.TestRule
import org.robolectric.Shadows

/**
 * The Compose tests host their content in a plain ComponentActivity. `ui-test-manifest` declares it for debug only
 * (it must never ship in a release APK), so under testReleaseUnitTest / testLocalUnitTest Robolectric is told about
 * it here instead. In debug it is already declared and this does nothing.
 */
class ComponentActivityRegistered : ExternalResource() {
    override fun before() {
        val app = ApplicationProvider.getApplicationContext<android.app.Application>()
        Shadows.shadowOf(app.packageManager).addActivityIfNotPresent(ComponentName(app, ComponentActivity::class.java))
    }
}

/** [compose] wrapped so the host activity is registered first. */
fun hostedBy(compose: TestRule): RuleChain = RuleChain.outerRule(ComponentActivityRegistered()).around(compose)
