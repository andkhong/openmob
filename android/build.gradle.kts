plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    // The Compose compiler ships with Kotlin since 2.0: its plugin version must equal the Kotlin version.
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.21" apply false
    // JVM screenshot tests of the redesign's theme and components (Robolectric, no device).
    id("io.github.takahirom.roborazzi") version "1.43.1" apply false
}
