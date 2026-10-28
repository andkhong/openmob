package dev.openmob.companion.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.ui.semantics.contentDescription
import dev.openmob.companion.ui.theme.PillShape
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.ui.draw.clip
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.remember
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.selected
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.NavigationDrawerItemDefaults
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
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.openmob.companion.Chats
import dev.openmob.companion.R
import dev.openmob.companion.ui.components.ActivityIcon
import dev.openmob.companion.ui.components.OmTextField
import dev.openmob.companion.ui.components.PhoneIcon
import dev.openmob.companion.ui.components.SettingsIcon
import dev.openmob.companion.ui.components.ShieldIcon
import dev.openmob.companion.ui.nav.Route
import dev.openmob.companion.ui.theme.OpenMobTheme
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

const val TAG_DRAWER = "drawer"
const val TAG_NEW_CHAT = "drawer-new-chat"
const val TAG_CHAT_SEARCH = "drawer-search"
const val TAG_SEARCH_OPEN = "drawer-search-open"
const val TAG_SEARCH_CLOSE = "drawer-search-close"
const val TAG_AVATAR = "drawer-avatar"
const val TAG_ACCOUNT_POPUP = "drawer-account-popup"
const val TAG_CHAT_MENU = "chat-menu"
const val TAG_DRAWER_LOADING = "drawer-loading"
const val TAG_DRAWER_THIS_PHONE_ONLY = "drawer-this-phone-only"
const val TAG_DRAWER_LIST = "drawer-list"
const val TAG_CHAT_MENU_RENAME = "chat-menu-rename"
const val TAG_CHAT_MENU_DELETE = "chat-menu-delete"

/** The places, in order (owner, 2026-10-17): Settings first, still one tap. */
val DRAWER_PLACES = listOf(Route.Settings, Route.Activity, Route.Indicator, Route.Connection, Route.SetupWelcome)

/** Tests set this false to draw the rename dialog's content inline (Robolectric never idles a field in a dialog). */
val LocalRenameInDialog = androidx.compose.runtime.staticCompositionLocalOf { true }

/**
 * The ☰ drawer, laid out like Claude's and ChatGPT's (owner, 2026-10-17): a small wordmark with a search icon, the
 * places, then the chats as the scrolling body, with the account avatar and "+ New chat" floating at the bottom.
 * No Disconnect (that is the status sheet's).
 */
