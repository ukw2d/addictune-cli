**addictune 0.3.1**, an authentication hotfix for the unofficial terminal client
for DI.FM and other AudioAddict radio networks.

## Fixed since 0.3.0

- **Sign-in restored.** Requires `addictune-sdk>=0.4.3`, which replaces the
  application authentication identity rejected by AudioAddict's API gateway.
  The gateway rejection could previously appear as “Invalid email or password”
  even when the account credentials were correct.
- SDK session creation was verified on DI.FM, RadioTunes, ROCKRADIO, JAZZRADIO,
  Classical Radio and ZenRadio, plus an authenticated DI.FM member request.

No account migration or password change is needed. This release restores login;
it does not yet change the UI's authentication error classification. The API's
application identity is undocumented and could be revoked again.

Downloads include Apple Silicon and Intel macOS installers, a Linux x86_64
archive, and a Windows x64 archive. `SHA256SUMS` contains their checksums.

This is beta software. Linux requires PortAudio (`libportaudio2` on
Debian/Ubuntu). Binaries are not code-signed or notarized, so macOS or Windows
may display a security warning.

See the [README](https://github.com/ukw2d/addictune-cli#-install) for installation
and account requirements, and [GitHub Issues](https://github.com/ukw2d/addictune-cli/issues)
to report bugs.
