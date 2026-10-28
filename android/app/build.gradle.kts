import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("io.github.takahirom.roborazzi")
}

// The owner's release key lives outside the repo (om keygen writes it; OPENMOB_SIGNING points elsewhere). Its
// passwords are read by Gradle only; never commit or print them. Without it, the signed builds fail to sign.
val signingFile = file(System.getenv("OPENMOB_SIGNING")
    ?: "${System.getProperty("user.home")}/.config/openmob-envs/release-signing.properties")

// The app's version (docs/phone-protocol.md §3.7): versionCode is the number of commits on the checked-out history
// (`git rev-list --count HEAD`), so it only grows along main and every build newer than the first (versionCode 1)
// is an update. versionName is "<count> (<short hash>)". Without git (a source zip, a CI checkout without history)
// the build still works: versionCode 1 and "unknown", with a warning.
fun git(vararg args: String): String? = try {
    val builder = ProcessBuilder(listOf("git") + args).directory(rootDir).redirectErrorStream(false)
    // git finds the repository from rootDir. A long-lived Gradle daemon can carry GIT_DIR and friends over from an
    // earlier build's environment (measured 2026-10-18), which would point git elsewhere: drop them.
    builder.environment().keys.removeAll { it.startsWith("GIT_") }
    val process = builder.start()
    val out = process.inputStream.bufferedReader().readText().trim()
    if (process.waitFor() == 0 && out.isNotEmpty()) out else null
} catch (e: Exception) {
    null
}
val gitCount: Int? = git("rev-list", "--count", "HEAD")?.toIntOrNull()?.takeIf { it > 0 }
val gitHash: String = git("rev-parse", "--short=7", "HEAD")?.takeIf { it.matches(Regex("[0-9a-f]{7,40}")) } ?: "unknown"
if (gitCount == null) logger.warn("OpenMob: git history not available; building with versionCode 1 (an update to no one).")
val appVersionCode: Int = gitCount ?: 1

// The server a typed pairing code goes to unless the phone's owner enters another (PairingFlow.HOSTED_SERVER).
// A self-hoster builds the app for their own server: ./gradlew assembleRelease -POPENMOB_DEFAULT_SERVER=https://…
// (or the environment variable OPENMOB_DEFAULT_SERVER). Unset: the hosted server, so the owner's builds don't change.
val defaultServer: String = (providers.gradleProperty("OPENMOB_DEFAULT_SERVER").orNull
    ?: providers.environmentVariable("OPENMOB_DEFAULT_SERVER").orNull)?.trim()?.trimEnd('/')?.takeIf { it.isNotEmpty() }
    ?: "https://openmob.fly.dev"
require(Regex("https?://[A-Za-z0-9.\\-]+(:[0-9]{1,5})?").matches(defaultServer)) {
    "OPENMOB_DEFAULT_SERVER must be a server address like https://openmob.example.com (no path), not '$defaultServer'"
}
// Release and local (owner-signed) builds must default to https://: a signed app that sends pairing codes over
// plain http would be one a phone owner can't tell apart from a safe one. Debug builds may use http:// (an emulator
// against a server on the developer's computer, e.g. http://10.0.2.2:8765). Checked when such a build runs, not at
// configuration, so a debug build or the unit tests with an http:// default still configure.
val requireHttpsDefaultServer = tasks.register("requireHttpsDefaultServer") {
    val server = defaultServer
    doLast {
        if (!server.startsWith("https://")) {
            throw GradleException("OPENMOB_DEFAULT_SERVER is '$server': release and local builds need an https:// " +
                "server address (http:// is allowed only in debug builds, e.g. ./gradlew assembleDebug).")
        }
    }
}
tasks.matching { it.name == "preReleaseBuild" || it.name == "preLocalBuild" }.configureEach {
    dependsOn(requireHttpsDefaultServer)
}

