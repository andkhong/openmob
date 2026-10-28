package dev.openmob.companion.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import dev.openmob.companion.R
import dev.openmob.companion.ui.theme.OpenMobTheme

const val TAG_RENAME_FIELD = "rename-field"
const val TAG_RENAME_SAVE = "rename-save"
const val TAG_DELETE_CONFIRM = "delete-confirm"
const val TITLE_MAX = 120

/** Rename a chat: one line, 120 characters at most (the server trims and caps too); Save off while empty. */
@Composable
fun RenameChatDialog(initial: String, onSave: (String) -> Unit, onCancel: () -> Unit) {
    Dialog(onDismissRequest = onCancel) { RenameChatContent(initial, onSave, onCancel) }
}

/** The rename dialog's content (tests draw it on its own: Robolectric never idles a text field inside a dialog window). */
@Composable
fun RenameChatContent(initial: String, onSave: (String) -> Unit, onCancel: () -> Unit) {
    var title by rememberSaveable { mutableStateOf(initial.take(TITLE_MAX)) }
    val ok = title.isNotBlank()
    val c = OpenMobTheme.colors
    run {
        Surface(shape = RoundedCornerShape(28.dp), color = c.surface) {
            Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text(stringResource(R.string.rd_chat_rename_title), style = MaterialTheme.typography.headlineSmall, color = c.ink,
                     modifier = Modifier.semantics { heading() })
                OutlinedTextField(
                    value = title, onValueChange = { title = it.replace('\n', ' ').take(TITLE_MAX) }, singleLine = true,
                    label = { Text(stringResource(R.string.rd_chat_rename_label)) },
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                    modifier = Modifier.fillMaxWidth().testTag(TAG_RENAME_FIELD),
                )
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    TextButton(onClick = onCancel, modifier = Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.ui_cancel)) }
                    TextButton(onClick = { onSave(title.trim()) }, enabled = ok,
                               modifier = Modifier.heightIn(min = 48.dp).testTag(TAG_RENAME_SAVE)) { Text(stringResource(R.string.rd_chat_save)) }
                }
            }
        }
    }
}

/** Delete a chat, after this confirmation. No screen lock: it only removes history. Red, never amber. */
@Composable
fun DeleteChatDialog(onDelete: () -> Unit, onCancel: () -> Unit) {
    val c = OpenMobTheme.colors
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text(stringResource(R.string.rd_chat_delete_title)) },
        text = { Text(stringResource(R.string.rd_chat_delete_body), style = MaterialTheme.typography.bodyMedium) },
        confirmButton = {
            TextButton(onClick = onDelete, colors = ButtonDefaults.textButtonColors(contentColor = c.onDangerContainer),
                       modifier = Modifier.heightIn(min = 48.dp).testTag(TAG_DELETE_CONFIRM)) { Text(stringResource(R.string.rd_chat_delete)) }
        },
        dismissButton = {
            TextButton(onClick = onCancel, modifier = Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.ui_cancel)) }
        },
    )
}
