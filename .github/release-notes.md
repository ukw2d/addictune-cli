**addictune 0.3.0**, an unofficial terminal client for DI.FM and other
AudioAddict radio networks.

What's new since 0.2.1:

- **Error reports.** When something breaks, addictune now sends an anonymous
  report to the developer so bugs get fixed without asking you for logs. It
  never includes your email, password, listen key, account id or stream
  tokens. On by default; turn it off in **Settings → General → Error reports**.
- **Account tier.** Settings → General shows whether you're signed in with a
  Premium or Free account.
- **Free accounts.** Premium streams now stop at once with a "Premium required"
  notice instead of reconnecting for two minutes.
- **Sign out** from the command palette (`Ctrl+P`).
- **Fixed:** playback errors and the debug log could show your listen key.
  If you shared a screenshot or log from an earlier version, regenerate your
  listen key on the station's website.
- **Fixed:** connection failures now say why (DNS, TLS, timeout) instead of a
  bare "Input/output error", and slow connections get more time to start.

Downloads include installers for Apple Silicon and Intel Macs, a Linux x86_64
archive, and a Windows x64 archive. `SHA256SUMS` contains checksums for all four
downloads.

This is beta software: features and behavior may change between releases.

Linux requires PortAudio (`libportaudio2` on Debian/Ubuntu). The binaries are not
code-signed or notarized, so macOS or Windows may display a security warning.

See the [README](https://github.com/ukw2d/addictune-cli#-install) for installation
and account requirements. Please report bugs through
[GitHub Issues](https://github.com/ukw2d/addictune-cli/issues).
