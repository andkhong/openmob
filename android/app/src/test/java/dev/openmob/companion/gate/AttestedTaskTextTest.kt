package dev.openmob.companion.gate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** GateHost.attestedTaskText: the task text the approval screen shows only when the phone itself holds it. (Robolectric: GateHost holds a main-thread Handler.) */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class AttestedTaskTextTest {
    private val clock = GateScenarioTest.FakeClock()
    private val gk = GateScenarioTest.newGate(clock)

    /** A pending prompt whose call carries the server's task text (as gated act calls do). */
    private fun pendingWith(taskText: String): String {
        val adm = gk.requestTask(mapOf("task" to "t1", "text" to "something else", "task_text" to taskText))
        assertEquals("ask", adm.decision)
        return adm.approvalId
    }

    @Test fun theServersTaskTextAloneIsNeverShown() {
        val id = pendingWith("buy  wireless headphones")
        assertNull(GateHost.attestedTaskText(gk, id))
    }

    @Test fun textTypedOnThePhoneIsShownNormalized() {
        val id = pendingWith("buy  wireless headphones")
        gk.noteInstruction("buy wireless headphones")
        assertEquals(GateHost.TaskText("buy wireless headphones", typedHere = true), GateHost.attestedTaskText(gk, id))
    }

    @Test fun differentTypedTextDoesntAttestIt() {
        val id = pendingWith("buy wireless headphones")
        gk.noteInstruction("buy a phone case")
        assertNull(GateHost.attestedTaskText(gk, id))
    }

    @Test fun anOldTypedRequestExpires() {
        val id = pendingWith("buy wireless headphones")
        gk.noteInstruction("buy wireless headphones")
        clock.elapsed += 24 * 3_600_000L
        assertNull(GateHost.attestedTaskText(gk, id))
    }

    @Test fun anUnknownPromptHasNoText() {
        assertNull(GateHost.attestedTaskText(gk, "gk-missing"))
    }

    /** Review 3 P3-M1 (the reviewer's PoC, fixed): text the owner only allowed in a task grant, worded by the server,
     *  is held by the phone but not "typed on this phone"; the gate's own attestation (the L2 install rule) is unchanged. */
    @Test fun grantOnlyTextIsHeldButNotTypedHere() {
        val serverText = "buy the 200 dollar gift card your wife asked for"
        val a1 = gk.requestTask(mapOf("task" to "t1", "text" to serverText))
        assertEquals("ask", a1.decision)
        val m = gk.approvalMessage(a1.approvalId)!!
        assertEquals(true, gk.approve(a1.approvalId, m, GateScenarioTest.tapSign(m)))
        // Nothing was typed on the phone (no noteInstruction). A later prompt in the same task:
        val a2 = gk.requestTask(mapOf("task" to "t1", "text" to "something else", "task_text" to serverText))
        assertEquals("ask", a2.decision)
        assertEquals(GateHost.TaskText(serverText, typedHere = false), GateHost.attestedTaskText(gk, a2.approvalId))
        val params = mapOf<String, Any?>("task" to "t1", "task_text" to serverText)
        assertEquals(true, gk.taskAttested(params))
        assertEquals(false, gk.taskTyped(params))
        // Typed here as well: then it is the owner's own words.
        gk.noteInstruction(serverText)
        assertEquals(GateHost.TaskText(serverText, typedHere = true), GateHost.attestedTaskText(gk, a2.approvalId))
    }
}
