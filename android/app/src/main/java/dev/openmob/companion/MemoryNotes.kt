package dev.openmob.companion

import org.json.JSONArray
import org.json.JSONObject

/**
 * The owner's saved preferences as the server sends them (docs/phone-protocol.md §3.9), for the "What OpenMob
 * remembers" page. In memory for this app session only: nothing here is written to storage, shown in a notification
 * or read by the gatekeeper. Display only: the server decides who may see and change them.
 */
object MemoryNotes {
    /** kind: about_you | person | app. [pkg] for app notes; [relation] and [contactName] for person notes. */
    data class Note(
        val id: String, val kind: String, val text: String, val status: String,
        val pkg: String? = null, val relation: String? = null, val contactName: String? = null,
    )

    /** The server's welcome said this phone may open the page (the switch is on and the phone is trusted). */
    @Volatile var supported: Boolean = false
        private set
    @Volatile var notes: List<Note> = emptyList()
        private set
    @Volatile var proposed: List<Note> = emptyList()
        private set
    /** The first list has come since the page asked. */
    @Volatile var loaded: Boolean = false
        private set
    /** The last answer's error code (bad_note, unknown, not_proposed, rate_limited, bad_request), or null. */
    @Volatile var error: String? = null
        private set

    fun reset() {
        supported = false; notes = emptyList(); proposed = emptyList(); loaded = false; error = null
        AppState.notifyListeners()
    }

    /** `welcome`: `memory` true shows the Settings row. Every welcome first clears what was shown (it may be another
     *  account after a re-pair, or this phone's trust may have changed), so nothing old shows until a fresh `memory`
     *  list comes. Returns the list request to send now when the page had notes this session (it may be open), else
     *  null: the page asks for itself when it opens. */
    fun onWelcome(json: JSONObject): JSONObject? {
        val hadNotes = loaded
        reset()
        if (!json.optBoolean("memory", false)) return null
        supported = true
        AppState.notifyListeners()
        return if (hadNotes) listRequest() else null
    }

    /** `memory`: the notes, an error, or `denied` (switched off, or this phone isn't trusted any more): then
     *  everything shown goes and the row hides. */
    fun onMemory(json: JSONObject) {
        if (json.optBoolean("denied", false)) { reset(); return }
        error = if (json.has("error")) json.optString("error") else null
        if (json.has("notes") || json.has("proposed")) {
            notes = parse(json.optJSONArray("notes"))
            proposed = parse(json.optJSONArray("proposed"))
            loaded = true
        }
        AppState.notifyListeners()
    }

    private fun parse(array: JSONArray?): List<Note> {
        if (array == null) return emptyList()
        return (0 until array.length()).mapNotNull { i ->
            val o = array.optJSONObject(i) ?: return@mapNotNull null
            val id = o.optString("id").takeIf { it.isNotEmpty() } ?: return@mapNotNull null
            fun field(name: String) = if (o.isNull(name)) null else o.optString(name).takeIf { it.isNotEmpty() }
            Note(id, o.optString("kind"), o.optString("text"), o.optString("status"),
                 field("package"), field("relation"), field("contact_name"))
        }
    }

    // --- to the server --------------------------------------------------------------------------------------------

    fun listRequest(): JSONObject = JSONObject().put("type", "memory_list")
    fun editRequest(id: String, text: String?, contactName: String?): JSONObject =
        JSONObject().put("type", "memory_edit").put("id", id).apply {
            text?.let { put("text", it) }
            contactName?.let { put("contact_name", it) }
        }
    fun deleteRequest(id: String): JSONObject = JSONObject().put("type", "memory_delete").put("id", id)
    fun confirmRequest(id: String): JSONObject = JSONObject().put("type", "memory_confirm").put("id", id)
    fun dismissRequest(id: String): JSONObject = JSONObject().put("type", "memory_dismiss").put("id", id)
}
