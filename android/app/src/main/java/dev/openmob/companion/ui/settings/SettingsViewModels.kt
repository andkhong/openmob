package dev.openmob.companion.ui.settings

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import dev.openmob.companion.ControlIndicator
import dev.openmob.companion.IndicatorColors
import dev.openmob.companion.IndicatorPrefs
import dev.openmob.companion.PillCorner
import dev.openmob.companion.R
import dev.openmob.companion.ui.state.AppOwnerControls
import dev.openmob.companion.ui.state.AppPhoneSource
import dev.openmob.companion.ui.state.OwnerControls
import dev.openmob.companion.ui.state.PhoneSource
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/*
 * Settings and the agent indicator settings. Both change only what OpenMob's own UI already changes, through the
 * same calls: Faster mode through ConnectionService (turning it on still goes server → approval → ApprovalActivity
 * behind the screen lock), the indicator through IndicatorPrefs plus ControlIndicator.refresh. No server, API or
 * protocol method reaches these; agents can't tap OpenMob's own screens (the gate's own_packages rule).
 */

data class SettingsUiState(
    val connected: Boolean = false,
    val fasterOn: Boolean = false,
    /** "session" or "phone" while on. */
    val fasterScope: String = "off",
    val neverUntil: Long = 0,
    /** The signed standing mode (the most this phone allows), or null when unknown. */
    val mode: String? = null,
    /** The server's mode when it differs, labelled as the server's (not enforced by the phone). */
    val serverMode: String? = null,
    val paired: Boolean = false,
    val serverHost: String = "",
    val checksDone: Int = 0,
    val checksTotal: Int = 4,
    val border: Boolean = true,
    val color: String = IndicatorColors.DEFAULT,
    val pill: Boolean = true,
    val corner: PillCorner = PillCorner.TOP_RIGHT,
    // --- About (§3.7) ----------------------------------------------------------------------------------------
    val appVersionCode: Int = 1,
    val appHash: String = "",
    /** The server's latest versionCode from the last welcome; null: not known (not connected, or no APK). */
    val latestVersion: Int? = null,
    /** latest is above this app's version (shown whether or not Home's card was put off). */
    val updateAvailable: Boolean = false,
    val updateDownloadable: Boolean = false,
)

class SettingsViewModel(
    private val source: PhoneSource,
    private val controls: OwnerControls,
    private val prefs: IndicatorPrefs,
    private val clock: () -> Long = System::currentTimeMillis,
) : ViewModel() {
    private val _state = MutableStateFlow(read())
    val state: StateFlow<SettingsUiState> = _state.asStateFlow()
    private val _notice = MutableStateFlow<Int?>(null)
    val notice: StateFlow<Int?> = _notice.asStateFlow()
    private val unsubscribe = source.listen { refresh() }

    private fun read(): SettingsUiState {
        val s = source.snapshot()
        val p = prefs.snapshot()
        return SettingsUiState(
            connected = s.connected,
            fasterOn = s.fasterOn,
            fasterScope = s.fasterScope,
            neverUntil = if (s.neverUntil * 1000 > clock()) s.neverUntil else 0,
            mode = s.mode,
            serverMode = s.serverMode,
            paired = s.paired,
            serverHost = s.serverHost,
            checksDone = s.checksDone,
            border = p.border,
            color = p.color,
            pill = p.pill,
            corner = p.corner,
            appVersionCode = s.appVersionCode,
            appHash = s.appHash,
            latestVersion = s.update?.latest,
            updateAvailable = dev.openmob.companion.UpdateLogic.newer(s.appVersionCode, s.update),
            updateDownloadable = s.updateDownloadable,
        )
    }

    /** Download update: the browser opens the paired server's own APK; anything else is refused (and logged). */
    fun downloadUpdate() { if (!controls.downloadUpdate()) _notice.value = R.string.update_link_refused }

    /** Also on resume: the indicator screen may have changed the summary. */
    fun refresh() { _state.value = read() }

    /** MainActivity.askFaster: the server answers with an approval the owner signs here, behind the screen lock. */
    fun requestFaster(scope: String) {
        // Display only: read before the request goes, since the prompt that would follow is dropped while the phone's
        // 2-an-hour limit is full. The request itself is sent as before.
        val wait = controls.fasterRetryInMs()
        val sent = controls.requestFaster(scope)
        if (sent && wait > 0) {
            _limitedMinutes.value = ((wait + 59_999) / 60_000).toInt().coerceAtLeast(1)
            return
        }
        _notice.value = if (sent) R.string.faster_asked else R.string.faster_offline
    }

    private val _limitedMinutes = MutableStateFlow<Int?>(null)
    /** "Limit reached: try again in N minutes", shown in place of the "asked" notice; null when not limited. */
    val limitedMinutes: StateFlow<Int?> = _limitedMinutes.asStateFlow()

    fun limitedShown() { _limitedMinutes.value = null }

    /** One tap, no lock (a tightening). */
    fun turnOffFaster() {
        controls.turnOffFaster()
        _notice.value = R.string.faster_turned_off
        refresh()
    }

    fun noticeShown() { _notice.value = null }

    override fun onCleared() { unsubscribe() }

    companion object {
        fun factory(context: Context): ViewModelProvider.Factory {
            val app = context.applicationContext
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T =
                    SettingsViewModel(AppPhoneSource(app), AppOwnerControls(app), ControlIndicator.prefs(app)) as T
            }
        }
    }
}

