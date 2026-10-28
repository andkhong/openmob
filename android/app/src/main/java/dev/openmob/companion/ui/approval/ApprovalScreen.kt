package dev.openmob.companion.ui.approval

import android.content.res.ColorStateList
import android.content.res.Configuration
import android.graphics.BitmapFactory
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import android.os.SystemClock
import kotlinx.coroutines.delay
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import dev.openmob.companion.ApprovalScreenState
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.CheckIcon
import dev.openmob.companion.ui.components.ShieldIcon
import dev.openmob.companion.ui.theme.ApprovalAmber
import dev.openmob.companion.ui.theme.DarkOpenMobColors
import dev.openmob.companion.ui.theme.LightOpenMobColors
import dev.openmob.companion.ui.theme.OpenMobColors
import dev.openmob.companion.ui.theme.OpenMobTheme
import dev.openmob.companion.ui.theme.PillShape

/**
 * The redesigned approval screen (mockups Approval / ApprovalDark). View layer only: what it shows comes from
 * [ApprovalScreenState] (ApprovalActivity's own render logic), and the two controls that grant anything, Approve and
 * "Always allow", are ApprovalActivity's own Android views embedded as they are, so their protections
 * (filterTouchesWhenObscured, accessibility data-sensitive, the click into onApprove) are the original ones. See
 * docs/design/redesign-approval.md.
 *
 * Text from the server is shown only under "Server says (not checked by the phone)" (or, for a task grant's text, under
 * its own "worded by the server" label), never in "Checked by this phone", which holds only what the phone built
 * itself: the crop, the action line from the signed fields (a permission change's from its parsed change, never its
 * `text`/`desc`), and task text the owner typed on this phone.
 */
object ApprovalScreen {
    const val TAG_CHECKED = "approval-checked"
    const val TAG_SERVER = "approval-server"
    const val TAG_APPROVE = "approval-approve"
    const val TAG_DENY = "approval-deny"
    const val TAG_TASK = "approval-task"
    const val TAG_TASK_GRANTED = "approval-task-granted"
    const val TAG_CLOSED = "approval-closed"
    const val TAG_LOCK_HEADING = "approval-lock-heading"
    const val TAG_CLOSE = "approval-close"
    const val TAG_AMOUNT = "approval-amount-unchecked"
    const val TAG_COUNTDOWN = "approval-countdown"

