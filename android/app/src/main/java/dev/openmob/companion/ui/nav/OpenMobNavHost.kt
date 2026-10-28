package dev.openmob.companion.ui.nav

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import dev.openmob.companion.ui.home.HomeRoute
import dev.openmob.companion.ui.settings.AddBlockedAppsRoute
import dev.openmob.companion.ui.settings.BlockedAppsRoute
import dev.openmob.companion.ui.settings.IndicatorRoute
import dev.openmob.companion.ui.settings.MemoryRoute
import dev.openmob.companion.ui.settings.SettingsRoute
import dev.openmob.companion.ui.setup.SetupRoute
import dev.openmob.companion.ui.activity.ActivityRoute

/** The redesign's navigation graph. Home, Settings, the indicator settings (step 2) and setup (step 4) are real;
 *  Activity (step 5) too. [real] false shows every placeholder (the step 1 skeleton, for its tests). */
@Composable
fun OpenMobNavHost(
    navController: NavHostController = rememberNavController(),
    startRoute: Route = Route.start,
    real: Boolean = true,
) {
    val navigate: (Route) -> Unit = { navController.navigate(it.path) { launchSingleTop = true } }
    val back: () -> Unit = { navController.popBackStack() }
    val finishSetup: () -> Unit = {
        navController.navigate(Route.Home.path) {
            popUpTo(Route.Home.path) { inclusive = true }
            launchSingleTop = true
        }
    }
    NavHost(navController = navController, startDestination = startRoute.path) {
        Route.entries.forEach { route ->
            composable(route.path) {
                when {
                    real && route == Route.Home ->
                        HomeRoute(openSettings = { navigate(Route.Settings) }, openActivity = { navigate(Route.Activity) },
                                  openSetup = { navigate(Route.SetupWelcome) }, openRoute = { navigate(it) })
                    real && route == Route.Settings -> SettingsRoute(back = back, openIndicator = { navigate(Route.Indicator) },
                                                                     openSetup = { navigate(Route.SetupReady) },
                                                                     openConnection = { navigate(Route.Connection) },
                                                                     openBlocked = { navigate(Route.Blocked) },
                                                                     openMemory = { navigate(Route.Memory) })
                    real && route == Route.Activity -> ActivityRoute(back = back)
                    real && (route.setupStep != null || route == Route.SetupWelcome || route == Route.Connection) ->
                        SetupRoute(route, navigate, back, finishSetup)
                    real && route == Route.Indicator -> IndicatorRoute(back = back)
                    real && route == Route.Blocked -> BlockedAppsRoute(back = back, openAdd = { navigate(Route.BlockedAdd) })
                    real && route == Route.BlockedAdd -> AddBlockedAppsRoute(back = back)
                    real && route == Route.Memory -> MemoryRoute(back = back)
                    else -> PlaceholderFor(route, back, navigate, finishSetup)
                }
            }
        }
    }
}