@Composable
fun HomeDrawerSheet(state: HomeUiState, onRoute: (Route) -> Unit, onChat: (String) -> Unit, onNewChat: () -> Unit,
                    onRename: (String, String) -> Unit = { _, _ -> }, onDelete: (String) -> Unit = {},
                    onMore: () -> Unit = {}, onSearch: (String) -> Unit = {},
                    nowMs: Long = System.currentTimeMillis(), zone: ZoneId = ZoneId.systemDefault()) {
    val c = OpenMobTheme.colors
    val menu = stringResource(R.string.rd_menu)
    var query by rememberSaveable { mutableStateOf("") }
    var searching by rememberSaveable { mutableStateOf(false) }
    var renamingId by rememberSaveable { mutableStateOf<String?>(null) }
    var deletingId by rememberSaveable { mutableStateOf<String?>(null) }
    ModalDrawerSheet(drawerContainerColor = c.surface, modifier = Modifier.testTag(TAG_DRAWER).semantics { paneTitle = menu }) {
        // Top bar: the brand (only here), and search as an icon that opens the field.
        Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            if (searching) {
                IconButton(onClick = { searching = false; query = ""; onSearch("") }, modifier = Modifier.size(48.dp).testTag(TAG_SEARCH_CLOSE)) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.rd_drawer_search_close), tint = c.ink)
                }
                OmTextField(query, { query = it }, placeholder = stringResource(R.string.rd_drawer_search), pill = true,
                            modifier = Modifier.weight(1f).testTag(TAG_CHAT_SEARCH))
            } else {
                Text(stringResource(R.string.rd_home_title), style = MaterialTheme.typography.titleMedium, color = c.ink,
                     modifier = Modifier.weight(1f).padding(start = 12.dp).semantics { heading() })
                if (state.chatsSupported) {
                    IconButton(onClick = { searching = true }, modifier = Modifier.size(48.dp).testTag(TAG_SEARCH_OPEN)) {
                        Icon(Icons.Filled.Search, contentDescription = stringResource(R.string.rd_drawer_search), tint = c.ink)
                    }
                }
            }
        }
        Box(Modifier.weight(1f)) {
            // The search runs on the server over all of this account's chats, about 300 ms after typing stops.
            LaunchedEffect(query, searching) {
                if (searching) { kotlinx.coroutines.delay(300); onSearch(query) }
            }
            val listState = rememberLazyListState()
            // The last row reached: the next page (the list's, or the search's), when there is one.
            val atEnd by remember { derivedStateOf {
                val info = listState.layoutInfo
                info.totalItemsCount > 0 && (info.visibleItemsInfo.lastOrNull()?.index ?: 0) >= info.totalItemsCount - 2
            } }
            // Until the server answers this query, the loaded chats are filtered here (instant); then its results.
            val searchingServer = state.chatsSupported && query.isNotBlank() && state.chatSearchQuery == query.trim()
            LaunchedEffect(atEnd, state.chatList.size, state.chatSearchResults.size) { if (atEnd) onMore() }
            LazyColumn(Modifier.fillMaxSize().padding(horizontal = 12.dp).testTag(TAG_DRAWER_LIST), state = listState, contentPadding = PaddingValues(bottom = 96.dp)) {
                if (!searching) {
                    items(DRAWER_PLACES, key = { "p-${it.name}" }) { route -> PlaceRow(route) { onRoute(route) } }
                    item(key = "div") { HorizontalDivider(color = c.divider, modifier = Modifier.padding(vertical = 8.dp)) }
                }
                if (!state.chatsSupported) {
                    item { Text(stringResource(if (state.pill == PillState.Connected) R.string.rd_drawer_no_chats_server
                                               else R.string.rd_drawer_chats_offline),
                                style = MaterialTheme.typography.bodySmall, color = c.inkSecondary, modifier = Modifier.padding(16.dp)) }
                } else {
                    // Searching: the server's results over every chat (titles only); else the list.
                    val groups = if (searchingServer) groupChats(state.chatSearchResults, "", nowMs, zone)
                                 else groupChats(state.chatList, query, nowMs, zone)
                    if (groups.isEmpty()) {
                        if (!state.chatLoading) item { Text(stringResource(if (query.isBlank()) R.string.rd_drawer_no_chats else R.string.rd_drawer_no_match),
                                    style = MaterialTheme.typography.bodySmall, color = c.inkSecondary, modifier = Modifier.padding(16.dp)) }
                    }
                    groups.forEach { (group, chats) ->
                        item(key = "g-$group") {
                            Text(stringResource(when (group) {
                                ChatGroup.Today -> R.string.rd_activity_today
                                ChatGroup.Yesterday -> R.string.rd_activity_yesterday
                                ChatGroup.Week -> R.string.rd_drawer_week
                                ChatGroup.Older -> R.string.rd_drawer_older
                            }), style = MaterialTheme.typography.labelMedium, color = c.inkSecondary,
                                modifier = Modifier.padding(start = 16.dp, top = 12.dp, bottom = 4.dp).semantics { heading() })
                        }
                        items(chats, key = { it.id }) { chat ->
                            ChatRow(chat, chat.id == state.currentChat, group, zone,
                                    onRename = { renamingId = chat.id }, onDelete = { deletingId = chat.id }) { onChat(chat.id) }
                        }
                    }
                }
                // An untrusted phone sees only its own chats (review 3, K3-M3): say why the others are missing.
                if (state.chatsSupported && state.chatsThisPhoneOnly) {
                    item(key = "this-phone-only") {
                        Text(stringResource(R.string.rd_drawer_this_phone_only), style = MaterialTheme.typography.bodySmall,
                             color = c.inkSecondary, modifier = Modifier.padding(16.dp).testTag(TAG_DRAWER_THIS_PHONE_ONLY))
                    }
                }
                if (state.chatLoading) {
                    item(key = "loading") {
                        Text(stringResource(R.string.rd_drawer_loading), style = MaterialTheme.typography.bodySmall, color = c.inkSecondary,
                             modifier = Modifier.padding(16.dp).testTag(TAG_DRAWER_LOADING)
                                 .semantics { liveRegion = androidx.compose.ui.semantics.LiveRegionMode.Polite })
                    }
                }
                item(key = "footer") {
                    Text(stringResource(R.string.rd_drawer_footer), style = MaterialTheme.typography.labelSmall, color = c.inkTertiary,
                         textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp))
                }
            }
            // Floating over the list: the account avatar (left) and "+ New chat" (right).
            Row(Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(horizontal = 16.dp, vertical = 16.dp),
                verticalAlignment = Alignment.CenterVertically) {
                AccountAvatar(state)
                Spacer(Modifier.weight(1f))
                Button(
                    onClick = onNewChat, shape = PillShape,
                    modifier = Modifier.heightIn(min = 48.dp).testTag(TAG_NEW_CHAT),
                    colors = ButtonDefaults.buttonColors(containerColor = c.signal, contentColor = c.onSignal),
                    contentPadding = PaddingValues(horizontal = 18.dp),
                ) {
                    Icon(Icons.Filled.Add, contentDescription = null, modifier = Modifier.size(20.dp))
                    Text(stringResource(R.string.rd_drawer_new_chat), style = MaterialTheme.typography.labelLarge,
                         modifier = Modifier.padding(start = 6.dp))
                }
            }
        }
    }
    renamingId?.let { id ->
        val initial = state.chatList.firstOrNull { it.id == id }?.title.orEmpty()
        val save: (String) -> Unit = { t -> onRename(id, t); renamingId = null }
        if (LocalRenameInDialog.current) RenameChatDialog(initial, save, onCancel = { renamingId = null })
        else RenameChatContent(initial, save, onCancel = { renamingId = null })
    }
    deletingId?.let { id -> DeleteChatDialog(onDelete = { onDelete(id); deletingId = null }, onCancel = { deletingId = null }) }
}

