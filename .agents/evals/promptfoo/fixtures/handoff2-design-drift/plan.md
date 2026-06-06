# Plan: Consolidate API surface to v2

## Goal
Migrate all consumers to v2. Remove v1 compatibility shim.

## Required changes
- Add v2 route handlers for `/users` and `/posts`
- Remove `v1_compat` middleware

## Explicitly out of scope
- Do not add rate limiting (planned for P5)
- Do not add pagination to v2 routes (separate ticket)
