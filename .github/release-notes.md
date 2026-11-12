**addictune 0.3.2**, an authentication error-reporting hotfix for the unofficial
terminal client for DI.FM and other AudioAddict radio networks.

## Fixed since 0.3.1

- **Application rejection no longer blames your password.** With SDK 0.4.4,
  a member-session HTTP 401 Basic challenge is distinguished from invalid
  account credentials. The login form and automatic sign-in report the
  affected network and HTTP status, for example:
  “DI.FM rejected application authentication (HTTP 401). Your account
  credentials could not be checked.”
- **Saved credentials are preserved** on application rejection, rather than
  deleted and followed by a request for another password.
- Ordinary invalid-credential handling remains unchanged. Remote response
  bodies are not displayed for application rejection.

The SDK's application identity remains a single constant for future rotation.
It is undocumented and could be revoked again. No password change or account
migration is required for this update.

Downloads include Apple Silicon and Intel macOS installers, a Linux x86_64
archive, and a Windows x64 archive. `SHA256SUMS` contains their checksums.

This is beta software. Linux requires PortAudio (`libportaudio2` on
Debian/Ubuntu). Binaries are not code-signed or notarized, so macOS or Windows
may display a security warning.

See the [README](https://github.com/ukw2d/addictune-cli#-install) for installation
and account requirements, and [GitHub Issues](https://github.com/ukw2d/addictune-cli/issues)
to report bugs.
