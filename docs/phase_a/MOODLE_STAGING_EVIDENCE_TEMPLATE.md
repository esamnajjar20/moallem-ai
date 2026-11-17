# Moodle Staging Evidence Pack — Moallem AI MVP

**Status:** REQUIRED before live Moodle integration  
**Fill this document and place the completed version in `docs/phase_a/MOODLE_STAGING_EVIDENCE.md`**

---

## 1. Site Information

| Field                        | Value |
|-----------------------------|-------|
| Staging URL (HTTPS only)    |       |
| Moodle version + build      |       |
| Last update date            |       |
| Web Services enabled?       | Yes / No |
| REST protocol enabled?      | Yes / No |
| Site shortname / ID         |       |

---

## 2. Teacher Test Account

| Field                              | Value |
|------------------------------------|-------|
| Username / Email                   |       |
| Is the account a Teacher in ≥1 course? | Yes / No |
| Has capability to create quizzes?  | Yes / No |
| Authentication method for WS       | Token / other |
| Token (store securely, do not commit) | (reference only) |

---

## 3. Synthetic Course

| Field                          | Value |
|--------------------------------|-------|
| Course ID / Shortname          |       |
| Contains files (PDF/DOCX/pages)? | Yes / No |
| Approximate file count & size  |       |
| Teacher enrolled as editingteacher? | Yes / No |

---

## 4. Required Web Service Functions (check availability)

- [ ] `core_webservice_get_site_info`
- [ ] `core_enrol_get_users_courses`
- [ ] `core_course_get_contents`
- [ ] `core_course_get_courses_by_field` (if used)
- [ ] Quiz creation functions (`mod_quiz_*` or equivalent)

---

## 5. Manual Verification Checklist

- [ ] Successful login
- [ ] List of teacher courses returned
- [ ] Course content + file metadata readable
- [ ] Account is not student-only

---

## 6. Notes / Limitations

_Record any missing functions, capability gaps, or site-specific constraints here._

---

## 7. Sign-off

| Role            | Name | Date | Signature |
|-----------------|------|------|-----------|
| Moodle Admin    |      |      |           |
| Moallem Owner   |      |      |           |
