# Bug-Fix Eval Case 004: useEffect missing dependency causes stale data fetch

## Symptom
The `OrderDetailsPage` only ever shows the order that was first opened in the
session. Clicking another order from the sidebar updates the URL and the
`orderId` route param, but the rendered details remain those of the original
order until a hard page reload.

## Reproduction
1. Navigate to `/orders/o_1001` and confirm details render for o_1001.
2. Click sidebar entry `o_1002` — URL updates to `/orders/o_1002`.
3. Order details on screen still show o_1001 (title, total, line items).
4. Hard-refresh the page; details now correctly show o_1002.

## Suspected Location
`/workspace/sample-app/src/pages/OrderDetailsPage.tsx:55` declares
`useEffect(() => { fetchOrder(orderId).then(setOrder); }, [])` with an empty
dependency array, so the fetch only fires on first mount and never re-runs
when `orderId` changes.

## Expected Behavior
When `orderId` changes, the page refetches and re-renders with the new order.
Loading and error states are honored on each transition.

## Acceptance
- Switching between two order IDs without reload renders the correct details
  for each in turn.
- Add `orderId` to the effect's dependency array.
- ESLint plugin `react-hooks/exhaustive-deps` runs clean (was previously
  disabled at file level — re-enable it).
