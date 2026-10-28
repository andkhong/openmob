package dev.openmob.companion.ui

import androidx.compose.ui.graphics.Color
import dev.openmob.companion.ui.theme.DarkOpenMobColors
import dev.openmob.companion.ui.theme.LightOpenMobColors
import dev.openmob.companion.ui.theme.OpenMobColors
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.pow

/** WCAG 2.x contrast of every text/background pair the components use, in both themes (plain JVM). */
class ColorContrastTest {
    private fun channel(v: Float): Double = if (v <= 0.04045f) v / 12.92 else ((v + 0.055) / 1.055).pow(2.4)
    private fun luminance(c: Color) = 0.2126 * channel(c.red) + 0.7152 * channel(c.green) + 0.0722 * channel(c.blue)
    private fun contrast(a: Color, b: Color): Double {
        val (hi, lo) = listOf(luminance(a), luminance(b)).sortedDescending()
        return (hi + 0.05) / (lo + 0.05)
    }

    private fun textPairs(c: OpenMobColors) = mapOf(
        "ink/ground" to (c.ink to c.ground),
        "ink/surface" to (c.ink to c.surface),
        "inkSecondary/ground" to (c.inkSecondary to c.ground),
        "inkSecondary/surface" to (c.inkSecondary to c.surface),
        "inkTertiary/ground" to (c.inkTertiary to c.ground),
        "inkTertiary/surface" to (c.inkTertiary to c.surface),
        "ink/neutralContainer" to (c.ink to c.neutralContainer),
        "inkSecondary/neutralContainer" to (c.inkSecondary to c.neutralContainer),
        "signal/surface" to (c.signal to c.surface),
        "signal/ground" to (c.signal to c.ground),
        "signal/signalContainer" to (c.signal to c.signalContainer),
        "onSignal/signal" to (c.onSignal to c.signal),
        "onAsking/asking" to (c.onAsking to c.asking),
        "onAskingContainer/askingContainer" to (c.onAskingContainer to c.askingContainer),
        "onDanger/danger" to (c.onDanger to c.danger),
        "onDangerContainer/dangerContainer" to (c.onDangerContainer to c.dangerContainer),
        "onInverse/inverse" to (c.onInverse to c.inverse),
    )

    private fun check(name: String, c: OpenMobColors) {
        val failures = textPairs(c).mapNotNull { (pair, colors) ->
            val ratio = contrast(colors.first, colors.second)
            if (ratio < 4.5) "$pair %.2f".format(ratio) else null
        }
        assertTrue("$name pairs below 4.5:1: $failures", failures.isEmpty())
    }

    @Test fun lightTextPairsMeetAa() = check("light", LightOpenMobColors)

    @Test fun darkTextPairsMeetAa() = check("dark", DarkOpenMobColors)

    @Test fun amberIsTheSameInBothThemes() = assertEquals(LightOpenMobColors.asking, DarkOpenMobColors.asking)

    @Test fun blueAndAmberDifferInLightnessNotOnlyHue() {
        // Light: dark blue against bright amber. Dark (step 6): the blue is at least 2:1 darker than the amber, so
        // "the agent" and "the phone is asking you" never look alike, even without colour vision.
        assertTrue(contrast(LightOpenMobColors.signal, LightOpenMobColors.asking) >= 3.0)
        assertTrue(contrast(DarkOpenMobColors.signal, DarkOpenMobColors.asking) >= 2.0)
    }
}
