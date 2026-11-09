# Bug-Fix Eval Case 018: OAuth scope mismatch — frontend asks `read`, backend expects `read:profile`

## Symptom
Login via the OAuth provider succeeds (user is redirected back with a
code), the backend exchanges the code for a token, but every subsequent
call to `/api/v1/me` returns HTTP 403 with body
`{"error": "insufficient_scope", "required": "read:profile"}`. Users see a
permanent "Failed to load your profile" toast and cannot use the app.

## Reproduction
1. Click "Sign in with Provider" on the login page.
2. Approve the consent screen (which only mentions `read`).
3. Land back on `/dashboard`; profile sidebar shows error toast.
4. Backend log shows token introspection returns `scope: "read"` but the
   route's authorization decorator expects `read:profile`.

## Suspected Location
The frontend OAuth init at
`/workspace/sample-app/src/auth/oauth_init.ts:14` sets `scope=read` in the
authorization URL. The backend at
`/workspace/sample-app/src/api/middleware/scopes.py:22` declares the
required scope for `/api/v1/me` as `read:profile`. The two have drifted —
the backend was tightened in a recent PR without updating the frontend.

## Expected Behavior
The frontend requests the union of all scopes the app needs (at minimum
`read:profile` and `read:org`). The consent screen lists those scopes. The
backend route succeeds.

## Acceptance
- Update the frontend OAuth init to request `read:profile read:org` (or
  the documented full scope set, whichever is current).
- Add a shared `scopes.ts` constants module imported by both the OAuth
  init and a backend manifest, so future drift is impossible.
- A Playwright test runs the full login flow and asserts the profile
  sidebar loads, no 403 in the network log.
