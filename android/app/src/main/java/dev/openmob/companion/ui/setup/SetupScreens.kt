package dev.openmob.companion.ui.setup

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import dev.openmob.companion.PairingFlow
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.CheckIcon
import dev.openmob.companion.ui.components.LinkButton
import dev.openmob.companion.ui.components.ListRow
import dev.openmob.companion.ui.components.MonoValue
import dev.openmob.companion.ui.components.OmCard
import dev.openmob.companion.ui.components.largeText
import dev.openmob.companion.ui.components.OmTextField
import dev.openmob.companion.ui.components.PhoneIcon
import dev.openmob.companion.ui.components.PrimaryButton
import dev.openmob.companion.ui.components.SecondaryButton
import dev.openmob.companion.ui.components.ShieldIcon
import dev.openmob.companion.ui.components.StopSquare
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.nav.ScreenScaffold
import dev.openmob.companion.ui.theme.OpenMobTheme
import dev.openmob.companion.ui.theme.PillShape

/** What the setup screens' buttons do; the route wires them (SetupRoute). */
data class SetupActions(
    val back: () -> Unit = {},
    val getStarted: () -> Unit = {},
    val typeCode: () -> Unit = {},
    val moreOptions: () -> Unit = {},
    val scanInstead: () -> Unit = {},
    val setCode: (String) -> Unit = {},
    val setServer: (String) -> Unit = {},
    val submitCode: () -> Unit = {},
    val submitOwnServer: () -> Unit = {},
    val signIn: () -> Unit = {},
    val developerToken: () -> Unit = {},
    val confirm: () -> Unit = {},
    val notMe: () -> Unit = {},
    val unpair: () -> Unit = {},
    val keep: () -> Unit = {},
    val agree: () -> Unit = {},
    val notNow: () -> Unit = {},
    val cantTurnOn: () -> Unit = {},
    val notifications: () -> Unit = {},
    val battery: () -> Unit = {},
    val samsungSleep: () -> Unit = {},
    val connect: () -> Unit = {},
    val home: () -> Unit = {},
)

const val TAG_CODE_ERROR = "setup-code-error"
const val TAG_CONFIRM_ACCOUNT = "setup-confirm-account"
const val TAG_CONFIRM_SERVER = "setup-confirm-server"
const val TAG_NO_UNDO = "setup-no-undo-notice"
const val TAG_UNUSUAL_CHARS = "setup-unusual-chars"
const val TAG_RESTRICTED = "setup-restricted-help"

@Composable
private fun errorText(e: SetupError?): String? = when (e) {
    null -> null
    is SetupError.Local -> stringResource(e.res)
    is SetupError.Shown -> e.text
}

@Composable
private fun Body(text: String) =
    Text(text, style = MaterialTheme.typography.bodyMedium, color = OpenMobTheme.colors.inkSecondary)

