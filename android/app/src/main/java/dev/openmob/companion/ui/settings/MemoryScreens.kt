package dev.openmob.companion.ui.settings

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.drawable.Drawable
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.openmob.companion.AppState
import dev.openmob.companion.ConnectionService
import dev.openmob.companion.MemoryNotes
import dev.openmob.companion.MemoryNotes.Note
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.ListRow
import dev.openmob.companion.ui.components.OmCard
import dev.openmob.companion.ui.components.PrimaryButton
import dev.openmob.companion.ui.components.SecondaryButton
import dev.openmob.companion.ui.components.SectionHeader
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.nav.ScreenScaffold
import dev.openmob.companion.ui.setup.SecureWhileShown
import dev.openmob.companion.ui.theme.OpenMobTheme
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/*
 * Settings › What OpenMob remembers (docs/superpowers/specs/2026-10-20-preferences-memory-design.md §5.5;
 * docs/phone-protocol.md §3.9): the owner's saved preferences, from the server. Its own page, opened from one Settings
 * row that shows only when the server's welcome said `memory` (the switch on and this phone trusted for approvals).
 * Waiting for you (Save / Dismiss), About you, People, Apps (by app, with its icon). Tap a note to edit it; its menu
 * deletes it. No note text ever goes into a notification.
 */

/** What the page reads and changes; [AppMemorySource] on the phone, a fake in tests. */
interface MemorySource {
    /** The welcome said this phone may see memory (and no `denied` came since). */
    fun available(): Boolean
    fun loaded(): Boolean
    fun notes(): List<Note>
    fun proposed(): List<Note>
    fun error(): String?
    /** Ask the server for the notes. False if not connected. */
    fun refresh(): Boolean
    fun edit(id: String, text: String?, contactName: String?): Boolean
    fun delete(id: String): Boolean
    fun confirm(id: String): Boolean
    fun dismiss(id: String): Boolean
    fun label(pkg: String): String = pkg
    fun icon(pkg: String): Drawable? = null
    fun listen(listener: () -> Unit): () -> Unit
}

class AppMemorySource(context: Context) : MemorySource {
    private val app = context.applicationContext
    override fun available() = MemoryNotes.supported
    override fun loaded() = MemoryNotes.loaded
    override fun notes() = MemoryNotes.notes
    override fun proposed() = MemoryNotes.proposed
    override fun error() = MemoryNotes.error
    override fun refresh() = ConnectionService.sendMemory(MemoryNotes.listRequest())
    override fun edit(id: String, text: String?, contactName: String?) =
        ConnectionService.sendMemory(MemoryNotes.editRequest(id, text, contactName))
    override fun delete(id: String) = ConnectionService.sendMemory(MemoryNotes.deleteRequest(id))
    override fun confirm(id: String) = ConnectionService.sendMemory(MemoryNotes.confirmRequest(id))
    override fun dismiss(id: String) = ConnectionService.sendMemory(MemoryNotes.dismissRequest(id))
    override fun label(pkg: String): String = runCatching {
        app.packageManager.getApplicationLabel(app.packageManager.getApplicationInfo(pkg, 0)).toString()
    }.getOrDefault(pkg)
    override fun icon(pkg: String): Drawable? = runCatching { app.packageManager.getApplicationIcon(pkg) }.getOrNull()
    override fun listen(listener: () -> Unit) = AppState.listen(listener)
}

/** The page's sections. [apps]: app notes by package, in the server's order. */
data class MemoryUiState(
    val proposed: List<Note> = emptyList(),
    val aboutYou: List<Note> = emptyList(),
    val people: List<Note> = emptyList(),
    val apps: Map<String, List<Note>> = emptyMap(),
    val available: Boolean = false,
    val loaded: Boolean = false,
    val error: String? = null,
) {
    val empty: Boolean get() = proposed.isEmpty() && aboutYou.isEmpty() && people.isEmpty() && apps.isEmpty()
}

class MemoryViewModel(val source: MemorySource) : ViewModel() {
    private val _state = MutableStateFlow(read())
    val state: StateFlow<MemoryUiState> = _state.asStateFlow()
    private val unsubscribe = source.listen { _state.value = read() }

    private fun read(): MemoryUiState {
        val notes = source.notes()
        return MemoryUiState(
            proposed = source.proposed(),
            aboutYou = notes.filter { it.kind == "about_you" },
            people = notes.filter { it.kind == "person" },
            apps = notes.filter { it.kind == "app" && it.pkg != null }.groupBy { it.pkg!! },
            available = source.available(), loaded = source.loaded(), error = source.error(),
        )
    }

