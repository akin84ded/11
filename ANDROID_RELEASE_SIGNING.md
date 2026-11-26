# Android release signing and data migration

## Persistent signing key

The Android workflow always produces a debug APK. It produces a release APK signed with a persistent key only when all four GitHub Actions secrets are configured:

- `ANDROID_KEYSTORE_BASE64` — Base64-encoded JKS/PKCS12 keystore file
- `ANDROID_KEYSTORE_PASSWORD` — keystore password
- `ANDROID_KEY_ALIAS` — key alias
- `ANDROID_KEY_PASSWORD` — key password

Create a key once on a trusted computer and keep a protected offline copy:

```bash
keytool -genkeypair -v -keystore prosperity-upload.jks -alias prosperity -keyalg RSA -keysize 2048 -validity 10000
base64 -w 0 prosperity-upload.jks
```

On Windows PowerShell, encode the file with:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("prosperity-upload.jks"))
```

Add the resulting value and the three passwords/alias as repository Actions secrets in GitHub: Settings → Secrets and variables → Actions. Never commit the keystore or put its passwords in source code or chat.

**Important:** this newly created key only establishes a stable signing identity for this and future release builds. It does not match an older debug APK signed with a different temporary key. Do not uninstall the older app until its signing key compatibility is established or its data has been safely exported.

## Backup and restore in the app

Use **Экспорт данных** to save a JSON backup through Android's file picker. It includes local SharedPreferences data such as candidates, holdings, notes, and the quotes cache. Store the file somewhere safe.

Use **Импорт данных** on the destination installation and select the backup. Import asks for confirmation and replaces the current local preferences with the backup contents. Export the destination data first if it also needs to be retained.

## Release checklist

- Configure all four signing secrets and run the Android workflow.
- Verify that the workflow produces both debug and release APKs.
- Keep the keystore and passwords in a secure backup; future releases must use the same key.
- Test installation/update on a spare device before replacing the daily-use installation.
- Test backup, restore, MOEX HTTPS quotes, analysis, and notifications on a real phone.
- Do not claim an update from an older build is safe until the installed APK and new APK signing certificates have been compared.