/** A polite live-region error line (red, with an icon: never colour alone). */
@Composable
private fun ErrorLine(text: String, tag: String) {
    val c = OpenMobTheme.colors
    Row(
        Modifier.fillMaxWidth().testTag(tag).background(c.dangerContainer, RoundedCornerShape(12.dp))
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite }.padding(12.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Icon(Icons.Filled.Warning, contentDescription = null, tint = c.onDangerContainer, modifier = Modifier.size(18.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, color = c.onDangerContainer)
    }
}

@Composable
private fun Bullet(icon: ImageVector, text: String) {
    val c = OpenMobTheme.colors
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.Top) {
        Icon(icon, contentDescription = null, tint = c.inkSecondary, modifier = Modifier.size(16.dp).padding(top = 2.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
    }
}

// ---------------------------------------------------------------- welcome and pair

@Composable
fun SetupWelcomeScreen(actions: SetupActions) {
    val c = OpenMobTheme.colors
    ScreenScaffold(title = stringResource(Route.SetupWelcome.title), largeTitle = true) {
        Body(stringResource(R.string.rd_setup_welcome_body, PairingFlow.hostOf(PairingFlow.HOSTED_SERVER)))
        OmCard {
            listOf(
                Triple(ShieldIcon, R.string.rd_setup_welcome_risky, R.string.rd_setup_welcome_risky_body),
                Triple(StopSquare, R.string.rd_setup_welcome_see, R.string.rd_setup_welcome_see_body),
                Triple(PhoneIcon, R.string.rd_setup_welcome_off, R.string.rd_setup_welcome_off_body),
            ).forEach { (icon, title, body) ->
                Row(Modifier.semantics(mergeDescendants = true) {}, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Icon(icon, contentDescription = null, tint = c.signal, modifier = Modifier.size(22.dp))
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(stringResource(title), style = MaterialTheme.typography.titleSmall, color = c.ink)
                        Text(stringResource(body), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
                    }
                }
            }
        }
        PrimaryButton(stringResource(R.string.rd_setup_get_started), onClick = actions.getStarted)
        Text(stringResource(R.string.rd_setup_welcome_note), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary,
             textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
fun SetupPairScreen(actions: SetupActions) {
    val c = OpenMobTheme.colors
    ScreenScaffold(title = stringResource(Route.SetupPair.title), onBack = actions.back, setupStep = 1) {
        Body(stringResource(R.string.rd_setup_pair_body))
        OmCard {
            Text(stringResource(R.string.rd_setup_pair_qr_title), style = MaterialTheme.typography.titleSmall, color = c.ink)
            Text(stringResource(R.string.rd_setup_pair_qr), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        }
        SecondaryButton(stringResource(R.string.rd_setup_pair_code_instead), onClick = actions.typeCode)
        LinkButton(stringResource(R.string.rd_setup_pair_more_title), onClick = actions.moreOptions)
    }
}

// ---------------------------------------------------------------- the typed code

@Composable
fun SetupCodeScreen(state: SetupUiState, actions: SetupActions) {
    if (!SecureWhileShown()) return // the code is typed here: no screenshots (owner, 2026-10-17)
    val c = OpenMobTheme.colors
    ScreenScaffold(title = stringResource(Route.SetupPairCode.title), onBack = actions.back, setupStep = 1) {
        Body(stringResource(R.string.rd_setup_code_body))
        CodeField(state, actions, onSubmit = actions.submitCode)
        errorText(state.codeError)?.let { ErrorLine(it, TAG_CODE_ERROR) }
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Bullet(Icons.Filled.Info, stringResource(R.string.rd_setup_code_expire))
            Bullet(Icons.Filled.Info, stringResource(R.string.rd_setup_code_case))
            Bullet(Icons.Filled.Info, stringResource(R.string.rd_setup_code_letters))
        }
        Text(stringResource(R.string.rd_setup_code_server, dev.openmob.companion.PairingFlow.hostOf(state.server)),
             style = OpenMobTheme.mono.small, color = c.inkTertiary)
        PrimaryButton(stringResource(if (state.busy) R.string.rd_setup_checking else R.string.rd_next),
                      onClick = actions.submitCode, enabled = !state.busy)
        LinkButton(stringResource(R.string.rd_setup_code_scan), onClick = actions.scanInstead)
        LinkButton(stringResource(R.string.rd_setup_pair_more_title), onClick = actions.moreOptions)
    }
}

@Composable
private fun CodeField(state: SetupUiState, actions: SetupActions, onSubmit: () -> Unit) {
    OmTextField(
        value = state.code,
        onValueChange = actions.setCode,
        placeholder = stringResource(R.string.rd_setup_code_hint),
        label = stringResource(R.string.rd_setup_code_label),
        textStyle = OpenMobTheme.mono.large,
        imeAction = ImeAction.Done,
        capitalization = KeyboardCapitalization.Characters,
        autoCorrect = false,
        onSubmit = onSubmit,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
fun SetupMoreScreen(state: SetupUiState, actions: SetupActions) {
    if (!SecureWhileShown()) return // the code can be typed here too
    val c = OpenMobTheme.colors
    ScreenScaffold(title = stringResource(Route.SetupPairMore.title), onBack = actions.back) {
        OmCard {
            Text(stringResource(R.string.rd_setup_more_own), style = MaterialTheme.typography.titleMedium, color = c.ink)
            Text(stringResource(R.string.rd_setup_more_own_body), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
            OmTextField(
                value = state.serverInput,
                onValueChange = actions.setServer,
                placeholder = stringResource(R.string.rd_setup_more_address_hint),
                label = stringResource(R.string.rd_setup_more_address),
                error = state.serverError?.let { stringResource(it) },
                keyboardType = androidx.compose.ui.text.input.KeyboardType.Uri,
                imeAction = ImeAction.Next,
                autoCorrect = false,
                modifier = Modifier.fillMaxWidth(),
            )
            Text(stringResource(R.string.rd_setup_more_address_help), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary)
            CodeField(state, actions, onSubmit = actions.submitOwnServer)
            errorText(state.codeError)?.let { ErrorLine(it, TAG_CODE_ERROR) }
            PrimaryButton(stringResource(if (state.busy) R.string.rd_setup_checking else R.string.rd_next),
                          onClick = actions.submitOwnServer, enabled = !state.busy)
        }
        OmCard(contentPadding = 0.dp) {
            ListRow(stringResource(R.string.rd_setup_more_signin), subtitle = stringResource(R.string.rd_setup_more_signin_body),
                    onClick = actions.signIn)
            HorizontalDivider(color = c.divider)
            ListRow(stringResource(R.string.rd_setup_more_token), subtitle = stringResource(R.string.rd_setup_more_token_body),
                    onClick = actions.developerToken)
        }
        Bullet(ShieldIcon, stringResource(R.string.rd_setup_more_note))
    }
}

// ---------------------------------------------------------------- confirm and replace

/** The account and server, large, so the owner can catch a code that came from someone else (owner condition 1). */
@Composable
private fun AccountServer(email: String, host: String, tagged: Boolean = true) {
    val c = OpenMobTheme.colors
    OmCard {
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(stringResource(R.string.rd_setup_account), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary)
            Text(email, style = OpenMobTheme.mono.large, color = c.ink,
                 modifier = if (tagged) Modifier.testTag(TAG_CONFIRM_ACCOUNT) else Modifier)
        }
        HorizontalDivider(color = c.divider)
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(stringResource(R.string.rd_setup_server), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary)
            Text(host, style = OpenMobTheme.mono.large, color = c.ink,
                 modifier = if (tagged) Modifier.testTag(TAG_CONFIRM_SERVER) else Modifier)
        }
        // A look-alike letter (Cyrillic "о" for "o") or an invisible one reads as the owner's own address.
        if (!plainAscii(email) || !plainAscii(host)) {
            Text(stringResource(R.string.rd_setup_unusual_chars), style = MaterialTheme.typography.titleSmall,
                 color = c.ink, modifier = Modifier.testTag(TAG_UNUSUAL_CHARS))
        }
    }
}

/** Printable ASCII without spaces: what an ordinary email address or host name is made of (review 3, K3-M2). */
internal fun plainAscii(s: String): Boolean = s.all { it in '!'..'~' }

@Composable
private fun OnlyYours() {
    val c = OpenMobTheme.colors
    // Neutral, not amber: amber only means "the phone is asking you to approve" (UX review 2, H2).
    Row(
        Modifier.fillMaxWidth().background(c.neutralContainer, RoundedCornerShape(14.dp))
            .semantics(mergeDescendants = true) {}.padding(14.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(ShieldIcon, contentDescription = null, tint = c.ink, modifier = Modifier.size(20.dp))
        Text(stringResource(R.string.rd_setup_only_yours), style = MaterialTheme.typography.titleSmall, color = c.ink)
    }
}

@Composable
fun SetupConfirmScreen(state: SetupUiState, actions: SetupActions) {
    if (!SecureWhileShown()) return // holds the checked code until the claim
    val checked = state.checked
    ScreenScaffold(title = stringResource(Route.SetupConfirm.title), onBack = actions.notMe, setupStep = 1) {
        if (checked != null) AccountServer(checked.email, checked.host)
        OnlyYours()
        // The back-check (owner, 2026-10-17): the dashboard names the phone that entered the code.
        if (state.phone.model.isNotEmpty()) Body(stringResource(R.string.rd_setup_dashboard_shows, state.phone.model))
        Body(stringResource(R.string.rd_setup_confirm_body))
        // Notifications are off: no "Paired · Undo" notice will appear (UX review 2, item 5).
        if (!state.phone.notificationsOn) {
            Text(stringResource(R.string.rd_setup_no_undo_notice), style = MaterialTheme.typography.bodySmall,
                 color = OpenMobTheme.colors.ink, modifier = Modifier.testTag(TAG_NO_UNDO))
        }
        errorText(state.confirmError)?.let { ErrorLine(it, TAG_CODE_ERROR) }
        PrimaryButton(stringResource(R.string.rd_setup_confirm_button), onClick = actions.confirm,
                      enabled = checked != null && !state.busy, icon = ShieldIcon)
        SecondaryButton(stringResource(R.string.rd_setup_not_me), onClick = actions.notMe)
    }
}

@Composable
fun SetupReplaceScreen(state: SetupUiState, actions: SetupActions) {
    if (!SecureWhileShown()) return // holds the checked code until the claim
    val c = OpenMobTheme.colors
    val checked = state.checked
    ScreenScaffold(title = stringResource(Route.SetupReplace.title), onBack = actions.keep, setupStep = 1) {
        Body(stringResource(R.string.rd_setup_replace_body))
        OmCard {
            Text(stringResource(R.string.rd_setup_replace_now), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary)
            MonoValue(state.phone.email.ifEmpty { "—" }, style = OpenMobTheme.mono.medium)
            MonoValue(state.phone.host, style = OpenMobTheme.mono.small)
            Text(stringResource(R.string.rd_setup_replace_with), style = MaterialTheme.typography.labelSmall, color = c.inkSecondary,
                 textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
            Text(stringResource(R.string.rd_setup_replace_new), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary)
            if (checked != null) {
                MonoValue(checked.email, style = OpenMobTheme.mono.medium)
                MonoValue(checked.host, style = OpenMobTheme.mono.small)
            }
        }
        Body(stringResource(R.string.rd_setup_replace_note))
        errorText(state.confirmError)?.let { ErrorLine(it, TAG_CODE_ERROR) }
        PrimaryButton(stringResource(R.string.rd_setup_replace_button), onClick = actions.unpair, icon = ShieldIcon)
        SecondaryButton(stringResource(R.string.rd_setup_replace_keep), onClick = actions.keep)
    }
}

// ---------------------------------------------------------------- consent and ready

/** The Accessibility disclosure (MainActivity's afterDisclosure, as a screen): only "Agree and open Settings" opens
 *  Android's Accessibility settings. */
@Composable
fun SetupConsentScreen(state: SetupUiState, actions: SetupActions) {
    val c = OpenMobTheme.colors
    ScreenScaffold(title = stringResource(Route.SetupConsent.title), onBack = actions.back, setupStep = 2) {
        Body(stringResource(R.string.rd_setup_consent_body, state.phone.host.ifEmpty { stringResource(R.string.rd_setup_your_server) }))
        OmCard {
            Bullet(PhoneIcon, stringResource(R.string.rd_setup_consent_see))
            Bullet(CheckIcon, stringResource(R.string.rd_setup_consent_act))
        }
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Bullet(ShieldIcon, stringResource(R.string.rd_setup_consent_only))
            // Where screen contents go (UX review 2, H3): the paired server, its AI model, and TypeSafe with Faster mode.
            Bullet(ShieldIcon, stringResource(R.string.rd_setup_consent_server,
                                              state.phone.host.ifEmpty { stringResource(R.string.rd_setup_your_server) }))
            Bullet(ShieldIcon, stringResource(R.string.rd_setup_consent_never))
            Bullet(ShieldIcon, stringResource(R.string.rd_setup_consent_off))
        }
        if (state.phone.accessibilityOn) {
            Text(stringResource(R.string.rd_setup_consent_on), style = MaterialTheme.typography.titleSmall, color = c.signal)
        } else {
            Column(Modifier.fillMaxWidth().border(1.dp, c.border, RoundedCornerShape(12.dp)).padding(12.dp)
                       .semantics(mergeDescendants = true) {}) {
                Text(stringResource(R.string.rd_setup_consent_next), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary)
                Text(stringResource(R.string.rd_setup_consent_path), style = OpenMobTheme.mono.medium, color = c.ink)
            }
        }
        PrimaryButton(stringResource(if (state.phone.accessibilityOn) R.string.rd_next else R.string.rd_setup_consent_agree),
                      onClick = actions.agree)
        SecondaryButton(stringResource(R.string.rd_setup_consent_not_now), onClick = actions.notNow)
        // Android 13+ blocks Accessibility for sideloaded apps until "Allow restricted settings": the steps inline
        // (UX review 2, H5), not behind a button.
        if (state.phone.restricted && !state.phone.accessibilityOn) {
            OmCard(modifier = Modifier.testTag(TAG_RESTRICTED)) {
                Text(stringResource(R.string.ui_restricted_why), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
                Text(stringResource(R.string.ui_restricted_steps), style = MaterialTheme.typography.bodySmall, color = c.ink)
                Text(stringResource(R.string.ui_restricted_missing), style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
                SecondaryButton(stringResource(R.string.ui_restricted_button), onClick = actions.cantTurnOn)
            }
        }
    }
}

@Composable
private fun CheckRow(done: Boolean, title: String, subtitle: String?, action: String?, onAction: () -> Unit) {
    val c = OpenMobTheme.colors
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(Modifier.weight(1f).semantics(mergeDescendants = true) {}, verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            val bg = if (done) c.signalContainer else c.neutralContainer
            androidx.compose.foundation.layout.Box(Modifier.size(28.dp).background(bg, CircleShape), contentAlignment = Alignment.Center) {
                if (done) Icon(CheckIcon, contentDescription = null, tint = c.signal, modifier = Modifier.size(16.dp))
            }
            // At large text, "Done" and the button go under the texts (side by side they squeeze the title).
            val large = largeText()
            Column(Modifier.weight(1f, fill = false), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(title, style = MaterialTheme.typography.titleSmall, color = c.ink)
                if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
                if (large && done) Text(stringResource(R.string.rd_setup_ready_done), style = MaterialTheme.typography.labelSmall, color = c.signal)
                if (large && !done && action != null) SecondaryButton(action, onClick = onAction, fillWidth = false)
            }
            if (!large && done) Text(stringResource(R.string.rd_setup_ready_done), style = MaterialTheme.typography.labelSmall, color = c.signal)
        }
        if (!largeText() && !done && action != null) SecondaryButton(action, onClick = onAction, fillWidth = false)
    }
}

@Composable
fun SetupReadyScreen(state: SetupUiState, actions: SetupActions) {
    val c = OpenMobTheme.colors
    val p = state.phone
    ScreenScaffold(title = stringResource(Route.SetupReady.title), onBack = actions.back, setupStep = 3) {
        Body(stringResource(R.string.rd_setup_ready_body))
        OmCard(contentPadding = 0.dp) {
            CheckRow(p.connected,
                     if (p.connected) stringResource(R.string.rd_setup_ready_connected, p.host) else stringResource(R.string.rd_setup_ready_paired, p.host),
                     null, if (p.paired && !p.running) stringResource(R.string.rd_setup_ready_connect) else null, actions.connect)
            HorizontalDivider(color = c.divider)
            CheckRow(p.accessibilityOn, stringResource(if (p.accessibilityOn) R.string.rd_setup_ready_a11y else R.string.rd_setup_ready_a11y_off),
                     null, stringResource(R.string.rd_setup_ready_turn_on), actions.back)
            HorizontalDivider(color = c.divider)
            CheckRow(p.notificationsOn, stringResource(R.string.rd_setup_ready_notifs), stringResource(R.string.rd_setup_ready_notifs_body),
                     stringResource(R.string.rd_setup_ready_allow), actions.notifications)
            HorizontalDivider(color = c.divider)
            CheckRow(p.batteryUnrestricted, stringResource(R.string.rd_setup_ready_battery), stringResource(R.string.rd_setup_ready_battery_body),
                     stringResource(R.string.rd_setup_ready_allow), actions.battery)
        }
        // Samsung also puts apps to sleep on its own schedule: its "Never sleeping apps" list (the old screen's link).
        if (p.batteryUnrestricted && p.samsung) LinkButton(stringResource(R.string.ui_samsung_sleep), onClick = actions.samsungSleep)
        Row(
            Modifier.fillMaxWidth().background(c.surface, RoundedCornerShape(16.dp)).border(1.dp, c.border, RoundedCornerShape(16.dp))
                .semantics(mergeDescendants = true) {}.padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            androidx.compose.foundation.layout.Box(Modifier.size(width = 6.dp, height = 44.dp).background(c.ink, PillShape))
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(stringResource(R.string.rd_setup_ready_spot), style = MaterialTheme.typography.titleSmall, color = c.ink)
                Text(stringResource(R.string.rd_setup_ready_spot_body), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
            }
        }
        PrimaryButton(stringResource(R.string.rd_setup_go_home), onClick = actions.home)
    }
}
