import 'dart:math';

import '../../../core/api/api_client.dart';
import '../domain/quiz_models.dart';

abstract class QuizRepository {
  Future<QuizDraft> requestGeneration({
    required String courseId,
    required String connectionId,
    required String title,
    required int questionCount,
    required List<String> questionTypes,
  });
  Future<QuizDraft> getDraft(String taskId);
  Future<void> approve(String taskId, {required String snapshotId, required String snapshotHash});
  Future<void> reject(String taskId, {required String snapshotId, required String snapshotHash, String? reason});
  Future<PublishStatus> getPublishStatus(String taskId);
  Future<PublishStatus> getVerifiedResult(String taskId);
}

String _idempotencyKey() {
  final r = Random.secure();
  final bytes = List<int>.generate(24, (_) => r.nextInt(256));
  return bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
}

class MockQuizRepository implements QuizRepository {
  final Map<String, QuizDraft> _drafts = {};
  final Map<String, PublishStatus> _publish = {};
  int _seq = 0;

  @override
  Future<QuizDraft> requestGeneration({
    required String courseId,
    required String connectionId,
    required String title,
    required int questionCount,
    required List<String> questionTypes,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 700));
    _seq += 1;
    final taskId = 'task-mock-$_seq';
    final types = questionTypes.isEmpty ? ['MULTICHOICE'] : questionTypes;
    final questions = List.generate(questionCount.clamp(1, 10), (i) {
      final t = types[i % types.length];
      if (t == 'TRUEFALSE') {
        return QuestionPreview(
          id: 'q-$i',
          typeCode: 'TRUEFALSE',
          stem: 'عبارة صحيحة رقم ${i + 1} تتعلق بالمقرر $courseId؟',
          points: 1,
          correctAnswer: 'true',
        );
      }
      return QuestionPreview(
        id: 'q-$i',
        typeCode: 'MULTICHOICE',
        stem: 'سؤال اختيار من متعدد رقم ${i + 1}',
        points: 1,
        options: const [
          AnswerOption(id: 'a', text: 'الخيار أ'),
          AnswerOption(id: 'b', text: 'الخيار ب'),
          AnswerOption(id: 'c', text: 'الخيار ج'),
        ],
        correctAnswer: 'الخيار أ',
      );
    });
    final draft = QuizDraft(
      taskId: taskId,
      title: title,
      questions: questions,
      instructions: 'أجب عن جميع الأسئلة',
      qualityIssues: const [
        QualityIssue(code: 'INFO', message: 'مسودة تجريبية (وضع المحاكاة)'),
      ],
      status: 'AWAITING_APPROVAL',
    );
    _drafts[taskId] = draft;
    return draft;
  }

  @override
  Future<QuizDraft> getDraft(String taskId) async {
    final d = _drafts[taskId];
    if (d == null) throw StateError('المسودة غير موجودة');
    return d;
  }

  @override
  Future<void> approve(String taskId, {required String snapshotId, required String snapshotHash}) async {
    final d = await getDraft(taskId);
    _drafts[taskId] = QuizDraft(
      taskId: d.taskId,
      title: d.title,
      instructions: d.instructions,
      questions: d.questions,
      qualityIssues: d.qualityIssues,
      status: 'APPROVED',
    );
  }

  @override
  Future<void> reject(String taskId, {required String snapshotId, required String snapshotHash, String? reason}) async {
    final d = await getDraft(taskId);
    _drafts[taskId] = QuizDraft(
      taskId: d.taskId,
      title: d.title,
      instructions: d.instructions,
      questions: d.questions,
      qualityIssues: d.qualityIssues,
      status: 'REJECTED',
    );
  }

  @override
  Future<PublishStatus> getPublishStatus(String taskId) async {
    return _publish[taskId] ??
        PublishStatus(taskId: taskId, state: 'APPROVED', message: 'جاهز للنشر عبر الـ Worker');
  }

  @override
  Future<PublishStatus> getVerifiedResult(String taskId) async {
    await Future<void>.delayed(const Duration(milliseconds: 400));
    final status = PublishStatus(
      taskId: taskId,
      state: 'COMPLETED',
      moodleQuizId: 9000 + _seq,
      message: 'تم إنشاء الاختبار في Moodle (محاكاة)',
    );
    _publish[taskId] = status;
    return status;
  }
}

/// Aligns with backend OpenAPI: POST /tasks, GET snapshot, POST approvals, GET task/result.
class ApiQuizRepository implements QuizRepository {
  ApiQuizRepository(this._client);
  final ApiClient _client;

  @override
  Future<QuizDraft> requestGeneration({
    required String courseId,
    required String connectionId,
    required String title,
    required int questionCount,
    required List<String> questionTypes,
  }) async {
    final data = await _client.postJson(
      'tasks',
      body: {
        'task_type': 'CREATE_QUIZ',
        'connection_id': connectionId,
        'course_id': courseId,
        'prompt': 'Generate quiz: $title',
        'quiz_spec': {
          'name': title,
          'question_count': questionCount,
          'question_types': questionTypes,
          'language': 'ar',
        },
        'locale': 'ar',
        'client_metadata': {'source_channel': 'ANDROID'},
      },
      headers: {'Idempotency-Key': _idempotencyKey()},
    );
    final taskId = data['task_id']?.toString() ?? '';
    // Draft is produced asynchronously by workers; return a placeholder shell.
    return QuizDraft(
      taskId: taskId,
      title: title,
      questions: const [],
      status: data['task_status']?.toString() ?? 'RECEIVED',
    );
  }

  @override
  Future<QuizDraft> getDraft(String taskId) async {
    final data = await _client.getJson('tasks/$taskId/snapshot');
    final content = data['content'] is Map
        ? Map<String, dynamic>.from(data['content'] as Map)
        : data;
    final preview = content['preview'] is Map
        ? Map<String, dynamic>.from(content['preview'] as Map)
        : content;
    return QuizDraft.fromJson({
      ...preview,
      'task_id': taskId,
      'status': data['status']?.toString() ?? 'AWAITING_APPROVAL',
    });
  }

  @override
  Future<void> approve(String taskId, {required String snapshotId, required String snapshotHash}) async {
    await _client.postJson(
      'tasks/$taskId/approvals',
      body: {
        'snapshot_id': snapshotId,
        'snapshot_hash': snapshotHash,
        'decision': 'APPROVED',
      },
      headers: {'Idempotency-Key': _idempotencyKey()},
    );
  }

  @override
  Future<void> reject(String taskId, {required String snapshotId, required String snapshotHash, String? reason}) async {
    await _client.postJson(
      'tasks/$taskId/approvals',
      body: {
        'snapshot_id': snapshotId,
        'snapshot_hash': snapshotHash,
        'decision': 'REJECTED',
        if (reason != null) 'comment': reason,
      },
      headers: {'Idempotency-Key': _idempotencyKey()},
    );
  }

  @override
  Future<PublishStatus> getPublishStatus(String taskId) async {
    final data = await _client.getJson('tasks/$taskId');
    return PublishStatus(
      taskId: taskId,
      state: data['status']?.toString() ?? data['task_status']?.toString() ?? 'UNKNOWN',
      message: data['message']?.toString(),
    );
  }

  @override
  Future<PublishStatus> getVerifiedResult(String taskId) async {
    final data = await _client.getJson('tasks/$taskId/result');
    return PublishStatus(
      taskId: taskId,
      state: 'COMPLETED',
      moodleQuizId: data['moodle_quiz_id'] as int?,
      message: data['message']?.toString(),
    );
  }
}
