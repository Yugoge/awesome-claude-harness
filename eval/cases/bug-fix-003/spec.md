# Bug-Fix Eval Case 003: Missing key prop in todo list triggers React reconciler warnings

## Symptom
React DevTools console floods with
`Warning: Each child in a list should have a unique "key" prop. Check the
render method of TodoList.` whenever the user adds or removes a todo. Worse,
checking off items occasionally toggles the wrong row because React reuses DOM
nodes by index.

## Reproduction
1. Open `/todos` in the dev build with React StrictMode enabled.
2. Add three todos rapidly, then check the middle one.
3. Observe a different todo's checkbox toggling on screen than the one
   clicked; console shows the key warning emitted N times per render.

## Suspected Location
`/workspace/sample-app/src/components/TodoList.tsx:24` renders
`{todos.map((t) => <TodoItem todo={t} />)}` without supplying `key={t.id}`.
Each Todo already has a stable UUID coming from the API.

## Expected Behavior
Every list item carries `key={t.id}`, the warning disappears, and toggling a
todo always updates exactly that todo's checkbox.

## Acceptance
- Console shows zero `key` prop warnings during a full add/check/delete cycle.
- An RTL test mounts 5 todos, toggles the third, and asserts only the third
  item's `aria-checked` changes.
- ESLint rule `react/jsx-key` is enabled at `error` severity in
  `.eslintrc.json` to prevent regression.
