class AnswerOption {
  const AnswerOption({required this.id, required this.text});
  final String id;
  final String text;
}

class QuestionPreview {
  const QuestionPreview({
    required this.id,
    required this.typeCode,
    required this.stem,
    required this.points,
    this.options = const [],
    this.correctAnswer,
    this.rationale,
    this.unsupported = false,
    this.unsupportedReason,
  });

  final String id;
  final String typeCode;
  final String stem;
  final double points;
  final List<AnswerOption> options;
  final String? correctAnswer;
  final String? rationale;
  final bool unsupported;
  final String? unsupportedReason;

  factory QuestionPreview.fromJson(Map<String, dynamic> json) {
    final opts = <AnswerOption>[];
    final rawOpts = json['options'];
    if (rawOpts is List) {
      for (final o in rawOpts) {
        if (o is Map) {
          opts.add(AnswerOption(
            id: o['option_id']?.toString() ?? o['id']?.toString() ?? '',
            text: o['text']?.toString() ?? '',
          ));
        }
      }
    }
    return QuestionPreview(
      id: json['question_id']?.toString() ?? json['id']?.toString() ?? '',
      typeCode: json['question_type_code']?.toString() ?? '',
      stem: json['stem']?.toString() ?? '',
      points: (json['points'] as num?)?.toDouble() ?? 0,
      options: opts,
      correctAnswer: json['correct_answer_preview']?.toString(),
      rationale: json['rationale']?.toString(),
      unsupported: json['unsupported'] == true,
      unsupportedReason: json['unsupported_reason']?.toString(),
    );
  }
}

class QualityIssue {
  const QualityIssue({required this.code, required this.message, this.severity = false});
  final String code;
  final String message;
  final bool severity;
}

class QuizDraft {
  const QuizDraft({
    required this.taskId,
    required this.title,
    required this.questions,
    this.instructions,
    this.qualityIssues = const [],
    this.status = 'DRAFT',
    this.snapshotId,
    this.snapshotHash,
  });

  final String taskId;
  final String title;
  final String? instructions;
  final List<QuestionPreview> questions;
  final List<QualityIssue> qualityIssues;
  final String status;

  /// Immutable snapshot the teacher is approving (server-issued; required for approval).
  final String? snapshotId;
  final String? snapshotHash;

  factory QuizDraft.fromJson(Map<String, dynamic> json) {
    final qs = <QuestionPreview>[];
    final rawQ = json['questions'] ?? json['preview']?['questions'];
    if (rawQ is List) {
      for (final q in rawQ) {
        if (q is Map) qs.add(QuestionPreview.fromJson(Map<String, dynamic>.from(q)));
      }
    }
    final issues = <QualityIssue>[];
    final rawIssues = json['quality_issues'] ?? json['quality_report']?['issues'];
    if (rawIssues is List) {
      for (final i in rawIssues) {
        if (i is Map) {
          issues.add(QualityIssue(
            code: i['code']?.toString() ?? '',
            message: i['message']?.toString() ?? '',
            severity: i['severity'] == 'error' || i['blocking'] == true,
          ));
        }
      }
    }
    return QuizDraft(
      taskId: json['task_id']?.toString() ?? '',
      title: json['title']?.toString() ?? json['name']?.toString() ?? 'اختبار',
      instructions: json['instructions']?.toString(),
      questions: qs,
      qualityIssues: issues,
      status: json['status']?.toString() ?? 'DRAFT',
      snapshotId: json['snapshot_id']?.toString(),
      snapshotHash: json['snapshot_hash']?.toString(),
    );
  }
}

class PublishStatus {
  const PublishStatus({
    required this.taskId,
    required this.state,
    this.moodleQuizId,
    this.message,
  });

  final String taskId;
  final String state;
  final int? moodleQuizId;
  final String? message;
}
