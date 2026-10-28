package dev.openmob.companion.ui.home

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedIconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.openmob.companion.AppState
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.MicIcon
import dev.openmob.companion.ui.theme.PillShape
import dev.openmob.companion.ui.components.SendIcon
import dev.openmob.companion.ui.components.largeText
import dev.openmob.companion.ui.theme.OpenMobTheme

const val TAG_COMPOSER = "composer"
const val TAG_COMPOSER_FIELD = "composer-field"
const val TAG_COMPOSER_SEND = "composer-send"
const val TAG_COMPOSER_MIC = "composer-mic"
const val TAG_MODEL_CHIP = "composer-model"

/** The composer's draft, hoisted so dictation can fill it (it never sends by itself). */
@Composable
fun rememberDraft(): MutableState<String> = rememberSaveable { mutableStateOf("") }

/** "Auto", "Low", "Medium", "High". */
@Composable
fun effortLabel(effort: String): String = stringResource(when (effort) {
    "low" -> R.string.rd_effort_low
    "medium" -> R.string.rd_effort_medium
    "high" -> R.string.rd_effort_high
    else -> R.string.rd_effort_auto
})

/**
 * Home's composer (canvas HomeComposer / HomeComposerWorking): a growing field (to about 5 lines, then it scrolls),
 * and under it the model chip, the mic (Android's speech recognizer; it fills the field) and Send. While a task
 * runs it sends a correction to the agent ("Send to agent"), and the model chip is locked: a pick applies to the
 * next task. No attach, no voice mode.
 */
