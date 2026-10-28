package dev.openmob.companion.ui.nav

import androidx.annotation.StringRes
import dev.openmob.companion.R

/**
 * Every screen of the redesign, with its real title. String routes (not type-safe routes) keep the
 * kotlinx-serialization plugin out of the build. Step 1 has no arguments.
 */
enum class Route(val path: String, @StringRes val title: Int, val setupStep: Int? = null) {
    Home("home", R.string.rd_home_title),
    Settings("settings", R.string.rd_settings_title),
    Indicator("settings/indicator", R.string.rd_indicator_title),
    Blocked("settings/blocked", R.string.blocked_title),
    BlockedAdd("settings/blocked/add", R.string.blocked_add_title),
    Memory("settings/memory", R.string.memory_title),
    Activity("activity", R.string.rd_activity_title),
    Connection("settings/connection", R.string.rd_settings_connection),
    SetupWelcome("setup/welcome", R.string.rd_setup_welcome_title),
    SetupPair("setup/pair", R.string.rd_setup_pair_title, setupStep = 1),
    SetupPairCode("setup/pair/code", R.string.rd_setup_pair_code_title, setupStep = 1),
    SetupPairMore("setup/pair/more", R.string.rd_setup_pair_more_title, setupStep = 1),
    SetupConfirm("setup/confirm", R.string.rd_setup_confirm_title, setupStep = 1),
    SetupReplace("setup/replace", R.string.rd_setup_replace_title, setupStep = 1),
    SetupSignIn("setup/signin", R.string.rd_setup_more_signin, setupStep = 1),
    SetupToken("setup/token", R.string.rd_setup_more_token, setupStep = 1),
    SetupConsent("setup/consent", R.string.rd_setup_consent_title, setupStep = 2),
    SetupReady("setup/ready", R.string.rd_setup_ready_title, setupStep = 3);

    companion object {
        const val SETUP_STEPS = 3
        val start = Home
    }
}
