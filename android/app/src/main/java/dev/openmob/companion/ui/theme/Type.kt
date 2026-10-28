package dev.openmob.companion.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.runtime.Immutable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import dev.openmob.companion.R

/**
 * IBM Plex Sans for the UI and IBM Plex Mono for exact values (servers, codes, amounts, the action being
 * approved). Both are bundled (SIL OFL 1.1, `assets/licenses/ibm-plex-ofl.txt`); no download at run time.
 * Only 400, 500 and 600 ship: bold text uses the semibold face.
 */
val PlexSans = FontFamily(
    Font(R.font.ibm_plex_sans_regular, FontWeight.Normal),
    Font(R.font.ibm_plex_sans_medium, FontWeight.Medium),
    Font(R.font.ibm_plex_sans_semibold, FontWeight.SemiBold),
    Font(R.font.ibm_plex_sans_semibold, FontWeight.Bold),
)

val PlexMono = FontFamily(
    Font(R.font.ibm_plex_mono_regular, FontWeight.Normal),
    Font(R.font.ibm_plex_mono_medium, FontWeight.Medium),
    Font(R.font.ibm_plex_mono_semibold, FontWeight.SemiBold),
    Font(R.font.ibm_plex_mono_semibold, FontWeight.Bold),
)

private fun sans(size: Int, line: Int, weight: FontWeight, tracking: Double = 0.0) = TextStyle(
    fontFamily = PlexSans,
    fontWeight = weight,
    fontSize = size.sp,
    lineHeight = line.sp,
    letterSpacing = tracking.em,
)

/** Sizes from the mockups (390 px wide artboards = dp). Sizes are in sp, so they follow the system font scale. */
val OpenMobTypography = Typography(
    displaySmall = sans(32, 38, FontWeight.SemiBold, -0.015),   // Setup welcome headline
    headlineMedium = sans(26, 32, FontWeight.SemiBold, -0.012), // Home status, setup step titles
    headlineSmall = sans(24, 30, FontWeight.SemiBold, -0.008),  // Live task, approval question
    titleLarge = sans(22, 28, FontWeight.SemiBold),             // Screen titles (Settings, Activity)
    titleMedium = sans(17, 24, FontWeight.SemiBold),            // Card titles (Faster mode)
    titleSmall = sans(15, 21, FontWeight.Medium),               // List row titles
    bodyLarge = sans(16, 24, FontWeight.Normal),
    bodyMedium = sans(15, 22, FontWeight.Normal),
    bodySmall = sans(13, 18, FontWeight.Normal),
    labelLarge = sans(16, 22, FontWeight.SemiBold),             // Buttons
    labelMedium = sans(13, 18, FontWeight.SemiBold, 0.03),      // Status chips, section headers
    labelSmall = sans(12, 16, FontWeight.Medium),
)

/** The mono styles for exact values. */
@Immutable
data class MonoTypography(
    val small: TextStyle = TextStyle(fontFamily = PlexMono, fontWeight = FontWeight.Normal, fontSize = 12.sp, lineHeight = 16.sp),
    val medium: TextStyle = TextStyle(fontFamily = PlexMono, fontWeight = FontWeight.Normal, fontSize = 13.sp, lineHeight = 18.sp),
    val large: TextStyle = TextStyle(fontFamily = PlexMono, fontWeight = FontWeight.Medium, fontSize = 20.sp, lineHeight = 28.sp),
    /** Amounts on the approval prompt, the typed pairing code. */
    val display: TextStyle = TextStyle(fontFamily = PlexMono, fontWeight = FontWeight.SemiBold, fontSize = 34.sp, lineHeight = 44.sp),
)