data class IndicatorUiState(
    val border: Boolean = true,
    /** A preset key or "#RRGGBB". */
    val color: String = IndicatorColors.DEFAULT,
    val pulse: Boolean = true,
    val pill: Boolean = true,
    val corner: PillCorner = PillCorner.TOP_RIGHT,
    /** The custom colour field, as typed. */
    val customText: String = "",
    val customInvalid: Boolean = false,
    /** The custom colour is close to the approval amber (similar hue and lightness): warn, suggest another. */
    val nearAmber: Boolean = false,
) {
    val customChosen: Boolean get() = color.startsWith("#")
}

/** The indicator settings: the same IndicatorPrefs the overlay reads, and ControlIndicator.refresh after each change
 *  (MainActivity's indicator card did exactly this). */
class IndicatorViewModel(
    private val prefs: IndicatorPrefs,
    private val onChanged: () -> Unit,
    private val onPreview: () -> Unit,
) : ViewModel() {
    private val _state = MutableStateFlow(read(prefs.color.takeIf { it.startsWith("#") }.orEmpty(), false))
    val state: StateFlow<IndicatorUiState> = _state.asStateFlow()

    private fun read(customText: String, invalid: Boolean): IndicatorUiState {
        val p = prefs.snapshot()
        return IndicatorUiState(p.border, p.color, p.pulse, p.pill, p.corner, customText, invalid)
    }

    private fun changed() {
        _state.value = read(_state.value.customText, false)
        onChanged()
    }

    fun setBorder(on: Boolean) { prefs.border = on; changed() }
    fun setPulse(on: Boolean) { prefs.pulse = on; changed() }
    fun setPill(on: Boolean) { prefs.pill = on; changed() }
    fun setCorner(corner: PillCorner) { prefs.corner = corner; changed() }

    /** A preset's key. */
    fun setPreset(key: String) {
        if (IndicatorColors.PRESETS.none { it.key == key }) return
        prefs.color = key
        changed()
    }

    fun setCustomText(text: String) { _state.value = _state.value.copy(customText = text.take(9), customInvalid = false) }

    /** As MainActivity's custom dialog: "#" added if missing, six hex digits, else nothing changes. */
    fun applyCustom(): Boolean {
        val v = _state.value.customText.trim().let { if (it.startsWith("#")) it else "#$it" }
        if (!IndicatorColors.valid(v)) {
            _state.value = _state.value.copy(customInvalid = true)
            return false
        }
        prefs.color = v
        _state.value = read(v.uppercase(), false).copy(nearAmber = nearAmber(IndicatorColors.argb(v)))
        onChanged()
        return true
    }

    /** Similar hue (IndicatorColors.nearApproval, 25°) and similar lightness (luminance within 0.15) to the amber. */
    private fun nearAmber(argb: Int): Boolean =
        IndicatorColors.nearApproval(argb) &&
            kotlin.math.abs(IndicatorColors.luminance(argb) - IndicatorColors.luminance(IndicatorColors.APPROVAL)) < 0.15

    /** The owner's 4-second preview (ControlIndicator.preview). */
    fun preview() = onPreview()

    companion object {
        fun factory(context: Context): ViewModelProvider.Factory {
            val app = context.applicationContext
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T = IndicatorViewModel(
                    ControlIndicator.prefs(app),
                    onChanged = { ControlIndicator.refresh() },
                    onPreview = { ControlIndicator.preview(app) },
                ) as T
            }
        }
    }
}
