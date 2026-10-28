package dev.openmob.companion.ui.settings

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
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
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Lock
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.openmob.companion.BlockedApps
import dev.openmob.companion.R
import dev.openmob.companion.gate.BlockedList
import dev.openmob.companion.gate.GateRules
import dev.openmob.companion.ui.components.ListRow
import dev.openmob.companion.ui.components.OmCard
import dev.openmob.companion.ui.components.PrimaryButton
import dev.openmob.companion.ui.components.SecondaryButton
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.nav.ScreenScaffold
import dev.openmob.companion.ui.theme.OpenMobTheme
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/*
 * Settings › Blocked apps and the Block-apps list (owner-approved revision, 2026-10-20: switches; "Blocked Apps
 * Mockup"; docs/design/blocked-apps.md). A switch turned on blocks at once (a tightening, no confirmation). A switch
 * turned off opens "Unblock <app>?", then Android's screen-lock prompt ([BlockedSource.confirmUnblock]); only its
 * success removes the app. Built-in blocks show a disabled switch, locked on. Agents can't reach these screens (the
 * gate's own_packages rule).
 */

/** One app in the lists: its package and label. */
data class BlockedRow(val pkg: String, val label: String)

/** An installed app in the list. [builtIn]: a built-in sensitive app (switch locked on); [blocked]: on the owner's list. */
data class AppChoice(val pkg: String, val label: String, val builtIn: Boolean, val blocked: Boolean)

/** What the screens read and change; [AppBlockedSource] on the phone, a fake in tests. */
interface BlockedSource {
    fun blocked(): List<String>
    fun label(pkg: String): String
    /** The app's icon as Android shows it, or null (not installed). */
    fun icon(pkg: String): Drawable? = null
    /** Launchable installed apps (pkg, label). */
    fun installed(): List<Pair<String, String>>
    fun builtIn(pkg: String): Boolean
    fun block(packages: List<String>): Boolean
    /** Android's screen-lock prompt, then the unblock; nothing changes unless the owner passes it. */
    fun confirmUnblock(activity: Activity?, row: BlockedRow, onDone: () -> Unit)
    fun listen(listener: () -> Unit): () -> Unit
}

class AppBlockedSource(context: Context) : BlockedSource {
    private val app = context.applicationContext
    private val rules by lazy { GateRules.builtIn() }
    override fun blocked() = BlockedApps.list(app)
    override fun label(pkg: String): String = runCatching {
        app.packageManager.getApplicationLabel(app.packageManager.getApplicationInfo(pkg, 0)).toString()
    }.getOrDefault(pkg)
    override fun icon(pkg: String): Drawable? = runCatching { app.packageManager.getApplicationIcon(pkg) }.getOrNull()
    @Suppress("DEPRECATION")
    override fun installed(): List<Pair<String, String>> = runCatching {
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val home = BlockedApps.home(app)
        app.packageManager.queryIntentActivities(launcher, 0).map { it.activityInfo.packageName }.distinct()
            .filter { !BlockedList.protectedPackage(it, home) }.map { it to label(it) }
    }.getOrDefault(emptyList())
    override fun builtIn(pkg: String) = rules.blocked(pkg)
    override fun block(packages: List<String>) = BlockedApps.block(app, packages)
    override fun confirmUnblock(activity: Activity?, row: BlockedRow, onDone: () -> Unit) {
        val a = activity ?: return
        BlockedApps.confirmUnblock(a, row.label) { BlockedApps.unblockAfterScreenLock(app, row.pkg); onDone() }
    }
    override fun listen(listener: () -> Unit) = BlockedApps.listen(listener)
}

data class BlockedUiState(
    val rows: List<BlockedRow> = emptyList(),
    val apps: List<AppChoice> = emptyList(),
    val query: String = "",
    /** The list's filter: every app, or only those blocked by the owner. */
    val onlyBlocked: Boolean = false,
)

class BlockedAppsViewModel(val source: BlockedSource, loadApps: Boolean) : ViewModel() {
    private val installed: List<Pair<String, String>> = if (loadApps) source.installed() else emptyList()
    private val _state = MutableStateFlow(read(BlockedUiState()))
    val state: StateFlow<BlockedUiState> = _state.asStateFlow()
    private val unsubscribe = source.listen { refresh() }

    private fun read(prev: BlockedUiState): BlockedUiState {
        val blocked = source.blocked()
        val set = blocked.toSet()
        val apps = installed.map { (pkg, label) -> AppChoice(pkg, label, source.builtIn(pkg), pkg in set) }
            .sortedBy { it.label.lowercase() }
        return prev.copy(rows = blocked.map { BlockedRow(it, source.label(it)) }, apps = apps)
    }

    fun refresh() { _state.value = read(_state.value) }
    fun search(q: String) { _state.value = _state.value.copy(query = q.take(60)) }
    fun showOnlyBlocked(on: Boolean) { _state.value = _state.value.copy(onlyBlocked = on) }

