import 'package:flutter_test/flutter_test.dart';
import 'package:moallem_mobile/core/app_config.dart';

void main() {
  test('accepts an absolute https URL', () {
    final c = AppConfig.parse('https://api.example.invalid/api/v1');
    expect(c.apiBaseUrl.host, 'api.example.invalid');
  });

  test('rejects empty, relative and non-http URLs', () {
    for (final bad in ['', '/api/v1', 'ftp://host/x', 'not a url']) {
      expect(() => AppConfig.parse(bad), throwsStateError, reason: bad);
    }
  });
}
