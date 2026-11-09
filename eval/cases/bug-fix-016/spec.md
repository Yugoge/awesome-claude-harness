# Bug-Fix Eval Case 016: Missing trailing-slash redirect causes 404 cascade

## Symptom
Users hitting `https://app.example.com/dashboard` (no trailing slash) get a
404 from the edge proxy. The application internally only registers
`/dashboard/` (with trailing slash). Analytics show ~7% of organic-search
traffic lands on the slash-less variant and bounces.

## Reproduction
1. `curl -i https://app.example.com/dashboard` returns 404.
2. `curl -i https://app.example.com/dashboard/` returns 200.
3. The frontend router (Next.js) generates trailing-slash URLs internally,
   but external links and email templates use the slash-less form.

## Suspected Location
`/workspace/sample-app/deploy/nginx/site.conf:42` lacks a
`rewrite ^([^.]*[^/])$ $1/ permanent;` rule. The frontend's `next.config.js`
has `trailingSlash: true` but the edge proxy never normalizes incoming
requests, so any external link without the slash hits a literal mismatch.

## Expected Behavior
A request without a trailing slash on a non-file path issues a 301 to the
slashed variant. The frontend never sees the slash-less form. Analytics
bounce rate from external links drops back to baseline.

## Acceptance
- Add the rewrite rule to the nginx config (skip rewrite for paths
  containing a `.` so static assets are not affected).
- A bash test using `curl -I` asserts `/dashboard` returns 301 and the
  `Location:` header is `/dashboard/`.
- Update the email-template builder (`src/email/links.py:18`) to also emit
  trailing-slash URLs as a defense in depth.
