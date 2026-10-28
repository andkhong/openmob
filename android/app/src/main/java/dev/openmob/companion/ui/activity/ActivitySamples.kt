package dev.openmob.companion.ui.activity

import dev.openmob.companion.AppState
import dev.openmob.companion.TaskLog
import java.time.ZoneId
import java.time.ZonedDateTime

/** Example history (made-up values) for the previews and screenshot tests: a fixed clock and zone. */
object ActivitySamples {
    val ZONE: ZoneId = ZoneId.of("UTC")
    val NOW: Long = ZonedDateTime.of(2026, 10, 17, 10, 52, 14, 0, ZONE).toInstant().toEpochMilli()
    private fun at(day: Int, h: Int, m: Int) = ZonedDateTime.of(2026, 10, day, h, m, 0, 0, ZONE).toInstant().toEpochMilli()

    val records = listOf(
        TaskLog.Record("t7", "Play some relaxed jazz", NOW - 14_000, steps = 3),
        TaskLog.Record("t6", "Buy wireless headphones under \$300", at(17, 10, 41), at(17, 10, 41) + 100_000, "stopped",
                       steps = 9, asks = 1, stoppedByOwner = true),
        TaskLog.Record("t5", "Reply “running late” to Sam", at(17, 9, 15), at(17, 9, 15) + 22_000, "stopped", steps = 3,
                       asks = 1, denied = true),
        TaskLog.Record("t4", "Find three coffee shops open now", at(17, 8, 30), at(17, 8, 30) + 48_000, "done", steps = 6),
        TaskLog.Record("t3", "Install a chess app and play 5 moves", at(16, 19, 4), at(16, 19, 4) + 130_000, "done", steps = 21),
        TaskLog.Record("t2", "Turn on Wi-Fi calling", at(16, 17, 20), at(16, 17, 20) + 65_000, "failed", steps = 7,
                       reason = "couldn't find the setting (7 steps)"),
        TaskLog.Record("t1", "", at(15, 12, 0), 0, "", steps = 2),
    )
    val running = AppState.TaskState("t7", "Play some relaxed jazz", "type_text: Typing “jazz”", 3, NOW - 14_000)

    fun full(filter: ActivityFilter = ActivityFilter.All) = ActivityMapper.map(records, running, filter, NOW, ZONE)
    fun empty() = ActivityMapper.map(emptyList(), null, ActivityFilter.All, NOW, ZONE)
}
