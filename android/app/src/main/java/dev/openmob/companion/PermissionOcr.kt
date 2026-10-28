package dev.openmob.companion

import android.graphics.Bitmap
import android.os.SystemClock
import android.util.Log
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import dev.openmob.companion.gate.GOcrLine
import java.util.concurrent.TimeUnit

/**
 * Reads the permission dialog Android 14+ hides from accessibility: the phone's own screenshot, through ML Kit text
 * recognition (the bundled Latin model: on the device, offline). The gatekeeper rebuilds the dialog from these lines
 * (Gatekeeper.withOcr) and judges taps on it; ui_elements lists them (class OCRText). Never on the main thread.
 */
object PermissionOcr {
    private const val CACHE_MS = 1500L
    private val recognizer by lazy { TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS) }
    /** A reading belongs to one window: a stale one never identifies another window (an app loading after the
     *  dialog closed). */
    private class Reading(val window: Int, val changed: Long, val at: Long, val lines: List<GOcrLine>)
    @Volatile private var cache: Reading? = null

    /** The screen's text lines, or null when the screen can't be captured or read. [fresh]: never the cached reading
     *  (the re-check right before an act: a dialog can swap its content in place with no event, review M1). */
    @Synchronized
    fun read(service: OpenMobAccessibilityService, window: Int, fresh: Boolean = false): List<GOcrLine>? {
        val now = SystemClock.uptimeMillis()
        if (!fresh) cache?.let { if (it.window == window && it.changed == service.lastChangeAt && now - it.at < CACHE_MS) return it.lines }
        val changed = service.lastChangeAt
        val bitmap = runCatching { PhoneActions(service).screenBitmap() }.getOrNull()
        if (bitmap == null) {
            Log.i(TAG, "ocr: screen capture failed")
            return null
        }
        // The agent indicator's Stop pill is OpenMob's own text, never part of a dialog.
        val lines = try { recognize(bitmap) } finally { bitmap.recycle() }
            ?.let { IndicatorGeometry.dropOwn(it, ControlIndicator.ownRects()) }
        val ms = SystemClock.uptimeMillis() - now
        if (lines == null) {
            Log.i(TAG, "ocr: recognition failed after ${ms} ms")
            return null
        }
        Log.i(TAG, "ocr: ${lines.size} lines in ${ms} ms, min conf ${"%.2f".format(lines.minOfOrNull { it.conf } ?: 0.0)}")
        cache = Reading(window, changed, SystemClock.uptimeMillis(), lines)
        return lines
    }

    /** The last reading if it's under 3 s old, without blocking (for the live view's gate, on any thread). A reading
     *  over a second old is refreshed in the background meanwhile. */
    fun cached(service: OpenMobAccessibilityService, window: Int): List<GOcrLine>? {
        val c = cache?.takeIf { it.window == window }
        val age = if (c == null) Long.MAX_VALUE else SystemClock.uptimeMillis() - c.at
        if (age > 1_000) refreshAsync(service, window)
        return if (age < 3_000) c?.lines else null
    }

    /** Forget the last reading (after a gesture: what it read may no longer be on screen). */
    fun invalidate() { cache = null; drawnCache = null }

    // --- words drawn near a tap on a drawn spot (review 2 M3, 2026-10-17) ---------------------------------------

    /** The crop read around a drawn spot, as shares of the screen: wider and taller than the gate's reach (rules.json
     *  canvas: dx 0.12 of the width, one row up and down, a price within 0.1 of the height below) so lines that only
     *  overlap the reach are read whole. */
    private const val DRAWN_HALF_W = 0.3
    private const val DRAWN_UP = 0.06
    private const val DRAWN_DOWN = 0.14
    /** Recognition of a drawn spot gives up after this: the gate then asks rather than wait (M3). */
    const val DRAWN_TIMEOUT_MS = 1200L
    private class Drawn(val x: Int, val y: Int, val changed: Long, val at: Long, val lines: List<GOcrLine>)
    @Volatile private var drawnCache: Drawn? = null

    /** The text lines drawn near (x, y), in screen pixels, or null when the screen can't be captured or read in time.
     *  [fresh]: never the cached reading (the re-check right before the gesture: a canvas can swap its drawn button
     *  with no accessibility event). Logged with its time (logcat OpenMobGate), never its words. */
    @Synchronized
    fun readDrawn(service: OpenMobAccessibilityService, x: Double, y: Double, fresh: Boolean = false): List<GOcrLine>? {
        val now = SystemClock.uptimeMillis()
        val px = x.toInt()
        val py = y.toInt()
        if (!fresh) drawnCache?.let {
            if (it.x == px && it.y == py && it.changed == service.lastChangeAt && now - it.at < CACHE_MS) return it.lines
        }
        val changed = service.lastChangeAt
        val full = runCatching { PhoneActions(service).screenBitmap() }.getOrNull()
        if (full == null) {
            Log.i(TAG, "ocr drawn: screen capture failed")
            return null
        }
        val w = full.width
        val h = full.height
        val left = (px - DRAWN_HALF_W * w).toInt().coerceIn(0, w - 1)
        val right = (px + DRAWN_HALF_W * w).toInt().coerceIn(left + 1, w)
        val top = (py - DRAWN_UP * h).toInt().coerceIn(0, h - 1)
        val bottom = (py + DRAWN_DOWN * h).toInt().coerceIn(top + 1, h)
        val crop = runCatching { Bitmap.createBitmap(full, left, top, right - left, bottom - top) }.getOrNull()
        if (crop !== full) full.recycle() // createBitmap returns the source itself when the crop is all of it
        if (crop == null) return null
        val lines = try { recognize(crop, DRAWN_TIMEOUT_MS) } finally { crop.recycle() }
            ?.map { GOcrLine(it.text, intArrayOf(it.bounds[0] + left, it.bounds[1] + top, it.bounds[2] + left, it.bounds[3] + top), it.conf) }
            ?.let { IndicatorGeometry.dropOwn(it, ControlIndicator.ownRects()) }
        val ms = SystemClock.uptimeMillis() - now
        if (lines == null) {
            Log.i(TAG, "ocr drawn: recognition failed or timed out after $ms ms")
            return null
        }
        Log.i(TAG, "ocr drawn: ${lines.size} lines in $ms ms (crop ${right - left}x${bottom - top}, fresh=$fresh)")
        drawnCache = Drawn(px, py, changed, SystemClock.uptimeMillis(), lines)
        return lines
    }

    private val worker =java.util.concurrent.Executors.newSingleThreadExecutor()

    /** Load the model ahead of time: its first use takes seconds (measured 3.5 s on an emulator), too long for a
     *  dialog to wait black. Runs once, in the background. */
    fun warmUp() {
        if (!busy.compareAndSet(false, true)) return
        worker.execute {
            try {
                val t = SystemClock.uptimeMillis()
                val bmp = Bitmap.createBitmap(64, 32, Bitmap.Config.ARGB_8888).apply { eraseColor(android.graphics.Color.WHITE) }
                recognize(bmp)
                bmp.recycle()
                Log.i(TAG, "ocr: model ready in ${SystemClock.uptimeMillis() - t} ms")
            } finally { busy.set(false) }
        }
    }
    private val busy = java.util.concurrent.atomic.AtomicBoolean(false)

    /** Read in the background (one at a time); [cached] has it afterwards. */
    fun refreshAsync(service: OpenMobAccessibilityService, window: Int) {
        if (!busy.compareAndSet(false, true)) return
        worker.execute { try { runCatching { read(service, window) } } finally { busy.set(false) } }
    }

    private fun recognize(bitmap: Bitmap, timeoutMs: Long = 5_000): List<GOcrLine>? = runCatching {
        val text = Tasks.await(recognizer.process(InputImage.fromBitmap(bitmap, 0)), timeoutMs, TimeUnit.MILLISECONDS)
        text.textBlocks.flatMap { it.lines }.mapNotNull { line ->
            val r = line.boundingBox ?: return@mapNotNull null
            GOcrLine(line.text, intArrayOf(r.left, r.top, r.right, r.bottom), line.confidence.toDouble())
        }.let { lines ->
            // A model that reports no confidence at all (every line 0) isn't "unsure": treat it as unreported.
            if (lines.isNotEmpty() && lines.all { it.conf <= 0.0 }) lines.map { GOcrLine(it.text, it.bounds, 1.0) } else lines
        }
    }.onFailure { Log.i(TAG, "ocr: ${it.javaClass.simpleName}: ${it.message}") }.getOrNull()

    const val TAG = "OpenMobGate"
}