    private fun colorsFor(view: View): OpenMobColors =
        if ((view.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES)
            DarkOpenMobColors else LightOpenMobColors

    /** Approve as the mockups draw it (an ink pill). Only its look changes: same object, listener and flags. */
    fun styleApprove(button: Button, colors: OpenMobColors = colorsFor(button)) {
        val density = button.resources.displayMetrics.density
        // The same style family as Deny (owner, 2026-10-17): an outlined pill, neither one solid.
        button.background = GradientDrawable().apply {
            cornerRadius = 28 * density
            setColor(colors.surface.toArgb())
            setStroke((2 * density).toInt(), colors.ink.toArgb())
        }
        button.isAllCaps = false
        button.setTextColor(colors.ink.toArgb())
        button.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
        runCatching { button.typeface = button.resources.getFont(R.font.ibm_plex_sans_semibold) }
        button.minHeight = (56 * density).toInt()
        button.minimumHeight = (56 * density).toInt()
        button.elevation = 0f
        button.stateListAnimator = null
    }

    /** "Always allow" in the theme's ink and blue. Same object, flags and default (unchecked). */
    fun styleAlways(box: CheckBox, colors: OpenMobColors = colorsFor(box)) {
        box.setTextColor(colors.ink.toArgb())
        box.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        runCatching { box.typeface = box.resources.getFont(R.font.ibm_plex_sans_regular) }
        box.buttonTintList = ColorStateList.valueOf(colors.signal.toArgb())
        box.minHeight = (48 * box.resources.displayMetrics.density).toInt()
    }

    @Composable
    fun Content(
        state: ApprovalScreenState?,
        status: String?,
        serverHost: String,
        approveView: Button,
        alwaysView: CheckBox,
        onDeny: () -> Unit,
        modifier: Modifier = Modifier,
        /** Close the screen (an answered or expired request: the only button then). */
        onClose: () -> Unit = {},
        /** The phone's monotonic clock (uptime ms, the one the expiry timer uses); tests pass their own. */
        now: () -> Long = { SystemClock.uptimeMillis() },
    ) {
        val c = OpenMobTheme.colors
        // The countdown, from when the phone received the request, against its own 2-minute expiry.
        var left by remember(state?.expiresAt) { mutableLongStateOf(state?.let { remainingMs(it, now()) } ?: -1L) }
        LaunchedEffect(state?.expiresAt) {
            while (state != null && state.expiresAt > 0 && left > 0) {
                delay(250)
                left = remainingMs(state, now())
            }
        }
        val expired = state != null && state.expiresAt > 0 && left <= 0
        // At 0 the screen shows it expired and leaves only Deny (or closing it), as the expiry path does.
        val shown = if (expired && state != null) state.copy(approveVisible = false, approveEnabled = false, alwaysVisible = false) else state
        val statusShown = if (expired) stringResource(R.string.approval_gone) else status
        // Answered or expired (UX review 2, B1): no Approve, no "Always allow", no amber band; one Close.
        if (state != null && (expired || !state.open)) return Closed(state, onClose, modifier)
        val oneTap = state?.gate == true && state.level == "tap"
        val large = LocalDensity.current.fontScale >= STACK_AT_FONT_SCALE
        val scroll = rememberScrollState()
        // The amber frame: "the phone is asking you", with the agent's blue inside it (as the indicator draws it).
        Column(
            modifier
                .fillMaxSize()
                .background(ApprovalAmber)
                .safeDrawingPadding()
                .padding(if (oneTap) 4.dp else 10.dp)
                .background(c.surface, RoundedCornerShape(22.dp))
                .border(2.dp, c.signal, RoundedCornerShape(22.dp)),
        ) {
            Column(
                Modifier
                    .weight(1f)
                    .verticalScroll(scroll)
                    .padding(start = 20.dp, end = 20.dp, top = 28.dp, bottom = 12.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                if (shown != null) Body(shown, serverHost, alwaysView, large)
                // At large text the approve note scrolls with the body, so the fixed bar keeps only the two buttons.
                if (shown != null && large) ApproveNote(shown)
                if (statusShown != null) {
                    Text(
                        statusShown,
                        style = MaterialTheme.typography.bodySmall,
                        color = c.onDangerContainer,
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(c.dangerContainer, RoundedCornerShape(12.dp))
                            .semantics { liveRegion = LiveRegionMode.Polite }
                            .padding(12.dp),
                    )
                }
            }
            // A rule above the buttons while more of the request is below: the body is cut, not the request.
            if (scroll.canScrollForward) Box(Modifier.fillMaxWidth().height(1.dp).background(c.border))
            if (shown != null) Actions(shown, approveView, onDeny, if (expired) 0 else left, large)
        }
    }

    /** An answered or expired request: what it was, that it's over, and Close. Nothing to approve or deny. */
    @Composable
    private fun Closed(state: ApprovalScreenState, onClose: () -> Unit, modifier: Modifier) {
        val c = OpenMobTheme.colors
        Column(
            modifier.fillMaxSize().background(c.ground).safeDrawingPadding().padding(20.dp)
                .semantics(mergeDescendants = false) { liveRegion = LiveRegionMode.Polite },
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            // The text scrolls (large font scales); Close stays at the bottom.
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Text(stringResource(R.string.rd_approval_closed_title), style = MaterialTheme.typography.headlineSmall, color = c.ink,
                     modifier = Modifier.semantics { heading() }.testTag(TAG_CLOSED))
                if (state.known) Text(state.question, style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary)
                Text(stringResource(R.string.rd_approval_closed_body), style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
            }
            OutlinedButton(
                onClick = onClose,
                modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).testTag(TAG_CLOSE),
                shape = PillShape,
                border = BorderStroke(2.dp, c.ink),
                colors = ButtonDefaults.outlinedButtonColors(containerColor = c.surface, contentColor = c.ink),
            ) { Text(stringResource(R.string.rd_approval_close), style = MaterialTheme.typography.labelLarge) }
        }
    }

    /** From this font scale up, Deny and Approve stack (Deny first) instead of sharing a row. */
    const val STACK_AT_FONT_SCALE = 1.3f

    /**
     * Deny and Approve at exactly the same size: each as tall as the taller one needs (at least 56dp), side by side
     * at half the width each, or stacked at full width. With one child (no Approve), it takes the full width.
     */
    @Composable
    private fun EqualButtons(stacked: Boolean, content: @Composable () -> Unit) {
        Layout(content, Modifier.fillMaxWidth()) { measurables, constraints ->
            val gap = 10.dp.roundToPx()
            val n = measurables.size
            val full = constraints.maxWidth
            val w = if (stacked || n < 2) full else (full - gap * (n - 1)) / n
            val h = maxOf(56.dp.roundToPx(), measurables.maxOfOrNull { it.maxIntrinsicHeight(w) } ?: 0)
            val placeables = measurables.map { it.measure(Constraints.fixed(w, h)) }
            val height = if (stacked) h * n + gap * (n - 1).coerceAtLeast(0) else h
            layout(full, height) {
                placeables.forEachIndexed { i, p -> if (stacked) p.place(0, i * (h + gap)) else p.place(i * (w + gap), 0) }
            }
        }
    }

    /** Ms until [state] expires by the phone's clock (never below 0); -1: no expiry known. */
    fun remainingMs(state: ApprovalScreenState, now: Long): Long =
        if (state.expiresAt <= 0) -1 else (state.expiresAt - now).coerceAtLeast(0)

    /** 1:58, 0:07. */
    fun clock(ms: Long): String {
        val s = (ms + 999) / 1000
        return "%d:%02d".format(s / 60, s % 60)
    }

    @Composable
    private fun Body(state: ApprovalScreenState, serverHost: String, alwaysView: CheckBox, large: Boolean) {
        val c = OpenMobTheme.colors
        // The ask: a polite live region, so TalkBack reads the question when the screen opens.
        Column(
            Modifier.semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            val chip = @Composable {
                Row(
                    Modifier.heightIn(min = 28.dp).background(c.askingContainer, PillShape).padding(horizontal = 10.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Icon(ShieldIcon, contentDescription = null, tint = c.onAskingContainer, modifier = Modifier.size(14.dp))
                    Text(state.label, style = MaterialTheme.typography.labelSmall, color = c.onAskingContainer)
                }
            }
            val from = @Composable {
                if (state.gate) {
                    Text(stringResource(R.string.rd_approval_from_phone), style = MaterialTheme.typography.labelSmall, color = c.inkSecondary)
                }
            }
            // Side by side; at large text, one under the other (they no longer fit on one line).
            if (large) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) { chip(); from() }
            } else {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    chip()
                    Spacer(Modifier.weight(1f))
                    from()
                }
            }
            // Screen-lock prompts say so with the lock and their own heading; one-tap prompts don't (owner, 2026-10-17).
            if (!(state.gate && state.level == "tap")) {
                Row(Modifier.testTag(TAG_LOCK_HEADING), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Icon(androidx.compose.material.icons.Icons.Filled.Lock, contentDescription = null, tint = c.ink,
                         modifier = Modifier.size(18.dp))
                    Text(stringResource(R.string.rd_approval_lock_heading), style = MaterialTheme.typography.titleSmall, color = c.ink)
                }
            }
            Text(
                state.question,
                style = if (state.gate && state.level == "tap") MaterialTheme.typography.titleMedium else MaterialTheme.typography.headlineSmall,
                color = c.ink,
                modifier = Modifier.semantics { heading() },
            )
            // A money prompt whose wording carries no price the phone read (UX review 2, item 12).
            if (state.amountUnchecked) {
                Text(stringResource(R.string.rd_approval_amount_unchecked), style = MaterialTheme.typography.titleSmall,
                     color = c.ink, modifier = Modifier.testTag(TAG_AMOUNT))
            }
        }