/** A place: icon and label, 48 dp at least; the label wraps at large text rather than being cut. */
@Composable
private fun PlaceRow(route: Route, onClick: () -> Unit) {
    val c = OpenMobTheme.colors
    val (label, icon) = placeRow(route)
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).clip(RoundedCornerShape(16.dp)).clickable(role = Role.Button, onClick = onClick)
            .testTag("drawer-${route.name}").padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Icon(icon, contentDescription = null, tint = c.ink, modifier = Modifier.size(22.dp))
        Text(label, style = MaterialTheme.typography.titleSmall, color = c.ink)
    }
}

/** The avatar: its popup shows the account and server (read only). */
@Composable
private fun AccountAvatar(state: HomeUiState) {
    val c = OpenMobTheme.colors
    var open by remember { mutableStateOf(false) }
    Box {
        val label = stringResource(R.string.rd_drawer_account_desc, state.email.ifEmpty { stringResource(R.string.rd_drawer_account) })
        Box(
            Modifier.size(48.dp).background(c.signalContainer, CircleShape).border(1.dp, c.border, CircleShape).clip(CircleShape)
                .clickable(role = Role.Button) { open = true }.testTag(TAG_AVATAR).semantics { contentDescription = label },
            contentAlignment = Alignment.Center,
        ) {
            // Drawn to the circle's size (dp), so large text doesn't burst it.
            val size = with(androidx.compose.ui.platform.LocalDensity.current) { 18.dp.toSp() }
            Text(state.email.take(1).uppercase().ifEmpty { "·" }, color = c.signal,
                 style = MaterialTheme.typography.labelLarge.copy(fontSize = size, lineHeight = size))
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }, modifier = Modifier.testTag(TAG_ACCOUNT_POPUP)) {
            Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(stringResource(R.string.rd_home_account), style = MaterialTheme.typography.labelSmall, color = c.inkSecondary)
                Text(state.email.ifEmpty { "—" }, style = OpenMobTheme.mono.medium, color = c.ink)
                Text(stringResource(R.string.rd_home_server), style = MaterialTheme.typography.labelSmall, color = c.inkSecondary,
                     modifier = Modifier.padding(top = 6.dp))
                Text(state.serverHost.ifEmpty { "—" }, style = OpenMobTheme.mono.medium, color = c.ink)
            }
        }
    }
}