    fun load() { source.refresh(); _state.value = read() }
    fun save(id: String) = source.confirm(id)
    fun dismiss(id: String) = source.dismiss(id)
    fun delete(id: String) = source.delete(id)
    /** Only what changed goes; nothing changed sends nothing (no write, no audit row). */
    fun edit(note: Note, text: String, contactName: String?): Boolean {
        val newText = text.takeIf { it != note.text }
        val newContact = contactName?.takeIf { note.kind == "person" && it != note.contactName }
        return if (newText == null && newContact == null) false else source.edit(note.id, newText, newContact)
    }
    override fun onCleared() { unsubscribe() }

    companion object {
        fun factory(context: Context): ViewModelProvider.Factory {
            val app = context.applicationContext
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T = MemoryViewModel(AppMemorySource(app)) as T
            }
        }
    }
}

const val TAG_MEMORY_ROW = "settings-memory"
const val TAG_MEMORY_WAITING = "memory-waiting"
const val TAG_MEMORY_ABOUT = "memory-about"
const val TAG_MEMORY_PEOPLE = "memory-people"
const val TAG_MEMORY_APPS = "memory-apps"
const val TAG_MEMORY_EMPTY = "memory-empty"
const val TAG_MEMORY_EDIT_FIELD = "memory-edit-text"
const val TAG_MEMORY_EDIT_CONTACT = "memory-edit-contact"
const val TAG_MEMORY_EDIT_SAVE = "memory-edit-save"
fun memorySaveTag(id: String) = "memory-save-$id"
fun memoryDismissTag(id: String) = "memory-dismiss-$id"
fun memoryNoteTag(id: String) = "memory-note-$id"
fun memoryMenuTag(id: String) = "memory-menu-$id"
fun memoryDeleteTag(id: String) = "memory-delete-$id"
const val NOTE_MAX = 300

data class MemoryActions(
    val back: () -> Unit = {},
    val save: (String) -> Unit = {},
    val dismiss: (String) -> Unit = {},
    val delete: (String) -> Unit = {},
    val edit: (Note, String, String?) -> Unit = { _, _, _ -> },
)

/** Settings' row: shown only when the server lets this phone see memory. */
@Composable
fun MemoryRow(onClick: () -> Unit) {
    OmCard(contentPadding = 0.dp) {
        ListRow(stringResource(R.string.memory_title), subtitle = stringResource(R.string.memory_row_subtitle),
                onClick = onClick, modifier = Modifier.testTag(TAG_MEMORY_ROW))
    }
}

@Composable
fun MemoryRowRoute(open: () -> Unit) {
    val context = LocalContext.current
    val vm: MemoryViewModel = viewModel(key = "memory-row", factory = MemoryViewModel.factory(context))
    val state by vm.state.collectAsStateWithLifecycle()
    if (state.available) MemoryRow(onClick = open)
}

/** A person note's who: "your wife = Sam". */
@Composable
private fun personLine(note: Note): String =
    stringResource(R.string.memory_person, note.relation.orEmpty(), note.contactName.orEmpty())

/** A proposal's card line: "Save this? <note>", or for a person "Save this? your <relation> = <contact> — <note>". */
@Composable
fun proposalLine(note: Note): String = if (note.kind == "person")
    stringResource(R.string.memory_save_person, note.relation.orEmpty(), note.contactName.orEmpty(), note.text)
else stringResource(R.string.memory_save_this, note.text)

private fun Drawable.toImage(px: Int = 96): ImageBitmap {
    val bitmap = Bitmap.createBitmap(px, px, Bitmap.Config.ARGB_8888)
    setBounds(0, 0, px, px)
    draw(Canvas(bitmap))
    return bitmap.asImageBitmap()
}

@Composable
private fun AppIcon(pkg: String, label: String, icon: (String) -> Drawable?) {
    val c = OpenMobTheme.colors
    val image = remember(pkg) { runCatching { icon(pkg)?.toImage() }.getOrNull() }
    if (image != null) {
        Image(image, contentDescription = null, modifier = Modifier.size(28.dp))
    } else {
        Box(Modifier.size(28.dp).background(c.neutralContainer, RoundedCornerShape(8.dp)), contentAlignment = Alignment.Center) {
            Text(label.take(1).uppercase(), style = MaterialTheme.typography.titleSmall, color = c.inkSecondary)
        }
    }
}

