import '../../../core/api/api_client.dart';
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

class ApiMoodleRepository implements MoodleRepository {
  ApiMoodleRepository(this._client);

  final ApiClient _client;

  @override
  Future<MoodleConnectionStatus> connectionStatus() async {
    try {
      final data = await _client.getJson('moodle/connection');
      return MoodleConnectionStatus(
        connected: data['status'] == 'ACTIVE',
        siteUrl: data['site_url']?.toString(),
        connectionId: data['connection_id']?.toString(),
      );
    } catch (_) {
      return const MoodleConnectionStatus(connected: false);
    }
  }

  @override
  Future<MoodleConnectionStatus> connect({
    required String siteUrl,
    required String token,
  }) async {
    final data = await _client.postJson('moodle/connection', body: {
      'site_url': siteUrl,
      'token': token,
    });
    return MoodleConnectionStatus(
      connected: true,
      siteUrl: data['site_url']?.toString() ?? siteUrl,
      connectionId: data['connection_id']?.toString(),
    );
  }

  @override
  Future<List<CourseSummary>> listCourses() async {
    final data = await _client.getJson('courses');
    final items = data['items'] ?? data['courses'] ?? data['data'];
    if (items is! List) return [];
    return items
        .whereType<Map>()
        .map((e) => CourseSummary.fromJson(Map<String, dynamic>.from(e)))
        .toList();
  }
}
