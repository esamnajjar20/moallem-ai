# Moodle Staging Validation Checklist — Moallem AI MVP

> لا تسجل أي سر أو token في ملف الأدلة. استخدم identifiers منقحة ومكاناً آمناً لتخزين النتائج.

## Site profile
- [ ] base URL verified over HTTPS and allowlisted
- [ ] Moodle version and build recorded
- [ ] REST protocol enabled and tested
- [ ] External service name and function allowlist recorded
- [ ] Teacher test user and course membership recorded
- [ ] Role/capability snapshot captured
- [ ] Rate limits/timeouts and reverse proxy behavior documented

## Read path
- [ ] list teacher courses: parameters and response captured
- [ ] get course contents: sections/modules visibility checked
- [ ] file discovery/download: permissions and file areas checked
- [ ] pagination, hidden courses, deleted/archived modules tested
- [ ] expired/revoked token behavior captured

## Quiz write path — release blocker
- [ ] create quiz shell/settings operation confirmed
- [ ] create/find question category operation confirmed
- [ ] create question operation confirmed for every MVP question type
- [ ] add question/slot to quiz operation confirmed
- [ ] ordering/marks/randomization behavior captured
- [ ] read quiz back and verify settings/questions
- [ ] duplicate request behavior and external idempotency strategy tested
- [ ] timeout-after-success reconciliation tested

## Evidence record (one per operation)
- test_id; date/time; site version/build; service name; function/plugin endpoint; role; required capability; sanitized request; sanitized response; expected result; actual result; latency; error class; evidence location; tester; status.

## Exit
- [ ] no Moodle write feature is marked SUPPORTED without passing evidence
- [ ] all mappings versioned and attached to adapter contract tests
- [ ] support matrix specifies exact tested Moodle version/role/configuration
