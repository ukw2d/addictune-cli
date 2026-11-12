# at-de2: distinguish application authentication failures

Status: current

## Goal and evidence
AudioAddict rejected the SDK's application Basic identity with HTTP 401 and `WWW-Authenticate: Basic`, before validating account credentials. SDK 0.4.3 classifies it as a member authentication error; the CLI blames the password and clears saved credentials. Identity already lives in one `_APP_AUTH` constant.

## Scope and ownership
SDK `AuthAPI.login` owns the `member_sessions` Basic challenge boundary. Raise a distinct public application-authentication error (an API error with status 401, not an account auth error), only when that endpoint responds 401 with a Basic challenge; do not display upstream body or credentials. Existing 422, ordinary 401/403 and other endpoints keep their behavior. The CLI owns text and reports the affected network and HTTP status in both the login form and silent recovery; it states that the account credentials could not be checked, without claiming whether they are valid. Stored credentials remain on application rejection; confirmed credential errors retain existing behavior. No new persistent data, configuration, endpoint, or background work.

## Integration and failure
User explicitly authorized SDK 0.4.4 publication and CLI 0.3.2 hotfix release. CLI must require SDK >=0.4.4 and lock the published PyPI artifact; no sibling path dependency. Independently review SDK before irreversible publication and CLI before committing/pushing/tagging. Verify all four installer builds and checksums before publishing the GitHub beta release. A Basic challenge proves application HTTP authentication failed at this endpoint, not whether the account password is valid or why the challenge occurred. Unrecognized challenges retain existing behavior. No raw remote errors are displayed in the UI.

## Acceptance and validation
Tests cover real mocked HTTP 401 Basic challenge with status, ordinary 401/403 and 422, both CLI UI paths, stored credentials retained for application rejection and removed on account failure, and network-specific names. Test through actual SDK and CLI integration. Run focused tests, both projects' gates and builds; independently review complete cross-repository diffs before completion. Rollback by reverting SDK and CLI changes together.
