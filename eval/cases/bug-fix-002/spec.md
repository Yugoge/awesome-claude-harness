# Bug-Fix Eval Case 002: Null prop access crashes UserCard render

## Symptom
The `UserCard` component crashes the entire profile page with
`TypeError: Cannot read properties of null (reading 'avatarUrl')` whenever the
backend returns a user without an `avatar` object. Sentry shows ~1.4k events
per day, all from `/profile/[id]` routes for users who never uploaded an
avatar.

## Reproduction
1. Visit `/profile/u_no_avatar` in dev (seeded user with `avatar = null`).
2. Observe the React error overlay; the page renders blank.
3. Network tab shows the API succeeded with `{ id: "u_no_avatar", avatar: null }`.

## Suspected Location
`/workspace/sample-app/src/components/UserCard.tsx:38` directly destructures
`const { avatarUrl } = user.avatar;` with no null guard. The TypeScript type
declares `avatar` as required, but the API contract permits `null` for
unverified accounts.

## Expected Behavior
When `user.avatar` is null, render a `<DefaultAvatar />` fallback and continue
rendering the rest of the card (name, bio, joined date) without throwing.

## Acceptance
- Visiting `/profile/u_no_avatar` renders without a React error.
- A new RTL test asserts the fallback avatar appears when `user.avatar = null`.
- TypeScript types in `types/User.ts` are corrected so `avatar` is
  `Avatar | null`, preventing the regression at compile time.
