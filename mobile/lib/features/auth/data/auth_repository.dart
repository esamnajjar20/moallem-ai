import '../../../core/api/api_client.dart';
import '../domain/session.dart';

/// Auth boundary. Real Auth0 PKCE is out of process for the shell;
/// [MockAuthRepository] enables offline Vertical Slice demos.
abstract class AuthRepository {
  Future<TeacherSession?> restoreSession();
  Future<TeacherSession> login({required String email, required String password});
  Future<void> logout();
}

class MockAuthRepository implements AuthRepository {
  TeacherSession? _session;

  @override
  Future<TeacherSession?> restoreSession() async => _session;

  @override
  Future<TeacherSession> login({
    required String email,
    required String password,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 400));
    if (email.trim().isEmpty) {
      throw StateError('البريد مطلوب');
    }
    _session = TeacherSession(
      userId: 'user-mock-1',
      displayName: email.split('@').first,
      accessToken: 'mock-access-token',
      membershipId: '00000000-0000-4000-8000-000000000001',
      tenantId: '00000000-0000-4000-8000-0000000000aa',
      moodleConnected: false,
    );
    return _session!;
  }

  @override
  Future<void> logout() async {
    _session = null;
  }
}

/// Placeholder for future Auth0 + backend subject mapping.
class ApiAuthRepository implements AuthRepository {
  ApiAuthRepository(this._client);

  final ApiClient _client;

  @override
  Future<TeacherSession?> restoreSession() async {
    // Token restore would use secure storage + /me
    return null;
  }

  @override
  Future<TeacherSession> login({
    required String email,
    required String password,
  }) async {
    // Real flow: Auth0 SDK → access token → GET /api/v1/me
    final me = await _client.getJson('me');
    return TeacherSession(
      userId: me['user_id']?.toString() ?? '',
      displayName: me['display_name']?.toString() ?? email,
      accessToken: _client.accessToken ?? '',
      membershipId: me['membership_id']?.toString() ?? '',
      tenantId: me['tenant_id']?.toString() ?? '',
      moodleConnected: me['moodle_connected'] == true,
    );
  }

  @override
  Future<void> logout() async {
    _client.accessToken = null;
    _client.activeMembershipId = null;
  }
}
