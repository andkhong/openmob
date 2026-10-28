package dev.openmob.companion.ui.home

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.Warning
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import dev.openmob.companion.R
import dev.openmob.companion.ui.activity.duration
import dev.openmob.companion.ui.components.BlockIcon
import dev.openmob.companion.ui.components.CheckIcon
import dev.openmob.companion.ui.components.StopSquare
import dev.openmob.companion.ui.setup.SecureWhileShown
import dev.openmob.companion.ui.theme.OpenMobTheme
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

const val TAG_THREAD = "thread"
const val TAG_LIVE_STEP = "thread-live"
const val TAG_JUMP = "thread-jump"

/** Home's thread (canvas Main, rev 6): requests right, replies left, steps collapsed, the live step last. */
@Composable
fun ThreadList(items: List<ThreadItem>, listState: LazyListState, actions: HomeActions, modifier: Modifier = Modifier,
               zone: ZoneId = ZoneId.systemDefault(),
               /** "Back to <app> to watch" under the live step: (label, package), or null. */
               backTo: Pair<String, String>? = null) {
    LazyColumn(
        state = listState,
        modifier = modifier.fillMaxWidth().testTag(TAG_THREAD),
        contentPadding = PaddingValues(vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        items(items, key = { it.key }) { item ->
            when (item) {
                is ThreadItem.Day -> DayLine(item.day, zone)
                is ThreadItem.Request -> RequestBubble(item, zone)
                is ThreadItem.Reply -> ReplyBlock(item)
                is ThreadItem.System -> SystemLine(item, zone)
                is ThreadItem.Question -> QuestionCard(item.text, item.readOnly)
                is ThreadItem.MemoryLine -> MemoryLine(item.text)
                is ThreadItem.MemoryCard -> MemoryProposal(item, actions)
                is ThreadItem.Live -> LiveStep(item.progress, actions, backTo)
            }
        }
    }
}

@Composable
private fun DayLine(day: LocalDate, zone: ZoneId) {
    val today = LocalDate.now(zone)
    val label = when (day) {
        today -> stringResource(R.string.rd_activity_today)
        today.minusDays(1) -> stringResource(R.string.rd_activity_yesterday)
        else -> day.format(DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM))
    }
    Text(label.uppercase(), style = MaterialTheme.typography.labelMedium, color = OpenMobTheme.colors.inkSecondary,
         textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
}

private fun clock(ms: Long, zone: ZoneId): String =
    Instant.ofEpochMilli(ms).atZone(zone).format(DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT))

@Composable
private fun RequestBubble(item: ThreadItem.Request, zone: ZoneId) {
    val c = OpenMobTheme.colors
    val you = stringResource(R.string.rd_thread_you, item.text)
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        // A correction or an answer: the same bubble, with its caption in the timestamp's style.
        item.caption?.let { Text(stringResource(it), style = MaterialTheme.typography.labelSmall, color = c.inkSecondary,
                                 modifier = Modifier.padding(end = 4.dp)) }
        Text(
            item.text, style = MaterialTheme.typography.bodyLarge, color = c.ink,
            modifier = Modifier.widthIn(max = 300.dp)
                .background(c.neutralContainer, RoundedCornerShape(18.dp, 18.dp, 4.dp, 18.dp))
                .padding(horizontal = 14.dp, vertical = 10.dp)
                .semantics { contentDescription = you },
        )
        if (item.atMs > 0) Text(clock(item.atMs, zone), style = MaterialTheme.typography.labelSmall, color = c.inkSecondary,
                                modifier = Modifier.padding(end = 4.dp))
    }
}

