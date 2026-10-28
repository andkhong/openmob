# Release signing

The phone app comes in three builds. All have the same package (`dev.openmob.companion`).

| Build | Signed with | Debuggable | Plain `http://` | For |
|---|---|---|---|---|
| `debug` | this machine's Android debug key (unprotected) | yes | local addresses | emulators and tests (`om build <env>`) |
| `local` | **the owner's release key** | no | local addresses (`ServerPolicy`) | the owner's own phone with their own server (`om build <env> signed`) |
| `release` | **the owner's release key** | no | never | what the hosted server offers for download (`om release`) |

`local` and `release` share the key, so a phone can move between them without reinstalling. A phone with a `debug` install has to uninstall OpenMob once (and pair again) to switch to a signed build. Android refuses to update an app with a different signature.

## Why

The `debug` build is debuggable. Anyone with USB access to the phone can read the app's private data, including its device key, with `run-as`. It's also signed with a debug key. Each developer machine makes its own (`~/.android/debug.keystore`), but that key isn't protected: its password is the well-known `android`, so anything that copies the file (malware, a backup, a shared build machine) can sign a "newer" app that installs over it. Security review 2026-10-09, M1.

## The key (once)

Run in your own terminal:

```sh
scripts/om keygen
```

It asks for a password (12 or more characters) without echoing it. It writes:
- `~/.config/openmob-envs/release.jks`: a 4096-bit RSA key, valid for 10,000 days;
- `~/.config/openmob-envs/release-signing.properties`: the paths and password Gradle reads.

Both are readable by you only (mode 600), and both are outside the repo. Set `OPENMOB_SIGNING` to keep the properties file elsewhere.

**Back up both files and the password,** for example in a password manager. If you lose them, every phone must uninstall OpenMob and pair again before it can take updates.

Agents never read these files or print the password. The build reads them itself.

## Building

```sh
scripts/om build gatekeeper signed   # the owner's phone: local build, installs with om phone gatekeeper
scripts/om release                   # main → deploy/OpenMob.apk (release), then: fly deploy -a openmob
```

To check a build, run `apksigner verify --print-certs <apk>`: it shows the signer. Then run `aapt2 dump xmltree <apk> --file AndroidManifest.xml`. It must show no `debuggable` attribute, and `usesCleartextTraffic=false` for `release`.

## The guard

The guard keeps a debug or unsigned build from reaching phones through the hosted server by mistake. `scripts/check_release_apk.py <apk>` (the checks are in `openmob/apk_check.py`, standard library only) refuses an APK when:
- its manifest has `android:debuggable` true, or `android:usesCleartextTraffic` true (or either set to something other than a plain `false`);
- a signer (v2/v3 APK Signing Block, or v1 `META-INF/*.RSA|EC|DSA`) has the certificate name `CN=Android Debug`, or it isn't signed at all;
- no release key is pinned (`OPENMOB_RELEASE_SIGNERS` is unset or blank: the guard fails closed), a v2/v3 signer's certificate SHA-256 isn't in `OPENMOB_RELEASE_SIGNERS`, or it has no v2/v3 signature at all (phones check only v2/v3: minSdk 30);
- its package isn't `dev.openmob.companion`.

It prints each signer's certificate SHA-256 (v2/v3). It runs in three places:
- **`om release`** checks the fresh build before copying it to `deploy/OpenMob.apk`; a failing build leaves the old file alone.
- **The Docker build** runs it right after copying `deploy/OpenMob.apk`, so `fly deploy` fails on a debug APK, with a message pointing to `scripts/om release`.
- **The server** checks before serving `/download/openmob.apk` when `OPENMOB_REQUIRE_RELEASE_APK=1` (the Docker image sets it). An unfit APK gets a loud error in the log at start and a 503 for phones, and the Connect page offers no download. Local servers (`om run`, `openmob run`) don't set it and serve debug builds as before.

A self-hosted image that knowingly serves a debug build opts out at build time: `docker build --build-arg OPENMOB_REQUIRE_RELEASE_APK=0 .`. The hosted server never does.

## Pinning the key

The guard accepts only the keys listed in `OPENMOB_RELEASE_SIGNERS` (certificate SHA-256s, comma-separated). The code has no built-in key: with none set, every APK is refused, with a message saying what to set.

- **The hosted server** (`openmob.fly.dev`) pins its release key in `fly.toml` under `[build.args]` (since 2026-10-20, `8b6dcac4…d3b8`, read from the APK prod serves). `fly deploy` passes it to the image build, and the Dockerfile hands it on to the server (`ENV`), so a renamed debug key or any other key is refused at build time and at serving time. `om release` checks against the same value (or `OPENMOB_RELEASE_SIGNERS` from your terminal, if set). A new release key means a new pin: add its SHA-256 there before building with it.
- **A self-hoster** creates their own key and pins it:

  ```sh
  scripts/om keygen                      # prints the new key's SHA256 fingerprint
  (cd android && ./gradlew assembleRelease)   # signs with the key om keygen made (or OPENMOB_SIGNING's file)
  python3 -I scripts/check_release_apk.py android/app/build/outputs/apk/release/app-release.apk
  ```

  The check prints the signer's `SHA-256` (64 hex digits, no colons; `keytool`'s colon-separated fingerprint is the same value), and refuses the APK until that key is pinned. Set it as `OPENMOB_RELEASE_SIGNERS` in your `.env` (with `OPENMOB_REQUIRE_RELEASE_APK=1` and `OPENMOB_APK` pointing at the APK), or pass it to your own image: `docker build --build-arg OPENMOB_RELEASE_SIGNERS=<sha256>[,<sha256>] .` If you host on Fly with this repository's `fly.toml`, replace the pin under `[build.args]` (and the app name and `OPENMOB_PUBLIC_URL`): the one there only accepts the hosted server's key.
