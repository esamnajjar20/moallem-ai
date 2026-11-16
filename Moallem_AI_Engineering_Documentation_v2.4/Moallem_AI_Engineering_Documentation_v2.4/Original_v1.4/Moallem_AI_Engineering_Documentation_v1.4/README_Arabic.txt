Moallem AI Agent — Engineering Documentation Package v1.3

Contents:
1) Original_Reports/: the original reports 01–21, unchanged.
2) Correction_Addendum/: specification correction and terminology addendum v1.1.
3) Architecture_Decisions/: ADR Register v1.0.
4) Data_Model/: ERD and Data Dictionary v1.0, with five diagram source files and rendered diagram PNGs.
5) Moodle_API_Matrix/: Moodle API capability matrix v1.0 in Excel and JSON, plus its usage notes.

Important status:
- The ERD/Data Dictionary is a proposed logical baseline for technical/product review.
- The source reports identify the core entities and design principles, but do not provide a complete physical schema or final column definitions.
- Column details, constraints, indexes and some tables are proposals to close that gap; they are not approved migrations.
- No statement in this package proves that the backend, database schema, Moodle integration, or operational controls have been implemented or tested.
- Before production migrations, approve identity/session design, primary-key strategy, role/permission matrix, tenant isolation, Moodle site sharing, retention, secrets management, and relevant ADRs.

Data model file:
Data_Model/Moallem_AI_ERD_Data_Dictionary_v1.0.docx

Moodle API matrix status:
- The matrix contains 246 function/capability records and 13 feature-gap records.
- Historical MoodleDocs entries are marked for live verification; Moodle 5.3 additions/updates are marked separately.
- The matrix does not prove that functions are enabled on the university Moodle site. Verify live API documentation, service membership, permissions, parameters, and staging behavior.
