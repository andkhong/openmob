package dev.openmob.companion.ui

import dev.openmob.companion.IndicatorPrefs
import dev.openmob.companion.IndicatorStore
import dev.openmob.companion.PillCorner
import dev.openmob.companion.R
import dev.openmob.companion.ui.settings.IndicatorViewModel
import dev.openmob.companion.ui.settings.SettingsViewModel
import dev.openmob.companion.ui.state.PhoneSnapshot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MapStore : IndicatorStore {
    val map = mutableMapOf<String, Any>()
    override fun bool(key: String, default: Boolean) = map[key] as? Boolean ?: default
    override fun str(key: String, default: String) = map[key] as? String ?: default
    override fun put(key: String, value: Boolean) { map[key] = value }
    override fun put(key: String, value: String) { map[key] = value }
}

/** Settings and the indicator settings write only what MainActivity's cards wrote, through the same calls. */
class SettingsViewModelTest {
    private val store = MapStore()
    private val prefs = IndicatorPrefs(store)
    private var refreshed = 0
    private var previewed = 0
    private fun indicator() = IndicatorViewModel(prefs, onChanged = { refreshed++ }, onPreview = { previewed++ })

    @Test fun indicatorDefaultsAreTheOverlaysDefaults() {
        val s = indicator().state.value
        assertTrue(s.border); assertTrue(s.pill); assertTrue(s.pulse)
        assertEquals("blue", s.color)
        assertEquals(PillCorner.TOP_RIGHT, s.corner)
    }

    @Test fun eachChangeIsSavedAndRefreshesTheOverlay() {
        val vm = indicator()
        vm.setBorder(false); vm.setPill(false); vm.setPulse(false); vm.setCorner(PillCorner.BOTTOM_LEFT); vm.setPreset("green")
        val p = prefs.snapshot()
        assertFalse(p.border); assertFalse(p.pill); assertFalse(p.pulse)
        assertEquals(PillCorner.BOTTOM_LEFT, p.corner)
        assertEquals("green", p.color)
        assertEquals(5, refreshed)
        assertEquals("green", vm.state.value.color)
        vm.setPreset("not-a-preset")
        assertEquals("green", prefs.color)
        assertEquals(5, refreshed)
    }

    @Test fun customColourIsValidatedAsBefore() {
        val vm = indicator()
        vm.setCustomText("12")
        assertFalse(vm.applyCustom())
        assertTrue(vm.state.value.customInvalid)
        assertEquals("blue", prefs.color)
        vm.setCustomText("00b8d4") // "#" added, as MainActivity's dialog did
        assertTrue(vm.applyCustom())
        assertEquals("#00B8D4", prefs.color)
        assertTrue(vm.state.value.customChosen)
        assertEquals("#00B8D4", vm.state.value.customText)
    }

    @Test fun previewIsTheOverlaysPreview() {
        indicator().preview()
        assertEquals(1, previewed)
    }

    @Test fun fasterModeTurnOnAsksTheServerAndOffIsOneTap() {
        val source = FakeSource(PhoneSnapshot(connected = true, running = true))
        val controls = FakeControls()
        val vm = SettingsViewModel(source, controls, prefs)
        vm.requestFaster("session")
        assertEquals(R.string.faster_asked, vm.notice.value)
        controls.connected = false
        vm.requestFaster("phone")
        assertEquals(R.string.faster_offline, vm.notice.value)
        vm.turnOffFaster()
        assertEquals(R.string.faster_turned_off, vm.notice.value)
        assertEquals(listOf("faster:session", "faster:phone", "fasterOff"), controls.calls)
    }

    // Owner, 2026-10-17: a request the 2-an-hour limit will drop says so, with the wait, instead of "asked".
    @Test fun aFasterRequestPastTheLimitSaysWhenToTryAgain() {
        val controls = FakeControls(retryInMs = 61 * 60_000L / 2) // 30.5 min left in the window
        val vm = SettingsViewModel(FakeSource(PhoneSnapshot(connected = true, running = true)), controls, prefs)
        vm.requestFaster("session")
        assertEquals(31, vm.limitedMinutes.value)   // rounded up
        assertEquals(null, vm.notice.value)         // not the "asked" toast
        assertEquals(listOf("faster:session"), controls.calls) // still sent, as before
        vm.limitedShown()
        controls.retryInMs = 0
        vm.requestFaster("session")
        assertEquals(null, vm.limitedMinutes.value)
        assertEquals(R.string.faster_asked, vm.notice.value)
    }

    @Test fun settingsFollowTheIndicatorPrefsOnRefresh() {
        val vm = SettingsViewModel(FakeSource(), FakeControls(), prefs)
        prefs.color = "pink"
        prefs.pill = false
        vm.refresh()
        assertEquals("pink", vm.state.value.color)
        assertFalse(vm.state.value.pill)
    }
}