/** One saved note: tap to edit; its menu edits or deletes. */
@Composable
private fun NoteRow(note: Note, title: String, subtitle: String?, onEdit: () -> Unit, onDelete: () -> Unit) {
    var menu by remember { mutableStateOf(false) }
    ListRow(title, subtitle = subtitle, onClick = onEdit, modifier = Modifier.testTag(memoryNoteTag(note.id)), trailing = {
        Box {
            IconButton(onClick = { menu = true }, modifier = Modifier.testTag(memoryMenuTag(note.id))) {
                Icon(Icons.Filled.MoreVert, contentDescription = stringResource(R.string.memory_more_cd),
                     tint = OpenMobTheme.colors.inkSecondary)
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(text = { Text(stringResource(R.string.memory_edit)) }, onClick = { menu = false; onEdit() })
                DropdownMenuItem(text = { Text(stringResource(R.string.memory_delete)) }, onClick = { menu = false; onDelete() },
                                 modifier = Modifier.testTag(memoryDeleteTag(note.id)))
            }
        }
    })
}

@Composable
private fun Section(title: String, tag: String, content: @Composable () -> Unit) {
    Column(Modifier.testTag(tag)) {
        SectionHeader(title)
        content()
    }
}

/** The page: back, the title, then its content. */
@Composable
fun MemoryPage(state: MemoryUiState, actions: MemoryActions, label: (String) -> String = { it },
               icon: (String) -> Drawable? = { null }) {
    // Review 5 P5-L4: the notes stay out of screenshots, the live view and Faster mode's frames (an agent's task may
    // be running while the owner reads them).
    if (!SecureWhileShown()) return
    ScreenScaffold(title = stringResource(Route.Memory.title), onBack = actions.back) {
        MemoryContent(state, actions, label, icon)
    }
}

