package dev.openmob.companion.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.runtime.Immutable
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** Spacing steps (dp), from the mockups' gaps and paddings. */
@Immutable
data class Spacing(
    val xxs: Dp = 2.dp,
    val xs: Dp = 4.dp,
    val sm: Dp = 8.dp,
    val md: Dp = 12.dp,
    val lg: Dp = 16.dp,
    val xl: Dp = 20.dp,
    val xxl: Dp = 24.dp,
    val xxxl: Dp = 32.dp,
    /** Side margin of every screen. */
    val screen: Dp = 20.dp,
)

/** Sizes the components share. Touch targets are never below [touchTarget]. */
@Immutable
data class Sizes(
    val touchTarget: Dp = 48.dp,
    val button: Dp = 52.dp,
    val buttonLarge: Dp = 56.dp,
    val listRow: Dp = 56.dp,
    val chip: Dp = 28.dp,
    val icon: Dp = 20.dp,
    val iconSmall: Dp = 16.dp,
    val avatar: Dp = 32.dp,
)

/** Corner radii (dp). Buttons and chips are full pills. */
@Immutable
data class Radii(
    val sm: Dp = 10.dp,
    val md: Dp = 14.dp,
    val card: Dp = 18.dp,
    val cardLarge: Dp = 20.dp,
    val sheet: Dp = 24.dp,
)

val OpenMobShapes = Shapes(
    extraSmall = RoundedCornerShape(10.dp),
    small = RoundedCornerShape(14.dp),
    medium = RoundedCornerShape(18.dp),
    large = RoundedCornerShape(20.dp),
    extraLarge = RoundedCornerShape(24.dp),
)

val PillShape = RoundedCornerShape(percent = 50)
