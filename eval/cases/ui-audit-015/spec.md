# UI-Audit Eval Case ui-audit-015: Social network profile + settings

## App Description
Public profile and personal-settings surface for the same social network as
ui-audit-014, also React Native Web. Primary user is a member curating
their public identity (avatar, bio, pinned posts) and tuning privacy
settings. The profile page must render correctly for anonymous visitors
as well, so audit captures both authenticated and anonymous states.

## Routes to Audit
- /profile/sample-user
- /profile/sample-user/posts
- /profile/sample-user/media
- /profile/sample-user/likes
- /settings/profile
- /settings/privacy
- /settings/notifications

## Audit Focus
Avatar upload affordance and crop UI, bio character-count feedback,
pinned-post visual emphasis, privacy-toggle clarity (current state vs
new state), follower-count rendering at large numbers (1.2K, 3.4M), and
parity of profile rendering between authenticated and anonymous viewers.

## Acceptance
- 7 routes captured at both viewports (>= 14 shots).
- Privacy toggles announce current state to screen readers.
- Bio character-count is visible and updates in real time.
- Avatar crop UI keyboard-operable.
- Final verdict PASS or WARNING.
