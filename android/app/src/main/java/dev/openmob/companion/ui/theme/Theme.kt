package dev.openmob.companion.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf

private val LocalOpenMobColors = staticCompositionLocalOf { LightOpenMobColors }
private val LocalSpacing = staticCompositionLocalOf { Spacing() }
private val LocalSizes = staticCompositionLocalOf { Sizes() }
private val LocalRadii = staticCompositionLocalOf { Radii() }
private val LocalMono = staticCompositionLocalOf { MonoTypography() }

/** Material3's roles mapped onto ours, so stock Material components (Switch, TextField, ...) match. */
internal fun OpenMobColors.toMaterial(): ColorScheme {
    val base = if (isDark) darkColorScheme() else lightColorScheme()
    return base.copy(
        primary = signal,
        onPrimary = onSignal,
        primaryContainer = signalContainer,
        onPrimaryContainer = ink,
        secondary = inkSecondary,
        onSecondary = surface,
        tertiary = asking,
        onTertiary = onAsking,
        tertiaryContainer = askingContainer,
        onTertiaryContainer = onAskingContainer,
        background = ground,
        onBackground = ink,
        surface = surface,
        onSurface = ink,
        surfaceVariant = neutralContainer,
        onSurfaceVariant = inkSecondary,
        surfaceContainerLowest = surface,
        surfaceContainerLow = surface,
        surfaceContainer = surface,
        surfaceContainerHigh = surface,
        surfaceContainerHighest = neutralContainer,
        inverseSurface = inverse,
        inverseOnSurface = onInverse,
        error = danger,
        onError = onDanger,
        errorContainer = dangerContainer,
        onErrorContainer = onDangerContainer,
        outline = outline,
        outlineVariant = border,
        scrim = ink.copy(alpha = 0.5f),
    )
}

/**
 * The redesign's theme. Dark mode follows the system unless [darkTheme] is given (previews and tests pass it).
 * No dynamic (wallpaper) colour: blue and amber carry meaning, so they never change.
 */
@Composable
fun OpenMobTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val colors = if (darkTheme) DarkOpenMobColors else LightOpenMobColors
    CompositionLocalProvider(
        LocalOpenMobColors provides colors,
        LocalSpacing provides Spacing(),
        LocalSizes provides Sizes(),
        LocalRadii provides Radii(),
        LocalMono provides MonoTypography(),
    ) {
        MaterialTheme(
            colorScheme = colors.toMaterial(),
            typography = OpenMobTypography,
            shapes = OpenMobShapes,
            content = content,
        )
    }
}

/** `OpenMobTheme.colors.signal`, `OpenMobTheme.spacing.lg`, ... inside an [OpenMobTheme]. */
object OpenMobTheme {
    val colors: OpenMobColors
        @Composable @ReadOnlyComposable get() = LocalOpenMobColors.current
    val spacing: Spacing
        @Composable @ReadOnlyComposable get() = LocalSpacing.current
    val sizes: Sizes
        @Composable @ReadOnlyComposable get() = LocalSizes.current
    val radii: Radii
        @Composable @ReadOnlyComposable get() = LocalRadii.current
    val mono: MonoTypography
        @Composable @ReadOnlyComposable get() = LocalMono.current
}
