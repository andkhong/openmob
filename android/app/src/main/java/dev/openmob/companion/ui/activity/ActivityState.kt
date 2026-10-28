package dev.openmob.companion.ui.activity

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import dev.openmob.companion.AppState
import dev.openmob.companion.TaskHistory
import dev.openmob.companion.TaskLog
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

enum class ActivityFilter { All, Asked, StoppedOrDenied }

/** What a row says happened. Each has its own icon and word (never colour alone). */
enum class RowKind {
    Running, Done, Stopped, StoppedByYou, Denied, Failed, Interrupted,
    /** A Faster mode request from Settings, answered on this phone (not a task; title holds its scope). */
    FasterApproved, FasterDenied,
}

data class ActivityRow(
    val id: String,
    /** The request as the server sent it; "" for a drive session (no request text). */
    val title: String,
    val kind: RowKind,
    val startedAt: Long,
    /** Running: time so far; else how long it took (0 if unknown). */
    val durationMs: Long,
    val steps: Int,
    val asks: Int,
    val reason: String,
)

data class DayGroup(val day: LocalDate, val rows: List<ActivityRow>)

data class ActivityUiState(
    val filter: ActivityFilter = ActivityFilter.All,
    val groups: List<DayGroup> = emptyList(),
    /** Tasks kept on the phone at all (before the filter): 0 shows the empty state. */
    val total: Int = 0,
    val today: LocalDate = LocalDate.now(),
)

/** The pure mapping from the phone's task history to the Activity screen (grouped by day, newest first). */
object ActivityMapper {
    fun row(r: TaskLog.Record, running: AppState.TaskState?, now: Long): ActivityRow {
        val live = r.running && running?.id == r.id
        val kind = when {
            r.kind == TaskLog.KIND_FASTER -> if (r.outcome == "approved") RowKind.FasterApproved else RowKind.FasterDenied
            live -> RowKind.Running
            r.running -> RowKind.Interrupted // the connection ended before the server said it ended
            r.denied && r.outcome != "done" -> RowKind.Denied
            r.outcome == "done" -> RowKind.Done
            r.outcome == "stopped" -> if (r.stoppedByOwner) RowKind.StoppedByYou else RowKind.Stopped
            else -> RowKind.Failed
        }
        return ActivityRow(
            id = r.id,
            title = r.request,
            kind = kind,
            startedAt = r.startedAt,
            durationMs = if (live) (now - r.startedAt).coerceAtLeast(0) else r.durationMs.coerceAtLeast(0),
            steps = if (live) maxOf(r.steps, running?.steps ?: 0) else r.steps,
            asks = r.asks,
            reason = r.reason,
        )
    }

    fun map(records: List<TaskLog.Record>, running: AppState.TaskState?, filter: ActivityFilter, now: Long,
            zone: ZoneId = ZoneId.systemDefault()): ActivityUiState {
        val rows = records.sortedByDescending { it.startedAt }.map { row(it, running, now) }.filter {
            when (filter) {
                ActivityFilter.All -> true
                // A Faster mode answer was an ask on this phone; a denied one is also "denied".
                ActivityFilter.Asked -> it.asks > 0 || it.kind in setOf(RowKind.FasterApproved, RowKind.FasterDenied)
                ActivityFilter.StoppedOrDenied -> it.kind in setOf(RowKind.Stopped, RowKind.StoppedByYou, RowKind.Denied, RowKind.FasterDenied)
            }
        }
        val groups = rows.groupBy { Instant.ofEpochMilli(it.startedAt).atZone(zone).toLocalDate() }
            .map { (day, list) -> DayGroup(day, list) }
        return ActivityUiState(filter, groups, records.size, Instant.ofEpochMilli(now).atZone(zone).toLocalDate())
    }
}

/** The Activity screen's state: the phone's task history, refreshed on every AppState change and each second while a
 *  task runs (its time). Read only. */
class ActivityViewModel(
    private val records: () -> List<TaskLog.Record>,
    private val running: () -> AppState.TaskState?,
    private val listen: (() -> Unit) -> () -> Unit,
    private val clock: () -> Long = System::currentTimeMillis,
    private val zone: ZoneId = ZoneId.systemDefault(),
) : ViewModel() {
    private var filter = ActivityFilter.All
    private val _state = MutableStateFlow(read())
    val state: StateFlow<ActivityUiState> = _state.asStateFlow()
    private val unsubscribe = listen { refresh() }
    private var ticker: Job? = null

    init { tick() }

    private fun read() = ActivityMapper.map(records(), running(), filter, clock(), zone)

    fun refresh() { _state.value = read(); tick() }

    fun setFilter(f: ActivityFilter) { filter = f; refresh() }

    private fun tick() {
        val live = _state.value.groups.any { g -> g.rows.any { it.kind == RowKind.Running } }
        if (!live) { ticker?.cancel(); ticker = null; return }
        if (ticker?.isActive == true) return
        ticker = viewModelScope.launch {
            while (isActive) {
                delay(1_000)
                _state.value = read()
            }
        }
    }

    override fun onCleared() { unsubscribe() }

    companion object {
        fun factory(context: Context): ViewModelProvider.Factory {
            val app = context.applicationContext
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    val log = TaskHistory.init(app)
                    return ActivityViewModel({ log.records() }, { AppState.task }, { cb -> AppState.listen(cb) }) as T
                }
            }
        }
    }
}
