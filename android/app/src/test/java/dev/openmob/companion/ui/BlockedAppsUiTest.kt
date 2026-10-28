package dev.openmob.companion.ui

import android.app.Notification
import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.semantics.SemanticsActions
import androidx.test.core.app.ApplicationProvider
import dev.openmob.companion.BlockedApps
import dev.openmob.companion.R
import dev.openmob.companion.ui.settings.AppBlockedSource
import dev.openmob.companion.ui.settings.BlockedAppsViewModel
import dev.openmob.companion.ui.settings.BlockedRow
import dev.openmob.companion.ui.settings.BlockedAppsContent
import dev.openmob.companion.ui.settings.TAG_BLOCKED_ROW
import dev.openmob.companion.ui.nav.OpenMobNavHost
import dev.openmob.companion.ui.nav.Route
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.isHeading
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.performScrollTo
import dev.openmob.companion.ui.settings.BlockedSource
import dev.openmob.companion.ui.settings.AddAppsActions
import dev.openmob.companion.ui.settings.AddBlockedAppsScreen
import dev.openmob.companion.ui.settings.TAG_BLOCKED_BUILTIN
import dev.openmob.companion.ui.settings.TAG_BLOCKED_CONFIRM_UNBLOCK
import dev.openmob.companion.ui.settings.TAG_BLOCKED_KEEP
import dev.openmob.companion.ui.settings.TAG_BLOCKED_YOURS
import dev.openmob.companion.ui.settings.switchTag
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.assertIsOn
import dev.openmob.companion.ui.theme.OpenMobTheme
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.robolectric.Shadows
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Owner-added blocked apps on the phone (docs/design/blocked-apps.md): unblocking needs the screen lock, a server
 *  request only adds, and the "Task stopped" notification never names the app. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class BlockedAppsUiTest {
    val rule = createAndroidComposeRule<ComponentActivity>()
    @get:Rule val host: org.junit.rules.RuleChain = hostedBy(rule)
    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private val gmail = "com.google.android.gm"

    @After fun clear() {
        BlockedApps.list(ctx).forEach { BlockedApps.unblockAfterScreenLock(ctx, it) }
    }

    @Test fun aServerRequestAddsAndNeverRemoves() {
        assertTrue(BlockedApps.block(ctx, listOf("com.whatsapp", gmail)))
        // Removal-shaped messages: no packages, an empty list, an "unblock" field. The list stays as it was.
        BlockedApps.onServerRequest(ctx, JSONObject().put("type", "block_apps").put("unblock", JSONArray().put(gmail)))
        BlockedApps.onServerRequest(ctx, JSONObject().put("type", "block_apps").put("packages", JSONArray()))
        BlockedApps.onServerRequest(ctx, JSONObject().put("type", "block_apps").put("packages", JSONArray().put("bad name")))
        assertEquals(listOf("com.whatsapp", gmail), BlockedApps.list(ctx))
        assertTrue(BlockedApps.onServerRequest(ctx, JSONObject().put("packages", JSONArray().put("org.telegram.messenger"))))
        assertEquals(listOf("com.whatsapp", gmail, "org.telegram.messenger"), BlockedApps.list(ctx))
        val report = BlockedApps.report(ctx)
        assertEquals("blocked_apps", report.getString("type"))
        assertEquals(3, report.getJSONArray("packages").length())
    }

    @Test fun theReportCarriesLabelsBesidePlainPackages() {
        val notes = "com.example.notes" // installed here, with a label (OpenMob itself can't be blocked: review 5 P5-L1)
        Shadows.shadowOf(ctx.packageManager).installPackage(android.content.pm.PackageInfo().apply {
            packageName = notes
            applicationInfo = android.content.pm.ApplicationInfo().apply { packageName = notes; nonLocalizedLabel = "Notes" }
        })
        BlockedApps.block(ctx, listOf(gmail, notes, ctx.packageName))
        assertEquals(listOf(gmail, notes), BlockedApps.list(ctx))
        val r = BlockedApps.report(ctx)
        assertEquals(gmail, r.getJSONArray("packages").getString(0)) // older servers read only this
        val apps = r.getJSONArray("apps")
        assertEquals(gmail, apps.getJSONObject(0).getString("package"))
        assertEquals("", apps.getJSONObject(0).getString("label")) // not installed here: no name
        assertTrue(apps.getJSONObject(1).getString("label").isNotEmpty()) // an installed app: its label
        assertEquals("Whats App", BlockedApps.cleanLabel("Whats\nApp‮\u0000"))
        assertEquals(60, BlockedApps.cleanLabel("x".repeat(100)).length)
    }

    @Test fun unblockingWithoutPassingTheScreenLockChangesNothing() {
        BlockedApps.block(ctx, listOf(gmail))
        // No screen lock set up (Robolectric): the prompt never succeeds, so the app stays blocked.
        var done = false
        AppBlockedSource(ctx).confirmUnblock(rule.activity, BlockedRow(gmail, "Gmail")) { done = true }
        rule.waitForIdle()
        assertFalse(done)
        assertEquals(listOf(gmail), BlockedApps.list(ctx))
        AppBlockedSource(ctx).confirmUnblock(null, BlockedRow(gmail, "Gmail")) { done = true }
        assertEquals(listOf(gmail), BlockedApps.list(ctx))
    }

    @Test fun theStoppedNotificationNeverNamesTheApp() {
        BlockedApps.block(ctx, listOf(gmail))
        val n = BlockedApps.notification(ctx)
        val shown = listOf(n.extras.getCharSequence(Notification.EXTRA_TITLE), n.extras.getCharSequence(Notification.EXTRA_TEXT),
                           n.extras.getCharSequence(Notification.EXTRA_BIG_TEXT), n.publicVersion?.extras?.getCharSequence(Notification.EXTRA_TITLE))
            .joinToString(" ")
        assertEquals(ctx.getString(R.string.blocked_hit_title), n.extras.getCharSequence(Notification.EXTRA_TITLE).toString())
        assertEquals(ctx.getString(R.string.blocked_hit_text), n.extras.getCharSequence(Notification.EXTRA_TEXT).toString())
        assertFalse(shown, shown.contains("gm", ignoreCase = true) || shown.contains("Gmail") || shown.contains("google"))
        assertEquals(Notification.VISIBILITY_PRIVATE, n.visibility)
    }

    /** A source whose screen-lock prompt is scripted: [lockPasses] decides whether the owner passes it. */
    private class Fake(var list: List<String> = emptyList()) : BlockedSource {
        val blockedCalls = mutableListOf<List<String>>()
        var prompts = 0
        var lockPasses = false
        override fun blocked() = list
        override fun label(pkg: String) = NAMES[pkg] ?: pkg
        override fun installed() = NAMES.entries.map { it.key to it.value }
        override fun builtIn(pkg: String) = pkg == CHASE
        override fun block(packages: List<String>): Boolean { blockedCalls += packages; list = list + packages; return true }
        override fun confirmUnblock(activity: android.app.Activity?, row: BlockedRow, onDone: () -> Unit) {
            prompts++
            if (lockPasses) { list = list - row.pkg; onDone() }
        }
        override fun listen(listener: () -> Unit): () -> Unit = {}
        companion object {
            const val CHASE = "com.chase.sig.android"
            val NAMES = mapOf(CHASE to "Chase", "com.whatsapp" to "WhatsApp", "com.google.android.gm" to "Gmail",
                              "com.android.chrome" to "Chrome")
        }
    }

    private fun showPicker(fake: Fake): BlockedAppsViewModel {
        val vm = BlockedAppsViewModel(fake, loadApps = true)
        rule.setContent {
            OpenMobTheme {
                val state by vm.state.collectAsState()
                AddBlockedAppsScreen(state, AddAppsActions(block = { vm.block(it) }, unblock = { vm.unblock(null, it) },
                                                           filter = vm::showOnlyBlocked))
            }
        }
        return vm
    }

    @Test fun settingsHasOneRowThatOpensTheBlockedAppsPageAndBackReturns() {
        rule.setContent { OpenMobTheme { OpenMobNavHost(startRoute = Route.Settings) } }
        rule.onNode(hasText(ctx.getString(R.string.rd_settings_title)) and isHeading()).assertExists()
        // Settings holds only the row (none of the page's content).
        rule.onAllNodes(hasText(ctx.getString(R.string.blocked_builtin_section).uppercase())).assertCountEquals(0)
        rule.onAllNodes(hasText(ctx.getString(R.string.blocked_row_subtitle, 4, 0))).assertCountEquals(1)
        rule.onNodeWithTag(TAG_BLOCKED_ROW).performScrollTo().performClick()
        rule.onNode(hasText(ctx.getString(R.string.blocked_title)) and isHeading()).assertExists()
        val builtIn = rule.onNodeWithTag(TAG_BLOCKED_BUILTIN).fetchSemanticsNode().positionInRoot.y
        val yours = rule.onNodeWithTag(TAG_BLOCKED_YOURS).fetchSemanticsNode().positionInRoot.y
        assertTrue("built in first", builtIn < yours)
        rule.onNodeWithContentDescription(ctx.getString(R.string.rd_back)).performClick()
        rule.onNode(hasText(ctx.getString(R.string.rd_settings_title)) and isHeading()).assertExists()
    }

    @Test fun settingsShowsTheBuiltInsFirstThenTheOwnersApps() {
        rule.setContent { OpenMobTheme { BlockedAppsContent(listOf(BlockedRow(gmail, "Gmail")), onAdd = {}, onUnblock = {}) } }
        val builtIn = rule.onNodeWithTag(TAG_BLOCKED_BUILTIN).fetchSemanticsNode().positionInRoot.y
        val yours = rule.onNodeWithTag(TAG_BLOCKED_YOURS).fetchSemanticsNode().positionInRoot.y
        assertTrue("built in first", builtIn < yours)
        rule.onAllNodes(hasText(ctx.getString(R.string.blocked_more))).assertCountEquals(1)
        rule.onAllNodes(hasText(ctx.getString(R.string.blocked_switch_footer))).assertCountEquals(1)
        // The four built-in switches are on and can't be changed.
        for (i in 0 until 4) rule.onNodeWithTag(switchTag("builtin-$i")).assertIsOn().assertIsNotEnabled()
        rule.onNodeWithTag(switchTag(gmail)).assertIsOn().assertIsEnabled()
    }

    @Test fun turningAnOwnersSwitchOffAsksAndKeepBlockedChangesNothing() {
        var unblocked: BlockedRow? = null
        rule.setContent { OpenMobTheme { BlockedAppsContent(listOf(BlockedRow(gmail, "Gmail")), onAdd = {}, onUnblock = { unblocked = it }) } }
        rule.onNodeWithTag(switchTag(gmail)).performSemanticsAction(SemanticsActions.OnClick)
        rule.onAllNodes(hasText(ctx.getString(R.string.blocked_unblock_title, "Gmail"))).assertCountEquals(1)
        rule.onNodeWithTag(TAG_BLOCKED_KEEP).performSemanticsAction(SemanticsActions.OnClick)
        rule.waitForIdle()
        assertEquals(null, unblocked)
        rule.onNodeWithTag(switchTag(gmail)).performSemanticsAction(SemanticsActions.OnClick)
        rule.onNodeWithTag(TAG_BLOCKED_CONFIRM_UNBLOCK).performSemanticsAction(SemanticsActions.OnClick)
        assertEquals(gmail, unblocked?.pkg) // then the route runs Android's screen-lock prompt
    }

    @Test fun inTheListSwitchingOnBlocksAtOnceWithNoConfirmation() {
        val fake = Fake(list = listOf(gmail))
        showPicker(fake)
        rule.onNodeWithTag(switchTag("com.whatsapp")).assertIsOff().performSemanticsAction(SemanticsActions.OnClick)
        rule.waitForIdle()
        assertEquals(listOf(listOf("com.whatsapp")), fake.blockedCalls)
        assertEquals(0, fake.prompts)
        rule.onAllNodes(hasText(ctx.getString(R.string.blocked_unblock_title, "WhatsApp"))).assertCountEquals(0)
        rule.onNodeWithTag(switchTag("com.whatsapp")).assertIsOn()
        rule.onAllNodes(hasText(ctx.resources.getQuantityString(R.plurals.blocked_count, 2, 2))).assertCountEquals(1)
    }

    @Test fun inTheListSwitchingOffNeedsTheScreenLockAndAFailedLockRemovesNothing() {
        val fake = Fake(list = listOf(gmail))
        showPicker(fake)
        rule.onNodeWithTag(switchTag(gmail)).assertIsOn().performSemanticsAction(SemanticsActions.OnClick)
        rule.onNodeWithTag(TAG_BLOCKED_CONFIRM_UNBLOCK).performSemanticsAction(SemanticsActions.OnClick) // the owner cancels or fails the lock
        rule.waitForIdle()
        assertEquals(1, fake.prompts)
        assertEquals(listOf(gmail), fake.list)
        rule.onNodeWithTag(switchTag(gmail)).assertIsOn()
        // Keep blocked: no prompt at all.
        rule.onNodeWithTag(switchTag(gmail)).performSemanticsAction(SemanticsActions.OnClick)
        rule.onNodeWithTag(TAG_BLOCKED_KEEP).performSemanticsAction(SemanticsActions.OnClick)
        rule.waitForIdle()
        assertEquals(1, fake.prompts)
        // The lock passes: only now is it removed.
        fake.lockPasses = true
        rule.onNodeWithTag(switchTag(gmail)).performSemanticsAction(SemanticsActions.OnClick)
        rule.onNodeWithTag(TAG_BLOCKED_CONFIRM_UNBLOCK).performSemanticsAction(SemanticsActions.OnClick)
        rule.waitForIdle()
        assertEquals(emptyList<String>(), fake.list)
        rule.onNodeWithTag(switchTag(gmail)).assertIsOff()
    }

    @Test fun builtInAppsShowALockedOnSwitch() {
        val fake = Fake()
        val vm = showPicker(fake)
        rule.onNodeWithTag(switchTag(Fake.CHASE)).assertIsOn().assertIsNotEnabled()
        rule.onAllNodes(hasText(ctx.getString(R.string.blocked_builtin_subtitle))).assertCountEquals(1)
        assertFalse(vm.block(Fake.CHASE)) // nothing to add: it's built in
        assertTrue(fake.blockedCalls.isEmpty())
        assertTrue(vm.state.value.apps.first { it.pkg == Fake.CHASE }.builtIn)
    }
}
