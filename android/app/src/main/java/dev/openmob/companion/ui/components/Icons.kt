package dev.openmob.companion.ui.components

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp

/** The Stop control's square, the same in the app and over other apps (mockups: "ink pill with a square"). */
val StopSquare: ImageVector = ImageVector.Builder(
    name = "StopSquare",
    defaultWidth = 24.dp,
    defaultHeight = 24.dp,
    viewportWidth = 24f,
    viewportHeight = 24f,
).apply {
    path(fill = SolidColor(Color.Black)) {
        moveTo(7f, 5f)
        lineTo(17f, 5f)
        quadTo(19f, 5f, 19f, 7f)
        lineTo(19f, 17f)
        quadTo(19f, 19f, 17f, 19f)
        lineTo(7f, 19f)
        quadTo(5f, 19f, 5f, 17f)
        lineTo(5f, 7f)
        quadTo(5f, 5f, 7f, 5f)
        close()
    }
}.build()

/** A line icon from SVG path data (the mockups' 1.6-2 px strokes); [androidx.compose.material3.Icon]'s tint colours it. */
private fun lineIcon(name: String, viewport: Float, stroke: Float, vararg paths: String): ImageVector =
    ImageVector.Builder(name = name, defaultWidth = 24.dp, defaultHeight = 24.dp, viewportWidth = viewport, viewportHeight = viewport)
        .apply {
            paths.forEach { d ->
                addPath(
                    pathData = addPathNodes(d),
                    stroke = SolidColor(Color.Black),
                    strokeLineWidth = stroke,
                    strokeLineCap = StrokeCap.Round,
                    strokeLineJoin = StrokeJoin.Round,
                )
            }
        }.build()

/* Step 2: the mockups' line icons (Material's core set has no mic, power, shield or bolt). */

/** Home's header: Activity (a clock) and Settings (sliders). */
/** App updates (the mockups' arrow into a tray): Download update. */
val DownloadIcon: ImageVector = lineIcon("Download", 24f, 1.8f, "M12 4v11", "M7.5 10.5L12 15l4.5-4.5", "M5 19h14")

val ActivityIcon: ImageVector = lineIcon("Activity", 24f, 1.8f, "M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18z", "M12 7v5l3 2")
val SettingsIcon: ImageVector = lineIcon(
    "Settings", 24f, 1.8f,
    "M4 7h10M18 7h2M4 17h4M12 17h8", "M16 5a2 2 0 1 1 0 4a2 2 0 1 1 0-4z", "M10 15a2 2 0 1 1 0 4a2 2 0 1 1 0-4z",
)
val MicIcon: ImageVector = lineIcon("Mic", 24f, 1.8f, "M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z", "M5 11a7 7 0 0 0 14 0M12 18v3")
val SendIcon: ImageVector = lineIcon("Send", 24f, 2f, "M5 12h14M13 6l6 6-6 6")
val PowerIcon: ImageVector = lineIcon("Power", 24f, 1.8f, "M12 3v8", "M6.3 6.3a8 8 0 1 0 11.4 0")
val ShieldIcon: ImageVector = lineIcon("Shield", 16f, 1.6f, "M8 1.5l5.5 2v4c0 3.4-2.4 5.9-5.5 7-3.1-1.1-5.5-3.6-5.5-7v-4z")
val BoltIcon: ImageVector = lineIcon("Bolt", 16f, 1.6f, "M9 1.5L3.5 9H8l-1 5.5L12.5 7H8z")
val PhoneIcon: ImageVector = lineIcon("Phone", 24f, 1.8f, "M9 2h6a3 3 0 0 1 3 3v14a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3V5a3 3 0 0 1 3-3z", "M10 18h4")
val CheckIcon: ImageVector = lineIcon("Check", 16f, 2f, "M3 8.5l3 3 7-7")
val BlockIcon: ImageVector = lineIcon("Block", 24f, 1.8f, "M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18z", "M5.6 5.6l12.8 12.8")
