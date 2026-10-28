package dev.openmob.companion.ui.setup

import android.content.res.Configuration
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import dev.openmob.companion.R
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.theme.OpenMobTheme

/** Example states (made-up values) for the previews and screenshot tests. */
object SetupSamples {
    private val checked = Checked("https://home-server.local", "K7P2QX", "owner@example.com")
    val fresh = SetupUiState()
    val codeTyped = SetupUiState(code = "k7p-2qx")
    val codeWrong = SetupUiState(code = "K7P-2QB",
        codeError = SetupError.Shown("Wrong code. Check it on your dashboard, or make a new one there."))
    val codeShape = SetupUiState(code = "K7P-2", codeError = SetupError.Local(R.string.rd_setup_code_shape))
    val more = SetupUiState(serverInput = "http://example.com", serverError = R.string.ui_invalid_server, code = "K7P2QX")
    val confirm = SetupUiState(checked = checked)
    val replace = SetupUiState(checked = checked,
        phone = PhoneSetup(paired = true, server = "https://openmob.fly.dev", email = "current@example.com"))
    val consent = SetupUiState(phone = PhoneSetup(paired = true, server = "https://home-server.local", email = "owner@example.com"))
    val ready = SetupUiState(phone = PhoneSetup(paired = true, server = "https://home-server.local", email = "owner@example.com",
        accessibilityOn = true, running = true, connected = true))

    val signIn = SetupUiState(phone = PhoneSetup(server = "https://openmob.fly.dev"))
    val token = SetupUiState(phone = PhoneSetup(paired = true, server = "https://openmob.fly.dev", email = "owner@example.com"),
        tokenPending = "http://192.168.1.20:8765" to "dev-token")
    val connection = SetupUiState(phone = PhoneSetup(paired = true, server = "https://home-server.local", email = "owner@example.com",
        running = true, connected = true, liveViewRequested = true, deviceId = "3f2a9c4e-0000-4000-8000-000000000000"))

    /** Every setup screen with an example state (name, route, state). */
    val all: List<Triple<String, Route, SetupUiState>> = listOf(
        Triple("welcome", Route.SetupWelcome, fresh),
        Triple("pair", Route.SetupPair, fresh),
        Triple("code", Route.SetupPairCode, codeTyped),
        Triple("code-wrong", Route.SetupPairCode, codeWrong),
        Triple("code-shape", Route.SetupPairCode, codeShape),
        Triple("more", Route.SetupPairMore, more),
        Triple("confirm", Route.SetupConfirm, confirm),
        Triple("replace", Route.SetupReplace, replace),
        Triple("consent", Route.SetupConsent, consent),
        Triple("ready", Route.SetupReady, ready),
        Triple("signin", Route.SetupSignIn, signIn),
        Triple("token-confirm", Route.SetupToken, token),
        Triple("connection", Route.Connection, connection),
    )
}

@Preview(name = "Setup confirm, light", widthDp = 390, heightDp = 844)
@Preview(name = "Setup confirm, dark", widthDp = 390, heightDp = 844, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun SetupConfirmPreview() {
    OpenMobTheme { SetupScreenFor(Route.SetupConfirm, SetupSamples.confirm, SetupActions()) }
}

@Preview(name = "Setup code, light", widthDp = 390, heightDp = 844)
@Composable
private fun SetupCodePreview() {
    OpenMobTheme { SetupScreenFor(Route.SetupPairCode, SetupSamples.codeWrong, SetupActions()) }
}
