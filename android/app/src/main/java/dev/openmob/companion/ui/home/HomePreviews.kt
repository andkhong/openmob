package dev.openmob.companion.ui.home

import android.content.res.Configuration
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.tooling.preview.PreviewParameter
import androidx.compose.ui.tooling.preview.PreviewParameterProvider
import dev.openmob.companion.AppState
import dev.openmob.companion.Chats
import dev.openmob.companion.ui.state.PendingApproval
import dev.openmob.companion.ui.theme.OpenMobTheme

/** Example states of every Home, for the previews and the screenshot tests. Made-up values only. */
object HomeSamples {
    /** What a server with Anthropic and OpenAI keys sends (§3.5). */
    val models = AppState.ModelState(
        listOf(
            AppState.PhoneModel("claude-haiku-5-5", "Haiku 5.5", "Fastest. Recommended for phone tasks", "fast", "main", true),
            AppState.PhoneModel("claude-sonnet-5-5", "Sonnet 5.5", "Slower per step. Better on tricky screens", "medium", "main", true),
            AppState.PhoneModel("claude-opus-5-5", "Opus 5.5", "Slowest. For long, multi-app tasks", "slow", "main", true),
            AppState.PhoneModel("gpt-6-luna", "GPT-6 Luna", "", "medium", "more", false),
        ),
        model = "claude-haiku-5-5", effort = "auto",
    )
    private val base = HomeUiState(
        serverHost = "home-server.local",
        email = "owner@example.com",
        paired = true,
        accessibilityOn = true,
        checksDone = 4,
        canAsk = true,
        mode = "auto",
        models = models,
    )
    private val task = TaskProgress(
        request = "Play some relaxed jazz",
        headline = "Searching Spotify for jazz…",
        step = 3,
        stepText = "Typing “jazz”",
        controller = "",
        elapsedSeconds = 14,
        asks = 0,
    )

    /** Made-up times on one fixed day (screenshots stay the same). */
    const val NOW: Long = 1_792_310_400_000L // 2026-10-17 10:00 UTC
    private const val MIN = 60_000L
    val chatList = listOf(
        Chats.Summary("c1", "Coffee, shopping, Chrome", NOW - 8 * MIN, "phone", true),
        Chats.Summary("c2", "Morning settings", NOW - 45 * MIN, "dashboard", true),
        Chats.Summary("c3", "Install a chess app and play 5 moves", NOW - 26 * 60 * MIN, "phone", true),
        Chats.Summary("c4", "Book a table for two on Friday", NOW - 3 * 24 * 60 * MIN, "other_phone", false),
        Chats.Summary("c5", "Find a pharmacy open late", NOW - 12 * 24 * 60 * MIN, "phone", true),
    )
    val chat = Chats.Thread("c1", "Coffee, shopping, Chrome", NOW - 8 * MIN, true, listOf(
        Chats.Turn("t1", "Find three coffee shops open now", NOW - 90 * MIN, NOW - 89 * MIN, "done",
                   "Three coffee shops are open now: Blue Door Coffee until 6 pm, Ritual until 7 pm and Corner Bean until 9 pm.",
                   9, listOf("launch_app: Google Maps", "tap: Search here", "type_text: Typing “coffee open now”", "tap: Open now"), 0, false, false, ""),
        Chats.Turn("t2", "Find wireless headphones under $300 and buy them", NOW - 19 * MIN, NOW - 17 * MIN, "stopped", "Stopped.",
                   7, listOf("launch_app: Example Shop", "type_text: Typing “wireless headphones”", "tap: Checkout"), 1, false, true, ""),
        Chats.Turn("t3", "Are Chrome’s notifications allowed?", NOW - 8 * MIN, NOW - 8 * MIN + 12_000, "done",
                   "Chrome’s notifications are allowed: the “Allow notifications” switch is on.",
                   6, listOf("open_settings: Apps › Chrome › Notifications"), 0, false, false, ""),
    ), first = 0, more = false)
    private val chatBase = base.copy(chatsSupported = true, currentChat = "c1", chatList = chatList, chatTitle = chat.title,
                                     notificationsOn = true, backgroundOk = true)
    private fun threadOf(task: TaskProgress? = null, ask: HomeAsk? = null) =
        ThreadMapper.map(chat, true, emptyList(), task, "t4".takeIf { task != null }, ask, java.time.ZoneOffset.UTC, NOW)

    val notSetUp = HomeUiState(status = HomeStatus.NotSetUp, checksDone = 1, paired = true)
    val disconnected = chatBase.copy(status = HomeStatus.Disconnected, canAsk = false, canConnect = true, connectionText = "Disconnected",
        latest = LatestTask("Find three coffee shops open now", "", true, 12, asks = 0))
    val connecting = chatBase.copy(status = HomeStatus.Connecting, canAsk = false, connectionText = "Connecting to home-server.local…")
    val connected = chatBase.copy(status = HomeStatus.Connected, connectionText = "Connected to home-server.local",
        latest = LatestTask("Find three coffee shops open now", "", true, 12, asks = 0), thread = threadOf())
    /** A new chat, with one issue (notifications off): "Your phone is ready". */
    val empty = chatBase.copy(status = HomeStatus.Connected, currentChat = null, chatTitle = "", notificationsOn = false)
    val working = chatBase.copy(status = HomeStatus.Working, task = task, thread = threadOf(task),
        backToAppPackage = "com.example.music", backToAppLabel = "Spotify")
    val asking = working.copy(status = HomeStatus.Asking, ask = HomeAsk.Approval(
        PendingApproval("gk1", "Send the message “On my way” to Sam in Messages?", "This phone"), more = 0))
    private val questionTask = task.copy(step = 5, stepText = "Opened the playlist")
    private val questionAsk = HomeAsk.Question("Should I play the first playlist, “Jazz Classics”?")
    val question = chatBase.copy(status = HomeStatus.Asking, task = questionTask, ask = questionAsk,
        thread = threadOf(questionTask, questionAsk))

    val all: List<Pair<String, HomeUiState>> = listOf(
        "not-set-up" to notSetUp, "disconnected" to disconnected, "connecting" to connecting, "connected" to connected,
        "working" to working, "asking" to asking, "asking-question" to question, "empty" to empty,
    )

    // App updates (§3.7; the owner's mockups): a newer build on the server, a required one, and a 4400.
    val updateAvailable = connected.copy(serverHost = "openmob.fly.dev", currentVersion = 47, updateDownloadable = true,
        update = dev.openmob.companion.UpdateState.Available(52))
    val updateRequired = connected.copy(serverHost = "openmob.fly.dev", currentVersion = 47, updateDownloadable = true,
        canAsk = false, update = dev.openmob.companion.UpdateState.Required(50, 52))
    val tooOld = disconnected.copy(connectionText = "This app is too old for the server. Update it.", updateDownloadable = true,
        update = dev.openmob.companion.UpdateState.TooOld)

    val updates: List<Pair<String, HomeUiState>> = listOf(
        "update-available" to updateAvailable, "update-required" to updateRequired, "too-old" to tooOld,
    )
}

class HomeStateProvider : PreviewParameterProvider<HomeUiState> {
    override val values = (HomeSamples.all + HomeSamples.updates).map { it.second }.asSequence()
}

@Preview(name = "Home, light", widthDp = 390, heightDp = 844)
@Preview(name = "Home, dark", widthDp = 390, heightDp = 844, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun HomePreview(@PreviewParameter(HomeStateProvider::class) state: HomeUiState) {
    OpenMobTheme { HomeScreen(state, HomeActions()) }
}
