package dev.openmob.companion.ui.setup

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import dev.openmob.companion.PairingFlow
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.DangerButton
import dev.openmob.companion.ui.components.MonoValue
import dev.openmob.companion.ui.components.OmCard
import dev.openmob.companion.ui.components.OmTextField
import dev.openmob.companion.ui.components.PrimaryButton
import dev.openmob.companion.ui.components.SecondaryButton
import dev.openmob.companion.ui.components.StatusChip
import dev.openmob.companion.ui.components.StatusKind
import dev.openmob.companion.ui.components.ToggleRow
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.nav.ScreenScaffold
import dev.openmob.companion.ui.theme.OpenMobTheme

/*
 * Step 6: what only the old screen had, in the new design. The sign-in fallback and the developer token (More
 * options), and Connection and pairing (live view, unpair, device id). Each calls the old screen's code path through
 * PairingFlow and SetupViewModel: the same checks, prompts and saving.
 */

@Composable
private fun FormError(state: SetupUiState) {
    val e = when (val f = state.formError) {
        null -> null
        is SetupError.Local -> stringResource(f.res)
        is SetupError.Shown -> f.text
    } ?: return
    Text(e, style = MaterialTheme.typography.bodySmall, color = OpenMobTheme.colors.onDangerContainer,
         modifier = Modifier.fillMaxWidth())
}

/** Sign in on this phone (no computer nearby): the session lives a few seconds in memory; then the usual confirm. */
@Composable
fun SetupSignInScreen(state: SetupUiState, onSubmit: (server: String, email: String, password: String, invite: String, create: Boolean) -> Unit,
                      back: () -> Unit) {
    if (!SecureWhileShown()) return // a password is typed here
    var server by rememberSaveable { mutableStateOf(state.phone.server.ifEmpty { PairingFlow.HOSTED_SERVER }) }
    var email by rememberSaveable { mutableStateOf(state.phone.email) }
    var password by rememberSaveable { mutableStateOf("") }
    var invite by rememberSaveable { mutableStateOf("") }
    ScreenScaffold(title = stringResource(Route.SetupSignIn.title), onBack = back, setupStep = 1) {
        Text(stringResource(R.string.ui_signin_explain), style = MaterialTheme.typography.bodyMedium, color = OpenMobTheme.colors.inkSecondary)
        OmTextField(server, { server = it }, placeholder = stringResource(R.string.ui_server_hint),
                    label = stringResource(R.string.rd_setup_more_address), keyboardType = KeyboardType.Uri,
                    imeAction = ImeAction.Next, autoCorrect = false, modifier = Modifier.fillMaxWidth())
        OmTextField(email, { email = it }, placeholder = stringResource(R.string.ui_email_hint), label = stringResource(R.string.ui_email_hint),
                    keyboardType = KeyboardType.Email, imeAction = ImeAction.Next, autoCorrect = false, modifier = Modifier.fillMaxWidth())
        OmTextField(password, { password = it }, placeholder = stringResource(R.string.ui_password_hint),
                    label = stringResource(R.string.ui_password_hint), keyboardType = KeyboardType.Password,
                    visualTransformation = PasswordVisualTransformation(), autoCorrect = false,
                    onSubmit = { onSubmit(server, email, password, invite, false) }, modifier = Modifier.fillMaxWidth())
        OmTextField(invite, { invite = it }, placeholder = stringResource(R.string.ui_invite_hint), autoCorrect = false,
                    modifier = Modifier.fillMaxWidth())
        FormError(state)
        PrimaryButton(stringResource(if (state.busy) R.string.rd_setup_checking else R.string.ui_signin),
                      onClick = { onSubmit(server, email, password, invite, false) }, enabled = !state.busy)
        SecondaryButton(stringResource(R.string.ui_create_account), onClick = { onSubmit(server, email, password, invite, true) },
                        enabled = !state.busy)
    }
}

