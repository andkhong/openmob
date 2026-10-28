# R8 keep rules for the release and local builds (owner, 2026-10-17). Keep this file narrow: every rule says
# why. The libraries ship their own consumer rules; AGP merges them (app/build/outputs/mapping/<variant>/
# configuration.txt shows the full set), so they are not repeated here.

# Stack traces from a release or local build: keep line numbers (not names). Retrace them with the build's own
# app/build/outputs/mapping/<variant>/mapping.txt; keep that file with any APK handed out.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# Checked on 2026-10-17 and needing no rule of ours (re-check when adding code that loads things by name):
#
# - Manifest components (MainActivity, ApprovalActivity, ApprovalReceiver, ConnectionService,
#   OpenMobTileService, OpenMobAccessibilityService) and res/xml/shortcuts.xml's targetClass: AAPT2 writes keep
#   rules for every class the manifest names (seeds.txt lists all six, unrenamed).
# - The gatekeeper's rules.json: a Java resource (src/main/resources/gatekeeper/rules.json) read with an absolute
#   path (GateRules.builtIn, getResourceAsStream("/gatekeeper/rules.json")), so class renaming can't break it;
#   R8 keeps Java resources, and resource shrinking only touches res/. Parsed by MiniJson into maps, by key.
# - JSON: org.json (platform) and MiniJson, both by string key. No Gson/Moshi/kotlinx-serialization, no
#   @SerializedName, no field-name reflection.
# - Enums: none is read with valueOf() from network strings. PillCorner and SettingsPages map explicit key
#   strings; Route uses explicit path strings. R8 keeps Enum.name values anyway.
# - SettingsPages: a Kotlin map of string literals (key -> intent action). Literals survive R8.
# - No Class.forName, getDeclared*, getMethod, ServiceLoader, getIdentifier or @JavascriptInterface in the app.
# - ML Kit text recognition (PermissionOcr): its AARs ship rules for native methods, proto fields and the
#   ComponentRegistrar classes named in the manifest (TextRegistrar, VisionCommonRegistrar,
#   CommonComponentRegistrar and BundledTextRecognizerCreator are kept unrenamed); its models are assets.
# - OkHttp 4.12 / Okio: ship their own rules (PublicSuffixDatabase kept, publicsuffixes.gz packaged, -dontwarn for
#   the optional TLS providers). R8 reported no missing classes.
# - Compose, Navigation, Activity: ship their own rules.
# - Release signing: Gradle-only (build.gradle.kts); no app code reads it. ApprovalKeys and SecureStore use the
#   platform's AndroidKeyStore and java.security providers, which live outside the APK.