/** Waiting for you, About you, People, Apps, in that order; each only when it has notes. Empty: how to add one. */
@Composable
fun MemoryContent(state: MemoryUiState, actions: MemoryActions, label: (String) -> String = { it },
                  icon: (String) -> Drawable? = { null }) {
    val c = OpenMobTheme.colors
    var editing by remember { mutableStateOf<Note?>(null) }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        when {
            !state.available -> Text(stringResource(R.string.memory_unavailable), style = MaterialTheme.typography.bodyMedium,
                                     color = c.inkSecondary)
            !state.loaded -> Text(stringResource(R.string.memory_loading), style = MaterialTheme.typography.bodyMedium,
                                  color = c.inkSecondary)
            else -> {
                Text(stringResource(R.string.memory_intro), style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary)
                state.error?.let {
                    Text(stringResource(if (it == "bad_note") R.string.memory_error_bad_note else R.string.memory_error_other),
                         style = MaterialTheme.typography.bodySmall, color = c.onDangerContainer)
                }
                if (state.empty) {
                    OmCard(modifier = Modifier.testTag(TAG_MEMORY_EMPTY)) {
                        Text(stringResource(R.string.memory_empty_title), style = MaterialTheme.typography.titleSmall, color = c.ink)
                        Text(stringResource(R.string.memory_empty), style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary)
                    }
                }
                if (state.proposed.isNotEmpty()) Section(stringResource(R.string.memory_waiting), TAG_MEMORY_WAITING) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        state.proposed.forEach { note ->
                            OmCard(highlighted = true) {
                                Text(proposalLine(note), style = MaterialTheme.typography.bodyLarge, color = c.ink)
                                Row(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Box(Modifier.weight(1f)) {
                                        PrimaryButton(stringResource(R.string.memory_save), onClick = { actions.save(note.id) },
                                                      modifier = Modifier.testTag(memorySaveTag(note.id)))
                                    }
                                    Box(Modifier.weight(1f)) {
                                        SecondaryButton(stringResource(R.string.memory_dismiss), onClick = { actions.dismiss(note.id) },
                                                        modifier = Modifier.testTag(memoryDismissTag(note.id)))
                                    }
                                }
                            }
                        }
                    }
                }
                if (state.aboutYou.isNotEmpty()) Section(stringResource(R.string.memory_about), TAG_MEMORY_ABOUT) {
                    OmCard(contentPadding = 0.dp) {
                        state.aboutYou.forEachIndexed { i, note ->
                            if (i > 0) HorizontalDivider(color = c.divider)
                            NoteRow(note, note.text, null, onEdit = { editing = note }, onDelete = { actions.delete(note.id) })
                        }
                    }
                }
                if (state.people.isNotEmpty()) Section(stringResource(R.string.memory_people), TAG_MEMORY_PEOPLE) {
                    OmCard(contentPadding = 0.dp) {
                        state.people.forEachIndexed { i, note ->
                            if (i > 0) HorizontalDivider(color = c.divider)
                            NoteRow(note, personLine(note), note.text, onEdit = { editing = note }, onDelete = { actions.delete(note.id) })
                        }
                    }
                }
                if (state.apps.isNotEmpty()) Section(stringResource(R.string.memory_apps), TAG_MEMORY_APPS) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        state.apps.forEach { (pkg, notes) ->
                            val name = label(pkg)
                            OmCard(contentPadding = 0.dp) {
                                Row(Modifier.padding(start = 16.dp, top = 12.dp, end = 16.dp, bottom = 4.dp),
                                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                    AppIcon(pkg, name, icon)
                                    Text(name, style = MaterialTheme.typography.titleSmall, color = c.ink,
                                         modifier = Modifier.semantics { heading() })
                                }
                                notes.forEachIndexed { i, note ->
                                    if (i > 0) HorizontalDivider(color = c.divider)
                                    NoteRow(note, note.text, null, onEdit = { editing = note }, onDelete = { actions.delete(note.id) })
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    editing?.let { note ->
        Dialog(onDismissRequest = { editing = null }) {
            EditNoteContent(note, onSave = { text, contact -> editing = null; actions.edit(note, text, contact) },
                            onCancel = { editing = null })
        }
    }
}

/** The edit dialog's content (tests draw it on its own: Robolectric never idles a text field inside a dialog window).
 *  The note's text, and for a person note its contact name; at most 300 characters; Save off while the text is blank. */
@Composable
fun EditNoteContent(note: Note, onSave: (String, String?) -> Unit, onCancel: () -> Unit) {
    val c = OpenMobTheme.colors
    var text by rememberSaveable(note.id) { mutableStateOf(note.text.take(NOTE_MAX)) }
    var contact by rememberSaveable(note.id) { mutableStateOf(note.contactName.orEmpty()) }
    val person = note.kind == "person"
    val ok = text.isNotBlank() && (!person || contact.isNotBlank())
    Surface(shape = RoundedCornerShape(28.dp), color = c.surface) {
        Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(stringResource(R.string.memory_edit_title), style = MaterialTheme.typography.headlineSmall, color = c.ink,
                 modifier = Modifier.semantics { heading() })
            if (person) {
                Text(stringResource(R.string.memory_edit_relation, note.relation.orEmpty()), style = MaterialTheme.typography.bodySmall,
                     color = c.inkSecondary)
                OutlinedTextField(
                    value = contact, onValueChange = { contact = it.replace('\n', ' ').take(NOTE_MAX) }, singleLine = true,
                    label = { Text(stringResource(R.string.memory_edit_contact)) },
                    modifier = Modifier.fillMaxWidth().testTag(TAG_MEMORY_EDIT_CONTACT),
                )
            }
            OutlinedTextField(
                value = text, onValueChange = { text = it.replace('\n', ' ').take(NOTE_MAX) },
                label = { Text(stringResource(R.string.memory_edit_text)) },
                modifier = Modifier.fillMaxWidth().testTag(TAG_MEMORY_EDIT_FIELD),
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = onCancel, modifier = Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.ui_cancel)) }
                TextButton(onClick = { onSave(text.trim(), if (person) contact.trim() else null) }, enabled = ok,
                           modifier = Modifier.heightIn(min = 48.dp).testTag(TAG_MEMORY_EDIT_SAVE)) {
                    Text(stringResource(R.string.memory_save))
                }
            }
        }
    }
}

/** The page, wired to the server: it asks for the notes each time it shows. */
@Composable
fun MemoryRoute(back: () -> Unit) {
    val context = LocalContext.current
    val vm: MemoryViewModel = viewModel(key = "memory-page", factory = MemoryViewModel.factory(context))
    val state by vm.state.collectAsStateWithLifecycle()
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { vm.load() }
    MemoryPage(state, MemoryActions(
        back = back, save = { vm.save(it) }, dismiss = { vm.dismiss(it) }, delete = { vm.delete(it) },
        edit = { note, text, contact -> vm.edit(note, text, contact) },
    ), label = vm.source::label, icon = vm.source::icon)
}