/** Developer token (a developer's own server): "Connect to <host>?", and the screen lock when it replaces a pairing. */
@Composable
fun SetupTokenScreen(state: SetupUiState, onSubmit: (server: String, token: String) -> Unit, onConfirm: () -> Unit,
                     onCancel: () -> Unit, back: () -> Unit) {
    if (!SecureWhileShown()) return // the token is typed here
    var server by rememberSaveable { mutableStateOf(state.phone.server) }
    var token by rememberSaveable { mutableStateOf("") }
    ScreenScaffold(title = stringResource(Route.SetupToken.title), onBack = back, setupStep = 1) {
        Text(stringResource(R.string.rd_setup_more_token_body), style = MaterialTheme.typography.bodyMedium,
             color = OpenMobTheme.colors.inkSecondary)
        OmTextField(server, { server = it }, placeholder = stringResource(R.string.ui_server_hint),
                    label = stringResource(R.string.rd_setup_more_address), keyboardType = KeyboardType.Uri,
                    imeAction = ImeAction.Next, autoCorrect = false, modifier = Modifier.fillMaxWidth())
        // Visible-password variation, as before: no autocorrect or suggestions learning the token.
        OmTextField(token, { token = it }, placeholder = stringResource(R.string.ui_token_hint), label = stringResource(R.string.ui_token_hint),
                    keyboardType = KeyboardType.Password, autoCorrect = false, onSubmit = { onSubmit(server, token) },
                    modifier = Modifier.fillMaxWidth())
        FormError(state)
        PrimaryButton(stringResource(R.string.rd_next), onClick = { onSubmit(server, token) })
    }
    state.tokenPending?.let { (target, _) ->
        val host = PairingFlow.hostOf(target)
        AlertDialog(
            onDismissRequest = onCancel,
            title = { Text(stringResource(R.string.ui_connect_title, host)) },
            text = {
                // Scrolls at large text sizes (a dialog's text isn't scrollable by itself).
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    Text(stringResource(R.string.ui_connect_body, host) +
                         if (state.phone.paired) "\n\n" + stringResource(R.string.ui_connect_replaces, state.phone.host) else "")
                }
            },
            confirmButton = { TextButton(onClick = onConfirm, modifier = Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.ui_connect)) } },
            dismissButton = { TextButton(onClick = onCancel, modifier = Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.ui_cancel)) } },
        )
    }
}

data class ConnectionActions(
    val back: () -> Unit = {},
    val connect: () -> Unit = {},
    val disconnect: () -> Unit = {},
    val liveView: (Boolean) -> Unit = {},
    val shareScreen: () -> Unit = {},
    val unpair: () -> Unit = {},
    val pairAgain: () -> Unit = {},
)

/** Connection and pairing: the server and account, Connect/Disconnect, the live view, unpair, the device id. */
@Composable
fun ConnectionScreen(state: SetupUiState, actions: ConnectionActions) {
    val c = OpenMobTheme.colors
    val p = state.phone
    var confirmUnpair by rememberSaveable { mutableStateOf(false) }
    ScreenScaffold(title = stringResource(Route.Connection.title), onBack = actions.back) {
        OmCard {
            when {
                p.connected -> StatusChip(StatusKind.Connected, stringResource(R.string.rd_status_connected))
                p.running -> StatusChip(StatusKind.Info, stringResource(R.string.rd_home_status_connecting))
                else -> StatusChip(StatusKind.Offline, stringResource(R.string.rd_status_offline))
            }
            if (p.paired) {
                MonoValue(label = stringResource(R.string.rd_home_server), value = p.host)
                if (p.email.isNotEmpty()) MonoValue(label = stringResource(R.string.rd_home_account), value = p.email)
                if (p.tokenMode) Text(stringResource(R.string.rd_connection_token_mode), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
                if (p.running) SecondaryButton(stringResource(R.string.ui_disconnect), onClick = actions.disconnect)
                else PrimaryButton(stringResource(R.string.ui_connect), onClick = actions.connect)
            } else {
                Text(stringResource(R.string.ui_pair_first), style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary)
                PrimaryButton(stringResource(R.string.rd_setup_pair_title), onClick = actions.pairAgain)
            }
        }
        OmCard(contentPadding = 0.dp) {
            ToggleRow(stringResource(R.string.ui_live_view), checked = p.smoothLiveView, onCheckedChange = actions.liveView,
                      subtitle = stringResource(R.string.ui_live_view_help))
            if (p.running && p.liveViewRequested && !p.screenSharing) {
                HorizontalDivider(color = c.divider)
                Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(stringResource(R.string.ui_step_screen_title), style = MaterialTheme.typography.titleSmall, color = c.ink)
                    Text(stringResource(R.string.ui_step_screen_body), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
                    SecondaryButton(stringResource(R.string.ui_step_screen_button), onClick = actions.shareScreen)
                }
            }
        }
        if (p.paired) {
            DangerButton(stringResource(R.string.ui_unpair), onClick = { confirmUnpair = true })
            Text(stringResource(R.string.ui_unpair_body), style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
        }
        if (p.deviceId.isNotEmpty()) {
            Row { MonoValue(stringResource(R.string.ui_device_id, p.deviceId), style = OpenMobTheme.mono.small) }
        }
    }
    if (confirmUnpair) {
        AlertDialog(
            onDismissRequest = { confirmUnpair = false },
            title = { Text(stringResource(R.string.ui_unpair_title)) },
            text = { Column(Modifier.verticalScroll(rememberScrollState())) { Text(stringResource(R.string.ui_unpair_body)) } },
            confirmButton = { TextButton(onClick = { confirmUnpair = false; actions.unpair() }, modifier = Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.ui_unpair)) } },
            dismissButton = { TextButton(onClick = { confirmUnpair = false }, modifier = Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.ui_cancel)) } },
        )
    }
}
