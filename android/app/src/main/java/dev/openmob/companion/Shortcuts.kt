package dev.openmob.companion

import android.content.Context
import android.content.Intent

/** Actions behind the home-screen shortcuts and the Quick Settings tile; MainActivity handles them. */
object Shortcuts {
    const val OPEN_ACCESSIBILITY = "dev.openmob.action.OPEN_ACCESSIBILITY"
    const val CONNECT = "dev.openmob.action.CONNECT"
    const val ASK = "dev.openmob.action.ASK"
    /** From the "share your screen for the live view?" notification (not a launcher shortcut). */
    const val SHARE_SCREEN = "dev.openmob.action.SHARE_SCREEN"
    val all = setOf(OPEN_ACCESSIBILITY, CONNECT, ASK, SHARE_SCREEN)

    /** The non-exported alias of MainActivity (AndroidManifest, res/xml/shortcuts.xml). MainActivity runs these
     *  actions only when they come through it: another app can start MainActivity with CONNECT, but not this
     *  (security review 4, L6: any app could reconnect OpenMob after the owner pressed Disconnect). */
    const val ENTRY = "dev.openmob.companion.ShortcutEntry"

    /** One of OpenMob's own shortcut intents, through [ENTRY]. */
    fun intent(context: Context, action: String): Intent = Intent().setClassName(context, ENTRY).setAction(action)
}
