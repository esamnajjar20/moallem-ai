# Moodle 5.3 Web Services Delta — Moallem AI

مرجع المقارنة: Moodle 5.3 LTS، تاريخ الإصدار 5 أكتوبر 2026.

| External function / change | What changed | Relevance to Moallem |
|---|---|---|
| `mod_assign_save_overrides` | New web service to create/update assignment overrides. | Supports user/group exceptions for assignment timing/access; requires `mod/assign:manageoverrides`-class permission and approval. |
| `mod_assign_get_overrides` | New web service to retrieve assignment overrides. | Read and verify the effective overrides configured for the assignment. |
| `mod_assign_delete_overrides` | New web service to delete assignment overrides. | Destructive write; require explicit confirmation and post-write verification. |
| `mod_assign_get_submission_status` | Response can include per-marker `markerfeedback` when marking workflow and allocation are configured. | Richer teacher feedback analysis; response parser must tolerate optional field. |
| `mod_forum_set_read_state` | New service sets read/unread state of a forum post for current user. | Minor UX/teacher workflow integration; requires manual mark-as-read setting and capability. |
| `mod_quiz_get_users_in_report` | New service returns users for quiz reports/search and filtering. | Helps teacher-facing report navigation and analytics filters; not quiz creation. |
| `mod_quiz_get_user_quiz_attempts` | Recommended replacement for deprecated `mod_quiz_get_user_attempts` since Moodle 5.1; includes all attempt states. | Use this in new adapters; update old function clients. |
| `gradereport_user_get_grade_items` | Optional `parentcategoryid` is present in Moodle 5.3 response for category grade items. | Response DTO must accept the optional field. |

| Moodle 5.3.1 | 12 November 2026 | Patch-level fixes | إصلاحات H5P offline، رفع الملفات ذات الأسماء الطويلة، حالات واجبات/درجات، completion override، وسلوك API tokens المنتهية أو الملغاة؛ ليست دوال Web Service جديدة. | https://moodledev.io/general/releases/5.3/5.3.1 |

## Implementation notes

- Moodle 5.3 release notes list the new services for assignment overrides, forum read state, and other web service changes.
- The exact identifiers for assignment override endpoints are corroborated in the 5.2.4-to-5.3 upgrade/source comparison.
- The exact quiz report service is documented in the official 5.3 `mod_quiz/UPGRADING.md`.
- Do not treat these additions as available on earlier Moodle versions.
- The service implementation in Core does not automatically mean the function has been included in a custom External Service or granted to a teacher token.

## Sources

- https://moodledev.io/general/releases/5.3
- https://moodledev.io/general/releases/5.3/5.3.1
- https://moodledev.io/versions
- https://github.com/moodle/moodle/blob/main/public/mod/quiz/UPGRADING.md
- https://fossies.org/diffs/moodle/5.2.4_vs_5.3/UPGRADING.md-diff.html
- https://fossies.org/dox/moodle-5.3/classmod__forum_1_1external_1_1set__read__state.html
