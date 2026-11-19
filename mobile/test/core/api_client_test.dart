
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:moallem_mobile/core/api/api_client.dart';
import 'package:moallem_mobile/core/api/api_exception.dart';
import 'package:moallem_mobile/core/app_config.dart';

ApiClient _client(MockClientHandler handler) => ApiClient(
      config: AppConfig(apiBaseUrl: Uri.parse('https://api.example.com/api/v1')),
      httpClient: MockClient(handler),
    );

void main() {
  test('attaches bearer token and active membership headers', () async {
    late http.Request seen;
    final client = _client((req) async {
      seen = req;
      return http.Response('{"ok":true}', 200);
    })
      ..accessToken = 'tok'
      ..activeMembershipId = 'm-1';
    await client.getJson('me');
    expect(seen.url.path, '/api/v1/me');
    expect(seen.headers['Authorization'], 'Bearer tok');
    expect(seen.headers['X-Active-Membership-ID'], 'm-1');
  });

  test('maps error envelope to ApiException', () async {
    final client = _client((_) async => http.Response(
          '{"error":{"code":"PERMISSION_DENIED","message":"no"}}',
          403,
        ));
    expect(
      client.getJson('tasks/1'),
      throwsA(isA<ApiException>()
          .having((e) => e.statusCode, 'status', 403)
          .having((e) => e.code, 'code', 'PERMISSION_DENIED')),
    );
  });

  test('maps transport failure to ApiException', () async {
    final client = _client((_) async => throw http.ClientException('down'));
    expect(
      client.getJson('me'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'NETWORK_ERROR')),
    );
  });

  test('sends the Idempotency-Key header on POST', () async {
    late http.Request seen;
    final client = _client((req) async {
      seen = req;
      return http.Response('{}', 202);
    });
    await client.postJson('tasks', body: {'a': 1}, headers: {'Idempotency-Key': 'k1'});
    expect(seen.headers['Idempotency-Key'], 'k1');
    expect(seen.body, '{"a":1}');
  });
}
