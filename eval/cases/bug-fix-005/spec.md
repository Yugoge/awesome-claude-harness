# Bug-Fix Eval Case 005: CSS overflow clips dropdown menu inside scrollable card

## Symptom
The user-actions dropdown attached to each row of the `<UserTable />` opens
inside the table's scrollable wrapper and gets clipped on the bottom-most
rows: only the top half of the menu is visible, and clicking outside the
clipped area dismisses it before any item can be chosen.

## Reproduction
1. Open `/admin/users` with at least 12 users (force scrolling).
2. Click the kebab menu on the last visible row.
3. Observe the dropdown is cut off at the bottom edge of the scroll
   container; the lower 40% of menu items is unreachable.

## Suspected Location
`/workspace/sample-app/src/components/UserTable.module.css:18` sets
`.scrollWrapper { overflow: hidden; }`. The Radix `<DropdownMenu />` portals
to a child of the wrapper rather than `document.body`, so any portion of the
menu beyond the wrapper's bounds is clipped by `overflow: hidden`.

## Expected Behavior
The dropdown is fully visible regardless of which row spawns it, even at the
bottom of a scrolled list, on both desktop (1280px) and mobile (375px).

## Acceptance
- Dropdown renders fully visible on the last row at both viewports.
- Either set Radix `<DropdownMenu.Portal container={document.body} />` OR
  change `.scrollWrapper` to `overflow: visible` and relocate scroll behavior.
- Visual regression screenshot stored for both viewports.
