# Plan: API route cleanup

## Goal
Remove legacy v1 routes. The new v2 router handles all endpoints.

## Required changes
- Remove `/api/v1/users` route handler
- Remove `/api/v1/posts` route handler
- Drop `legacy_router` import from `app.py`
- Remove the `v1_compat` middleware — no longer needed
- Add v2 route tests

## Must NOT exist after this change
- `/api/v1/users` must not appear in any route registration
- `/api/v1/posts` must not appear in any route registration
- `legacy_router` should not be imported
