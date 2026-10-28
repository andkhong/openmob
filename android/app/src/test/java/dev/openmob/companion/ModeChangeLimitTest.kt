package dev.openmob.companion

import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Settings' "Limit reached: try again in N minutes" reads N1's window (2 prompts an hour) without changing it. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ModeChangeLimitTest {
    private val now = 10_000_000L

    @Test fun theWaitIsUntilFewerThanTwoPromptsAreInTheHour() {
        assertEquals(0, Approvals.retryInMs(emptyList(), now))
        assertEquals(0, Approvals.retryInMs(listOf(now - 1_000), now))                 // one in the window
        assertEquals(0, Approvals.retryInMs(listOf(now - 3_600_000L, now - 1_000), now)) // the older one aged out
        // Two in the hour: free again when the older one is an hour old.
        assertEquals(600_000L, Approvals.retryInMs(listOf(now - 3_000_000L, now - 1_000), now))
        // Three in the hour (unordered): the count drops below 2 when the middle one ages out.
        assertEquals(1_600_000L, Approvals.retryInMs(listOf(now - 1_000, now - 3_000_000L, now - 2_000_000L), now))
    }

    @Test fun nothingShownYetMeansNoWait() {
        assertEquals(0, Approvals.modeChangeRetryInMs())
    }
}