/** One chat. Tap opens it; long-press (or TalkBack's actions) offers Rename and Delete (owner, 2026-10-17). */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
private fun ChatRow(chat: Chats.Summary, current: Boolean, group: ChatGroup, zone: ZoneId,
                    onRename: () -> Unit, onDelete: () -> Unit, onClick: () -> Unit) {
    val c = OpenMobTheme.colors
    val time = Instant.ofEpochMilli(chat.updatedMs).atZone(zone)
    val whenText = if (group == ChatGroup.Today || group == ChatGroup.Yesterday) time.format(DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT))
                   else time.format(DateTimeFormatter.ofLocalizedDate(FormatStyle.SHORT))
    val sub = when (chat.origin) {
        "dashboard" -> stringResource(R.string.rd_drawer_from_dashboard, whenText)
        "other_phone" -> stringResource(R.string.rd_drawer_other_phone, whenText)
        "api" -> stringResource(R.string.rd_drawer_from_api, whenText)
        "mcp" -> stringResource(R.string.rd_drawer_from_mcp, whenText)
        // Not typed on a phone (review 3 S3-L3): an outside agent's drive session, the server's terminal, or not recorded.
        "drive" -> stringResource(R.string.rd_drawer_from_drive, whenText)
        "local" -> stringResource(R.string.rd_drawer_from_local, whenText)
        "unknown" -> stringResource(R.string.rd_drawer_from_unknown, whenText)
        else -> whenText
    }
    val currentLabel = stringResource(R.string.rd_drawer_current)
    val renameLabel = stringResource(R.string.rd_chat_rename)
    val deleteLabel = stringResource(R.string.rd_chat_delete)
    val title = chat.title.ifEmpty { stringResource(R.string.rd_drawer_new_chat) }
    var menu by remember { mutableStateOf(false) }
    Box {
        Column(
            Modifier.fillMaxWidth().heightIn(min = 56.dp)
                .background(if (current) c.signalContainer else androidx.compose.ui.graphics.Color.Transparent, RoundedCornerShape(16.dp))
                .clip(RoundedCornerShape(16.dp))
                .combinedClickable(role = Role.Button, onClick = onClick, onLongClick = { menu = true },
                                   onLongClickLabel = stringResource(R.string.rd_chat_more))
                .testTag("chat-${chat.id}")
                .semantics(mergeDescendants = true) {
                    selected = current
                    if (current) stateDescription = currentLabel
                    customActions = listOf(
                        CustomAccessibilityAction(renameLabel) { onRename(); true },
                        CustomAccessibilityAction(deleteLabel) { onDelete(); true },
                    )
                }
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Text(title, style = MaterialTheme.typography.titleSmall, color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(sub, style = MaterialTheme.typography.bodySmall, color = c.inkSecondary)
        }
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }, modifier = Modifier.testTag(TAG_CHAT_MENU)) {
            DropdownMenuItem(text = { Text(renameLabel) }, onClick = { menu = false; onRename() },
                             modifier = Modifier.heightIn(min = 48.dp).testTag(TAG_CHAT_MENU_RENAME))
            DropdownMenuItem(text = { Text(deleteLabel, color = c.onDangerContainer) }, onClick = { menu = false; onDelete() },
                             modifier = Modifier.heightIn(min = 48.dp).testTag(TAG_CHAT_MENU_DELETE))
        }
    }
}

@Composable
private fun placeRow(route: Route): Pair<String, ImageVector> = when (route) {
    Route.Settings -> stringResource(R.string.rd_settings_title) to SettingsIcon
    Route.Activity -> stringResource(R.string.rd_activity_title) to ActivityIcon
    Route.Indicator -> stringResource(R.string.rd_indicator_title) to ShieldIcon
    Route.Connection -> stringResource(R.string.rd_settings_connection) to PhoneIcon
    else -> stringResource(R.string.rd_drawer_help) to Icons.Filled.Info
}