    /** A switch turned on: blocked at once (no lock: a tightening). Built-in apps are blocked already. */
    fun block(pkg: String): Boolean {
        if (source.builtIn(pkg)) return false
        val ok = source.block(listOf(pkg))
        refresh()
        return ok
    }

    /** After "Unblock with screen lock": Android's prompt; the app goes only if the owner passes it. */
    fun unblock(activity: Activity?, row: BlockedRow) = source.confirmUnblock(activity, row) { refresh() }

    override fun onCleared() { unsubscribe() }

    companion object {
        fun factory(context: Context, loadApps: Boolean): ViewModelProvider.Factory {
            val app = context.applicationContext
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T = BlockedAppsViewModel(AppBlockedSource(app), loadApps) as T
            }
        }
    }
}

const val TAG_BLOCKED_ADD = "blocked-add"
const val TAG_BLOCKED_BUILTIN = "blocked-builtin"
const val TAG_BLOCKED_YOURS = "blocked-yours"
const val TAG_BLOCKED_CONFIRM_UNBLOCK = "blocked-confirm-unblock"
const val TAG_BLOCKED_KEEP = "blocked-keep"
const val TAG_BLOCKED_FILTER = "blocked-filter"
fun switchTag(pkg: String) = "blocked-switch-$pkg"

private fun Context.activity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.activity()
    else -> null
}

private fun Drawable.toImage(px: Int = 96): ImageBitmap {
    val bitmap = Bitmap.createBitmap(px, px, Bitmap.Config.ARGB_8888)
    setBounds(0, 0, px, px)
    draw(Canvas(bitmap))
    return bitmap.asImageBitmap()
}

/** The app's real icon (PackageManager), or its initial on a tile when there is none. */
@Composable
private fun AppIcon(pkg: String, label: String, icon: (String) -> Drawable?) {
    val c = OpenMobTheme.colors
    val image = remember(pkg) { runCatching { icon(pkg)?.toImage() }.getOrNull() }
    if (image != null) {
        Image(image, contentDescription = null, modifier = Modifier.size(36.dp))
    } else {
        Box(Modifier.size(36.dp).background(c.neutralContainer, RoundedCornerShape(10.dp)), contentAlignment = Alignment.Center) {
            Text(label.take(1).uppercase(), style = MaterialTheme.typography.titleSmall, color = c.inkSecondary)
        }
    }
}

/** One row: icon, name (and a subtitle), and a Material 3 switch. The whole row is the switch (one target of at least
 *  60 dp, role Switch, as ToggleRow), so TalkBack reads the name and state together and a tap anywhere flips it. */
@Composable
private fun SwitchRow(pkg: String, label: String, checked: Boolean, enabled: Boolean, description: String,
                      icon: ((String) -> Drawable?)?, subtitle: String? = null, onChange: (Boolean) -> Unit) {
    val c = OpenMobTheme.colors
    Row(
        Modifier.fillMaxWidth().heightIn(min = 60.dp)
            .toggleable(value = checked, enabled = enabled, role = Role.Switch, onValueChange = onChange)
            .semantics { contentDescription = description }
            .testTag(switchTag(pkg))
            .padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        if (icon != null) AppIcon(pkg, label, icon)
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.titleSmall, color = c.ink)
            subtitle?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = c.inkSecondary) }
        }
        Switch(
            checked = checked, onCheckedChange = null, enabled = enabled,
            thumbContent = if (!enabled) { { Icon(Icons.Filled.Lock, contentDescription = null, modifier = Modifier.size(12.dp)) } } else null,
        )
    }
}

/** "Unblock <App>?" as a bottom sheet: Unblock with screen lock (then Android's prompt) or Keep blocked. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UnblockSheet(row: BlockedRow, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    val c = OpenMobTheme.colors
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
                     containerColor = c.surface) {
        Column(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, bottom = 24.dp).navigationBarsPadding(),
               verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text(stringResource(R.string.blocked_unblock_title, row.label), style = MaterialTheme.typography.titleLarge,
                 color = c.ink, modifier = Modifier.semantics { heading() })
            Text(row.pkg, style = OpenMobTheme.mono.medium, color = c.inkSecondary)
            Text(stringResource(R.string.blocked_sheet_body, row.label), style = MaterialTheme.typography.bodyMedium, color = c.ink)
            Text(stringResource(R.string.blocked_unblock_screens), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
            PrimaryButton(stringResource(R.string.blocked_unblock_button), onClick = onConfirm, icon = Icons.Filled.Lock,
                          modifier = Modifier.testTag(TAG_BLOCKED_CONFIRM_UNBLOCK))
            SecondaryButton(stringResource(R.string.blocked_keep), onClick = onDismiss, modifier = Modifier.testTag(TAG_BLOCKED_KEEP))
            Text(stringResource(R.string.blocked_unblock_note), style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
        }
    }
}

private val BUILTINS = listOf(
    R.string.rd_blocked_banking to R.string.rd_blocked_banking_body,
    R.string.rd_blocked_wallets to R.string.rd_blocked_wallets_body,
    R.string.rd_blocked_passwords to R.string.rd_blocked_passwords_body,
    R.string.rd_blocked_openmob to R.string.rd_blocked_openmob_body,
)

const val TAG_BLOCKED_ROW = "settings-blocked-apps"

/** Settings' one row for Blocked apps: "4 built in · N by you", opening the Blocked apps page. */
@Composable
fun BlockedAppsRow(count: Int, onClick: () -> Unit) {
    OmCard(contentPadding = 0.dp) {
        ListRow(stringResource(R.string.blocked_title), subtitle = stringResource(R.string.blocked_row_subtitle, BUILTINS.size, count),
                onClick = onClick, modifier = Modifier.testTag(TAG_BLOCKED_ROW))
    }
}