/** "Done · 6 steps · 12 s" (collapsed; expands to the step list), then the reply. Long-press the reply to copy. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ReplyBlock(item: ThreadItem.Reply) {
    val c = OpenMobTheme.colors
    val context = LocalContext.current
    var open by rememberSaveable(item.key) { mutableStateOf(false) }
    val word = when (item.outcome) {
        "done" -> stringResource(R.string.rd_activity_done)
        "failed" -> stringResource(R.string.rd_thread_failed)
        // The task reached an app the owner blocked (docs/design/blocked-apps.md): stopped, not failed.
        "blocked" -> stringResource(R.string.blocked_thread_outcome)
        else -> ""
    }
    val parts = listOfNotNull(
        word.takeIf { it.isNotEmpty() },
        item.steps.takeIf { it > 0 }?.let { pluralStringResource(R.plurals.rd_thread_steps, it, it) },
        item.durationMs.takeIf { it > 0 }?.let { duration(it) },
    )
    Column(Modifier.fillMaxWidth().padding(end = 24.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        if (parts.isNotEmpty()) {
            val expandable = item.stepLines.isNotEmpty()
            val state = stringResource(if (open) R.string.rd_expanded else R.string.rd_collapsed)
            Row(
                Modifier.heightIn(min = 48.dp).widthIn(min = 48.dp)
                    .then(if (expandable) Modifier.combinedClickable(role = Role.Button, onClick = { open = !open })
                              .semantics { stateDescription = state } else Modifier)
                    .padding(end = 10.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                when (item.outcome) {
                    "done" -> Icon(CheckIcon, contentDescription = null, tint = c.signal, modifier = Modifier.size(16.dp))
                    "failed" -> Icon(Icons.Filled.Warning, contentDescription = null, tint = c.onDangerContainer, modifier = Modifier.size(16.dp))
                    "blocked" -> Icon(BlockIcon, contentDescription = null, tint = c.ink, modifier = Modifier.size(16.dp))
                }
                Text(parts.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
                if (expandable) {
                    Icon(if (open) Icons.Filled.KeyboardArrowDown else Icons.AutoMirrored.Filled.KeyboardArrowRight,
                         contentDescription = null, tint = c.inkSecondary, modifier = Modifier.size(16.dp))
                }
            }
            if (open) {
                Column(
                    Modifier.fillMaxWidth().background(c.surface, RoundedCornerShape(12.dp))
                        .border(1.dp, c.border, RoundedCornerShape(12.dp)).padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    item.stepLines.forEachIndexed { i, line ->
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("${i + 1}", style = OpenMobTheme.mono.small, color = c.inkTertiary, textAlign = TextAlign.End,
                                 modifier = Modifier.widthIn(min = 18.dp))
                            Text(HomeMapper.stepLabel(line), style = OpenMobTheme.mono.small, color = c.ink)
                        }
                    }
                }
            }
        }
        if (item.text.isNotEmpty()) {
            val copied = stringResource(R.string.rd_thread_copied)
            val copyLabel = stringResource(R.string.rd_thread_copy)
            val agent = stringResource(R.string.rd_thread_agent, item.text)
            val copy = { copyText(context, item.text); Toast.makeText(context, copied, Toast.LENGTH_SHORT).show() }
            Text(
                item.text, style = MaterialTheme.typography.bodyLarge, color = c.ink,
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)
                    .combinedClickable(onClick = {}, onLongClick = copy, onLongClickLabel = copyLabel)
                    .semantics {
                        contentDescription = agent
                        customActions = listOf(CustomAccessibilityAction(copyLabel) { copy(); true })
                    },
            )
        }
    }
}

internal fun copyText(context: Context, text: String) {
    context.getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("OpenMob reply", text))
}

@Composable
private fun SystemLine(item: ThreadItem.System, zone: ZoneId) {
    val c = OpenMobTheme.colors
    Row(Modifier.fillMaxWidth().semantics(mergeDescendants = true) {}, horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically) {
        Icon(if (item.interrupted) Icons.Filled.Warning else if (item.denied) Icons.Filled.Close else StopSquare, contentDescription = null,
             tint = c.ink, modifier = Modifier.size(14.dp))
        Text(stringResource(if (item.interrupted) R.string.rd_thread_failed else if (item.denied) R.string.rd_thread_denied
                            else R.string.rd_activity_stopped_you),
             style = MaterialTheme.typography.labelLarge, color = c.ink, modifier = Modifier.padding(start = 8.dp))
        if (item.atMs > 0) Text(" · ${clock(item.atMs, zone)}", style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
    }
}

/** "Your agent asks": the agent's question, from the server and not checked by this phone (blue, never amber). */
@Composable
fun QuestionCard(text: String, readOnly: Boolean = false) {
    val c = OpenMobTheme.colors
    Column(
        Modifier.fillMaxWidth().background(c.signalContainer, RoundedCornerShape(OpenMobTheme.radii.md))
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite }
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(stringResource(R.string.rd_home_question), style = MaterialTheme.typography.labelMedium, color = c.signal)
        Text(text, style = MaterialTheme.typography.titleSmall, color = c.ink)
        Text(stringResource(R.string.rd_thread_question_source), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        if (!readOnly) {
            Text(stringResource(R.string.rd_thread_answer_below), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
            // Review 4 L10: a question can be planted ("type your password to continue"); the answer goes to the server.
            Text(stringResource(R.string.rd_thread_no_secrets), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        }
    }
}

const val TAG_THREAD_MEMORY = "thread-memory"
fun threadMemorySaveTag(id: String) = "thread-memory-save-$id"
fun threadMemoryDismissTag(id: String) = "thread-memory-dismiss-$id"

/** "Used your preferences: …" and "Sending to …": one small line, not a card (§3.9). */
@Composable
private fun MemoryLine(text: String) {
    if (!SecureWhileShown()) return // review 5 P5-L4: out of screenshots and Faster frames while it shows
    Text(text, style = MaterialTheme.typography.bodySmall, color = OpenMobTheme.colors.inkSecondary,
         modifier = Modifier.fillMaxWidth().testTag(TAG_THREAD_MEMORY))
}

/** "Save this? …": the agent's proposal, nothing saved until Save. Text comes from the server (a placeholder for a
 *  deleted note or an untrusted phone, with no buttons); a saved one says "Saved". */
@Composable
private fun MemoryProposal(item: ThreadItem.MemoryCard, actions: HomeActions) {
    if (!SecureWhileShown()) return // review 5 P5-L4
    val c = OpenMobTheme.colors
    Column(
        Modifier.fillMaxWidth().background(c.signalContainer, RoundedCornerShape(OpenMobTheme.radii.md))
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(item.text, style = MaterialTheme.typography.titleSmall, color = c.ink)
        // Where a proposal came from (review 5 M5-L3): "Suggested from what the agent saw on screen", the app.
        if (item.origin.isNotBlank()) Text(item.origin, style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        when (item.status) {
            "proposed" -> dev.openmob.companion.ui.components.ButtonPair {
                Box(Modifier.weight(1f)) {
                    dev.openmob.companion.ui.components.PrimaryButton(stringResource(R.string.memory_save),
                        onClick = { actions.memoryConfirm(item.noteId) }, modifier = Modifier.testTag(threadMemorySaveTag(item.noteId)))
                }
                Box(Modifier.weight(1f)) {
                    dev.openmob.companion.ui.components.SecondaryButton(stringResource(R.string.rd_memory_not_now),
                        onClick = { actions.memoryDismiss(item.noteId) }, modifier = Modifier.testTag(threadMemoryDismissTag(item.noteId)))
                }
            }
            // A current server words a saved card "Saved: …" itself; an older one still says "Save this? …".
            "active" -> if (!item.text.startsWith("Saved")) {
                Text(stringResource(R.string.rd_memory_saved), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
            }
        }
    }
}

/** The running task's current step: the last item, a polite live region. */
@Composable
private fun LiveStep(task: TaskProgress, actions: HomeActions, backTo: Pair<String, String>?) {
    val c = OpenMobTheme.colors
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(
            Modifier.fillMaxWidth().heightIn(min = 56.dp).testTag(TAG_LIVE_STEP)
                .background(c.signalContainer.copy(alpha = if (c.isDark) 1f else 0.6f), RoundedCornerShape(OpenMobTheme.radii.md))
                .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite }
                .padding(horizontal = 14.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    if (task.step > 0) stringResource(R.string.rd_thread_working_step, task.step) else stringResource(R.string.rd_status_working),
                    style = MaterialTheme.typography.labelMedium, color = c.signal,
                )
                Text(task.stepText ?: task.headline ?: stringResource(R.string.rd_home_step_waiting),
                     style = MaterialTheme.typography.bodyLarge, color = c.ink)
            }
            task.elapsedSeconds?.let { Text(elapsed(it), style = OpenMobTheme.mono.medium, color = c.inkSecondary) }
        }
        backTo?.let { (label, pkg) ->
            dev.openmob.companion.ui.components.LinkButton(stringResource(R.string.rd_home_back_to_app, label),
                                                           onClick = { actions.backToApp(pkg) })
        }
    }
}

/** "Jump to latest": when the owner scrolled up while the agent works. */
@Composable
fun JumpToLatest(onClick: () -> Unit, modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    Box(
        modifier.heightIn(min = 48.dp).background(c.inverse, RoundedCornerShape(24.dp))
            .combinedClickableCompat(onClick).testTag(TAG_JUMP).padding(horizontal = 16.dp),
        contentAlignment = Alignment.Center,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Icon(Icons.Filled.KeyboardArrowDown, contentDescription = null, tint = c.onInverse, modifier = Modifier.size(18.dp))
            Text(stringResource(R.string.rd_thread_jump), style = MaterialTheme.typography.labelLarge, color = c.onInverse)
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
private fun Modifier.combinedClickableCompat(onClick: () -> Unit): Modifier = this.combinedClickable(role = Role.Button, onClick = onClick)

/** A new chat: the calm "Your phone is ready". */
@Composable
fun EmptyChat(modifier: Modifier = Modifier) {
    val c = OpenMobTheme.colors
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
           horizontalAlignment = Alignment.CenterHorizontally,
           verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically)) {
        AppMark()
        Text(stringResource(R.string.rd_empty_title), style = MaterialTheme.typography.headlineMedium, color = c.ink, textAlign = TextAlign.Center)
        Text(stringResource(R.string.rd_empty_body), style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary, textAlign = TextAlign.Center)
        Text(stringResource(R.string.rd_empty_note), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary, textAlign = TextAlign.Center)
    }
}
