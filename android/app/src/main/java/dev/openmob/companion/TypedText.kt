package dev.openmob.companion

/** What a field holds after type_text: [text] inserted at the selection (replacing it; no known selection means
 *  append), or, with [replace], [text] alone. Replace is for search and address boxes, which otherwise keep the
 *  last query ("Spotify" + "chess games" gave "Spotifychess games" on a Samsung). Returns the text and the cursor.
 *  The gatekeeper judges typing with the same function (review 2 L2, 2026-10-17): what it judges is what the phone
 *  inserts. */
internal object TypedText {
    fun result(old: String, selection: Pair<Int, Int>?, text: String, replace: Boolean): Pair<String, Int> {
        if (replace) return text to text.length
        val (start, end) = selection ?: (old.length to old.length)
        return old.substring(0, start) + text + old.substring(end) to start + text.length
    }

    /** A field's reported selection, ordered and clamped to its text; null when it doesn't report one (-1). */
    fun selection(start: Int, end: Int, length: Int): Pair<Int, Int>? {
        if (start < 0 || end < 0) return null
        return minOf(start, end).coerceAtMost(length) to maxOf(start, end).coerceAtMost(length)
    }
}
