package dev.openmob.companion.ui.nav

import android.content.res.Configuration
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import dev.openmob.companion.ui.theme.OpenMobTheme

@Preview(name = "Home, light", widthDp = 390, heightDp = 844)
@Preview(name = "Home, dark", widthDp = 390, heightDp = 844, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun HomePreview() {
    OpenMobTheme { PlaceholderFor(Route.Home, {}, {}, {}) }
}

@Preview(name = "Setup pair, light", widthDp = 390, heightDp = 844)
@Preview(name = "Setup pair, dark", widthDp = 390, heightDp = 844, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun SetupPairPreview() {
    OpenMobTheme { PlaceholderFor(Route.SetupPair, {}, {}, {}) }
}
