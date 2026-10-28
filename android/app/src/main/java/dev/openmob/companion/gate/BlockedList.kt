package dev.openmob.companion.gate

/**
 * The owner's blocked apps (owner, 2026-10-20; docs/design/blocked-apps.md), as plain Kotlin so the JVM tests run it.
 * The list is exact package names on top of the built-in sensitive apps; [Gatekeeper.ownerBlocked] enforces it.
 *
 * Who may change it:
 * - **Add:** the owner on the phone, or a `block_apps` request from the server (the dashboard). [withServerRequest]
 *   only ever adds: it reads one field, `packages`, and nothing in a message can remove an entry.
 * - **Remove:** only the owner on this phone, after Android's screen-lock prompt ([without], called from the unblock
 *   sheet's success callback). A compromised server can only tighten the list.
 */
object BlockedList {
    /** At most this many entries (a server can't grow the list, or a report, without bound). */
    const val MAX = 200
    /** Android package names: two or more dot-separated Java identifiers (ASCII only), at most 255 characters. */
    private val PACKAGE = Regex("^[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+$")

    fun valid(pkg: String): Boolean = pkg.length <= 255 && PACKAGE.matches(pkg)

    private val rules: GateRules by lazy { GateRules.builtIn() }

    /**
     * Never blockable (review 5 P5-L1, narrowed by the owner's tighten-only rule after re-review 1, N3): exactly
     * OpenMob itself, the phone's current default Home app ([home]: resolved by the caller) and System UI, by exact
     * package name. Blocking them would lock the owner out (the act watch sends the phone Home, so a blocked Home app
     * loops) or block the phone's own shell. Everything else, Settings, permission controllers, installers and any app
     * with "launcher" in its name included, can be blocked like any app.
     */
    fun protectedPackage(pkg: String, home: Set<String> = emptySet()): Boolean {
        val r = rules
        return pkg in r.own || pkg in home || pkg == r.surfStr("systemui")
    }

    /** [current] plus [add] (in order, no duplicates), or null when any entry is malformed or the result would pass
     *  [MAX]: a request is taken whole or not at all. A [protectedPackage] in [add] is left out (never added). */
    fun with(current: List<String>, add: List<String>, home: Set<String> = emptySet()): List<String>? {
        if (add.any { !valid(it) }) return null
        val out = LinkedHashSet(current)
        out.addAll(add.filterNot { protectedPackage(it, home) })
        return if (out.size > MAX) null else out.toList()
    }

    /** A server's `block_apps` request ({"type": "block_apps", "packages": [...]}) applied to [current]: only adds.
     *  Null (refused, nothing changes) when `packages` isn't a list of strings, is empty or too long, or holds a
     *  malformed name. Any other field (an "unblock", a "remove", a "replace") is ignored. */
    fun withServerRequest(current: List<String>, message: Map<String, Any?>, home: Set<String> = emptySet()): List<String>? {
        val raw = message["packages"] as? List<*> ?: return null
        if (raw.isEmpty() || raw.size > MAX || raw.any { it !is String }) return null
        return with(current, raw.map { it as String }, home)
    }

    /** [current] without [pkg]: only for the owner's Unblock on this phone, after the screen lock. */
    fun without(current: List<String>, pkg: String): List<String> = current.filter { it != pkg }

    /** A stored list, read back: malformed entries dropped, capped (a damaged file never loosens a valid entry). */
    fun parse(stored: List<String>): List<String> = LinkedHashSet(stored.filter(::valid)).toList().take(MAX)
}
