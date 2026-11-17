import 'package:flutter_test/flutter_test.dart';
import 'package:moallem_mobile/core/app_config.dart';

void main() {
  test('parses https base url', () {
    final c = AppConfig.parse('https://api.example.com/api/v1');
    expect(c.apiBaseUrl.host, 'api.example.com');
    expect(c.useMocks, isFalse);
  });

  test('allows empty url when mocks enabled', () {
    final c = AppConfig.parse('', useMocks: true);
    expect(c.useMocks, isTrue);
  });

  test('rejects malformed url', () {
    expect(() => AppConfig.parse('not-a-url'), throwsStateError);
  });
}
