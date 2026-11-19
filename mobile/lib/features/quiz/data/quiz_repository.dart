import 'dart:math';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_exception.dart';
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

  /// Waits (polling) until the generated draft is ready for approval.
  Future<QuizDraft> awaitDraft(
    String taskId, {
    Duration interval = const Duration(seconds: 2),
    Duration timeout = const Duration(minutes: 3),
  });

  /// Waits (polling) for the worker to publish and for Moodle verification to finish.
  Future<PublishStatus> awaitPublishResult(
    String taskId, {
    Duration interval = const Duration(seconds: 2),
    Duration timeout = const Duration(minutes: 3),
  });
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
      snapshotId: '00000000-0000-4000-8000-0000000000a$_seq',
      snapshotHash: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
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
      snapshotId: d.snapshotId,
      snapshotHash: d.snapshotHash,
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
      snapshotId: d.snapshotId,
      snapshotHash: d.snapshotHash,
    );
  }

  @override
  Future<PublishStatus> getPublishStatus(String taskId) async {
    return _publish[taskId] ??
        PublishStatus(taskId: taskId, state: 'APPROVED', message: 'جاهز للنشر عبر الـ Worker');
  }

  @override
  Future<QuizDraft> awaitDraft(
    String taskId, {
    Duration interval = const Duration(seconds: 2),
    Duration timeout = const Duration(minutes: 3),
  }) => getDraft(taskId);

  @override
  Future<PublishStatus> awaitPublishResult(
    String taskId, {
    Duration interval = const Duration(seconds: 2),
    Duration timeout = const Duration(minutes: 3),
  }) async {
    final draft = await getDraft(taskId);
    if (draft.status != 'APPROVED') {
      return PublishStatus(
        taskId: taskId,
        state: draft.status,
        message: 'لم تتم الموافقة على الاختبار بعد (محاكاة)',
      );
    }
    return getVerifiedResult(taskId);
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
        : <String, dynamic>{};
    final preview = content['preview'] is Map
        ? Map<String, dynamic>.from(content['preview'] as Map)
        : content;
    return QuizDraft.fromJson({
      ...preview,
      'task_id': taskId,
      'status': 'AWAITING_APPROVAL',
      'snapshot_id': data['snapshot_id'],
      'snapshot_hash': data['snapshot_hash'],
      'quality_report': data['quality_report'],
    });
  }

  static const _generationFailed = {
    'FAILED',
    'CANCELLED',
    'REJECTED',
    'EXPIRED',
    'NEEDS_INPUT',
    'NEEDS_REVISION',
  };

  Future<String> _taskStatus(String taskId) async {
    final data = await _client.getJson('tasks/$taskId');
    return data['task_status']?.toString() ?? data['status']?.toString() ?? 'UNKNOWN';
  }

  @override
  Future<QuizDraft> awaitDraft(
    String taskId, {
    Duration interval = const Duration(seconds: 2),
    Duration timeout = const Duration(minutes: 3),
  }) async {
    final deadline = DateTime.now().add(timeout);
    while (true) {
      final status = await _taskStatus(taskId);
      if (status == 'AWAITING_APPROVAL') return getDraft(taskId);
      if (_generationFailed.contains(status)) {
        throw ApiException(message: 'تعذر توليد الاختبار ($status)', code: status);
      }
      if (DateTime.now().isAfter(deadline)) {
        throw ApiException(
          message: 'استغرق التوليد وقتاً أطول من المتوقع، حاول لاحقاً',
          code: 'GENERATION_TIMEOUT',
        );
      }
      await Future<void>.delayed(interval);
    }
  }

  static const _publishStopped = {'FAILED', 'CANCELLED', 'EXPIRED', 'NEEDS_RECONCILIATION'};

  @override
  Future<PublishStatus> awaitPublishResult(
    String taskId, {
    Duration interval = const Duration(seconds: 2),
    Duration timeout = const Duration(minutes: 3),
  }) async {
    final deadline = DateTime.now().add(timeout);
    while (true) {
      final status = await _taskStatus(taskId);
      if (status == 'COMPLETED') return getVerifiedResult(taskId);
      if (_publishStopped.contains(status)) {
        return PublishStatus(
          taskId: taskId,
          state: status,
          message: status == 'NEEDS_RECONCILIATION'
              ? 'تعذر التأكد من نتيجة النشر؛ يلزم فحص يدوي قبل إعادة المحاولة'
              : 'لم يكتمل النشر',
        );
      }
      if (DateTime.now().isAfter(deadline)) {
        return PublishStatus(
          taskId: taskId,
          state: status,
          message: 'النشر ما زال قيد التنفيذ، افتح هذه الصفحة لاحقاً',
        );
      }
      await Future<void>.delayed(interval);
    }
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
    final verified = data['verification_status'] == 'VERIFIED';
    return PublishStatus(
      taskId: taskId,
      state: verified ? 'COMPLETED' : 'UNVERIFIED',
      moodleQuizId: int.tryParse(data['external_object_id']?.toString() ?? ''),
      message: verified ? 'تم إنشاء الاختبار والتحقق منه في Moodle' : 'لم يتم التحقق من الاختبار',
    );
  }
}