        val crop = remember(state.crop) { state.crop?.let { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() } }
        val task = state.taskText
        if (crop != null || state.actionLine.isNotEmpty() || task != null) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .testTag(TAG_CHECKED)
                    .border(1.dp, c.border, RoundedCornerShape(16.dp))
                    .padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Icon(CheckIcon, contentDescription = null, tint = c.signal, modifier = Modifier.size(14.dp))
                    Text(stringResource(R.string.rd_approval_checked), style = MaterialTheme.typography.labelSmall, color = c.signal)
                }
                if (crop != null) {
                    Image(
                        crop,
                        contentDescription = stringResource(R.string.rd_approval_crop),
                        contentScale = ContentScale.Fit,
                        modifier = Modifier.fillMaxWidth().heightIn(max = 220.dp)
                            .border(1.dp, c.border, RoundedCornerShape(10.dp)),
                    )
                }
                if (state.actionLine.isNotEmpty()) {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(stringResource(R.string.rd_approval_exactly), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary)
                        // A plain description, not a raw tool line (UX review 2, H6); the signed content is unchanged.
                        Text(state.actionLine, style = OpenMobTheme.mono.medium, color = c.ink)
                    }
                }
                // Only text the owner typed on this phone. A grant's text (worded by the server) is shown below, outside.
                if (task != null) {
                    Text(
                        stringResource(R.string.rd_approval_task, task),
                        style = MaterialTheme.typography.bodySmall,
                        color = c.inkSecondary,
                        modifier = Modifier.fillMaxWidth().testTag(TAG_TASK).padding(top = 2.dp),
                    )
                }
            }
        }

        // A task the owner allowed here in a task grant: held by the phone, but worded by the server (review 3, P3-M1).
        val granted = state.grantTaskText
        if (granted != null) {
            Column(
                Modifier.fillMaxWidth().testTag(TAG_TASK_GRANTED).padding(horizontal = 4.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(stringResource(R.string.rd_approval_task_granted), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary)
                Text("“$granted”", style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
            }
        }

        val serverText = if (state.gate) state.serverSays else ""
        val who = listOf(serverHost, state.requester).filter { it.isNotBlank() }.joinToString(" · ")
        if (serverText.isNotEmpty() || state.requester.isNotEmpty()) {
            Column(
                Modifier.fillMaxWidth().testTag(TAG_SERVER).padding(horizontal = 4.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(stringResource(R.string.rd_approval_server_says), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary)
                if (serverText.isNotEmpty()) {
                    Text(
                        "“$serverText”",
                        style = MaterialTheme.typography.bodyMedium.copy(fontStyle = FontStyle.Italic),
                        color = c.inkSecondary,
                    )
                }
                if (who.isNotEmpty()) Text(who, style = OpenMobTheme.mono.small, color = c.inkTertiary)
            }
        }

        Text(state.explain, style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)

        if (state.alwaysVisible) {
            AndroidView(factory = { alwaysView }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp))
        }
    }

    @Composable
    private fun ApproveNote(state: ApprovalScreenState) {
        if (!state.approveVisible) return
        val c = OpenMobTheme.colors
        val tapLevel = state.gate && state.level == "tap"
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
            Icon(ShieldIcon, contentDescription = null, tint = c.inkSecondary, modifier = Modifier.size(16.dp).padding(top = 1.dp))
            Text(
                stringResource(if (tapLevel) R.string.rd_approval_tap_note else R.string.rd_approval_lock_note),
                style = MaterialTheme.typography.bodySmall,
                color = c.inkSecondary,
            )
        }
    }

    @Composable
    private fun Actions(state: ApprovalScreenState, approveView: Button, onDeny: () -> Unit, leftMs: Long, large: Boolean) {
        val c = OpenMobTheme.colors
        Column(
            Modifier.padding(start = 20.dp, end = 20.dp, bottom = 20.dp, top = if (large) 12.dp else 0.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (!large) ApproveNote(state)
            // Deny and Approve: the same size, side by side; with no Approve (a blocker), Deny alone. At large text
            // (font scale 1.3 and up) they stack, Deny first, so neither label is cut; both stay in this fixed bar
            // under the scrolling body, so Approve is never on screen without Deny.
            EqualButtons(stacked = large) {
                OutlinedButton(
                    onClick = onDeny,
                    enabled = state.denyEnabled,
                    modifier = Modifier.testTag(TAG_DENY),
                    shape = PillShape,
                    border = BorderStroke(2.dp, if (state.denyEnabled) c.ink else c.border),
                    colors = ButtonDefaults.outlinedButtonColors(containerColor = c.surface, contentColor = c.ink),
                ) { Text(stringResource(R.string.approval_deny), style = MaterialTheme.typography.labelLarge, textAlign = TextAlign.Center) }
                if (state.approveVisible) {
                    AndroidView(factory = { approveView }, modifier = Modifier.testTag(TAG_APPROVE))
                }
            }
            if (state.open) {
                Text(
                    if (leftMs >= 0) stringResource(R.string.rd_approval_expires_in, clock(leftMs))
                    else stringResource(R.string.rd_approval_footer),
                    style = MaterialTheme.typography.labelSmall,
                    color = c.inkTertiary,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth().testTag(TAG_COUNTDOWN),
                )
            }
        }
    }
}