android {
    namespace = "dev.openmob.companion"
    compileSdk = 35

    defaultConfig {
        // 64-bit ARM only: the bundled OCR model (PermissionOcr) ships a native library per ABI (~11 MB each).
        ndk { abiFilters += listOf("arm64-v8a") }
        applicationId = "dev.openmob.companion"
        minSdk = 30 // AccessibilityService.takeScreenshot
        targetSdk = 35
        versionCode = appVersionCode
        versionName = "$appVersionCode ($gitHash)"
        buildConfigField("String", "GIT_HASH", "\"$gitHash\"")
        buildConfigField("String", "DEFAULT_SERVER", "\"$defaultServer\"")
    }

    signingConfigs {
        if (signingFile.exists()) {
            create("owner") {
                val p = Properties().apply { signingFile.inputStream().use { load(it) } }
                storeFile = file(p.getProperty("storeFile"))
                storePassword = p.getProperty("storePassword")
                keyAlias = p.getProperty("keyAlias")
                keyPassword = p.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        // Plain http:// is for a developer's own server on the local network. Release builds turn
        // cleartext off at the platform level too; in every build ServerPolicy only lets http://
        // reach local addresses (Android's network config can't express private IP ranges).
        debug {
            manifestPlaceholders["usesCleartext"] = "true"
        }
        // What phones download from a hosted server: the owner's key, not debuggable, https only.
        // R8 (owner, 2026-10-17): shrink, optimize and obfuscate the code, and drop unused resources. Compose
        // grew the unshrunk APK from 22 MB to 38 MB. Keep rules: proguard-rules.pro (each one says why).
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            manifestPlaceholders["usesCleartext"] = "false"
            signingConfig = signingConfigs.findByName("owner")
        }
        // The owner's own phone against their own server on the local network: the same key (so it updates
        // over a release install and back), not debuggable, and http:// to local addresses (ServerPolicy).
        // initWith copies release's R8 code settings, so the owner's phone runs the same shrunk code as release.
        // It does not carry resource shrinking over (measured: AGP 8.7 kept every resource), so set it again.
        create("local") {
            initWith(getByName("release"))
            isShrinkResources = true
            manifestPlaceholders["usesCleartext"] = "true"
            matchingFallbacks += listOf("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    // The redesign (Jetpack Compose; owner, 2026-10-17). Step 1 is the foundation only: RedesignActivity is
    // declared in the debug manifest alone, and MainActivity stays the app.
    buildFeatures {
        compose = true
        buildConfig = true // BuildConfig.VERSION_CODE and GIT_HASH (Settings › About, the hello)
    }
    testOptions {
        // Robolectric renders the Compose components in the JVM unit tests (semantics and screenshots).
        unitTests.isIncludeAndroidResources = true
    }
    // The gatekeeper's shared scenario fixtures (also run by pytest through the Python reference engine).
    sourceSets.getByName("test").resources.srcDir("../../tests/fixtures/gatekeeper")
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // On-device OCR of the permission dialogs Android 14+ hides from accessibility: the bundled Latin model
    // (offline, no network, no Play services download).
    implementation("com.google.mlkit:text-recognition:16.0.1")
    testImplementation("junit:junit:4.13.2")

    // Jetpack Compose (the redesign). Exact versions: BOM 2025.06.01 = Compose 1.8.3 and Material3 1.3.2. Newer
    // BOMs and activity 1.11+ need compileSdk 36, which AGP 8.7 does not support; navigation 2.9 pulls in
    // lifecycle 2.9, whose lint check crashes AGP 8.7 lint (lintVitalAnalyzeRelease), so navigation stays on 2.8.
    val composeBom = platform("androidx.compose:compose-bom:2025.06.01")
    implementation(composeBom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.navigation:navigation-compose:2.8.9")
    // Step 2's ViewModels (the versions navigation 2.8.9 already brings in; 2.9 would hit the lint crash above).
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    debugImplementation("androidx.compose.ui:ui-tooling")
    // Hosts createComposeRule's activity in the debug unit tests.
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    testImplementation(composeBom)
    testImplementation("androidx.compose.ui:ui-test-junit4")
    testImplementation("org.robolectric:robolectric:4.14.1")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.7.3")
    testImplementation("io.github.takahirom.roborazzi:roborazzi:1.43.1")
    testImplementation("io.github.takahirom.roborazzi:roborazzi-compose:1.43.1")
}

roborazzi {
    // Reference images go here. The repo ignores *.png, so they are local: record them on the base commit
    // (`recordRoborazziDebug`), then `verifyRoborazziDebug` on the change shows any visual difference.
    outputDir.set(file("src/test/screenshots"))
}
