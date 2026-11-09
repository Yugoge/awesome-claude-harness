# UI-Audit Eval Case ui-audit-014: Social network feed + composer

## App Description
Interest-graph social network built on React Native Web (one codebase for
mobile and web) with a Relay GraphQL backend. Primary user is a returning
member scrolling a chronological feed, posting media, and reacting to
others' posts. Audit covers the web build only; the native build has its
own test suite.

## Routes to Audit
- /home
- /home/foryou
- /home/following
- /compose
- /post/abc123
- /notifications
- /messages

## Audit Focus
Infinite-scroll footer accessibility (must not strand keyboard users),
compose-modal media upload affordances, optimistic-UI feedback for like
and repost actions, notification dot contrast, and sticky composer
keyboard behaviour on iOS Safari (an historical regression vector).

## Acceptance
- 7 routes captured at both viewports (>= 14 shots).
- Like and repost actions show within 100ms optimistic feedback.
- Compose modal traps focus and supports Escape to dismiss with confirmation.
- ui-state-matrix shows >= 6 of 7 states present on action buttons.
- Final verdict PASS or WARNING.