/** Settings' row, with the owner's count from the phone's list. */
@Composable
fun BlockedAppsRowRoute(open: () -> Unit) {
    val context = LocalContext.current
    val vm: BlockedAppsViewModel = viewModel(key = "blocked-row", factory = BlockedAppsViewModel.factory(context, loadApps = false))
    val state by vm.state.collectAsStateWithLifecycle()
    BlockedAppsRow(state.rows.size, onClick = open)
}

/** The Blocked apps page: back, the title, then its content. */
@Composable
fun BlockedAppsPage(rows: List<BlockedRow>, onBack: () -> Unit, onAdd: () -> Unit, onUnblock: (BlockedRow) -> Unit,
                    icon: (String) -> Drawable? = { null }) {
    ScreenScaffold(title = stringResource(Route.Blocked.title), onBack = onBack) {
        BlockedAppsContent(rows, onAdd, onUnblock, icon)
    }
}

/** The page's content: the intro, "Always blocked · built in" first (switches locked on), then "Blocked by you" (each
 *  with its switch on: turning it off asks to unblock), then Block more apps, then the footer. */
@Composable
fun BlockedAppsContent(rows: List<BlockedRow>, onAdd: () -> Unit, onUnblock: (BlockedRow) -> Unit,
                       icon: (String) -> Drawable? = { null }) {
    val c = OpenMobTheme.colors
    var asking by remember { mutableStateOf<BlockedRow?>(null) }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(stringResource(R.string.blocked_intro), style = MaterialTheme.typography.bodyMedium, color = c.inkSecondary)
        OmCard(contentPadding = 0.dp, modifier = Modifier.testTag(TAG_BLOCKED_BUILTIN)) {
            Row(Modifier.padding(start = 16.dp, top = 14.dp, end = 16.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(Icons.Filled.Lock, contentDescription = null, tint = c.inkSecondary, modifier = Modifier.size(14.dp))
                Text(stringResource(R.string.blocked_builtin_section).uppercase(), style = MaterialTheme.typography.labelMedium,
                     color = c.inkSecondary, modifier = Modifier.semantics { heading() })
            }
            BUILTINS.forEachIndexed { i, (title, body) ->
                if (i > 0) HorizontalDivider(color = c.divider)
                val name = stringResource(title)
                SwitchRow("builtin-$i", name, checked = true, enabled = false,
                          description = stringResource(R.string.blocked_builtin_cd, name), icon = null,
                          subtitle = stringResource(body), onChange = {})
            }
        }
        OmCard(contentPadding = 0.dp, modifier = Modifier.testTag(TAG_BLOCKED_YOURS)) {
            Text(stringResource(R.string.blocked_by_you, rows.size).uppercase(), style = MaterialTheme.typography.labelMedium,
                 color = c.inkSecondary, modifier = Modifier.padding(start = 16.dp, top = 14.dp, end = 16.dp, bottom = 4.dp)
                    .semantics { heading() })
            if (rows.isEmpty()) {
                Text(stringResource(R.string.blocked_none_added), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary,
                     modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
            }
            rows.forEachIndexed { i, row ->
                if (i > 0) HorizontalDivider(color = c.divider)
                SwitchRow(row.pkg, row.label, checked = true, enabled = true,
                          description = stringResource(R.string.blocked_on_cd, row.label), icon = icon) { on ->
                    if (!on) asking = row
                }
            }
            HorizontalDivider(color = c.divider)
            ListRow(stringResource(R.string.blocked_more), onClick = onAdd, modifier = Modifier.testTag(TAG_BLOCKED_ADD))
        }
        Text(stringResource(R.string.blocked_switch_footer), style = MaterialTheme.typography.bodySmall, color = c.inkTertiary)
    }
    asking?.let { row -> UnblockSheet(row, onConfirm = { asking = null; onUnblock(row) }, onDismiss = { asking = null }) }
}

/** The Blocked apps page, wired to the phone's list. */
@Composable
fun BlockedAppsRoute(back: () -> Unit, openAdd: () -> Unit) {
    val context = LocalContext.current
    val vm: BlockedAppsViewModel = viewModel(key = "blocked-page", factory = BlockedAppsViewModel.factory(context, loadApps = false))
    val state by vm.state.collectAsStateWithLifecycle()
    androidx.lifecycle.compose.LifecycleEventEffect(androidx.lifecycle.Lifecycle.Event.ON_RESUME) { vm.refresh() }
    BlockedAppsPage(state.rows, onBack = back, onAdd = openAdd, onUnblock = { vm.unblock(context.activity(), it) },
                    icon = vm.source::icon)
}

data class AddAppsActions(
    val back: () -> Unit = {},
    val search: (String) -> Unit = {},
    val filter: (Boolean) -> Unit = {},
    val block: (String) -> Unit = {},
    val unblock: (BlockedRow) -> Unit = {},
)

/** The Block-apps list, like Settings › Notifications › App notifications: search, an "All apps" filter, a count, and
 *  every launchable app with a switch. On blocks at once; off asks to unblock (sheet, then the screen lock). */
@Composable
fun AddBlockedAppsScreen(state: BlockedUiState, actions: AddAppsActions, icon: (String) -> Drawable? = { null }) {
    val c = OpenMobTheme.colors
    var asking by remember { mutableStateOf<BlockedRow?>(null) }
    var menu by remember { mutableStateOf(false) }
    ScreenScaffold(title = stringResource(Route.BlockedAdd.title), onBack = actions.back) {
        OutlinedTextField(
            value = state.query, onValueChange = actions.search, singleLine = true,
            label = { Text(stringResource(R.string.blocked_search)) }, modifier = Modifier.fillMaxWidth(),
        )
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) {
                SecondaryButton(stringResource(if (state.onlyBlocked) R.string.blocked_filter_yours else R.string.blocked_filter_all),
                                onClick = { menu = true }, icon = Icons.Filled.ArrowDropDown, fillWidth = false,
                                modifier = Modifier.testTag(TAG_BLOCKED_FILTER))
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    DropdownMenuItem(text = { Text(stringResource(R.string.blocked_filter_all)) },
                                     onClick = { menu = false; actions.filter(false) })
                    DropdownMenuItem(text = { Text(stringResource(R.string.blocked_filter_yours)) },
                                     onClick = { menu = false; actions.filter(true) })
                }
            }
            val n = state.apps.count { it.blocked && !it.builtIn }
            Text(pluralStringResource(R.plurals.blocked_count, n, n), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        }
        val q = state.query.trim()
        val shown = state.apps.filter {
            (!state.onlyBlocked || (it.blocked && !it.builtIn)) &&
                (q.isEmpty() || it.label.contains(q, ignoreCase = true) || it.pkg.contains(q, ignoreCase = true))
        }
        OmCard(contentPadding = 0.dp) {
            if (shown.isEmpty()) Text(stringResource(R.string.blocked_no_apps), style = MaterialTheme.typography.bodySmall,
                                      color = c.inkSecondary, modifier = Modifier.padding(16.dp))
            shown.forEachIndexed { i, a ->
                if (i > 0) HorizontalDivider(color = c.divider)
                val on = a.builtIn || a.blocked
                SwitchRow(a.pkg, a.label, checked = on, enabled = !a.builtIn,
                          description = stringResource(when {
                              a.builtIn -> R.string.blocked_builtin_cd
                              on -> R.string.blocked_on_cd
                              else -> R.string.blocked_off_cd
                          }, a.label),
                          icon = icon, subtitle = if (a.builtIn) stringResource(R.string.blocked_builtin_subtitle) else null) { want ->
                    if (want) actions.block(a.pkg) else asking = BlockedRow(a.pkg, a.label)
                }
            }
        }
        Text(stringResource(R.string.blocked_picker_footer), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
    }
    asking?.let { row -> UnblockSheet(row, onConfirm = { asking = null; actions.unblock(row) }, onDismiss = { asking = null }) }
}

@Composable
fun AddBlockedAppsRoute(back: () -> Unit) {
    val context = LocalContext.current
    val vm: BlockedAppsViewModel = viewModel(key = "blocked-add", factory = BlockedAppsViewModel.factory(context, loadApps = true))
    val state by vm.state.collectAsStateWithLifecycle()
    AddBlockedAppsScreen(state, AddAppsActions(
        back = back, search = vm::search, filter = vm::showOnlyBlocked,
        block = { vm.block(it) }, unblock = { vm.unblock(context.activity(), it) },
    ), icon = vm.source::icon)
}
