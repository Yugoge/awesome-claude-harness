# Bug-Fix Eval Case 006: Stale closure in event handler reads outdated counter

## Symptom
The `<RateLimitedButton />` component is supposed to disable itself after 3
clicks within a 10-second window. Instead, after the 3rd click it never
re-enables, and the displayed remaining-clicks counter freezes at the value
captured on first render (`3 left`).

## Reproduction
1. Render `<RateLimitedButton onSubmit={...} maxClicks={3} windowMs={10000} />`.
2. Click rapidly 5 times.
3. UI shows `3 left` for all 5 clicks; the underlying `onSubmit` fires every
   time despite the rate-limit logic.

## Suspected Location
`/workspace/sample-app/src/hooks/useRateLimit.ts:42` defines
`const handleClick = useCallback(() => { if (count < max) onSubmit(); }, [])`
with an empty dependency list, so `count` is captured at the value `0` from
first render and never updated, defeating the limit check.

## Expected Behavior
After `maxClicks` clicks within `windowMs`, the button is disabled and the
counter ticks down accurately. After the window elapses, the counter resets
and the button re-enables.

## Acceptance
- An RTL test with `jest.useFakeTimers()` clicks 4 times in 1s and asserts
  only 3 `onSubmit` calls fire and the button disables on click 4.
- After advancing 10s, the button re-enables and counter resets to `3 left`.
- The `useCallback` dependency list correctly includes `count` and `max` (or
  the implementation switches to a ref-based counter to avoid re-binding).
