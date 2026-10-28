package dev.openmob.companion.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color

/**
 * The "Control Room" colour roles (redesign mockups, 2026-10-17). Two colours carry meaning and nothing else
 * uses them:
 * - [signal] (blue) is the agent: connected, working, the indicator border;
 * - [asking] (amber) only ever means "the phone is asking you". It keeps the same hue in both themes.
 *
 * Every text/background pair used by the components is checked for at least 4.5:1 contrast in `ColorContrastTest`.
 * Blue and amber differ in lightness as well as hue, so they stay distinct without colour vision.
 */
@Immutable
data class OpenMobColors(
    val ground: Color,
    val surface: Color,
    val surfaceSunken: Color,
    val ink: Color,
    val inkSecondary: Color,
    val inkTertiary: Color,
    val border: Color,
    val divider: Color,
    val outline: Color,
    val signal: Color,
    val onSignal: Color,
    val signalContainer: Color,
    val asking: Color,
    val onAsking: Color,
    val askingContainer: Color,
    val onAskingContainer: Color,
    val danger: Color,
    val onDanger: Color,
    val dangerContainer: Color,
    val onDangerContainer: Color,
    val neutralContainer: Color,
    /** The Stop control and the primary "commit" button: an ink pill (light) or a pale pill (dark). */
    val inverse: Color,
    val onInverse: Color,
    val isDark: Boolean,
)

/** The approval amber: identical in light and dark so the band reads the same. */
val ApprovalAmber = Color(0xFFFFB300)

val LightOpenMobColors = OpenMobColors(
    ground = Color(0xFFF3F5F8),
    surface = Color(0xFFFFFFFF),
    surfaceSunken = Color(0xFFF3F5F8),
    ink = Color(0xFF0E1621),
    inkSecondary = Color(0xFF4A5566),
    inkTertiary = Color(0xFF5F6B7C),
    border = Color(0xFFDDE2EA),
    divider = Color(0xFFE6EAF0),
    outline = Color(0xFFC9D0DB),
    signal = Color(0xFF1F4FE0),
    onSignal = Color(0xFFFFFFFF),
    signalContainer = Color(0xFFE8EEFF),
    asking = ApprovalAmber,
    onAsking = Color(0xFF0E1621),
    askingContainer = Color(0xFFFFF5DC),
    onAskingContainer = Color(0xFF7A4300),
    danger = Color(0xFFB42318),
    onDanger = Color(0xFFFFFFFF),
    dangerContainer = Color(0xFFFEF3F2),
    onDangerContainer = Color(0xFF912018),
    neutralContainer = Color(0xFFEDEFF3),
    inverse = Color(0xFF0E1621),
    onInverse = Color(0xFFFFFFFF),
    isDark = false,
)

val DarkOpenMobColors = OpenMobColors(
    ground = Color(0xFF0B0F15),
    surface = Color(0xFF151B24),
    surfaceSunken = Color(0xFF0B0F15),
    ink = Color(0xFFE8EDF4),
    inkSecondary = Color(0xFFA9B4C4),
    inkTertiary = Color(0xFF8C98AB),
    border = Color(0xFF263041),
    divider = Color(0xFF263041),
    outline = Color(0xFF3A475A),
    // Step 6: darker than before (#7C9BFF) so blue and the approval amber differ clearly in lightness (2:1).
    signal = Color(0xFF5A7CFF),
    onSignal = Color(0xFF0B0F15),
    signalContainer = Color(0xFF121A33),
    asking = ApprovalAmber,
    onAsking = Color(0xFF0E1621),
    askingContainer = Color(0xFF2A2110),
    onAskingContainer = Color(0xFFFFC94D),
    danger = Color(0xFFFF8A80),
    onDanger = Color(0xFF0B0F15),
    dangerContainer = Color(0xFF2D1513),
    onDangerContainer = Color(0xFFFFB4AB),
    neutralContainer = Color(0xFF1E2632),
    inverse = Color(0xFFE8EDF4),
    onInverse = Color(0xFF0B0F15),
    isDark = true,
)