@Composable
fun Composer(
    draft: MutableState<String>,
    working: Boolean,
    /** The agent asked a question: the text is the answer. */
    answering: Boolean = false,
    /** Not connected: disabled, "Connect to give your agent a task". */
    offline: Boolean = false,
    /** Below the server's minimum app version (§3.7): disabled, "Update to ask your agent", no model chip. */
    updateRequired: Boolean = false,
    enabled: Boolean,
    models: AppState.ModelState?,
    onModel: () -> Unit,
    onMic: () -> Unit,
    /** True when sent (the field clears). */
    onSend: (String) -> Boolean,
    modifier: Modifier = Modifier,
) {
    val c = OpenMobTheme.colors
    val text = draft.value
    @Suppress("NAME_SHADOWING") val enabled = enabled && !updateRequired
    val label = stringResource(when {
        updateRequired -> R.string.update_composer_label
        offline -> R.string.rd_composer_label_offline
        answering -> R.string.rd_composer_label_answer
        working -> R.string.rd_composer_label_working
        else -> R.string.rd_composer_label
    })
    val send = { if (text.isNotBlank() && onSend(text)) draft.value = "" }
    Column(modifier.fillMaxWidth().testTag(TAG_COMPOSER), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Column(
            Modifier.fillMaxWidth()
                .background(c.surface, RoundedCornerShape(24.dp))
                .border(1.dp, c.outline, RoundedCornerShape(24.dp))
                .padding(start = 10.dp, end = 10.dp, top = 12.dp, bottom = 10.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            val style = MaterialTheme.typography.bodyLarge.copy(color = c.ink)
            BasicTextField(
                value = text,
                onValueChange = { draft.value = it },
                enabled = enabled,
                textStyle = style,
                cursorBrush = SolidColor(c.signal),
                minLines = if (largeText() || updateRequired) 1 else if (working) 2 else 3,
                maxLines = 5, // then it scrolls
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).padding(horizontal = 8.dp).testTag(TAG_COMPOSER_FIELD)
                    .semantics { contentDescription = label },
                decorationBox = { inner ->
                    Box {
                        if (text.isEmpty()) {
                            Text(stringResource(when {
                                updateRequired -> R.string.update_composer_hint
                                offline -> R.string.rd_composer_hint_offline
                                answering -> R.string.rd_composer_hint_answer
                                working -> R.string.rd_composer_hint_working
                                else -> R.string.rd_composer_hint
                            }),
                                 style = style, color = c.inkTertiary)
                        }
                        inner()
                    }
                },
            )
            val chip = @Composable { if (models != null && !offline && !updateRequired) ModelChip(models, locked = working, onClick = onModel) }
            val buttons = @Composable {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedIconButton(
                        onClick = onMic, enabled = enabled,
                        modifier = Modifier.size(48.dp).testTag(TAG_COMPOSER_MIC),
                        border = BorderStroke(1.dp, c.outline),
                        colors = IconButtonDefaults.outlinedIconButtonColors(containerColor = c.surface, contentColor = c.ink),
                    ) { Icon(MicIcon, contentDescription = stringResource(R.string.rd_composer_dictate), modifier = Modifier.size(22.dp)) }
                    Button(
                        onClick = send,
                        enabled = enabled && text.isNotBlank(),
                        modifier = Modifier.heightIn(min = 48.dp).testTag(TAG_COMPOSER_SEND),
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp),
                        shape = PillShape,
                        colors = ButtonDefaults.buttonColors(containerColor = c.signal, contentColor = c.onSignal),
                    ) {
                        Text(stringResource(when {
                            answering -> R.string.rd_composer_send_answer
                            working -> R.string.rd_composer_send_working
                            else -> R.string.rd_composer_send
                        }),
                             style = MaterialTheme.typography.labelLarge, maxLines = 1, softWrap = false)
                        // "Send to agent" is long: no arrow then, so the row fits a phone's width at normal text.
                        if (!working && !answering) Icon(SendIcon, contentDescription = null, modifier = Modifier.padding(start = 6.dp).size(18.dp))
                    }
                }
            }
            // One row; at large text the chip gets its own line above the buttons. Update required: a plain disabled
            // field (the mockup), nothing to press.
            if (updateRequired) {
                // no chip, mic or Send
            } else if (largeText()) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) { chip(); buttons() }
            } else {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    // The chip gives way (ellipsizes) on a narrow phone; Send and the mic keep their size.
                    Box(Modifier.weight(1f)) { chip() }
                    buttons()
                }
            }
        }
        // At large text the locked chip says it itself (its description): the hint line would push the field off.
        if (working && models != null && !largeText()) {
            Text(stringResource(R.string.rd_composer_model_hint), style = MaterialTheme.typography.bodySmall,
                 color = c.inkTertiary, modifier = Modifier.padding(start = 14.dp))
        }
    }
}

/** "Haiku 5.5 · Auto ▾" (opens the model sheet); while a task runs "🔒 Haiku 5.5", disabled. */
@Composable
private fun ModelChip(models: AppState.ModelState, locked: Boolean, onClick: () -> Unit) {
    val c = OpenMobTheme.colors
    val current = models.current
    val name = current?.label ?: models.model
    val shown = if (!locked && current?.effort == true) "$name · ${effortLabel(models.effort)}" else name
    val description = if (locked) stringResource(R.string.rd_composer_model_locked_desc, name)
                      else stringResource(R.string.rd_composer_model_desc, shown)
    OutlinedButton(
        onClick = onClick,
        enabled = !locked,
        modifier = Modifier.heightIn(min = 48.dp).testTag(TAG_MODEL_CHIP).semantics { contentDescription = description },
        shape = PillShape,
        border = BorderStroke(1.dp, c.border),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = c.ground, contentColor = c.ink,
                                                     disabledContainerColor = c.ground, disabledContentColor = c.inkSecondary),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(start = 14.dp, end = 10.dp),
    ) {
        if (locked) Icon(Icons.Filled.Lock, contentDescription = null, modifier = Modifier.padding(end = 6.dp).size(16.dp))
        Text(shown, style = MaterialTheme.typography.labelLarge, maxLines = 1,
             overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
        if (!locked) Icon(Icons.Filled.KeyboardArrowDown, contentDescription = null, modifier = Modifier.padding(start = 2.dp).size(20.dp))
    }
}
