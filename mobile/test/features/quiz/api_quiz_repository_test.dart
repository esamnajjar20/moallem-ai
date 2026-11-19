import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:moallem_mobile/core/api/api_client.dart';
import 'package:moallem_mobile/core/api/api_exception.dart';
import 'package:moallem_mobile/core/app_config.dart';
import 'package:moallem_mobile/features/quiz/data/quiz_repository.dart';

const _hash = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
const _snapshotId = '00000000-0000-4000-8000-0000000000d1';

ApiQuizRepository _repo(MockClientHandler handler) => ApiQuizRepository(
      ApiClient(
        config: AppConfig(apiBaseUrl: Uri.parse('https://api.example.com/api/v1')),
        httpClient: MockClient(handler),
      ),
    );

http.Response _json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

void main() {
  test('create-task payload matches the API contract', () async {
    late Map<String, dynamic> body;
    late http.Request request;
    final repo = _repo((req) async {
      request = req;
      body = jsonDecode(req.body) as Map<String, dynamic>;
      return _json({'task_id': 't1', 'task_status': 'RECEIVED'}, 202);
    });
    await repo.requestGeneration(
      courseId: '12',
      connectionId: '00000000-0000-4000-8000-0000000000c1',
      title: 'اختبار',
      questionCount: 5,
      questionTypes: ['MULTICHOICE'],
    );
    expect(body['task_type'], 'CREATE_QUIZ');
    expect(body['connection_id'], '00000000-0000-4000-8000-0000000000c1');
    expect(body['course_id'], '12');
    expect((body['quiz_spec'] as Map)['question_count'], 5);
    expect(request.headers['Idempotency-Key'], isNotEmpty);
  });

  test('awaitDraft polls until AWAITING_APPROVAL and returns snapshot ids', () async {
    var polls = 0;
    final repo = _repo((req) async {
      if (req.url.path.endsWith('/snapshot')) {
        return _json({
          'snapshot_id': _snapshotId,
          'snapshot_hash': _hash,
          'content': {
            'preview': {
              'title': 'اختبار',
              'questions': [
                {'question_id': 'q1', 'question_type_code': 'TRUEFALSE', 'stem': 's', 'points': 1},
              ],
            },
          },
          'quality_report': {'issues': []},
        });
      }
      polls += 1;
      return _json({'task_status': polls < 3 ? 'DRAFTING' : 'AWAITING_APPROVAL'});
    });
    final draft = await repo.awaitDraft('t1', interval: Duration.zero);
    expect(polls, 3);
    expect(draft.snapshotId, _snapshotId);
    expect(draft.snapshotHash, _hash);
    expect(draft.questions, hasLength(1));
  });

  test('awaitDraft fails fast when generation failed', () async {
    final repo = _repo((_) async => _json({'task_status': 'FAILED'}));
    expect(
      repo.awaitDraft('t1', interval: Duration.zero),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'FAILED')),
    );
  });

  test('approve sends the server snapshot id and hash', () async {
    late Map<String, dynamic> body;
    final repo = _repo((req) async {
      body = jsonDecode(req.body) as Map<String, dynamic>;
      return _json({'approval_id': 'a1'}, 201);
    });
    await repo.approve('t1', snapshotId: _snapshotId, snapshotHash: _hash);
    expect(body['decision'], 'APPROVED');
    expect(body['snapshot_id'], _snapshotId);
    expect(body['snapshot_hash'], _hash);
  });

  test('publish result is COMPLETED only after server verification', () async {
    final repo = _repo((req) async {
      if (req.url.path.endsWith('/result')) {
        return _json({'external_object_id': '9001', 'verification_status': 'VERIFIED'});
      }
      return _json({'task_status': 'COMPLETED'});
    });
    final result = await repo.awaitPublishResult('t1', interval: Duration.zero);
    expect(result.state, 'COMPLETED');
    expect(result.moodleQuizId, 9001);
  });

  test('NEEDS_RECONCILIATION is surfaced, never shown as success', () async {
    final repo = _repo((_) async => _json({'task_status': 'NEEDS_RECONCILIATION'}));
    final result = await repo.awaitPublishResult('t1', interval: Duration.zero);
    expect(result.state, 'NEEDS_RECONCILIATION');
    expect(result.moodleQuizId, isNull);
  });
}
