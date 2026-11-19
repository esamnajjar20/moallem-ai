import '../../../core/api/api_client.dart';
import '../../../core/api/api_exception.dart';
import '../domain/course.dart';

abstract class MoodleRepository {
  Future<MoodleConnectionStatus> connectionStatus();
  Future<MoodleConnectionStatus> connect({
    required String siteUrl,
    required String token,
  });
  Future<List<CourseSummary>> listCourses();
}

class MockMoodleRepository implements MoodleRepository {
  bool _connected = false;

  @override
  Future<MoodleConnectionStatus> connectionStatus() async {
    return MoodleConnectionStatus(
      connected: _connected,
      siteUrl: _connected ? 'https://moodle.staging.example' : null,
      connectionId: _connected ? 'conn-mock-1' : null,
    );
  }

  @override
  Future<MoodleConnectionStatus> connect({
    required String siteUrl,
    required String token,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 500));
    if (!siteUrl.startsWith('https://')) {
      throw StateError('يجب أن يكون رابط Moodle عبر HTTPS');
    }
    if (token.trim().length < 8) {
      throw StateError('رمز الخدمة غير صالح');
    }
    _connected = true;
    return connectionStatus();
  }

  @override
  Future<List<CourseSummary>> listCourses() async {
    if (!_connected) return [];
    return const [
      CourseSummary(id: '101', title: 'الرياضيات — الصف السابع', shortName: 'MATH7'),
      CourseSummary(id: '102', title: 'العلوم — الصف السابع', shortName: 'SCI7'),
      CourseSummary(id: '103', title: 'اللغة العربية', shortName: 'AR'),
    ];
  }
}

/// Talks to the endpoints that exist today: `GET /courses?connection_id=`.
/// There is no connection-management endpoint yet (gap CONN-API), so the connection UUID
/// comes from `--dart-define=MOALLEM_CONNECTION_ID` and [connect] is unavailable.
class ApiMoodleRepository implements MoodleRepository {
  ApiMoodleRepository(this._client, {this.connectionId});

  final ApiClient _client;
  final String? connectionId;

  @override
  Future<MoodleConnectionStatus> connectionStatus() async {
    final id = connectionId;
    if (id == null || id.isEmpty) {
      return const MoodleConnectionStatus(connected: false);
    }
    return MoodleConnectionStatus(connected: true, connectionId: id);
  }

  @override
  Future<MoodleConnectionStatus> connect({
    required String siteUrl,
    required String token,
  }) async {
    throw ApiException(
      message: 'ربط Moodle من التطبيق غير متاح بعد؛ اضبط MOALLEM_CONNECTION_ID',
      code: 'CONNECTION_API_UNAVAILABLE',
    );
  }

  @override
  Future<List<CourseSummary>> listCourses() async {
    final id = connectionId;
    if (id == null || id.isEmpty) return [];
    final courses = <CourseSummary>[];
    String? cursor;
    // Follow pagination; bounded so a misbehaving server cannot loop forever.
    for (var page = 0; page < 20; page++) {
      final data = await _client.getJson('courses', query: {
        'connection_id': id,
        'limit': '100',
        if (cursor != null) 'cursor': cursor,
      });
      final items = data['items'];
      if (items is List<dynamic>) {
        courses.addAll(
          items.whereType<Map<String, dynamic>>().map(CourseSummary.fromJson),
        );
      }
      cursor = data['next_cursor']?.toString();
      if (data['has_more'] != true || cursor == null) break;
    }
    return courses;
  }
}
