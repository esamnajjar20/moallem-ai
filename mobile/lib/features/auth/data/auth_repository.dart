import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../../core/api/api_client.dart';
import '../domain/session.dart';

/// Auth boundary. The Auth0 PKCE flow (DEC: native app + PKCE) is not implemented yet;
/// until it lands, [ApiAuthRepository] signs in with an access token issued out of band
/// and validates it against `GET /me`. [MockAuthRepository] enables offline demos.
abstract class AuthRepository {
  Future<TeacherSession?> restoreSession();
  Future<TeacherSession> login({required String email, required String password});
  Future<void> logout();
}

/// Where the access token lives between launches.
abstract class TokenStore {
  Future<String?> read();
  Future<void> write(String token);
  Future<void> clear();
}

class MemoryTokenStore implements TokenStore {
  String? _token;

  @override
  Future<String?> read() async => _token;

  @override
  Future<void> write(String token) async => _token = token;

  @override
  Future<void> clear() async => _token = null;
}

class SecureTokenStore implements TokenStore {
  SecureTokenStore([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  static const _key = 'moallem.access_token';
  final FlutterSecureStorage _storage;

  @override
  Future<String?> read() => _storage.read(key: _key);

  @override
  Future<void> write(String token) => _storage.write(key: _key, value: token);

  @override
  Future<void> clear() => _storage.delete(key: _key);
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

const _teacherRoles = {'TEACHER', 'ADMIN'};

class ApiAuthRepository implements AuthRepository {
  ApiAuthRepository(this._client, [TokenStore? store]) : _store = store ?? MemoryTokenStore();

  final ApiClient _client;
  final TokenStore _store;

  @override
  Future<TeacherSession?> restoreSession() async {
    final token = await _store.read();
    if (token == null || token.isEmpty) return null;
    try {
      return await _establish(token, fallbackName: '');
    } catch (_) {
      // Expired or revoked token: forget it and ask the user to sign in again.
      await logout();
      return null;
    }
  }

  /// `password` carries the access token in this interim flow; `email` is only a label.
  @override
  Future<TeacherSession> login({
    required String email,
    required String password,
  }) async {
    final token = password.trim();
    if (token.isEmpty) {
      throw StateError('رمز الدخول مطلوب');
    }
    final session = await _establish(token, fallbackName: email.trim());
    await _store.write(token);
    return session;
  }

  /// Validates the token with `GET /me` and selects the active teacher membership.
  Future<TeacherSession> _establish(String token, {required String fallbackName}) async {
    _client.accessToken = token;
    _client.activeMembershipId = null; // /me is exempt from the membership header
    try {
      final me = await _client.getJson('me');
      final memberships = me['memberships'];
      var active = const <String, dynamic>{};
      if (memberships is List<dynamic>) {
        for (final m in memberships.whereType<Map<String, dynamic>>()) {
          final roles = m['roles'];
          if (m['status'] == 'ACTIVE' &&
              roles is List<dynamic> &&
              roles.any(_teacherRoles.contains)) {
            active = m;
            break;
          }
        }
      }
      final membershipId = active['membership_id']?.toString() ?? '';
      if (membershipId.isEmpty) {
        throw StateError('لا توجد عضوية معلم نشطة لهذا الحساب');
      }
      _client.activeMembershipId = membershipId;
      final userId = me['user_id']?.toString() ?? '';
      return TeacherSession(
        userId: userId,
        displayName: fallbackName.isEmpty ? userId : fallbackName,
        accessToken: token,
        membershipId: membershipId,
        tenantId: active['tenant_id']?.toString() ?? '',
      );
    } catch (_) {
      _client.accessToken = null;
      _client.activeMembershipId = null;
      rethrow;
    }
  }

  @override
  Future<void> logout() async {
    _client.accessToken = null;
    _client.activeMembershipId = null;
    await _store.clear();
  }
}
