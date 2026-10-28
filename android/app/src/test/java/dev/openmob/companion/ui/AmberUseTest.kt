package dev.openmob.companion.ui

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/**
 * Amber means only "the phone is asking you to approve" (UX review 2, H1/H2). This lists every use of the amber in the
 * app's code; a new one fails here until it is added to [ALLOWED] on purpose, with its reason.
 */
class AmberUseTest {
    private val pattern = Regex("""\.asking\b|askingContainer|onAsking\b|onAskingContainer|ApprovalAmber|FFB300|StatusKind\.Asking|AskingBand\(""")

    /** File (under src/main/java/dev/openmob/companion) → amber references, and why each is the phone asking. */
    private val ALLOWED = mapOf(
        "ui/theme/Color.kt" to 13,                     // the colour roles themselves (light and dark)
        "ui/theme/Theme.kt" to 3,                      // mapped onto Material's tertiary roles
        "ui/components/Surfaces.kt" to 5,              // AskingBand: the "phone is asking you" band
        "ui/components/Status.kt" to 3,                // the "Asking you" status chip
        "ui/components/Gallery.kt" to 2,               // the component gallery (previews only)
        "ui/approval/ApprovalScreen.kt" to 5,          // the approval screen: band, label chip
        "ui/home/HomeScreen.kt" to 1,                  // Home: a pending approval's band (not the agent's questions)
        "ui/settings/IndicatorSettingsScreen.kt" to 2, // the legend's "Thick amber: waiting for your answer" sample
        "IndicatorModel.kt" to 1,                      // the overlay's approval state colour
        "Approvals.kt" to 1,                           // the approval notification's accent
    )

    @Test fun amberIsUsedOnlyWhereThePhoneAsks() {
        val root = File("src/main/java/dev/openmob/companion")
        val found = root.walkTopDown().filter { it.isFile && it.extension == "kt" }.associate { f ->
            f.relativeTo(root).path to pattern.findAll(f.readText()).count()
        }.filterValues { it > 0 }
        assertEquals("amber uses (file → count); update ALLOWED only for a 'the phone is asking' use", ALLOWED, found)
    }
}
