package dev.openmob.companion.ui.approval

import android.content.res.Configuration
import android.widget.Button
import android.widget.CheckBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.tooling.preview.Preview
import dev.openmob.companion.ApprovalScreenState
import dev.openmob.companion.R
import dev.openmob.companion.ui.theme.DarkOpenMobColors
import dev.openmob.companion.ui.theme.LightOpenMobColors
import dev.openmob.companion.ui.theme.OpenMobTheme

/** Example states (made-up values) for the previews and screenshot tests. */
object ApprovalSamples {
    private val base = ApprovalScreenState(
        open = true, known = true, label = "APPROVAL NEEDED", question = "Buy now · \$249.99 in Example Shop?",
        explain = "This phone stopped the agent to ask you. The question and the picture come from what this phone sees, not from the server.",
        gate = true, level = "fingerprint", kind = "gate", alwaysVisible = false, alwaysText = "",
        requesterLine = "Server says: “These are the headphones you asked for.”", requester = "",
        serverSays = "These are the headphones you asked for. Ordering one pair.", crop = null,
        actionLine = "Tap “Buy now” · Example Shop › Checkout", blocker = null,
        denyEnabled = true, approveEnabled = true, approveVisible = true,
    )
    val purchase = base
    val tap = base.copy(level = "tap", question = "Send “On my way” to Sam in Messages?", actionLine = "", serverSays = "",
        alwaysVisible = true, alwaysText = "Always allow for Messages\nAgents could send any message as you for 30 days")
    val modeChange = base.copy(gate = false, kind = "mode_change", label = "CHANGE HOW AGENTS ASK",
        question = "Turn on Faster mode for this session?", requester = "Claude", serverSays = "",
        actionLine = "mode_change: Faster mode, this session",
        explain = "Agents would ask you less on this phone. This needs your screen lock.")
    val blocked = modeChange.copy(blocker = "mismatch", approveEnabled = false, approveVisible = false)
    val gone = base.copy(open = false, denyEnabled = false, approveEnabled = false)

    /** The status lines the original screen shows, as they appear here. */
    const val INTERRUPTED = "Interrupted. The screen lock prompt comes back in a moment; or tap Approve or Deny."
    const val MISMATCH = "This request doesn't match the action it describes, so it can't be approved. Deny it."
}

@Composable
private fun Sample(state: ApprovalScreenState, status: String? = null, dark: Boolean) {
    val ctx = LocalContext.current
    val approve = remember { Button(ctx).apply { text = ctx.getString(R.string.approval_approve) } }
    val always = remember { CheckBox(ctx).apply { text = state.alwaysText } }
    ApprovalScreen.styleApprove(approve, if (dark) DarkOpenMobColors else LightOpenMobColors)
    ApprovalScreen.styleAlways(always, if (dark) DarkOpenMobColors else LightOpenMobColors)
    OpenMobTheme(darkTheme = dark) {
        ApprovalScreen.Content(state, status, "home-server.local", approve, always, onDeny = {})
    }
}

@Preview(name = "Approval, light", widthDp = 390, heightDp = 844)
@Composable
private fun ApprovalLightPreview() = Sample(ApprovalSamples.purchase, dark = false)

@Preview(name = "Approval, dark", widthDp = 390, heightDp = 844, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun ApprovalDarkPreview() = Sample(ApprovalSamples.purchase, dark = true)

@Preview(name = "Approval, permission change", widthDp = 390, heightDp = 844)
@Composable
private fun ApprovalModePreview() = Sample(ApprovalSamples.modeChange, dark = false)
