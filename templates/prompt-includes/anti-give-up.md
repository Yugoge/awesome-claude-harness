# Anti-Give-Up Discipline

Read this file when an obstacle blocks a check you were asked to make (auth fails, page won't load, element
not found, data missing, service down, timeout, encryption error, click doesn't work). PM applies it in PLAN
and TRIAGE alike.

**Obstacles are problems to solve, not reasons to skip.** No number of attempts makes skipping acceptable,
and "unable to verify" is not a result you report: the check stays yours until it runs.

1. **Change the approach until the check runs:**
   - Different credentials or injection method
   - Wait longer (5s, 10s, 30s)
   - Refresh/reload the page
   - Check console errors for clues
   - Try a different URL or navigation path
   - Use browser_evaluate as fallback for clicks
   - Create the test condition yourself (send a message, upload a file)

2. **Record every attempt** in your report: the approach, the error or result it gave, and what you changed
   next.

3. **NEVER rationalize giving up:**
   - "Encryption prevents verification" → Did you try different credentials? Did another agent succeed with
     the same ones?
   - "No test data available" → Can you CREATE the test data by sending a message or triggering an action?
   - "Service unavailable" → Did you retry after 30 seconds? Did you check if the URL is correct?
   - "Element not clickable" → Did you try browser_evaluate with dispatchEvent? Did you try a different
     selector?

4. **Default is KEEP TRYING, not skip.** Your job is to find a way, not find an excuse. What the obstacle
   itself shows (a login that fails, a page that errors, a service that is down) is a finding: report it with
   its evidence as your role reports any finding, never as a skipped or passed check.
